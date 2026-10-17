<template>
  <div class="page">
    <div class="card header">
      <div>
        <h2>{{ t('qa.title') }}</h2>
        <p class="hint">{{ t('qa.hint') }}</p>
      </div>
    </div>

    <div class="qa-layout">
      <!-- 左侧输入区 -->
      <div class="input-panel card">
        <div class="mode-select">
          <label>{{ t('qa.mode') }}：</label>
          <select v-model="mode">
            <option value="auto">{{ t('qa.modeAuto') }}</option>
            <option value="cypher">{{ t('qa.modeCypher') }}</option>
            <option value="open">{{ t('qa.modeOpen') }}</option>
          </select>
        </div>
        <textarea
          v-model="question"
          rows="4"
          :placeholder="t('qa.placeholder')"
          @keydown.enter.prevent="ask"
        ></textarea>
        <div class="toolbar">
          <button :disabled="busy || !question.trim()" @click="ask">{{ busy ? t('qa.thinking') : t('qa.ask') }}</button>
        </div>
        <div v-if="message" class="message" :class="messageType">{{ message }}</div>
      </div>

      <!-- 右侧答案区 -->
      <div class="answer-panel card" v-if="result">
        <div class="answer-header">
          <span class="mode-tag">{{ result.mode === 'cypher' ? t('qa.modeCypher') : t('qa.modeOpen') }}</span>
        </div>
        <div class="answer-body">{{ result.answer }}</div>

        <!-- 来源引用 -->
        <div v-if="result.sources && result.sources.length" class="sources-section">
          <strong>{{ t('qa.sources') }}：</strong>
          <span v-for="(s, i) in result.sources" :key="i" class="source-tag">{{ s }}</span>
        </div>

        <!-- 溯源详情（可折叠） -->
        <div class="trace-section">
          <button class="ghost small" @click="showTrace = !showTrace">
            {{ showTrace ? t('qa.hideTrace') : t('qa.showTrace') }}
          </button>
          <div v-if="showTrace" class="trace-content">
            <!-- Cypher模式 -->
            <div v-if="result.mode === 'cypher'">
              <h4>{{ t('qa.generatedCypher') }}</h4>
              <pre>{{ result.cypher }}</pre>
              <h4>{{ t('qa.queryResult') }}</h4>
              <pre>{{ JSON.stringify(result.results, null, 2) }}</pre>
            </div>
            <!-- RAG模式 -->
            <div v-if="result.mode === 'rag' && result.subgraph">
              <h4>{{ t('qa.subgraph') }}</h4>
              <div class="subgraph-stats">{{ t('qa.subgraphStats', { n: result.subgraph.nodes.length, m: result.subgraph.edges.length }) }}</div>
              <div class="subgraph-wrap">
                <ForceGraph :nodes="result.subgraph.nodes" :edges="result.subgraph.edges" />
              </div>
            </div>
          </div>
        </div>
      </div>
    </div>
  </div>
</template>

<script setup>
import { ref } from 'vue'
import api from '../api.js'
import ForceGraph from '../components/ForceGraph.vue'
import { t, locale } from '../i18n.js'

const question = ref('')
const mode = ref('auto')
const busy = ref(false)
const message = ref('')
const messageType = ref('info')
const result = ref(null)
const showTrace = ref(false)

async function ask() {
  if (!question.value.trim()) return
  busy.value = true
  message.value = ''
  result.value = null
  showTrace.value = false
  try {
    const res = await api.askQuestion({ question: question.value.trim(), mode: mode.value, lang: locale.value })
    result.value = res
    if (res.error) {
      message.value = res.error
      messageType.value = 'error'
    }
  } catch (e) {
    message.value = t('qa.msgRequestFail') + '：' + (e?.response?.data?.error || e.message)
    messageType.value = 'error'
  } finally {
    busy.value = false
  }
}
</script>

<style scoped>
.page { display: flex; flex-direction: column; gap: 16px; }
.header { display: flex; justify-content: space-between; align-items: center; }
h2 { font-size: 20px; }
.hint { color: #6b7280; font-size: 13px; }

.qa-layout {
  display: grid;
  grid-template-columns: 1fr 1fr;
  gap: 16px;
  align-items: start;
}
@media (max-width: 1100px) {
  .qa-layout { grid-template-columns: 1fr; }
}

.input-panel { display: flex; flex-direction: column; gap: 10px; min-width: 0; }
.mode-select { display: flex; align-items: center; gap: 8px; font-size: 13px; }
.mode-select select {
  padding: 6px 10px;
  border: 1px solid #e5e7eb;
  border-radius: 6px;
  font-size: 13px;
}
textarea {
  width: 100%;
  padding: 10px;
  border: 1px solid #e5e7eb;
  border-radius: 6px;
  font-size: 14px;
  resize: vertical;
  box-sizing: border-box;
}
.toolbar { display: flex; gap: 8px; }

.answer-panel { min-height: 200px; min-width: 0; }
.answer-header { margin-bottom: 10px; }
.mode-tag {
  background: #dbeafe;
  color: #1d4ed8;
  padding: 2px 8px;
  border-radius: 4px;
  font-size: 12px;
}
.answer-body {
  font-size: 15px;
  line-height: 1.7;
  white-space: pre-wrap;
  overflow-wrap: anywhere;
}

.sources-section {
  margin-top: 12px;
  padding-top: 10px;
  border-top: 1px solid #f3f4f6;
  font-size: 12px;
}
.source-tag {
  background: #f3f4f6;
  color: #374151;
  padding: 2px 6px;
  border-radius: 4px;
  margin-right: 4px;
  font-size: 12px;
}

.trace-section { margin-top: 12px; }
.trace-content {
  margin-top: 8px;
  background: #f9fafb;
  padding: 10px;
  border-radius: 6px;
  font-size: 12px;
}
.trace-content h4 { font-size: 12px; color: #6b7280; margin: 8px 0 4px; }
.trace-content pre {
  background: #fff;
  padding: 8px;
  border-radius: 4px;
  border: 1px solid #e5e7eb;
  overflow: auto;
  max-height: 200px;
  white-space: pre-wrap;
  overflow-wrap: anywhere;
}
.subgraph-stats { color: #6b7280; font-size: 12px; margin-bottom: 6px; }
.subgraph-wrap {
  height: 280px;
  background: #fff;
  border: 1px solid #e5e7eb;
  border-radius: 6px;
  overflow: hidden;
}

button.small { padding: 4px 10px; font-size: 12px; }
.message {
  margin-top: 8px;
  padding: 8px 12px;
  border-radius: 4px;
  font-size: 13px;
}
.message.info { background: #eff6ff; color: #1d4ed8; }
.message.error { background: #fef2f2; color: #dc2626; }
</style>
