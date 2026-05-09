"""Dashboard API constants."""

from __future__ import annotations

from datetime import timedelta, timezone

NEGATIVE_LABELS = ('愤怒', '悲伤', '恐惧')
NEGATIVE_LABEL_IDS = (1, 2, 3)
ANGER_FEAR_LABEL_IDS = (1, 3)

PRIMARY_MODEL_NAME = 'ERNIE mixed-v2'
PRIMARY_MODEL_VERSION = 'ernie-usual-mixed-v2'
PRIMARY_CHECKPOINT = 'runs/ernie-usual-mixed-v2/best'
SECONDARY_MODEL_NAME = 'BERT mixed-v2'
SECONDARY_MODEL_VERSION = 'bert-usual-mixed-v2'
SECONDARY_CHECKPOINT = 'runs/bert-usual-mixed-v2/best'
BERT_USAGE = '对照模型与困难样本发现工具'

DISPLAY_TZ = timezone(timedelta(hours=8))  # Asia/Shanghai
STABLE_DAY_THRESHOLD = 10000

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

RISK_TOPIC_CANDIDATE_LIMIT = 200
RISK_TOPIC_DEFAULT_LIMIT = 20
EVIDENCE_DEFAULT_LIMIT = 8
EVIDENCE_MAX_LIMIT = 30
TOPIC_DETAIL_ACTOR_DEFAULT_LIMIT = 8
ACTOR_DEFAULT_LIMIT = 20
ACTOR_MAX_LIMIT = 50
ACTOR_CANDIDATE_LIMIT = 300
INFLUENCE_DEFAULT_LIMIT = 80
INFLUENCE_MAX_LIMIT = 200
DISAGREEMENT_DEFAULT_LIMIT = 6
DISAGREEMENT_MAX_LIMIT = 30
LOW_CONFIDENCE_THRESHOLD = 0.70
LOW_MARGIN_THRESHOLD = 0.15
SOURCE_TYPES = ('hot', 'keyword', 'kol', 'retweet')
RISK_FACTOR_LABELS = {
    'negative_ratio': '负面占比',
    'negative_growth': '负面增长',
    'interaction_growth': '互动增量',
    'anger_fear': '愤怒/恐惧',
    'kol_verified': 'KOL/认证',
    'source_diversity': '入口扩散',
}
