<template>
  <div class="page">
    <div class="card header">
      <div>
        <h2>{{ t('concept.title') }}</h2>
        <p class="hint">{{ t('concept.hint') }}</p>
      </div>
      <div class="toolbar">
        <button class="ghost" @click="reload">{{ t('concept.refresh') }}</button>
      </div>
    </div>
    <div class="card graph-card">
      <ForceGraph
        v-if="data"
        :nodes="data.nodes"
        :edges="data.edges"
        :color-map="colorMap"
      />
      <div v-else class="empty">{{ status }}</div>
    </div>
  </div>
</template>

<script setup>
import { ref, onMounted, computed } from 'vue'
import api from '../api.js'
import ForceGraph from '../components/ForceGraph.vue'
import { t, locale } from '../i18n.js'

const raw = ref(null)
const status = ref(t('concept.loading'))

const data = computed(() => {
  if (!raw.value) return null
  const en = locale.value === 'en'
  return {
    nodes: raw.value.nodes.map(n => ({
      id: n.id,
      // circle text / tooltip title: English name in en mode, Chinese label in zh mode
      name: en ? (n.name || n.label) : (n.label || n.name),
      label: n.name, // legend / subtitle (always English identifier)
      color: n.color,
      props: { table: n.table, source: n.source, text_source_ids: n.text_source_ids },
    })),
    edges: raw.value.edges.map(e => ({
      source: e.source, target: e.target,
      label: en ? (e.name || e.label) : (e.label || e.name),
      type: e.name,
    })),
  }
})

const colorMap = computed(() => {
  if (!data.value) return {}
  const m = {}
  for (const n of data.value.nodes) m[n.label] = n.color
  return m
})

async function reload() {
  status.value = t('concept.loading')
  raw.value = null
  try {
    const g = await api.conceptGraph()
    if (!g.nodes || g.nodes.length === 0) {
      status.value = t('concept.notBuilt')
      return
    }
    raw.value = g
  } catch (e) {
    status.value = t('concept.loadFail') + ': ' + e.message
  }
}

onMounted(reload)
</script>

<style scoped>
.page { height: 100%; display: flex; flex-direction: column; gap: 12px; }
.header { display: flex; justify-content: space-between; align-items: center; }
.graph-card { flex: 1; min-height: 400px; padding: 0; overflow: hidden; }
.empty { display: flex; align-items: center; justify-content: center; height: 100%; color: #6b7280; }
h2 { font-size: 20px; }
.hint { color: #6b7280; font-size: 13px; }
</style>
