<template>
  <div class="page">
    <div class="card header">
      <div>
        <h2>{{ t('reasoning.title') }}</h2>
        <p class="hint">{{ t('reasoning.hint') }}</p>
      </div>
    </div>

    <!-- 推理类型选择 -->
    <div class="type-cards">
      <div
        v-for="tp in types"
        :key="tp.key"
        class="type-card"
        :class="{ active: selectedType === tp.key }"
        @click="selectedType = tp.key"
      >
        <h4>{{ tp.label }}</h4>
        <p>{{ tp.desc }}</p>
      </div>
    </div>

    <!-- 输入区 -->
    <div class="input-panel card">
      <div class="input-row">
        <div class="field">
          <label>{{ t('reasoning.seedEntity') }}</label>
          <input
            v-model="seedName"
            list="entity-list"
            :placeholder="t('reasoning.seedPlaceholder')"
          />
          <datalist id="entity-list">
            <option v-for="e in allEntities" :key="e.id" :value="e.name">
              {{ e.name }} ({{ e.label }})
            </option>
          </datalist>
        </div>
        <div class="field">
          <label>{{ t('reasoning.entityType') }}</label>
          <select v-model="seedLabel">
            <option value="Event">{{ t('reasoning.typeEvent') }}</option>
            <option value="Organization">{{ t('reasoning.typeOrganization') }}</option>
            <option value="Person">{{ t('reasoning.typePerson') }}</option>
            <option value="Country">{{ t('reasoning.typeCountry') }}</option>
            <option value="Equipment">{{ t('reasoning.typeEquipment') }}</option>
            <option value="Facility">{{ t('reasoning.typeFacility') }}</option>
          </select>
        </div>
        <div class="field">
          <label>{{ t('reasoning.depth') }}</label>
          <input type="range" v-model.number="depth" min="1" max="4" />
          <span class="range-val">{{ depth }}</span>
        </div>
      </div>
      <div class="toolbar">
        <button :disabled="busy || !seedName.trim()" @click="analyze">{{ busy ? t('reasoning.thinking') : t('reasoning.analyze') }}</button>
      </div>
      <div v-if="message" class="message" :class="messageType">{{ message }}</div>
    </div>

    <!-- 结果区 -->
    <div v-if="result" class="result-layout">
      <!-- 指标面板 -->
      <div class="metrics card" v-if="result.metrics">
        <div class="metric" v-for="(v, k) in result.metrics" :key="k">
          <span class="metric-key">{{ metricLabel(k) }}</span>
          <span class="metric-val">{{ v }}</span>
        </div>
      </div>

      <div class="result-body">
        <!-- 推理报告 -->
        <div class="report-panel card">
          <h3>{{ t('reasoning.report') }}</h3>
          <pre class="report-text">{{ result.report }}</pre>
        </div>

        <!-- 关联子图 -->
        <div class="graph-panel card">
          <h3>{{ t('reasoning.subgraph') }}</h3>
          <div class="graph-wrap">
            <ForceGraph
              v-if="result.subgraph && result.subgraph.nodes.length"
              :nodes="result.subgraph.nodes"
              :edges="result.subgraph.edges"
            />
            <div v-else class="empty">{{ t('reasoning.noSubgraph') }}</div>
          </div>
        </div>
      </div>
    </div>
  </div>
</template>

<script setup>
import { ref, computed, onMounted } from 'vue'
import api from '../api.js'
import ForceGraph from '../components/ForceGraph.vue'
import { t } from '../i18n.js'

const types = computed(() => [
  {
    key: 'event_correlation',
    label: t('reasoning.type.eventCorr'),
    desc: t('reasoning.type.eventCorrDesc'),
  },
  {
    key: 'participant_network',
    label: t('reasoning.type.participant'),
    desc: t('reasoning.type.participantDesc'),
  },
  {
    key: 'temporal_chain',
    label: t('reasoning.type.temporal'),
    desc: t('reasoning.type.temporalDesc'),
  },
])

const selectedType = ref('event_correlation')
const seedName = ref('')
const seedLabel = ref('Event')
const depth = ref(2)
const busy = ref(false)
const message = ref('')
const messageType = ref('info')
const result = ref(null)
const allEntities = ref([])

