export type RangeKey = 'all_available' | '24h' | '7d'
export type EmotionLabel = '积极' | '愤怒' | '悲伤' | '恐惧' | '惊讶' | '中性'

export interface MetaResponse {
  schema_version: string
  generated_at: string
  data_window: { start: string; end: string; available_days: number; is_partial_history: boolean }
  time_range_options: RangeKey[]
  model: { name: string; model_version: string; checkpoint: string }
  labels: EmotionLabel[]
  negative_labels: EmotionLabel[]
}

export interface OverviewResponse {
  post_count: number
  sampled_comment_count: number
  active_topic_count: number
  latest_interactions: number
  kol_entry_post_count: number
  verified_actor_count: number
  profile_tier_distribution: Record<string, number>
  negative_ratio: number
  risk_index: number
  avg_confidence: number
  low_confidence_count: number
  prediction_sample_count: number
}

export type EmotionCounts = Record<EmotionLabel, number>

export interface EmotionTimeseriesPoint {
  time: string
  granularity: 'day'
  counts: EmotionCounts
  negative_ratio: number
  avg_confidence: number
  total?: number
}

export type RiskLevel = 'high' | 'medium_high' | 'medium' | 'low'

export interface RiskTopic {
  topic_id: string
  title: string
  lead: string
  post_count: number
  risk_score: number
  risk_level: RiskLevel
  dominant_emotion: EmotionLabel
  negative_ratio: number
  negative_growth: number
  negative_growth_label: string
  interaction_growth: number
  interaction_growth_label: string
  latest_interactions: number
  sample_count: number
  post_sample_count: number
  sampled_comment_count: number
  kol_entry_count: number
  verified_actor_count: number
  source_mix: Record<string, number>
  emotion_counts: EmotionCounts
  avg_confidence: number
  risk_factors: Record<string, number>
  risk_factor_labels: Record<string, string>
  note: string
}

export interface TopicMeta {
  topic_id: string
  title: string
  lead: string
  read_count: number
  discuss_count: number
  first_seen_at: string | null
  last_seen_at: string | null
  post_count: number
  risk_score: number
  risk_level: RiskLevel
  dominant_emotion: EmotionLabel
  negative_ratio: number
  negative_growth: number
  negative_growth_label: string
  interaction_growth: number
  interaction_growth_label: string
  latest_interactions: number
  interaction_delta: number
  post_sample_count: number
  sampled_comment_count: number
  sample_count: number
  avg_confidence: number | null
  kol_entry_count: number
  verified_actor_count: number
  high_follower_actor_count: number
  risk_factors: Record<string, number>
  risk_factor_labels: Record<string, string>
  note: string
}

export interface EngagementPoint {
  time: string
  comments_count: number
  attitudes_count: number
  reposts_count: number
  interaction_count: number
}

export interface Actor {
  actor_id: string
  evidence_token: string
  display_name: string
  verified: boolean
  verified_type: number
  verified_reason: string
  profile_tier: number
  followers_bucket: string
  topic_count: number
  top_topic_id: string | null
  top_topic_title: string | null
  post_count: number
  comment_count: number
  sample_count: number
  dominant_emotion: EmotionLabel
  negative_ratio: number
  interaction_count: number
  interaction_contribution: number
  actor_influence_score: number
  roles: string[]
  emotion_counts: EmotionCounts
}

export interface EvidenceSample {
  sample_id: string
  source: 'post' | 'comment'
  source_id: string
  post_id: string
  topic_id: string | null
  created_at: string | null
  content: string
  pred_label: EmotionLabel
  confidence: number
  second_label: EmotionLabel
  margin: number
  interaction_count: number
  actor_role: string
  evidence_reason: string
}

export interface EvidenceResponse {
  samples: EvidenceSample[]
  next_cursor: string | null
}

export interface DataQualityResponse {
  comment_sampling_notice: string
  engagement_notice: string
  timezone_notice: string
  history_window_notice: string
  user_tier_notice: string
  post_discovery_notice: string
  profile_tier_distribution: Record<string, number>
  generated_from: string[]
}

export interface InfluenceEmotionPoint {
  actor_id: string
  display_name: string
  influence_score: number
  negative_ratio: number
  interaction_count: number
  dominant_emotion: EmotionLabel
  topic_id: string | null
  topic_title: string
  roles: string[]
}

export interface ModelEvalSlice {
  samples: number
  accuracy: number
  macro_f1: number
  per_class_f1: Record<EmotionLabel, number>
}

export interface BertComparison {
  name: string
  usage: string
  agreement_rate: number
  oracle_accuracy: number
  bert_accuracy: number
  bert_macro_f1: number
  ernie_only_correct: number | null
  bert_only_correct: number | null
}

export interface ModelQualityResponse {
  primary_model: string
  checkpoint: string
  business_eval: ModelEvalSlice | null
  smp_test: ModelEvalSlice | null
  confusion_matrix: number[][] | null
  confusion_labels: EmotionLabel[]
  top_confusions: { true: EmotionLabel; pred: EmotionLabel; count: number }[]
  bert_comparison: BertComparison | null
}

export interface DisagreementMatrixCell {
  ernie_label: EmotionLabel
  bert_label: EmotionLabel
  count: number
}

export interface DisagreementSample {
  source: 'post' | 'comment'
  source_id: string
  post_id: string
  created_at: string | null
  content: string
  ernie_label: EmotionLabel
  ernie_confidence: number | null
  ernie_margin: number | null
  bert_label: EmotionLabel
  bert_confidence: number | null
  bert_margin: number | null
}

export interface ModelDisagreementResponse {
  primary_model: string
  primary_model_version: string
  primary_checkpoint: string
  secondary_model: string
  secondary_model_version: string
  secondary_checkpoint: string
  secondary_usage: string
  samples_total: number
  agreement_count: number
  agreement_rate: number
  labels: EmotionLabel[]
  matrix: DisagreementMatrixCell[]
  top_disagreements: DisagreementSample[]
}

export interface TopicDetailResponse {
  topic: TopicMeta
  timeline: EmotionTimeseriesPoint[]
  emotion_distribution: {
    counts: EmotionCounts
    ratios: Record<EmotionLabel, number>
    total: number
    negative_count: number
    negative_ratio: number
    anger_fear_count: number
    anger_fear_ratio: number
  }
  engagement_curve: EngagementPoint[]
  source_mix: Record<string, number>
  source_counts: Record<string, number>
  top_actors: Actor[]
  evidence_samples: EvidenceSample[]
}
