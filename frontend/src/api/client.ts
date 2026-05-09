import type {
  Actor, DataQualityResponse, EmotionTimeseriesPoint, EvidenceResponse, InfluenceEmotionPoint, MetaResponse,
  ModelDisagreementResponse, ModelQualityResponse,
  OverviewResponse, RangeKey, RiskTopic, TopicDetailResponse,
} from '@/types/api'

const BASE = '/api/dashboard'

async function fetchJSON<T>(path: string): Promise<T> {
  const r = await fetch(BASE + path)
  if (!r.ok) throw new Error(`HTTP ${r.status}: ${path}`)
  return r.json() as Promise<T>
}

export const api = {
  meta: () => fetchJSON<MetaResponse>('/meta'),
  overview: (range: RangeKey) => fetchJSON<OverviewResponse>(`/overview?range=${range}`),
  emotionTimeseries: (range: RangeKey) =>
    fetchJSON<EmotionTimeseriesPoint[]>(`/emotion-timeseries?range=${range}`),
  riskTopics: (range: RangeKey, limit = 10, q = '') => {
    const u = new URLSearchParams({ range, limit: String(limit) })
    if (q) u.set('q', q)
    return fetchJSON<RiskTopic[]>(`/risk-topics?${u}`)
  },
  topicDetail: (topicId: string, range: RangeKey, opts?: { limit?: number; actorLimit?: number }) => {
    const u = new URLSearchParams({ range })
    if (opts?.limit) u.set('limit', String(opts.limit))
    if (opts?.actorLimit) u.set('actor_limit', String(opts.actorLimit))
    return fetchJSON<TopicDetailResponse>(`/topics/${topicId}?${u}`)
  },
  actors: (range: RangeKey, limit = 30, topicId?: string | null) => {
    const u = new URLSearchParams({ range, limit: String(limit) })
    if (topicId) u.set('topic_id', topicId)
    return fetchJSON<Actor[]>(`/actors?${u}`)
  },
  influenceEmotion: (range: RangeKey, limit = 80, topicId?: string | null) => {
    const u = new URLSearchParams({ range, limit: String(limit) })
    if (topicId) u.set('topic_id', topicId)
    return fetchJSON<InfluenceEmotionPoint[]>(`/influence-emotion?${u}`)
  },
  evidence: (params: { range: RangeKey; topicId?: string | null; q?: string; cursor?: string; limit?: number; actorId?: string }) => {
    const u = new URLSearchParams({ range: params.range })
    if (params.topicId) u.set('topic_id', params.topicId)
    if (params.q) u.set('q', params.q)
    if (params.cursor) u.set('cursor', params.cursor)
    if (params.limit) u.set('limit', String(params.limit))
    if (params.actorId) u.set('actor_id', params.actorId)
    return fetchJSON<EvidenceResponse>(`/evidence?${u}`)
  },
  modelQuality: () => fetchJSON<ModelQualityResponse>('/model-quality'),
  modelDisagreement: (limit = 12) => fetchJSON<ModelDisagreementResponse>(`/model-disagreement?limit=${limit}`),
  dataQuality: () => fetchJSON<DataQualityResponse>('/data-quality'),
}
