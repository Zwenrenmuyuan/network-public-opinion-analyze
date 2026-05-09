"""Evidence sample route."""

from __future__ import annotations

from flask import Blueprint, jsonify

from .config import ANGER_FEAR_LABEL_IDS, EVIDENCE_DEFAULT_LIMIT, EVIDENCE_MAX_LIMIT, LOW_MARGIN_THRESHOLD, NEGATIVE_LABEL_IDS, PRIMARY_MODEL_VERSION
from .utils import display_text, limit_arg, q_arg, resolve_window, round_float, to_float, to_int, topic_id_arg, utc_to_cst_iso


def register_evidence_routes(api: Blueprint, ck) -> None:
    @api.route('/evidence')
    def api_evidence():
        return jsonify(evidence_samples(
            ck,
            resolve_window(ck),
            topic_id_arg(),
            limit_arg('limit', EVIDENCE_DEFAULT_LIMIT, EVIDENCE_MAX_LIMIT),
            q_arg(),
        ))


def evidence_samples(ck, window: dict, topic_id: int | None, limit: int, q: str = '') -> list[dict]:
    topic_filter = '' if topic_id is None else f'AND pt.topic_id = {topic_id}'
    start = window['start_utc_str']
    end = window['end_utc_str']
    rows = ck.query_json(_evidence_sql(start, end, topic_filter, q, limit))
    out = []
    for idx, row in enumerate(rows, 1):
        reason_parts = [row['pred_label']]
        if to_float(row.get('interaction_count')) > 0:
            reason_parts.append('高互动')
        if row.get('actor_role') == 'verified_actor':
            reason_parts.append('认证账号')
        if to_float(row.get('margin')) < LOW_MARGIN_THRESHOLD:
            reason_parts.append('低 margin')
        out.append({
            'sample_id': f'ev_{idx:06d}',
            'source': row.get('source'),
            'source_id': str(row.get('source_id')),
            'post_id': str(row.get('post_id')),
            'topic_id': str(row.get('topic_id')) if row.get('topic_id') is not None else None,
            'created_at': utc_to_cst_iso(row.get('created_at_utc')),
            'content': display_text(row.get('content')),
            'pred_label': row.get('pred_label'),
            'confidence': round_float(row.get('confidence'), 4),
            'second_label': row.get('second_label'),
            'margin': round_float(row.get('margin'), 4),
            'interaction_count': to_int(row.get('interaction_count')),
            'actor_role': row.get('actor_role'),
            'evidence_reason': ' + '.join(reason_parts),
        })
    return out


def _evidence_sql(start: str, end: str, topic_filter: str, q: str, limit: int) -> str:
    q_filter_post = f"AND positionCaseInsensitive(p.text_raw, '{q}') > 0" if q else ''
    q_filter_comment = f"AND positionCaseInsensitive(c.text_raw, '{q}') > 0" if q else ''
    score_expr = f"""
      if(sp.pred_label_id IN {ANGER_FEAR_LABEL_IDS}, 30, if(sp.pred_label_id IN {NEGATIVE_LABEL_IDS}, 20, 0))
      + sp.confidence * 20
      + if(sp.margin < {LOW_MARGIN_THRESHOLD}, 12, 0)
      + log(1 + ifNull(e.interaction_count, 0)) * 3
      + if(u.verified = 1, 10, 0)
    """
    engagement_join = f"""
      LEFT JOIN (
        SELECT post_id, argMax(comments_count + attitudes_count + reposts_count, captured_at) AS interaction_count
        FROM weibo.post_engagement_ts
        WHERE captured_at >= '{start}' AND captured_at <= '{end}'
        GROUP BY post_id
      ) AS e ON e.post_id = sp.post_id
    """
    where_common = f"""
      sp.model_version = '{PRIMARY_MODEL_VERSION}'
      AND sp.source_created_at >= '{start}'
      AND sp.source_created_at <= '{end}'
      {topic_filter}
    """
    return f"""
        SELECT
          source,
          source_id,
          post_id,
          topic_id,
          created_at_utc,
          content,
          pred_label,
          confidence,
          second_label,
          margin,
          actor_role,
          interaction_count
        FROM (
          SELECT
            sp.source_type AS source,
            sp.source_id AS source_id,
            sp.post_id AS post_id,
            toString(any(pt.topic_id)) AS topic_id,
            toString(sp.source_created_at) AS created_at_utc,
            p.text_raw AS content,
            sp.pred_label AS pred_label,
            sp.confidence AS confidence,
            sp.second_label AS second_label,
            sp.margin AS margin,
            if(u.verified = 1, 'verified_actor', if(u.profile_tier >= 1, concat('tier', toString(u.profile_tier)), 'tier0')) AS actor_role,
            ifNull(e.interaction_count, 0) AS interaction_count,
            ({score_expr}) AS evidence_score
          FROM dashboard.sentiment_prediction AS sp
          INNER JOIN weibo.post_topic AS pt ON pt.post_id = sp.post_id
          INNER JOIN weibo.post AS p ON p.post_id = sp.source_id
          LEFT JOIN weibo.user AS u FINAL ON u.uid = p.user_id
          {engagement_join}
          WHERE {where_common}
            AND sp.source_type = 'post'
            {q_filter_post}
          GROUP BY
            sp.source_type, sp.source_id, sp.post_id, sp.source_created_at, p.text_raw,
            sp.pred_label, sp.pred_label_id, sp.confidence, sp.second_label, sp.margin,
            u.verified, u.profile_tier, e.interaction_count

          UNION ALL

          SELECT
            sp.source_type AS source,
            sp.source_id AS source_id,
            sp.post_id AS post_id,
            toString(any(pt.topic_id)) AS topic_id,
            toString(sp.source_created_at) AS created_at_utc,
            c.text_raw AS content,
            sp.pred_label AS pred_label,
            sp.confidence AS confidence,
            sp.second_label AS second_label,
            sp.margin AS margin,
            if(u.verified = 1, 'verified_actor', if(u.profile_tier >= 1, concat('tier', toString(u.profile_tier)), 'tier0')) AS actor_role,
            ifNull(e.interaction_count, 0) AS interaction_count,
            ({score_expr}) AS evidence_score
          FROM dashboard.sentiment_prediction AS sp
          INNER JOIN weibo.post_topic AS pt ON pt.post_id = sp.post_id
          INNER JOIN weibo.comment AS c ON c.post_id = sp.post_id AND c.comment_id = sp.source_id
          LEFT JOIN weibo.user AS u FINAL ON u.uid = c.user_id
          {engagement_join}
          WHERE {where_common}
            AND sp.source_type = 'comment'
            {q_filter_comment}
          GROUP BY
            sp.source_type, sp.source_id, sp.post_id, sp.source_created_at, c.text_raw,
            sp.pred_label, sp.pred_label_id, sp.confidence, sp.second_label, sp.margin,
            u.verified, u.profile_tier, e.interaction_count
        )
        ORDER BY evidence_score DESC
        LIMIT {limit}
    """
