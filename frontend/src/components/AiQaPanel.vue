<script setup lang="ts">
import { computed, onMounted, ref, watch } from 'vue'
import { api } from '@/api/client'
import type { QaMessage, QaMessageMetadata, QaResponse, QaSession, RangeKey } from '@/types/api'
import { formatDate } from '@/utils/format'

const props = withDefaults(defineProps<{
  range: RangeKey
  topicId?: string | null
  title?: string
}>(), {
  topicId: null,
  title: 'AI 多轮问答',
})

const sessions = ref<QaSession[]>([])
const messages = ref<QaMessage[]>([])
const sessionId = ref<string | null>(null)
const question = ref('')
const loading = ref(false)
const historyLoading = ref(false)
const error = ref('')
const storeUnavailable = ref(false)

const scopeLabel = computed(() => (props.topicId ? '话题上下文' : '总览上下文'))
const activeSession = computed(() => sessions.value.find((x) => x.session_id === sessionId.value) || null)
const visibleSessions = computed(() => sessions.value.filter((item) => {
  const sameRange = item.range === props.range
  const sameTopic = props.topicId ? item.topic_id === props.topicId : !item.topic_id
  return sameRange && sameTopic
}))
const defaultPrompts = computed(() => props.topicId
  ? ['为什么这个话题风险高？', '主要是谁在带动？', '有哪些代表性证据？', '这些证据可靠吗？']
  : ['当前主要风险是什么？', '哪些话题最值得关注？', '哪些账号需要关注？', '评论能代表全网吗？'])
const suggestedPrompts = computed(() => {
  const lastAssistant = [...messages.value].reverse().find((x) => x.role === 'assistant')
  const suggestions = lastAssistant?.metadata?.suggested_next_questions || []
  return suggestions.length ? suggestions : defaultPrompts.value
})

function emptyMeta(): QaMessageMetadata {
  return {
    key_points: [],
    evidence_refs: [],
    used_tools: [],
    caveats: [],
    suggested_next_questions: [],
    llm_model: '',
  }
}

function responseToMessage(resp: QaResponse): QaMessage {
  return {
    role: 'assistant',
    content: resp.answer,
    created_at: resp.generated_at,
    metadata: {
      key_points: resp.key_points,
      evidence_refs: resp.evidence_refs,
      used_tools: resp.used_tools,
      caveats: resp.caveats,
      suggested_next_questions: resp.suggested_next_questions,
      llm_model: resp.llm_model,
    },
  }
}

function markError(e: unknown) {
  const message = (e as Error).message
  error.value = message
  if (message.includes('Redis') || message.includes('QA 会话功能需要')) storeUnavailable.value = true
}

async function loadSessions() {
  historyLoading.value = true
  try {
    const resp = await api.qaSessions(30)
    sessions.value = resp.sessions
    storeUnavailable.value = false
  } catch (e) {
    markError(e)
  } finally {
    historyLoading.value = false
  }
}

async function loadSession(id: string) {
  if (loading.value) return
  historyLoading.value = true
  error.value = ''
  try {
    const resp = await api.qaSession(id)
    sessionId.value = resp.session.session_id
    messages.value = resp.messages
    storeUnavailable.value = false
  } catch (e) {
    markError(e)
  } finally {
    historyLoading.value = false
  }
}

function newChat() {
  sessionId.value = null
  messages.value = []
  question.value = ''
  error.value = ''
}

async function send(text?: string) {
  const content = (text ?? question.value).trim()
  if (!content || loading.value || storeUnavailable.value) return
  question.value = ''
  error.value = ''
  loading.value = true
  messages.value.push({
    role: 'user',
    content,
    created_at: new Date().toISOString(),
    metadata: emptyMeta(),
  })
  try {
    const resp = await api.askQa({
      sessionId: sessionId.value,
      range: props.range,
      topicId: props.topicId,
      question: content,
    })
    sessionId.value = resp.session_id
    messages.value.push(responseToMessage(resp))
    await loadSessions()
  } catch (e) {
    markError(e)
  } finally {
    loading.value = false
  }
}

watch(() => [props.range, props.topicId] as const, () => {
  newChat()
})

onMounted(() => { loadSessions() })
</script>