const metricKeys = {
  related_events: 'reasoning.metric.relatedEvents',
  shared_participants: 'reasoning.metric.sharedParticipants',
  path_count: 'reasoning.metric.pathCount',
  event_count: 'reasoning.metric.eventCount',
  co_participant_count: 'reasoning.metric.coParticipant',
  chain_length: 'reasoning.metric.chainLength',
  region: 'reasoning.metric.region',
}

function metricLabel(k) {
  const key = metricKeys[k]
  return key ? t(key) : k
}

async function loadEntities() {
  try {
    const g = await api.instanceGraph({ limit: 500 })
    allEntities.value = (g.nodes || []).map(n => ({
      id: n.id,
      name: n.name,
      label: n.label,
    }))
  } catch (e) {
    console.error(t('reasoning.msgLoadEntitiesFail'), e)
  }
}

async function analyze() {
  if (!seedName.value.trim()) return
  busy.value = true
  message.value = ''
  result.value = null
  try {
    const res = await api.analyzeReasoning({
      type: selectedType.value,
      seed: { name: seedName.value.trim(), label: seedLabel.value },
      depth: depth.value,
    })
    result.value = res
    if (res.error) {
      message.value = res.error
      messageType.value = 'error'
    }
  } catch (e) {
    message.value = t('reasoning.msgRequestFail') + '：' + (e?.response?.data?.error || e.message)
    messageType.value = 'error'
  } finally {
    busy.value = false
  }
}

onMounted(loadEntities)
</script>

<style scoped>
.page { display: flex; flex-direction: column; gap: 16px; }
.header { display: flex; justify-content: space-between; align-items: center; }
h2 { font-size: 20px; }
.hint { color: #6b7280; font-size: 13px; }

.type-cards {
  display: grid;
  grid-template-columns: repeat(3, 1fr);
  gap: 12px;
}
@media (max-width: 900px) {
  .type-cards { grid-template-columns: 1fr; }
}
.type-card {
  padding: 14px;
  border: 2px solid #e5e7eb;
  border-radius: 8px;
  cursor: pointer;
  transition: all .2s;
}
.type-card:hover { border-color: #93c5fd; }
.type-card.active {
  border-color: #2563eb;
  background: #eff6ff;
}
.type-card h4 { font-size: 14px; margin-bottom: 4px; }
.type-card p { font-size: 12px; color: #6b7280; line-height: 1.5; }

.input-panel { display: flex; flex-direction: column; gap: 12px; }
.input-row {
  display: grid;
  grid-template-columns: 2fr 1fr 120px;
  gap: 12px;
  align-items: end;
}
@media (max-width: 900px) {
  .input-row { grid-template-columns: 1fr; }
}
.field { display: flex; flex-direction: column; gap: 4px; }
.field label { font-size: 12px; color: #6b7280; }
.field input, .field select {
  padding: 8px 10px;
  border: 1px solid #e5e7eb;
  border-radius: 6px;
  font-size: 13px;
  box-sizing: border-box;
}
.range-val { font-size: 13px; color: #2563eb; font-weight: 600; }

.toolbar { display: flex; gap: 8px; }

.result-layout { display: flex; flex-direction: column; gap: 12px; }

.metrics {
  display: flex;
  flex-wrap: wrap;
  gap: 12px;
}
.metric {
  background: #f9fafb;
  padding: 8px 14px;
  border-radius: 6px;
  display: flex;
  gap: 8px;
  align-items: center;
  font-size: 13px;
}
.metric-key { color: #6b7280; }
.metric-val { color: #2563eb; font-weight: 600; }

.result-body {
  display: grid;
  grid-template-columns: 1fr 1fr;
  gap: 16px;
}
@media (max-width: 1100px) {
  .result-body { grid-template-columns: 1fr; }
}

.report-panel { min-height: 300px; }
.report-panel h3 { font-size: 15px; margin-bottom: 10px; }
.report-text {
  font-size: 13px;
  line-height: 1.7;
  white-space: pre-wrap;
  font-family: inherit;
}

.graph-panel { min-height: 300px; }
.graph-panel h3 { font-size: 15px; margin-bottom: 10px; }
.graph-wrap {
  height: 360px;
  background: #fafafa;
  border-radius: 6px;
  overflow: hidden;
}
.empty { display: flex; align-items: center; justify-content: center; height: 100%; color: #6b7280; }

.message {
  margin-top: 8px;
  padding: 8px 12px;
  border-radius: 4px;
  font-size: 13px;
}
.message.error { background: #fef2f2; color: #dc2626; }
</style>
