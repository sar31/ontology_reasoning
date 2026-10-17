<template>
  <div class="page">
    <div class="card header">
      <div>
        <h2>{{ t('rules.title') }}</h2>
        <p class="hint">{{ t('rules.hint') }}</p>
      </div>
      <div class="toolbar">
        <button :disabled="busy" @click="initRules">{{ t('rules.initNodes') }}</button>
        <button class="ghost" @click="reload">{{ t('rules.refresh') }}</button>
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

    <div class="grid" v-if="filteredRules.length">
      <div class="card rule-card" v-for="r in filteredRules" :key="r.id">
        <div class="rule-header">
          <h3>{{ r.name }}</h3>
          <div>
            <span class="tag cat" :class="r.category">{{ r.category === 'construction' ? t('rules.cat.construction') : t('rules.cat.domain') }}</span>
            <span class="status" :class="{active: r.is_active}">{{ r.is_active ? t('rules.active') : t('rules.inactive') }}</span>
          </div>
        </div>
        <p class="desc">{{ r.description }}</p>
        <div class="meta">
          <span class="tag">{{ t('rules.triggerCondition') }}: {{ r.trigger_condition }}</span>
          <span class="tag">→ {{ r.function_name || r.action_function }}</span>
        </div>
        <div class="toolbar" style="margin-top:12px;">
          <button :disabled="busy || !r.is_active" @click="trigger(r.id)">{{ t('rules.trigger') }}</button>
        </div>
        <div v-if="results[r.id]" class="result">
          <div class="result-header">
            <span>{{ t('rules.result') }}</span>
            <button class="ghost small" @click="delete results[r.id]">{{ t('rules.collapse') }}</button>
          </div>
          <pre>{{ JSON.stringify(results[r.id], null, 2) }}</pre>
        </div>
      </div>
    </div>
    <div v-if="!rules.length" class="card empty">{{ t('rules.empty') }}</div>
  </div>
</template>

<script setup>
import { ref, computed, onMounted } from 'vue'
import api from '../api.js'
import { t, tRule } from '../i18n.js'

const rules = ref([])
const busy = ref(false)
const message = ref('')
const messageType = ref('info')
const results = ref({})
const activeTab = ref('construction')

const tabs = computed(() => [
  { key: 'construction', label: t('rules.cat.construction') },
  { key: 'domain', label: t('rules.cat.domain') },
])

const displayRules = computed(() => rules.value.map(tRule))

const filteredRules = computed(() =>
  displayRules.value.filter(r => r.category === activeTab.value)
)

function countByCategory(cat) {
  return rules.value.filter(r => r.category === cat).length
}

async function reload() {
  try {
    rules.value = await api.rules()
  } catch (e) {
    showMessage(t('rules.msgLoadFail') + ': ' + e.message, 'error')
  }
}

async function initRules() {
  busy.value = true
  try {
    await api.buildRules()
    showMessage(t('rules.msgInitOk'), 'success')
    await reload()
  } catch (e) {
    showMessage(t('rules.msgInitFail') + ': ' + e.message, 'error')
  } finally {
    busy.value = false
  }
}

async function trigger(id) {
  busy.value = true
  try {
    const res = await api.triggerRule(id)
    results.value[id] = res
    showMessage(t('rules.msgTriggerOk', { name: res.rule_name }), 'success')
  } catch (e) {
    showMessage(t('rules.msgTriggerFail') + ': ' + (e?.response?.data?.error || e.message), 'error')
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

/* Cards */
.grid { display: grid; grid-template-columns: repeat(auto-fill, minmax(340px, 1fr)); gap: 16px; }
.rule-card { display: flex; flex-direction: column; gap: 8px; }
.rule-header { display: flex; justify-content: space-between; align-items: flex-start; gap: 8px; }
.rule-header div { display: flex; gap: 4px; flex-shrink: 0; }
.rule-header h3 { font-size: 16px; margin: 0; }
.status { font-size: 11px; padding: 2px 8px; border-radius: 999px; background: #e5e7eb; color: #6b7280; }
.status.active { background: #dcfce7; color: #166534; }
.desc { color: #4b5563; font-size: 13px; line-height: 1.5; }
.meta { display: flex; gap: 6px; flex-wrap: wrap; }

/* Tags */
.tag { display: inline-block; padding: 2px 8px; border-radius: 4px; font-size: 11px; background: #f3f4f6; color: #4b5563; }
.tag.cat { font-size: 11px; }
.tag.cat.construction { background: #dbeafe; color: #1d4ed8; }
.tag.cat.domain { background: #fef3c7; color: #92400e; }

/* Result */
.result { margin-top: 8px; background: #f9fafb; padding: 10px; border-radius: 6px; overflow: auto; max-height: 260px; }
.result-header { display: flex; justify-content: space-between; margin-bottom: 6px; font-size: 12px; color: #6b7280; }
.result pre { font-size: 11px; color: #374151; margin: 0; white-space: pre-wrap; }
.small { font-size: 12px; padding: 2px 8px; }
</style>
