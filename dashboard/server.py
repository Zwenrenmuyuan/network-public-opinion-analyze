"""Dashboard 后端网关 (Flask)。

启动：
    uv run python dashboard/server.py
    uv run python dashboard/server.py --port 8000 --debug

路由：
    GET /                           托管 dashboard/index.html
    GET /static/<path>              托管 dashboard/static/
    GET /api/dashboard/meta          数据窗口、模型版本、标签
    GET /api/dashboard/data-quality  数据口径文案 + 窗口内 tier 分布
    GET /api/dashboard/overview      总览 KPI（情绪相关字段在 dashboard.sentiment_prediction
                                     建好前为 null）
    GET /api/dashboard/model-quality 模型质量：business_eval + smp_test + 混淆 top + BERT 对比

设计依据：docs/dashboard-design.md § 9.1 / 9.2 / 9.9 / 9.10。
"""

from __future__ import annotations

import argparse
import json
import os
from datetime import datetime, timedelta, timezone
from pathlib import Path

# 我们自己用 ck.load_env_file 加载 .env；让 Flask 别再重复加载并抱怨没装 python-dotenv。
# 必须在 import flask 之前设。
os.environ.setdefault('FLASK_SKIP_DOTENV', '1')

from flask import Flask, jsonify, send_from_directory

# dashboard/ 不是 Python 包；脚本运行时 sys.path[0] = dashboard/，
# 所以可以直接 import 同目录的 ck.py。
from ck import CKClient

# src/npo 由 hatch wheel editable 安装，import 直接走包。
from npo.config import LABELS_ZH

DASHBOARD_DIR = Path(__file__).resolve().parent
PROJECT_ROOT = DASHBOARD_DIR.parent
NEGATIVE_LABELS = ('愤怒', '悲伤', '恐惧')
PRIMARY_MODEL_NAME = 'ERNIE mixed-v2'
PRIMARY_CHECKPOINT = 'runs/ernie-usual-mixed-v2/best'
SECONDARY_MODEL_NAME = 'BERT mixed-v2'
BERT_USAGE = '对照模型与困难样本发现工具'
DISPLAY_TZ = timezone(timedelta(hours=8))  # Asia/Shanghai
# 把 first_crawled_at 当天 < 该阈值的日期视为爬虫尚未稳定运行 / 历史尾巴，
# 用于算 data_window.start。当前数据：4-23 = 4 行 (试运行)，4-25 起每天 3 万+，阈值 10000 干净分隔。
STABLE_DAY_THRESHOLD = 10000

# model-quality 数据源：scripts/evaluate.py 和 scripts/analyze_model_disagreement.py 的产物
# 直接读 json，不依赖任何手写文档。缺文件时对应字段返回 null，不让 endpoint 整个挂。
MODEL_QUALITY_SOURCES = {
    'business_eval': PROJECT_ROOT / 'runs' / 'ernie-usual-mixed-v2' / 'final_business_eval_report.json',
    'smp_test':      PROJECT_ROOT / 'runs' / 'ernie-usual-mixed-v2' / 'final_test_report.json',
    'disagreement':  PROJECT_ROOT / 'results' / 'model_disagreement' / 'usual_business_eval_ernie_vs_bert_summary.json',
}

# 数据口径文案（设计文档 § 9.10）
DATA_QUALITY_NOTICES = {
    'comment_sampling_notice': '评论为采样集合，不代表全量评论分布。',
    'engagement_notice': '互动数来自 post_engagement_ts 平台快照。',
    'timezone_notice': '存储为 UTC，前端展示为东八区。',
    'history_window_notice': '当前爬虫仅有约 14 天稳定历史数据，趋势和风险分只按实际可用窗口解释。',
    'user_tier_notice': 'followers_count 等画像字段仅 profile_tier >= 1 可信。',
    'post_discovery_notice': 'post_discovery 是多行发现事件，不等于帖子数。',
}
DATA_QUALITY_SOURCES = [
    'post', 'comment', 'post_engagement_ts',
    'topic', 'post_topic', 'post_discovery', 'user',
]

app = Flask(__name__, static_folder=None)
app.json.ensure_ascii = False  # JSON 响应里中文标签不要转义成 \u
ck = CKClient()


# ---------- 共享 helper ----------

