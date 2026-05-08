"""把 export_dashboard_business_data.py 产出的 .native 文件导入本地 ClickHouse 容器。

步骤：
  1. 连接 sanity 检查 (SELECT version)
  2. 读取爬虫仓库的 schema.sql (默认 ../network-public-opinion-spider/sql/ddl/schema.sql)
     按 ; 拆分逐条执行，建库 + 8 张表 (`CREATE ... IF NOT EXISTS`，可重入)
  3. 逐表 POST .native 数据 → INSERT INTO weibo.{table} FORMAT Native
  4. 行数核对：本地 count() vs export_meta.json

环境变量复用 export_dashboard_business_data.py 的 .env 加载（user/password 从 .env）。
本地容器 host 必须显式 --host 给入，因为 .env 里 CLICKHOUSE_HOST 还指向云端 CK。
"""

from __future__ import annotations

import argparse
import json
import os
import re
import sys
from pathlib import Path
from urllib.parse import urlencode

import httpx

SCRIPTS_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(SCRIPTS_DIR))
from dataset_paths import ROOT  # noqa: E402

DEFAULT_RAW_ROOT = ROOT / 'data' / 'dashboard' / 'raw'
DEFAULT_SCHEMA = ROOT.parent / 'network-public-opinion-spider' / 'sql' / 'ddl' / 'schema.sql'
TABLES = [
    'topic', 'post', 'post_engagement_ts', 'post_topic',
    'post_media', 'post_discovery', 'comment', 'user',
]
IDENTIFIER_RE = re.compile(r'^[A-Za-z_][A-Za-z0-9_]*$')


def load_env_file(path: Path) -> None:
    if not path.exists():
        return
    for raw_line in path.read_text(encoding='utf-8').splitlines():
        line = raw_line.strip()
        if not line or line.startswith('#'):
            continue
        if line.startswith('export '):
            line = line[len('export '):].strip()
        if '=' not in line:
            continue
        key, value = line.split('=', 1)
        key = key.strip()
        value = value.strip().strip('"\'')
        if key and key not in os.environ:
            os.environ[key] = value


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    p.add_argument('--host', required=True,
                   help='本地容器 IP/hostname (例如 192.168.123.249)')
    p.add_argument('--port', type=int, default=8123)
    p.add_argument('--scheme', default='http')
    p.add_argument('--database', default='weibo')
    p.add_argument('--user', default=os.getenv('READONLY_USER'))
    p.add_argument('--password', default=os.getenv('READONLY_PASSWORD'))
    p.add_argument('--raw-root', type=Path, default=DEFAULT_RAW_ROOT)
    p.add_argument('--schema-file', type=Path, default=DEFAULT_SCHEMA)
    p.add_argument('--tables', nargs='*', default=None,
                   help='只导入指定表 (空格分隔)，默认全部 8 张')
    p.add_argument('--skip-schema', action='store_true',
                   help='跳过建库建表 (容器已有 schema 时用)')
    p.add_argument('--skip-import', action='store_true',
                   help='只 sanity + 建表，不灌数据')
    p.add_argument('--timeout', type=float, default=900.0)
    return p.parse_args()


def require_config(args: argparse.Namespace) -> None:
    missing = []
    if not args.user:
        missing.append('READONLY_USER or --user')
    if not args.password:
        missing.append('READONLY_PASSWORD or --password')
    if missing:
        raise SystemExit('缺少连接信息: ' + ', '.join(missing))
    if not IDENTIFIER_RE.fullmatch(args.database):
        raise SystemExit(f'非法 database: {args.database!r}')


def post_query(client: httpx.Client, base: str, auth: httpx.BasicAuth,
               sql: str, body: bytes | None = None) -> httpx.Response:
    if body is None:
        resp = client.post(base, content=sql, auth=auth)
    else:
        url = f'{base}?{urlencode({"query": sql})}'
        resp = client.post(url, content=body, auth=auth)
    if resp.status_code != 200:
        raise SystemExit(f'CK 错误 {resp.status_code}: {resp.text[:500]}')
    return resp


def split_schema_statements(sql_text: str) -> list[str]:
    """按 ; 拆 schema.sql。先剥掉 -- 行/行内注释。schema.sql 没有字符串里嵌 ; 的情况。"""
    cleaned: list[str] = []
    for line in sql_text.splitlines():
        stripped = line.strip()
        if stripped.startswith('--'):
            continue
        idx = line.find('--')
        if idx >= 0:
            line = line[:idx]
        cleaned.append(line)
    text = '\n'.join(cleaned)
    return [s.strip() for s in text.split(';') if s.strip()]


def apply_schema(client: httpx.Client, base: str, auth: httpx.BasicAuth,
                 schema_path: Path) -> None:
    if not schema_path.exists():
        raise SystemExit(f'schema.sql 不存在: {schema_path}')
    print(f'读 schema: {schema_path}')
    statements = split_schema_statements(schema_path.read_text(encoding='utf-8'))
    print(f'  拆出 {len(statements)} 条 DDL')
    for i, stmt in enumerate(statements, 1):
        head = ' '.join(stmt.split()[:5])
        print(f'  [{i}/{len(statements)}] {head} ...')
        post_query(client, base, auth, stmt)
    print('  schema OK')


def import_native(client: httpx.Client, base: str, auth: httpx.BasicAuth,
                  database: str, table: str, native_path: Path) -> None:
    if not native_path.exists():
        raise SystemExit(f'缺文件: {native_path}')
    sql = f'INSERT INTO {database}.{table} FORMAT Native'
    size = native_path.stat().st_size
    print(f'  INSERT {table:<20} <- {native_path.name} ({size:,} bytes)')
    with native_path.open('rb') as f:
        body = f.read()
    post_query(client, base, auth, sql, body=body)


def count_table(client: httpx.Client, base: str, auth: httpx.BasicAuth,
                database: str, table: str) -> int:
    resp = post_query(client, base, auth, f'SELECT count() FROM {database}.{table}')
    return int(resp.text.strip())


def main() -> None:
    load_env_file(ROOT / '.env')
    args = parse_args()
    require_config(args)
    base = f'{args.scheme}://{args.host}:{args.port}/'
    auth = httpx.BasicAuth(args.user, args.password)
    selected = args.tables or TABLES
    for t in selected:
        if t not in TABLES:
            raise SystemExit(f'未知表: {t}')

    print(f'连接: {base}, db={args.database}')
    with httpx.Client(timeout=args.timeout) as client:
        version = post_query(client, base, auth, 'SELECT version()').text.strip()
        print(f'版本: {version}')

        if not args.skip_schema:
            apply_schema(client, base, auth, args.schema_file)

        if args.skip_import:
            print('--skip-import：建表完成，不灌数据')
            return

        meta_path = args.raw_root / 'export_meta.json'
        meta = json.loads(meta_path.read_text(encoding='utf-8')) if meta_path.exists() else {}
        meta_tables = meta.get('tables', {})

        print('\n== 导入 ==')
        for table in selected:
            native_path = args.raw_root / f'{table}.native'
            import_native(client, base, auth, args.database, table, native_path)

        print('\n== sanity（local count vs export_meta） ==')
        all_match = True
        for table in selected:
            n = count_table(client, base, auth, args.database, table)
            expected = meta_tables.get(table, {}).get('rows', -1)
            if expected == n:
                tag = 'OK'
            else:
                tag = f'WARN expected={expected:,}'
                all_match = False
            print(f'  {table:<20} rows={n:>10,}  ({tag})')
        if not all_match:
            print('\n⚠ 行数有不匹配，看上面 WARN。')


if __name__ == '__main__':
    main()
