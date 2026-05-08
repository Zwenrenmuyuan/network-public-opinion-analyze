"""初始化本地 ClickHouse 上的 dashboard 库与情绪预测表。

  CREATE DATABASE IF NOT EXISTS dashboard;
  CREATE TABLE IF NOT EXISTS dashboard.sentiment_prediction (...)
    ENGINE = ReplacingMergeTree(predicted_at)
    PARTITION BY toYYYYMM(source_created_at)
    ORDER BY (model_version, source_type, source_id);

DDL 与 docs/dashboard-design.md § 7.4 一致。content_hash 列宽 UInt64，
实际值由 predict_business_emotions.py 用 blake2b(digest_size=8) 算清洗后 content。

用法：
  uv run python scripts/dashboard/init_dashboard_schema.py
  uv run python scripts/dashboard/init_dashboard_schema.py --drop   # 重置表（会丢预测数据）

连接信息从 .env 读：CLICKHOUSE_HOST 等（开发期指向 192.168.123.249）。
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

# scripts/dashboard/ → ../../dashboard/ 才能 import ck.CKClient
ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(ROOT / 'dashboard'))
from ck import CKClient  # noqa: E402

DATABASE = 'dashboard'
TABLE = 'sentiment_prediction'

DDL_CREATE_DB = f'CREATE DATABASE IF NOT EXISTS {DATABASE}'

DDL_CREATE_TABLE = f"""
CREATE TABLE IF NOT EXISTS {DATABASE}.{TABLE}
(
    source_type LowCardinality(String),
    source_id UInt64,
    post_id UInt64,
    source_created_at DateTime,
    content_hash UInt64,

    model_key LowCardinality(String),
    model_version LowCardinality(String),
    checkpoint String,

    pred_label LowCardinality(String),
    pred_label_id UInt8,
    confidence Float32,
    second_label LowCardinality(String),
    second_label_id UInt8,
    second_prob Float32,
    margin Float32,

    prob_positive Float32,
    prob_angry Float32,
    prob_sad Float32,
    prob_fear Float32,
    prob_surprise Float32,
    prob_neutral Float32,

    predicted_at DateTime DEFAULT now()
)
ENGINE = ReplacingMergeTree(predicted_at)
PARTITION BY toYYYYMM(source_created_at)
ORDER BY (model_version, source_type, source_id)
SETTINGS index_granularity = 8192
""".strip()


def main() -> None:
    p = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    p.add_argument('--drop', action='store_true',
                   help='先 DROP TABLE 再 CREATE（开发期重置用，会丢预测数据）')
    args = p.parse_args()

    ck = CKClient()
    print(f'连接: {ck.host}:{ck.port}, db={DATABASE}')

    if args.drop:
        print(f'  DROP TABLE IF EXISTS {DATABASE}.{TABLE}')
        ck.query_text(f'DROP TABLE IF EXISTS {DATABASE}.{TABLE}')

    print(f'  {DDL_CREATE_DB}')
    ck.query_text(DDL_CREATE_DB)

    print(f'  CREATE TABLE IF NOT EXISTS {DATABASE}.{TABLE} (...)')
    ck.query_text(DDL_CREATE_TABLE)

    rows = ck.query_json(f'DESCRIBE TABLE {DATABASE}.{TABLE}')
    print(f'\n表结构 ({len(rows)} 列):')
    for r in rows:
        print(f'  {r["name"]:<22} {r["type"]}')

    n = ck.query_json(f'SELECT count() AS n FROM {DATABASE}.{TABLE}')[0]['n']
    print(f'\n当前行数: {n}')


if __name__ == '__main__':
    main()