<template>
  <section class="qa-card">
    <div class="qa-head">
      <div>
        <p class="eyebrow">LLM / QA AGENT</p>
        <h2 class="qa-title">{{ title }} <em>{{ scopeLabel }}</em></h2>
      </div>
      <div class="head-actions">
        <button class="ghost-btn" :disabled="historyLoading" @click="loadSessions">刷新历史</button>
        <button class="ghost-btn primary" @click="newChat">新建对话</button>
      </div>
    </div>

    <p class="qa-note">受控 Agent 只调用 Dashboard 只读分析工具；会话记录保存在 Redis，默认 7 天滚动保留。</p>
    <p v-if="error" class="error">{{ error }}</p>

    <div class="qa-layout">
      <aside class="session-list">
        <div class="list-head">
          <span>历史会话</span>
          <small>{{ historyLoading ? '加载中' : `${visibleSessions.length} 条` }}</small>
        </div>
        <button
          v-for="item in visibleSessions"
          :key="item.session_id"
          class="session-item"
          :class="{ active: item.session_id === sessionId }"
          @click="loadSession(item.session_id)"
        >
          <strong>{{ item.title }}</strong>
          <span>{{ formatDate(item.updated_at) }} · {{ item.message_count }} msgs</span>
        </button>
        <p v-if="!visibleSessions.length && !historyLoading" class="empty-copy">当前上下文暂无 7 天内会话。</p>
      </aside>

      <div class="chat-panel">
        <div class="chat-meta">
          <span>{{ activeSession ? activeSession.title : '当前新对话' }}</span>
          <span>{{ scopeLabel }}</span>
          <span v-if="sessionId">{{ sessionId }}</span>
        </div>

        <div class="message-list">
          <article v-for="(msg, idx) in messages" :key="`${msg.created_at}-${idx}`" class="message" :class="msg.role">
            <p class="role">{{ msg.role === 'user' ? 'YOU' : 'AI' }}</p>
            <p class="content">{{ msg.content }}</p>

            <div v-if="msg.role === 'assistant'" class="answer-meta">
              <div v-if="msg.metadata.key_points.length" class="meta-block">
                <span>关键依据</span>
                <p>{{ msg.metadata.key_points.join('；') }}</p>
              </div>
              <div class="tag-row">
                <span v-for="tool in msg.metadata.used_tools" :key="tool">{{ tool }}</span>
                <span v-for="ref in msg.metadata.evidence_refs" :key="ref">{{ ref }}</span>
              </div>
              <div v-if="msg.metadata.caveats.length" class="meta-block muted">
                <span>口径限制</span>
                <p>{{ msg.metadata.caveats.join('；') }}</p>
              </div>
            </div>
          </article>

          <div v-if="!messages.length" class="empty-chat">
            输入问题开始多轮研判。Agent 会先选择只读数据工具，再基于工具结果回答。
          </div>
        </div>

        <div class="prompt-row">
          <button v-for="item in suggestedPrompts" :key="item" :disabled="loading || storeUnavailable" @click="send(item)">
            {{ item }}
          </button>
        </div>

        <div class="composer">
          <textarea
            v-model="question"
            :disabled="loading || storeUnavailable"
            rows="3"
            placeholder="继续追问，例如：那主要是谁在带动？"
            @keydown.meta.enter.prevent="send()"
            @keydown.ctrl.enter.prevent="send()"
          />
          <button :disabled="loading || storeUnavailable || !question.trim()" @click="send()">
            {{ loading ? '分析中...' : '发送' }}
          </button>
        </div>
      </div>
    </div>
  </section>
</template>

