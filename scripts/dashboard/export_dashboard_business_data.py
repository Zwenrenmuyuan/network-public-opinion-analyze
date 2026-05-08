"""从云端 ClickHouse 导出 dashboard 用业务数据 (Native 格式)。

设计文档 docs/dashboard-design.md § 6 列出的 8 张表，按 schema.sql 的列顺序输出，
方便后续直接 `INSERT ... FORMAT Native` 进本地容器：

  topic / post / post_engagement_ts / post_topic / post_media /
  post_discovery / comment / user

输出：
  data/dashboard/raw/{table}.native
  data/dashboard/raw/export_meta.json    导出时间、CK 版本、各表行数和字节数

环境变量复用 scripts/data_repair/export_business_data.py 风格 (.env 自动加载)：
  CLICKHOUSE_HOST, CLICKHOUSE_PORT, CLICKHOUSE_DATABASE,
  READONLY_USER, READONLY_PASSWORD

只 SELECT，不写入数据库。
"""

from __future__ import annotations

import argparse
import json
import os
import re
import sys
from datetime import datetime, timezone
from pathlib import Path

import httpx

SCRIPTS_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(SCRIPTS_DIR))
from dataset_paths import ROOT  # noqa: E402

DEFAULT_OUT_ROOT = ROOT / 'data' / 'dashboard' / 'raw'
DEFAULT_SINCE = '2026-04-01 00:00:00'
IDENTIFIER_RE = re.compile(r'^[A-Za-z_][A-Za-z0-9_]*$')
DATETIME_RE = re.compile(r'^\d{4}-\d{2}-\d{2}(?: \d{2}:\d{2}:\d{2})?$')

# 每张表：列顺序严格按 schema.sql 走，方便 INSERT FORMAT Native 直接成功；
# time_col 用于分区裁剪，None 表示该表不分区，全量导出。
# post.raw_json 可能很大，默认置空字符串；--include-raw-json 时改写为真实列。
TABLES: list[dict] = [
    {
        'name': 'topic',
        'time_col': 'first_seen_at',
        'columns': (
            'topic_id, title, read_count, discuss_count, lead, hot_value, '
            'first_seen_at, last_seen_at, crawled_at'
        ),
    },
    {
        'name': 'post',
        'time_col': 'created_at',
        'columns_no_raw': (
            'post_id, mblogid, user_id, text_raw, region_name, source_client, '
            'created_at, edit_count, has_images, has_video, is_long_text, '
            "retweet_of, mblog_type, visible_type, '' AS raw_json, "
            'first_crawled_at, last_crawled_at'
        ),
        'columns_with_raw': (
            'post_id, mblogid, user_id, text_raw, region_name, source_client, '
            'created_at, edit_count, has_images, has_video, is_long_text, '
            'retweet_of, mblog_type, visible_type, raw_json, '
            'first_crawled_at, last_crawled_at'
        ),
    },
    {
        'name': 'post_engagement_ts',
        'time_col': 'captured_at',
        'columns': 'post_id, captured_at, comments_count, attitudes_count, reposts_count',
    },
    {
        'name': 'post_topic',
        'time_col': None,
        'columns': 'post_id, topic_id, linked_at',
    },
    {
        'name': 'post_media',
        'time_col': None,
        'columns': (
            'post_id, media_type, media_id, media_url, order_index, '
            'width, height, crawled_at'
        ),
    },
    {
        'name': 'post_discovery',
        'time_col': None,
        'columns': 'post_id, source_type, source_value, discovered_at',
    },
    {
        'name': 'comment',
        'time_col': 'created_at',
        'columns': (
            'comment_id, post_id, parent_comment_id, reply_to_comment_id, '
            'user_id, text_raw, region_name, source_client, like_count, '
            'floor_number, created_at, first_crawled_at'
        ),
    },
    {
        'name': 'user',
        'time_col': None,
        'columns': (
            'uid, screen_name, verified, verified_type, mbrank, mbtype, '
            'avatar_hd, profile_url, followers_count, friends_count, '
            'statuses_count, description, location, verified_reason, gender, '
            'registered_at, ip_location, labels, birthday, '
            'profile_tier, profile_fetched_at, first_seen_at'
        ),
    },
]


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
    p.add_argument('--since', default=DEFAULT_SINCE,
                   help=f'分区裁剪时间下界 (UTC)，默认 {DEFAULT_SINCE}')
    p.add_argument('--out-root', type=Path, default=DEFAULT_OUT_ROOT)
    p.add_argument('--scheme', default=os.getenv('CLICKHOUSE_SCHEME', 'http'))
    p.add_argument('--host', default=os.getenv('CLICKHOUSE_HOST'))
    p.add_argument('--port', type=int, default=int(os.getenv('CLICKHOUSE_PORT', '8123')))
    p.add_argument('--database', default=os.getenv('CLICKHOUSE_DATABASE', 'weibo'))
    p.add_argument('--user', default=os.getenv('READONLY_USER'))
    p.add_argument('--password', default=os.getenv('READONLY_PASSWORD'))
    p.add_argument('--include-raw-json', action='store_true',
                   help='保留 post.raw_json (默认置为空字符串以减小体积)')
    p.add_argument('--tables', nargs='*', default=None,
                   help='只导出指定表，默认全部 (空格分隔)')
    p.add_argument('--skip-count', action='store_true',
                   help='跳过导出前的 count() 统计 (省一轮查询)')
    p.add_argument('--timeout', type=float, default=600.0)
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


