"""Read-only dashboard tools exposed to the QA agent."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from .actors import actor_summary
from .disagreement import model_disagreement
from .evidence import evidence_samples
from .model_quality import model_quality_payload
from .risk import build_risk_topics
from .summary import data_quality_payload, emotion_timeseries_payload, overview_payload
from .topics import topic_detail


TOOL_DESCRIPTIONS = {
    'overview': '总览指标：样本量、负向比例、风险指数、互动量、账号分层。',
    'risk_topics': '高风险话题列表：风险分、负向占比、增长和关键账号信号。',
    'topic_detail': '当前话题详情：情绪分布、风险因子、来源构成、趋势和样本。',
    'actors': '关键账号：角色、影响力、负向比例、互动和关联话题。',
    'evidence': '代表性证据样本：文本片段、预测标签、置信度、margin 和理由。',
    'emotion_timeseries': '情绪趋势：按天聚合的标签分布、负向比例和平均置信度。',
    'model_quality': '模型质量：业务集/测试集指标、混淆和 BERT 对比。',
    'model_disagreement': '业务集 ERNIE 与 BERT 分歧矩阵和高置信分歧样本。',
    'data_quality': '数据口径：采样评论、情绪模型、风险分、时区和来源限制。',
}

DEFAULT_TOOL_LIMIT = 5
MAX_TOOL_LIMIT = 8
MAX_TOOL_CALLS = 3
TEXT_MAX_CHARS = 80
TIMESERIES_POINTS = 14


def default_tool_calls(topic_id: int | None) -> list[dict[str, Any]]:
    if topic_id is None:
        names = ['risk_topics', 'actors', 'evidence']
    else:
        names = ['topic_detail', 'actors', 'evidence']
    return [{'name': name, 'args': {'limit': DEFAULT_TOOL_LIMIT}} for name in names]


def sanitize_tool_calls(raw_calls: Any, topic_id: int | None) -> list[dict[str, Any]]:
    if not isinstance(raw_calls, list):
        return default_tool_calls(topic_id)
    calls: list[dict[str, Any]] = []
    seen: set[str] = set()
    for raw in raw_calls:
        if not isinstance(raw, dict):
            continue
        name = str(raw.get('name') or '').strip()
        if name not in TOOL_DESCRIPTIONS or name in seen:
            continue
        seen.add(name)
        args = raw.get('args') if isinstance(raw.get('args'), dict) else {}
        calls.append({'name': name, 'args': {'limit': _limit(args.get('limit'))}})
        if len(calls) >= MAX_TOOL_CALLS:
            break
    return calls or default_tool_calls(topic_id)


def execute_tool_calls(
    ck,
    project_root: Path,
    window: dict,
    topic_id: int | None,
    tool_calls: list[dict[str, Any]],
) -> tuple[list[dict[str, Any]], set[str]]:
    results: list[dict[str, Any]] = []
    evidence_ids: set[str] = set()
    for call in tool_calls:
        name = call['name']
        limit = _limit(call.get('args', {}).get('limit'))
        try:
            data, refs = _execute_one(ck, project_root, window, topic_id, name, limit)
            results.append({'name': name, 'data': data})
            evidence_ids.update(refs)
        except LookupError:
            results.append({'name': name, 'error': '当前话题不存在或没有可用数据'})
        except ValueError as exc:
            results.append({'name': name, 'error': str(exc)})
    return results, evidence_ids


def _execute_one(ck, project_root: Path, window: dict, topic_id: int | None,
                 name: str, limit: int) -> tuple[Any, set[str]]:
    if name == 'overview':
        return overview_payload(ck, window), set()
    if name == 'risk_topics':
        return [_risk_topic_payload(x) for x in build_risk_topics(ck, window, limit)], set()
    if name == 'topic_detail':
        if topic_id is None:
            raise ValueError('当前没有选中话题，无法读取话题详情')
        detail = topic_detail(ck, window, topic_id, evidence_limit=limit, actor_limit=limit)
        if detail is None:
            raise LookupError(topic_id)
        data = _topic_detail_payload(detail)
        return data, {x['sample_id'] for x in data.get('evidence_samples', [])}
    if name == 'actors':
        return [_actor_payload(x) for x in actor_summary(ck, window, topic_id, limit)], set()
    if name == 'evidence':
        samples = [_evidence_payload(x) for x in evidence_samples(ck, window, topic_id, limit)['samples']]
        return samples, {x['sample_id'] for x in samples}
    if name == 'emotion_timeseries':
        return emotion_timeseries_payload(ck, window)[-TIMESERIES_POINTS:], set()
    if name == 'model_quality':
        return _model_quality_payload(model_quality_payload(project_root)), set()
    if name == 'model_disagreement':
        return _model_disagreement_payload(model_disagreement(ck, limit)), set()
    if name == 'data_quality':
        return data_quality_payload(ck), set()
    raise ValueError('不支持的 QA 工具')


def _topic_detail_payload(detail: dict) -> dict:
    topic = detail['topic']
    return {
        'topic': {
            'topic_id': topic.get('topic_id'),
            'title': topic.get('title'),
            'lead': topic.get('lead'),
            'risk_score': topic.get('risk_score'),
            'risk_level': topic.get('risk_level'),
            'dominant_emotion': topic.get('dominant_emotion'),
            'negative_ratio': topic.get('negative_ratio'),
            'negative_growth_label': topic.get('negative_growth_label'),
            'interaction_growth_label': topic.get('interaction_growth_label'),
            'sample_count': topic.get('sample_count'),
            'latest_interactions': topic.get('latest_interactions'),
            'kol_entry_count': topic.get('kol_entry_count'),
            'verified_actor_count': topic.get('verified_actor_count'),
            'risk_factors': topic.get('risk_factors'),
        },
        'emotion_distribution': detail.get('emotion_distribution'),
        'source_counts': detail.get('source_counts'),
        'timeline': detail.get('timeline', [])[-TIMESERIES_POINTS:],
        'engagement_curve': detail.get('engagement_curve', [])[-TIMESERIES_POINTS:],
        'top_actors': [_actor_payload(x) for x in detail.get('top_actors', [])[:DEFAULT_TOOL_LIMIT]],
        'evidence_samples': [_evidence_payload(x) for x in detail.get('evidence_samples', [])[:DEFAULT_TOOL_LIMIT]],
    }


def _risk_topic_payload(item: dict) -> dict:
    return {
        'topic_id': item.get('topic_id'),
        'title': item.get('title'),
        'risk_score': item.get('risk_score'),
        'risk_level': item.get('risk_level'),
        'dominant_emotion': item.get('dominant_emotion'),
        'negative_ratio': item.get('negative_ratio'),
        'negative_growth_label': item.get('negative_growth_label'),
        'interaction_growth_label': item.get('interaction_growth_label'),
        'sample_count': item.get('sample_count'),
        'kol_entry_count': item.get('kol_entry_count'),
        'verified_actor_count': item.get('verified_actor_count'),
    }


def _actor_payload(item: dict) -> dict:
    return {
        'actor_id': item.get('actor_id'),
        'display_name': item.get('display_name'),
        'roles': item.get('roles'),
        'dominant_emotion': item.get('dominant_emotion'),
        'negative_ratio': item.get('negative_ratio'),
        'sample_count': item.get('sample_count'),
        'interaction_count': item.get('interaction_count'),
        'actor_influence_score': item.get('actor_influence_score'),
        'top_topic_title': item.get('top_topic_title'),
    }


def _evidence_payload(item: dict) -> dict:
    content = _trim(item.get('content') or '', TEXT_MAX_CHARS)
    return {
        'sample_id': item.get('sample_id'),
        'source': item.get('source'),
        'created_at': item.get('created_at'),
        'content': content,
        'pred_label': item.get('pred_label'),
        'confidence': item.get('confidence'),
        'second_label': item.get('second_label'),
        'margin': item.get('margin'),
        'interaction_count': item.get('interaction_count'),
        'evidence_reason': item.get('evidence_reason'),
    }


def _model_quality_payload(payload: dict) -> dict:
    return {
        'primary_model': payload.get('primary_model'),
        'checkpoint': payload.get('checkpoint'),
        'business_eval': payload.get('business_eval'),
        'smp_test': payload.get('smp_test'),
        'top_confusions': payload.get('top_confusions'),
        'bert_comparison': payload.get('bert_comparison'),
    }


def _model_disagreement_payload(payload: dict) -> dict:
    samples = []
    for item in payload.get('top_disagreements', [])[:DEFAULT_TOOL_LIMIT]:
        samples.append({
            'source': item.get('source'),
            'created_at': item.get('created_at'),
            'content': _trim(item.get('content') or '', TEXT_MAX_CHARS),
            'ernie_label': item.get('ernie_label'),
            'ernie_confidence': item.get('ernie_confidence'),
            'bert_label': item.get('bert_label'),
            'bert_confidence': item.get('bert_confidence'),
        })
    return {
        'primary_model': payload.get('primary_model'),
        'secondary_model': payload.get('secondary_model'),
        'secondary_usage': payload.get('secondary_usage'),
        'samples_total': payload.get('samples_total'),
        'agreement_rate': payload.get('agreement_rate'),
        'matrix': payload.get('matrix'),
        'top_disagreements': samples,
    }


def _limit(raw: Any) -> int:
    try:
        value = int(raw)
    except (TypeError, ValueError):
        value = DEFAULT_TOOL_LIMIT
    return max(1, min(value, MAX_TOOL_LIMIT))


def _trim(text: str, max_chars: int) -> str:
    text = str(text or '').strip()
    if len(text) <= max_chars:
        return text
    return text[:max_chars].rstrip() + '...'