def _get_data_window() -> dict:
    """返回 {start_cst, end_cst, available_days, start_utc_str}。

    start_utc_str 用 'YYYY-MM-DD HH:MM:SS' 格式，给业务 SQL 拼到 `WHERE created_at >= '...'`。
    其它三项给 meta endpoint 直接展示用。
    """
    row = ck.query_one(f"""
        SELECT
          (SELECT min(d) FROM (
            SELECT toDate(first_crawled_at, 'Asia/Shanghai') AS d, count() AS n
            FROM weibo.post GROUP BY d HAVING n >= {STABLE_DAY_THRESHOLD}
          )) AS stable_start_cst,
          max(created_at) AS end_utc
        FROM weibo.post
    """)
    if not row or not row.get('end_utc'):
        raise RuntimeError('weibo.post 无数据，无法计算 data_window')

    raw_start = row.get('stable_start_cst')
    if raw_start and raw_start != '0000-00-00':
        start_cst = datetime.strptime(raw_start, '%Y-%m-%d').replace(tzinfo=DISPLAY_TZ)
    else:
        fb = ck.query_one('SELECT min(first_crawled_at) AS m FROM weibo.post')
        start_cst = (datetime.strptime(fb['m'], '%Y-%m-%d %H:%M:%S')
                     .replace(tzinfo=timezone.utc).astimezone(DISPLAY_TZ))

    end_cst = (datetime.strptime(row['end_utc'], '%Y-%m-%d %H:%M:%S')
               .replace(tzinfo=timezone.utc).astimezone(DISPLAY_TZ))
    available_days = max(1, (end_cst.date() - start_cst.date()).days + 1)
    start_utc_str = start_cst.astimezone(timezone.utc).strftime('%Y-%m-%d %H:%M:%S')

    return {
        'start_cst': start_cst,
        'end_cst': end_cst,
        'available_days': available_days,
        'start_utc_str': start_utc_str,
    }


def _profile_tier_distribution(start_utc_str: str) -> dict[str, float]:
    """窗口内活跃用户的 tier 分布。返回如 {'0': 0.7421, '1': 0.2104, '2': 0.0475}。"""
    rows = ck.query_json(f"""
        SELECT profile_tier AS tier, count(DISTINCT uid) AS n
        FROM weibo.user FINAL
        WHERE uid IN (
          SELECT DISTINCT user_id FROM weibo.post WHERE created_at >= '{start_utc_str}'
          UNION DISTINCT
          SELECT DISTINCT user_id FROM weibo.comment WHERE created_at >= '{start_utc_str}'
        )
        GROUP BY profile_tier ORDER BY profile_tier
    """)
    total = sum(int(r['n']) for r in rows)
    if total == 0:
        return {}
    return {str(r['tier']): round(int(r['n']) / total, 4) for r in rows}


def _scalar(sql: str) -> int:
    """跑一条返回单个 'n' 字段的聚合 SQL，转 int。空结果返回 0。"""
    row = ck.query_one(sql)
    if not row or row.get('n') is None:
        return 0
    return int(row['n'])


def _load_json(path: Path) -> dict | None:
    """读 json 文件；缺失返回 None（让上层把对应字段降级为 null 而不是整个 endpoint 挂）。"""
    try:
        return json.loads(path.read_text(encoding='utf-8'))
    except FileNotFoundError:
        return None


def _extract_eval(report: dict | None) -> dict | None:
    """把 scripts/evaluate.py 的 final_*_report.json 抽成 dashboard 需要的字段。"""
    if not report:
        return None
    labels = report.get('labels') or list(LABELS_ZH)
    per_class = report.get('per_class_f1') or []
    return {
        'samples': report.get('samples'),
        'accuracy': round(report.get('accuracy', 0.0), 4),
        'macro_f1': round(report.get('macro_f1', 0.0), 4),
        'per_class_f1': {label: round(float(f1), 4) for label, f1 in zip(labels, per_class)},
    }


def _top_confusions(matrix: list[list[int]] | None, labels: list[str], top_n: int = 3) -> list[dict]:
    """从 NxN 混淆矩阵 (行=真, 列=预测) 取最大的 top_n 个 off-diagonal cell。"""
    if not matrix:
        return []
    cells = []
    for i, row in enumerate(matrix):
        for j, count in enumerate(row):
            if i == j or not count:
                continue
            cells.append({'true': labels[i], 'pred': labels[j], 'count': int(count)})
    cells.sort(key=lambda c: c['count'], reverse=True)
    return cells[:top_n]


# ---------- routes ----------

@app.route('/')
def index():
    return send_from_directory(DASHBOARD_DIR, 'index.html')


@app.route('/static/<path:filename>')
def static_files(filename: str):
    return send_from_directory(DASHBOARD_DIR / 'static', filename)


@app.route('/api/dashboard/meta')
def api_meta():
    w = _get_data_window()
    time_range_options = ['all_available']
    if w['available_days'] >= 1:
        time_range_options.append('24h')
    if w['available_days'] >= 7:
        time_range_options.append('7d')
    return jsonify({
        'schema_version': 'dashboard.v1',
        'generated_at': datetime.now(DISPLAY_TZ).isoformat(timespec='seconds'),
        'data_window': {
            'start': w['start_cst'].isoformat(timespec='seconds'),
            'end': w['end_cst'].isoformat(timespec='seconds'),
            'available_days': w['available_days'],
            'is_partial_history': w['available_days'] < 30,
        },
        'time_range_options': time_range_options,
        'model': {'name': PRIMARY_MODEL_NAME, 'checkpoint': PRIMARY_CHECKPOINT},
        'labels': list(LABELS_ZH),
        'negative_labels': list(NEGATIVE_LABELS),
    })


@app.route('/api/dashboard/data-quality')
def api_data_quality():
    w = _get_data_window()
    return jsonify({
        **DATA_QUALITY_NOTICES,
        'profile_tier_distribution': _profile_tier_distribution(w['start_utc_str']),
        'generated_from': DATA_QUALITY_SOURCES,
    })


