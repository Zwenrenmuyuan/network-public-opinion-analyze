"""从 ClickHouse HTTP 接口导出业务 post/comment Parquet。

连接信息从环境变量读取，避免把账号密码写进仓库：
  CLICKHOUSE_HOST, CLICKHOUSE_PORT, CLICKHOUSE_DATABASE,
  READONLY_USER, READONLY_PASSWORD

本脚本只读 ClickHouse，不会写入数据库。
"""

from __future__ import annotations

import argparse
import os
import re
import sys
from pathlib import Path

import httpx

SCRIPTS_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(SCRIPTS_DIR))
from dataset_paths import ROOT  # noqa: E402

DEFAULT_OUT_ROOT = ROOT / 'data' / 'business'
DEFAULT_SINCE = '2026-04-24 00:00:00'
IDENTIFIER_RE = re.compile(r'^[A-Za-z_][A-Za-z0-9_]*$')
DATETIME_RE = re.compile(r'^\d{4}-\d{2}-\d{2}(?: \d{2}:\d{2}:\d{2})?$')


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
    p.add_argument('--source', choices=['post', 'comment', 'both'], default='both')
    p.add_argument('--since', default=DEFAULT_SINCE,
                   help=f'UTC created_at 下界，默认 {DEFAULT_SINCE}')
    p.add_argument('--out-root', type=Path, default=DEFAULT_OUT_ROOT)
    p.add_argument('--scheme', default=os.getenv('CLICKHOUSE_SCHEME', 'http'))
    p.add_argument('--host', default=os.getenv('CLICKHOUSE_HOST'))
    p.add_argument('--port', type=int, default=int(os.getenv('CLICKHOUSE_PORT', '8123')))
    p.add_argument('--database', default=os.getenv('CLICKHOUSE_DATABASE', 'weibo'))
    p.add_argument('--user', default=os.getenv('READONLY_USER'))
    p.add_argument('--password', default=os.getenv('READONLY_PASSWORD'))
    p.add_argument('--limit', type=int, default=None,
                   help='仅用于 smoke test；正式导出不要传')
    p.add_argument('--timeout', type=float, default=300.0)
    p.add_argument('--skip-count', action='store_true',
                   help='跳过导出前 count() 统计')
    return p.parse_args()


def require_config(args: argparse.Namespace) -> None:
    missing = []
    if not args.host:
        missing.append('CLICKHOUSE_HOST or --host')
    if not args.user:
        missing.append('READONLY_USER or --user')
    if not args.password:
        missing.append('READONLY_PASSWORD or --password')
    if missing:
        raise SystemExit('缺少连接信息: ' + ', '.join(missing))
    if not IDENTIFIER_RE.fullmatch(args.database):
        raise SystemExit(f'非法 database 名: {args.database!r}')
    if not DATETIME_RE.fullmatch(args.since):
        raise SystemExit('--since 必须形如 YYYY-MM-DD 或 YYYY-MM-DD HH:MM:SS')


def build_query(source: str, database: str, since: str, limit: int | None, output_format: str) -> str:
    if source == 'post':
        table = f'{database}.post'
        columns = 'post_id, text_raw, created_at, region_name, has_images, has_video'
        order_by = 'created_at, post_id'
    elif source == 'comment':
        table = f'{database}.comment'
        columns = 'comment_id, post_id, text_raw, created_at, region_name, like_count'
        order_by = 'created_at, post_id, comment_id'
    else:
        raise ValueError(f'unknown source: {source}')

    limit_sql = f'\nLIMIT {limit}' if limit is not None else ''
    return f"""
SELECT {columns}
FROM {table} FINAL
WHERE created_at >= '{since}' AND text_raw != ''
ORDER BY {order_by}{limit_sql}
FORMAT {output_format}
""".strip()


def query_text(client: httpx.Client, url: str, auth: httpx.BasicAuth, sql: str) -> str:
    resp = client.post(url, content=sql, auth=auth)
    resp.raise_for_status()
    return resp.text.strip()


def count_rows(client: httpx.Client, url: str, auth: httpx.BasicAuth, source: str, args: argparse.Namespace) -> str:
    sql = build_query(source, args.database, args.since, args.limit, 'Null')
    count_sql = 'SELECT count() FROM (' + sql.rsplit('FORMAT', 1)[0].strip() + ')'
    return query_text(client, url, auth, count_sql)


def export_parquet(client: httpx.Client, url: str, auth: httpx.BasicAuth, source: str, args: argparse.Namespace) -> Path:
    filename = 'posts.parquet' if source == 'post' else 'comments.parquet'
    if args.limit is not None:
        filename = filename.replace('.parquet', f'.sample{args.limit}.parquet')
    out_path = args.out_root / filename
    out_path.parent.mkdir(parents=True, exist_ok=True)

    sql = build_query(source, args.database, args.since, args.limit, 'Parquet')
    with client.stream('POST', url, content=sql, auth=auth) as resp:
        resp.raise_for_status()
        with out_path.open('wb') as f:
            for chunk in resp.iter_bytes():
                f.write(chunk)
    return out_path


def main() -> None:
    load_env_file(ROOT / '.env')
    args = parse_args()
    require_config(args)

    sources = ['post', 'comment'] if args.source == 'both' else [args.source]
    url = f'{args.scheme}://{args.host}:{args.port}/'
    auth = httpx.BasicAuth(args.user, args.password)

    print(f'ClickHouse: {args.host}:{args.port}/{args.database}, since={args.since}, source={args.source}')
    if args.limit is not None:
        print(f'注意：当前是 sample 导出，limit={args.limit}')

    with httpx.Client(timeout=args.timeout) as client:
        version = query_text(client, url, auth, 'SELECT version()')
        print(f'version={version}')
        for source in sources:
            if not args.skip_count:
                total = count_rows(client, url, auth, source, args)
                print(f'{source}: rows={total}')
            out_path = export_parquet(client, url, auth, source, args)
            print(f'{source}: 写出 {out_path}')


if __name__ == '__main__':
    main()