def build_select(table: dict, args: argparse.Namespace) -> str:
    name = table['name']
    if name == 'post':
        cols = table['columns_with_raw'] if args.include_raw_json else table['columns_no_raw']
    else:
        cols = table['columns']
    where = ''
    if table['time_col'] is not None:
        where = f"\nWHERE {table['time_col']} >= '{args.since}'"
    return f"SELECT {cols}\nFROM {args.database}.{name}{where}"


def query_text(client: httpx.Client, url: str, auth: httpx.BasicAuth, sql: str) -> str:
    resp = client.post(url, content=sql, auth=auth)
    resp.raise_for_status()
    return resp.text.strip()


def count_rows(client: httpx.Client, url: str, auth: httpx.BasicAuth,
               table: dict, args: argparse.Namespace) -> int:
    select = build_select(table, args)
    sql = f'SELECT count() FROM ({select})'
    return int(query_text(client, url, auth, sql))


def export_native(client: httpx.Client, url: str, auth: httpx.BasicAuth,
                  table: dict, args: argparse.Namespace) -> tuple[Path, int]:
    out_path = args.out_root / f"{table['name']}.native"
    out_path.parent.mkdir(parents=True, exist_ok=True)
    sql = f"{build_select(table, args)}\nFORMAT Native"
    bytes_written = 0
    with client.stream('POST', url, content=sql, auth=auth) as resp:
        resp.raise_for_status()
        with out_path.open('wb') as f:
            for chunk in resp.iter_bytes():
                f.write(chunk)
                bytes_written += len(chunk)
    return out_path, bytes_written


def main() -> None:
    load_env_file(ROOT / '.env')
    args = parse_args()
    require_config(args)

    selected = TABLES if args.tables is None else [t for t in TABLES if t['name'] in set(args.tables)]
    if not selected:
        raise SystemExit(f'没有匹配的表，--tables={args.tables}')

    args.out_root.mkdir(parents=True, exist_ok=True)
    url = f'{args.scheme}://{args.host}:{args.port}/'
    auth = httpx.BasicAuth(args.user, args.password)

    print(f'ClickHouse: {args.host}:{args.port}/{args.database}, since={args.since}')
    print(f'输出目录: {args.out_root}')
    print(f'include_raw_json={args.include_raw_json}, tables={[t["name"] for t in selected]}')

    meta: dict = {
        'exported_at': datetime.now(timezone.utc).isoformat(),
        'source': {'host': args.host, 'database': args.database, 'since': args.since},
        'include_raw_json': args.include_raw_json,
        'tables': {},
    }
    with httpx.Client(timeout=args.timeout) as client:
        version = query_text(client, url, auth, 'SELECT version()')
        print(f'CH 版本: {version}')
        meta['source']['version'] = version

        for table in selected:
            n = -1
            if not args.skip_count:
                n = count_rows(client, url, auth, table, args)
            out_path, size = export_native(client, url, auth, table, args)
            n_str = f'{n:>10,}' if n >= 0 else '         ?'
            print(f"  {table['name']:<20} rows={n_str}  bytes={size:>12,}  -> {out_path.name}")
            meta['tables'][table['name']] = {'rows': n, 'bytes': size}

    meta_path = args.out_root / 'export_meta.json'
    meta_path.write_text(json.dumps(meta, ensure_ascii=False, indent=2), encoding='utf-8')
    print(f'写出 {meta_path}')


if __name__ == '__main__':
    main()
