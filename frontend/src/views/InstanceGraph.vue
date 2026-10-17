<template>
  <div class="page">
    <div class="card header">
      <div>
        <h2>{{ t('instance.title') }}</h2>
        <p class="hint">{{ t('instance.hint') }}</p>
      </div>
      <div class="toolbar">
        <label>{{ t('instance.labelFilter') }}：</label>
        <select v-model="label">
          <option value="">{{ t('instance.all') }}</option>
          <optgroup v-if="coreLabels.length" :label="t('instance.coreTypes')">
            <option v-for="l in coreLabels" :key="l.label" :value="l.label">{{ l.label }} ({{ l.count }})</option>
          </optgroup>
          <optgroup v-if="otherLabels.length" :label="t('instance.otherTypes')">
            <option v-for="l in otherLabels" :key="l.label" :value="l.label">{{ l.label }} ({{ l.count }})</option>
          </optgroup>
        </select>
        <label>{{ t('instance.count') }}：</label>
        <input type="number" v-model.number="limit" min="10" max="2000" step="10" style="width:80px;" />
        <button class="ghost" @click="reload">{{ t('instance.refresh') }}</button>
      </div>
    </div>
    <div class="card graph-card">
      <ForceGraph
        v-if="data && data.nodes.length"
        :nodes="data.nodes"
        :edges="data.edges"
      />
      <div v-else class="empty">{{ status }}</div>
    </div>
  </div>
</template>

<script setup>
import { ref, onMounted, computed, watch } from 'vue'
import api from '../api.js'
import ForceGraph from '../components/ForceGraph.vue'
import { t, locale } from '../i18n.js'

const raw = ref(null)
const status = ref(t('instance.loading'))
const CORE_LABELS = ['Country','Person','Organization','Equipment','Facility','Event']
const labelStats = ref([])   // [{ label, count }]
const label = ref('')
const limit = ref(300)

const coreLabels = computed(() => labelStats.value.filter(x => CORE_LABELS.includes(x.label)))
const otherLabels = computed(() => labelStats.value.filter(x => !CORE_LABELS.includes(x.label)))

const data = computed(() => raw.value)

async function loadLabels() {
  try {
    labelStats.value = await api.instanceLabels()
  } catch (e) {
    labelStats.value = []
  }
}

async function reload() {
  status.value = t('instance.loading')
  raw.value = null
  try {
    const g = await api.instanceGraph({ label: label.value, limit: limit.value, lang: locale.value })
    if (!g.nodes || g.nodes.length === 0) {
      status.value = t('instance.empty')
      return
    }
    raw.value = g
  } catch (e) {
    status.value = t('instance.loadFail') + ': ' + e.message
  }
}

onMounted(() => { loadLabels(); reload() })
watch(locale, reload)
</script>

<style scoped>
.page { height: 100%; display: flex; flex-direction: column; gap: 12px; }
.header { display: flex; justify-content: space-between; align-items: center; flex-wrap: wrap; gap: 8px; }
.toolbar label { font-size: 13px; color: #6b7280; }
.graph-card { flex: 1; min-height: 400px; padding: 0; overflow: hidden; }
.empty { display: flex; align-items: center; justify-content: center; height: 100%; color: #6b7280; }
h2 { font-size: 20px; }
.hint { color: #6b7280; font-size: 13px; }
</style>
