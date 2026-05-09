"""Evidence sample route."""

from __future__ import annotations

import base64
import json

from flask import Blueprint, jsonify, request

from .actors import decode_actor_evidence_token
from .config import ANGER_FEAR_LABEL_IDS, EVIDENCE_DEFAULT_LIMIT, EVIDENCE_MAX_LIMIT, LOW_MARGIN_THRESHOLD, NEGATIVE_LABEL_IDS, PRIMARY_MODEL_VERSION
from .utils import display_text, limit_arg, q_arg, resolve_window, round_float, to_float, to_int, topic_id_arg, utc_to_cst_iso


def register_evidence_routes(api: Blueprint, ck) -> None:
    @api.route('/evidence')
    def api_evidence():
        actor_token = request.args.get('actor_id', '').strip()
        actor_uid = decode_actor_evidence_token(actor_token) if actor_token else None
        return jsonify(evidence_samples(
            ck,
            resolve_window(ck),
            topic_id_arg(),
            limit_arg('limit', EVIDENCE_DEFAULT_LIMIT, EVIDENCE_MAX_LIMIT),
            q_arg(),
            request.args.get('cursor', '').strip(),
            actor_uid,
        ))


def evidence_samples(ck, window: dict, topic_id: int | None, limit: int,
                     q: str = '', cursor: str = '', actor_uid: int | None = None) -> dict:
    """返回 {samples, next_cursor}。

    keyset 分页：cursor 编码上一页最后一行的 (evidence_score, source, source_id)；
    服务端按 score DESC + source ASC + source_id ASC 排序，配合 (score, source, source_id)
    的字典序 WHERE 拿下一页。score 相同时 (source, source_id) 做 stable tie-breaker。
    """
    topic_filter = '' if topic_id is None else f'AND pt.topic_id = {topic_id}'
    actor_filter_post = '' if actor_uid is None else f'AND p.user_id = {actor_uid}'
    actor_filter_comment = '' if actor_uid is None else f'AND c.user_id = {actor_uid}'
    start = window['start_utc_str']
    end = window['end_utc_str']
    cursor_where = _cursor_where(_decode_cursor(cursor))
    rows = ck.query_json(_evidence_sql(
        start, end, topic_filter, q, cursor_where, limit,
        actor_filter_post, actor_filter_comment,
    ))
    samples = []
    for idx, row in enumerate(rows, 1):
        reason_parts = [row['pred_label']]
        if to_float(row.get('interaction_count')) > 0:
            reason_parts.append('高互动')
        if row.get('actor_role') == 'verified_actor':
            reason_parts.append('认证账号')
        if to_float(row.get('margin')) < LOW_MARGIN_THRESHOLD:
            reason_parts.append('低 margin')
        samples.append({
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

    next_cursor = None
    if rows and len(rows) >= limit:
        last = rows[-1]
        next_cursor = _encode_cursor(
            float(last.get('evidence_score') or 0),
            str(last.get('source') or ''),
            int(last.get('source_id') or 0),
        )
    return {'samples': samples, 'next_cursor': next_cursor}


def _encode_cursor(score: float, source_type: str, source_id: int) -> str:
    # source_id 是 UInt64，可能超 JS Number 安全范围；存字符串再 decode 时转 int。
    payload = json.dumps({'s': score, 't': source_type, 'i': str(source_id)},
                         ensure_ascii=False, separators=(',', ':'))
    return base64.urlsafe_b64encode(payload.encode('utf-8')).decode('ascii').rstrip('=')


def _decode_cursor(cursor: str) -> tuple[float, str, int] | None:
    if not cursor:
        return None
    try:
        pad = '=' * ((-len(cursor)) % 4)
        raw = base64.urlsafe_b64decode((cursor + pad).encode('ascii'))
        d = json.loads(raw)
        return float(d['s']), str(d['t']), int(d['i'])
    except (ValueError, KeyError, TypeError):
        return None


def _cursor_where(cursor: tuple[float, str, int] | None) -> str:
    if cursor is None:
        return ''
    score, st, sid = cursor
    st_esc = st.replace("'", "''")
    return f"""
      AND (
        evidence_score < {score}
        OR (evidence_score = {score} AND source > '{st_esc}')
        OR (evidence_score = {score} AND source = '{st_esc}' AND source_id > {sid})
      )
    """


def _evidence_sql(start: str, end: str, topic_filter: str, q: str,
                  cursor_where: str, limit: int,
                  actor_filter_post: str = '', actor_filter_comment: str = '') -> str:
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
          interaction_count,
          evidence_score
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
            {actor_filter_post}
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
            {actor_filter_comment}
          GROUP BY
            sp.source_type, sp.source_id, sp.post_id, sp.source_created_at, c.text_raw,
            sp.pred_label, sp.pred_label_id, sp.confidence, sp.second_label, sp.margin,
            u.verified, u.profile_tier, e.interaction_count
        )
        WHERE 1 = 1
          {cursor_where}
        ORDER BY evidence_score DESC, source ASC, source_id ASC
        LIMIT {limit}
    """
