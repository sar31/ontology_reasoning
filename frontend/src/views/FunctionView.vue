<template>
  <div class="page">
    <div class="card header">
      <div>
        <h2>{{ t('function.title') }}</h2>
        <p class="hint">{{ t('function.hint') }}</p>
      </div>
      <div class="toolbar">
        <button :disabled="busy" @click="initFunctions">{{ t('function.initNodes') }}</button>
        <button class="ghost" @click="reload">{{ t('function.refresh') }}</button>
      </div>
    </div>
    <div v-if="message" class="message" :class="messageType">{{ message }}</div>

    <!-- Category Tabs -->
    <div class="tabs">
      <button
        v-for="tab in tabs"
        :key="tab.key"
        class="tab"
        :class="{ active: activeTab === tab.key }"
        @click="activeTab = tab.key"
      >
        {{ tab.label }}
        <span class="count">{{ countByCategory(tab.key) }}</span>
      </button>
    </div>

    <div class="card">
      <table class="data-table" v-if="filteredFunctions.length">
        <thead>
          <tr>
            <th>{{ t('function.thOrder') }}</th>
            <th>{{ t('function.thName') }}</th>
            <th>{{ t('function.thCategory') }}</th>
            <th>{{ t('function.thTargetLayer') }}</th>
            <th>{{ t('function.thOpType') }}</th>
            <th>{{ t('function.thDesc') }}</th>
          </tr>
        </thead>
        <tbody>
          <tr v-for="f in filteredFunctions" :key="f.id">
            <td>{{ f.order }}</td>
            <td><b>{{ f.name }}</b></td>
            <td><span class="tag" :class="f.category">{{ categoryLabel(f.category) }}</span></td>
            <td>{{ targetLabel(f.target_layer) }}</td>
            <td>{{ opLabel(f.operation_type) }}</td>
            <td class="muted">{{ f.description }}</td>
          </tr>
        </tbody>
      </table>
      <div v-else class="empty">{{ t('function.empty') }}</div>
    </div>
  </div>
</template>

<script setup>
import { ref, computed, onMounted } from 'vue'
import api from '../api.js'
import { t, tFunction } from '../i18n.js'

const functions = ref([])
const busy = ref(false)
const message = ref('')
const messageType = ref('info')
const activeTab = ref('construction')

const tabs = computed(() => [
  { key: 'construction', label: t('function.cat.construction') },
  { key: 'domain', label: t('function.cat.domain') },
])

const displayFunctions = computed(() => functions.value.map(tFunction))

const filteredFunctions = computed(() =>
  displayFunctions.value.filter(f => f.category === activeTab.value)
)

function countByCategory(cat) {
  return functions.value.filter(f => f.category === cat).length
}

function categoryLabel(cat) {
  const key = { construction: 'function.cat.construction', domain: 'function.cat.domain' }[cat]
  return key ? t(key) : cat
}

function targetLabel(tl) {
  const key = { concept: 'function.target.concept', instance: 'function.target.instance', group: 'function.target.group' }[tl]
  return key ? t(key) : tl
}

function opLabel(o) {
  const key = { node: 'function.op.node', relation: 'function.op.relation', analysis: 'function.op.analysis' }[o]
  return key ? t(key) : o
}

async function reload() {
  try {
    functions.value = await api.functions()
  } catch (e) {
    showMessage(t('function.msgLoadFail') + ': ' + e.message, 'error')
  }
}

async function initFunctions() {
  busy.value = true
  try {
    await api.buildFunctions()
    showMessage(t('function.msgInitOk'), 'success')
    await reload()
  } catch (e) {
    showMessage(t('function.msgInitFail') + ': ' + e.message, 'error')
  } finally {
    busy.value = false
  }
}

function showMessage(m, type='info') {
  message.value = m
  messageType.value = type
}

onMounted(reload)
</script>

<style scoped>
.page { display: flex; flex-direction: column; gap: 16px; }
.header { display: flex; justify-content: space-between; align-items: center; flex-wrap: wrap; gap: 8px; }
h2 { font-size: 20px; margin: 0; }
.hint { color: #6b7280; font-size: 13px; margin: 4px 0 0 0; }
.empty { padding: 40px; text-align: center; color: #6b7280; }
.message { padding: 8px 12px; border-radius: 4px; font-size: 13px; }
.message.info { background: #eff6ff; color: #1d4ed8; }
.message.success { background: #ecfdf5; color: #059669; }
.message.error { background: #fef2f2; color: #dc2626; }

/* Tabs */
.tabs { display: flex; gap: 4px; background: #f3f4f6; padding: 4px; border-radius: 8px; width: fit-content; }
.tab {
  padding: 6px 18px;
  border: none;
  border-radius: 6px;
  background: transparent;
  color: #6b7280;
  font-size: 14px;
  cursor: pointer;
  transition: all .2s;
}
.tab:hover { color: #374151; }
.tab.active { background: #fff; color: #111827; box-shadow: 0 1px 3px rgba(0,0,0,.1); }
.count { margin-left: 6px; font-size: 11px; color: #9ca3af; }

/* Table */
.data-table { width: 100%; border-collapse: collapse; font-size: 13px; }
.data-table th, .data-table td { padding: 8px 10px; text-align: left; border-bottom: 1px solid #f3f4f6; }
.data-table th { color: #6b7280; font-weight: 500; background: #f9fafb; }

/* Tags */
.tag { display: inline-block; padding: 2px 8px; border-radius: 4px; font-size: 12px; }
.tag.construction { background: #dbeafe; color: #1d4ed8; }
.tag.domain { background: #fef3c7; color: #92400e; }
.muted { color: #9ca3af; }
</style>