<style scoped>
.qa-card {
  margin: 32px var(--shell-pad-x) 0;
  padding: 26px;
  border: 1px solid rgba(142, 190, 255, 0.22);
  background:
    radial-gradient(circle at 100% 0, rgba(142, 190, 255, 0.1), transparent 32%),
    rgba(255,255,255,0.014);
}
.qa-head,
.head-actions,
.chat-meta,
.tag-row,
.composer,
.list-head {
  display: flex;
  align-items: center;
}
.qa-head {
  justify-content: space-between;
  gap: 20px;
}
.head-actions {
  gap: 10px;
}
.qa-title {
  margin-top: 10px;
  font-family: var(--serif-cn);
  font-size: 26px;
  color: var(--ink);
}
.qa-title em {
  margin-left: 12px;
  font-family: var(--serif);
  font-style: italic;
  font-weight: 300;
  color: #8ebeff;
  font-size: 0.62em;
}
.ghost-btn,
.composer button,
.prompt-row button {
  border: 1px solid var(--line);
  color: var(--ink-2);
  font-family: var(--mono);
  font-size: 10px;
  letter-spacing: 0.12em;
  transition: border-color 0.2s, color 0.2s, background 0.2s;
}
.ghost-btn {
  padding: 9px 12px;
}
.ghost-btn.primary,
.composer button {
  border-color: #8ebeff;
  color: #8ebeff;
}
.ghost-btn:hover:not(:disabled),
.prompt-row button:hover:not(:disabled) {
  border-color: #8ebeff;
  color: #8ebeff;
}
.qa-note,
.empty-copy,
.empty-chat {
  color: var(--muted);
  font-size: 12px;
  line-height: 1.8;
}
.qa-note {
  margin-top: 14px;
}
.error {
  margin-top: 14px;
  color: var(--alert);
  font-family: var(--mono);
  font-size: 12px;
}
.qa-layout {
  margin-top: 22px;
  display: grid;
  grid-template-columns: 260px 1fr;
  gap: 18px;
}
.session-list {
  border: 1px solid var(--line);
  padding: 14px;
  display: grid;
  align-content: start;
  gap: 10px;
  max-height: 620px;
  overflow: auto;
}
.list-head {
  justify-content: space-between;
  color: var(--muted);
  font-family: var(--mono);
  font-size: 10px;
  letter-spacing: 0.14em;
}
.session-item {
  padding: 12px;
  border: 1px solid transparent;
  background: rgba(255,255,255,0.025);
  text-align: left;
  display: grid;
  gap: 6px;
}
.session-item.active {
  border-color: #8ebeff;
}
.session-item strong {
  color: var(--ink);
  font-size: 13px;
  line-height: 1.5;
}
.session-item span {
  color: var(--muted);
  font-family: var(--mono);
  font-size: 10px;
}
.chat-panel {
  border: 1px solid var(--line);
  min-height: 560px;
  display: grid;
  grid-template-rows: auto 1fr auto auto;
}
.chat-meta {
  flex-wrap: wrap;
  gap: 10px;
  padding: 14px 16px;
  border-bottom: 1px solid var(--line);
  color: var(--muted);
  font-family: var(--mono);
  font-size: 10px;
  letter-spacing: 0.1em;
}
.message-list {
  padding: 18px;
  display: grid;
  align-content: start;
  gap: 14px;
  max-height: 520px;
  overflow: auto;
}
.message {
  max-width: 88%;
  padding: 14px;
  border: 1px solid var(--line);
  background: rgba(0,0,0,0.12);
}
.message.user {
  justify-self: end;
  border-color: rgba(245,195,74,0.25);
}
.message.assistant {
  justify-self: start;
  border-color: rgba(142,190,255,0.24);
}
.role {
  margin-bottom: 8px;
  color: var(--muted);
  font-family: var(--mono);
  font-size: 10px;
  letter-spacing: 0.18em;
}
.content {
  white-space: pre-wrap;
  color: var(--ink-2);
  line-height: 1.8;
  font-size: 14px;
}
.answer-meta {
  margin-top: 12px;
  display: grid;
  gap: 10px;
}
.meta-block {
  padding-top: 10px;
  border-top: 1px dashed var(--line);
}
.meta-block span {
  color: #8ebeff;
  font-family: var(--mono);
  font-size: 10px;
  letter-spacing: 0.16em;
}
.meta-block p {
  margin-top: 6px;
  color: var(--ink-2);
  font-size: 12px;
  line-height: 1.7;
}
.meta-block.muted span,
.meta-block.muted p {
  color: var(--muted);
}
.tag-row {
  flex-wrap: wrap;
  gap: 6px;
}
.tag-row span {
  padding: 4px 7px;
  border: 1px solid var(--line);
  color: var(--muted);
  font-family: var(--mono);
  font-size: 10px;
}
.prompt-row {
  padding: 12px 16px;
  border-top: 1px solid var(--line);
  display: flex;
  flex-wrap: wrap;
  gap: 8px;
}
.prompt-row button {
  padding: 7px 9px;
}
.composer {
  gap: 12px;
  padding: 14px 16px;
  border-top: 1px solid var(--line);
}
.composer textarea {
  flex: 1;
  resize: vertical;
  min-height: 74px;
  padding: 12px;
  border: 1px solid var(--line);
  background: rgba(0,0,0,0.18);
  color: var(--ink);
  line-height: 1.6;
}
.composer textarea:disabled,
.composer button:disabled,
.prompt-row button:disabled,
.ghost-btn:disabled {
  opacity: 0.5;
  cursor: not-allowed;
}
.composer button {
  align-self: stretch;
  min-width: 92px;
}
@media (max-width: 980px) {
  .qa-layout { grid-template-columns: 1fr; }
  .qa-head { align-items: flex-start; flex-direction: column; }
  .session-list { max-height: 220px; }
  .message { max-width: 100%; }
}
@media (max-width: 640px) {
  .composer { flex-direction: column; align-items: stretch; }
  .head-actions { flex-wrap: wrap; }
}
</style>
