"""业务集双模型分歧分析路由。

读 dashboard.sentiment_prediction 中 ERNIE 与 BERT 在相同 (source_type, source_id) 上的
预测，给出一致率、6×6 分歧矩阵和 Top N 高分歧样本。

矩阵和样本都是全数据窗口聚合，不带 range/topic 过滤——这是模型解释面板，
关心的是模型本身在业务集上的表现，不随用户切时间范围而变。
"""

from __future__ import annotations

from flask import Blueprint, jsonify

from npo.config import LABELS_ZH

from .cache import cached_endpoint
from .config import (
    BERT_USAGE,
    DISAGREEMENT_DEFAULT_LIMIT,
    DISAGREEMENT_MAX_LIMIT,
    PRIMARY_CHECKPOINT,
    PRIMARY_MODEL_NAME,
    PRIMARY_MODEL_VERSION,
    SECONDARY_CHECKPOINT,
    SECONDARY_MODEL_NAME,
    SECONDARY_MODEL_VERSION,
)
from .utils import display_text, limit_arg, ratio, round_float, to_int, utc_to_cst_iso


def register_disagreement_routes(api: Blueprint, ck) -> None:
    @api.route('/model-disagreement')
    @cached_endpoint('model-disagreement')
    def api_model_disagreement():
        limit = limit_arg('limit', DISAGREEMENT_DEFAULT_LIMIT, DISAGREEMENT_MAX_LIMIT)
        return jsonify(model_disagreement(ck, limit))


def model_disagreement(ck, limit: int) -> dict:
    matrix_rows = ck.query_json(_matrix_sql())
    matrix_dict: dict[tuple[str, str], int] = {}
    total = 0
    agree = 0
    for r in matrix_rows:
        n = to_int(r['n'])
        key = (r['ernie_label'], r['bert_label'])
        matrix_dict[key] = n
        total += n
        if r['ernie_label'] == r['bert_label']:
            agree += n

    # 补齐 6×6 cell（缺失填 0），保证前端 heatmap 维度恒定。
    matrix = [
        {'ernie_label': el, 'bert_label': bl, 'count': matrix_dict.get((el, bl), 0)}
        for el in LABELS_ZH
        for bl in LABELS_ZH
    ]

    samples = ck.query_json(_top_disagreement_sql(limit))
    top = [
        {
            'source': row['source'],
            'source_id': str(row['source_id']),
            'post_id': str(row['post_id']),
            'created_at': utc_to_cst_iso(row['created_at_utc']),
            'content': display_text(row.get('content')),
            'ernie_label': row['ernie_label'],
            'ernie_confidence': round_float(row.get('ernie_confidence')),
            'ernie_margin': round_float(row.get('ernie_margin')),
            'bert_label': row['bert_label'],
            'bert_confidence': round_float(row.get('bert_confidence')),
            'bert_margin': round_float(row.get('bert_margin')),
        }
        for row in samples
    ]

    return {
        'primary_model': PRIMARY_MODEL_NAME,
        'primary_model_version': PRIMARY_MODEL_VERSION,
        'primary_checkpoint': PRIMARY_CHECKPOINT,
        'secondary_model': SECONDARY_MODEL_NAME,
        'secondary_model_version': SECONDARY_MODEL_VERSION,
        'secondary_checkpoint': SECONDARY_CHECKPOINT,
        'secondary_usage': BERT_USAGE,
        'samples_total': total,
        'agreement_count': agree,
        'agreement_rate': round(ratio(agree, total), 4),
        'labels': list(LABELS_ZH),
        'matrix': matrix,
        'top_disagreements': top,
    }


def _matrix_sql() -> str:
    return f"""
        SELECT
          e.pred_label AS ernie_label,
          b.pred_label AS bert_label,
          count() AS n
        FROM dashboard.sentiment_prediction AS e
        INNER JOIN dashboard.sentiment_prediction AS b
          ON e.source_type = b.source_type AND e.source_id = b.source_id
        WHERE e.model_version = '{PRIMARY_MODEL_VERSION}'
          AND b.model_version = '{SECONDARY_MODEL_VERSION}'
        GROUP BY e.pred_label, b.pred_label
    """


def _top_disagreement_sql(limit: int) -> str:
    """post / comment 各取一半 top 分歧样本，再按总置信度合并排序取 Top limit。

    分歧定义：两模型 top1 标签不同。优先级 = ernie.confidence + bert.confidence
    （两边都高置信但答案不同 = 模型真正分歧，比 margin 低、模糊样本更值得讲）。
    """
    half = max(1, limit)  # 多取一些，UNION 后再 LIMIT，保证总量足
    return f"""
        SELECT * FROM (
          (
            SELECT
              'post' AS source,
              e.source_id AS source_id,
              e.post_id AS post_id,
              toString(e.source_created_at) AS created_at_utc,
              p.text_raw AS content,
              e.pred_label AS ernie_label,
              e.confidence AS ernie_confidence,
              e.margin AS ernie_margin,
              b.pred_label AS bert_label,
              b.confidence AS bert_confidence,
              b.margin AS bert_margin
            FROM dashboard.sentiment_prediction AS e
            INNER JOIN dashboard.sentiment_prediction AS b
              ON e.source_type = b.source_type AND e.source_id = b.source_id
            INNER JOIN weibo.post AS p ON p.post_id = e.source_id
            WHERE e.model_version = '{PRIMARY_MODEL_VERSION}'
              AND b.model_version = '{SECONDARY_MODEL_VERSION}'
              AND e.source_type = 'post'
              AND e.pred_label != b.pred_label
            ORDER BY (e.confidence + b.confidence) DESC
            LIMIT {half}
          )
          UNION ALL
          (
            SELECT
              'comment' AS source,
              e.source_id AS source_id,
              e.post_id AS post_id,
              toString(e.source_created_at) AS created_at_utc,
              c.text_raw AS content,
              e.pred_label AS ernie_label,
              e.confidence AS ernie_confidence,
              e.margin AS ernie_margin,
              b.pred_label AS bert_label,
              b.confidence AS bert_confidence,
              b.margin AS bert_margin
            FROM dashboard.sentiment_prediction AS e
            INNER JOIN dashboard.sentiment_prediction AS b
              ON e.source_type = b.source_type AND e.source_id = b.source_id
            INNER JOIN weibo.comment AS c ON c.comment_id = e.source_id
            WHERE e.model_version = '{PRIMARY_MODEL_VERSION}'
              AND b.model_version = '{SECONDARY_MODEL_VERSION}'
              AND e.source_type = 'comment'
              AND e.pred_label != b.pred_label
            ORDER BY (e.confidence + b.confidence) DESC
            LIMIT {half}
          )
        )
        ORDER BY (ernie_confidence + bert_confidence) DESC
        LIMIT {limit}
    """