@app.route('/api/dashboard/overview')
def api_overview():
    w = _get_data_window()
    s = w['start_utc_str']

    post_count = _scalar(
        f"SELECT count(DISTINCT post_id) AS n FROM weibo.post WHERE created_at >= '{s}'"
    )
    sampled_comment_count = _scalar(
        f"SELECT count(DISTINCT comment_id) AS n FROM weibo.comment WHERE created_at >= '{s}'"
    )
    # 「活跃话题」= 热榜登记过 (在 weibo.topic 里) 且窗口内有 post 关联的话题。
    # 不限定 topic 表会数到 post_topic 里所有 # 标签话题 (~6.8 万，含用户随手提的)，
    # 与设计文档「话题层 = 风险话题榜」的语义不符。
    active_topic_count = _scalar(f"""
        SELECT count(DISTINCT topic_id) AS n
        FROM weibo.post_topic
        WHERE topic_id IN (SELECT topic_id FROM weibo.topic)
          AND post_id IN (SELECT DISTINCT post_id FROM weibo.post WHERE created_at >= '{s}')
    """)
    latest_interactions = _scalar(f"""
        SELECT sum(c) + sum(l) + sum(r) AS n
        FROM (
          SELECT post_id,
            argMax(comments_count, captured_at) AS c,
            argMax(attitudes_count, captured_at) AS l,
            argMax(reposts_count, captured_at) AS r
          FROM weibo.post_engagement_ts
          WHERE post_id IN (SELECT DISTINCT post_id FROM weibo.post WHERE created_at >= '{s}')
          GROUP BY post_id
        )
    """)
    kol_entry_post_count = _scalar(f"""
        SELECT count(DISTINCT post_id) AS n
        FROM weibo.post_discovery
        WHERE source_type = 'kol'
          AND post_id IN (SELECT DISTINCT post_id FROM weibo.post WHERE created_at >= '{s}')
    """)
    verified_actor_count = _scalar(f"""
        SELECT count(DISTINCT uid) AS n
        FROM weibo.user FINAL
        WHERE verified = 1
          AND uid IN (
            SELECT DISTINCT user_id FROM weibo.post WHERE created_at >= '{s}'
            UNION DISTINCT
            SELECT DISTINCT user_id FROM weibo.comment WHERE created_at >= '{s}'
          )
    """)

    return jsonify({
        'post_count': post_count,
        'sampled_comment_count': sampled_comment_count,
        'active_topic_count': active_topic_count,
        'latest_interactions': latest_interactions,
        'kol_entry_post_count': kol_entry_post_count,
        'verified_actor_count': verified_actor_count,
        'profile_tier_distribution': _profile_tier_distribution(s),
        # 情绪相关字段：等 dashboard.sentiment_prediction 表上线（阶段 B 之后）
        'negative_ratio': None,
        'risk_index': None,
        'avg_confidence': None,
        'low_confidence_count': None,
    })


@app.route('/api/dashboard/model-quality')
def api_model_quality():
    business = _load_json(MODEL_QUALITY_SOURCES['business_eval'])
    smp_test = _load_json(MODEL_QUALITY_SOURCES['smp_test'])
    disagreement = _load_json(MODEL_QUALITY_SOURCES['disagreement'])

    # business_eval 的混淆矩阵代表生产场景下的错误结构；优先用它取 top confusions。
    cm_source = business or smp_test
    matrix = cm_source.get('confusion_matrix') if cm_source else None
    cm_labels = (cm_source.get('labels') if cm_source else None) or list(LABELS_ZH)

    bert_cmp = None
    if disagreement:
        bert = disagreement.get('bert', {})
        bert_cmp = {
            'name': SECONDARY_MODEL_NAME,
            'usage': BERT_USAGE,
            'agreement_rate': round(disagreement.get('agreement_rate', 0.0), 4),
            'oracle_accuracy': round(disagreement.get('oracle_accuracy', 0.0), 4),
            'bert_accuracy': round(bert.get('accuracy', 0.0), 4),
            'bert_macro_f1': round(bert.get('macro_f1', 0.0), 4),
            'ernie_only_correct': disagreement.get('ernie_only_correct'),
            'bert_only_correct': disagreement.get('bert_only_correct'),
        }

    return jsonify({
        'primary_model': PRIMARY_MODEL_NAME,
        'checkpoint': PRIMARY_CHECKPOINT,
        'business_eval': _extract_eval(business),
        'smp_test': _extract_eval(smp_test),
        'top_confusions': _top_confusions(matrix, cm_labels, top_n=3),
        'bert_comparison': bert_cmp,
    })


def main() -> None:
    p = argparse.ArgumentParser()
    p.add_argument('--host', default='0.0.0.0')
    p.add_argument('--port', type=int, default=8000)
    p.add_argument('--debug', action='store_true')
    args = p.parse_args()
    print(f'Dashboard 后端启动: http://localhost:{args.port}/  ->  CK={ck.host}:{ck.port}')
    app.run(host=args.host, port=args.port, debug=args.debug)


if __name__ == '__main__':
    main()
