<template>
  <div class="page">
    <div class="card">
      <h2>{{ t('home.title') }}</h2>
      <p class="hint">{{ t('home.hint') }}</p>
      <div class="toolbar" style="margin-top:16px;">
        <button :disabled="busy" @click="run('buildAll')">{{ t('home.buildAll') }}</button>
        <button class="ghost" :disabled="busy" @click="run('buildConcepts')">{{ t('home.buildConcepts') }}</button>
        <button class="ghost" :disabled="busy" @click="run('buildInstances')">{{ t('home.buildInstances') }}</button>
        <button class="danger" :disabled="busy" @click="run('clear')">{{ t('home.clear') }}</button>
        <button class="ghost" :disabled="busy" @click="loadStats">{{ t('home.refreshStats') }}</button>
        <button class="ghost" :disabled="busy" @click="run('migrateSource')">{{ t('home.migrateSource') }}</button>
        <button class="ghost" :disabled="busy" @click="run('buildFunctions')">{{ t('home.buildFunctions') }}</button>
        <button class="ghost" :disabled="busy" @click="run('buildRules')">{{ t('home.buildRules') }}</button>
      </div>
      <div v-if="message" class="message" :class="messageType">{{ message }}</div>
    </div>

    <div class="grid">
      <div class="card">
        <h3>{{ t('home.neo4jStatus') }}</h3>
        <div class="kv-grid" v-if="stats">
          <div class="kv"><span>{{ t('home.concepts') }}</span><b>{{ stats.neo4j.concepts }}</b></div>
          <div class="kv"><span>{{ t('home.conceptRelations') }}</span><b>{{ stats.neo4j.concept_relations }}</b></div>
          <div class="kv"><span>{{ t('home.instances') }}</span><b>{{ stats.neo4j.instances }}</b></div>
          <div class="kv"><span>{{ t('home.instanceRelations') }}</span><b>{{ stats.neo4j.instance_relations }}</b></div>
        </div>
        <h4 v-if="stats" style="margin-top:16px;">{{ t('home.instanceDist') }}</h4>
        <div class="kv-grid" v-if="stats">
          <div class="kv" v-for="(n,k) in stats.neo4j.by_label" :key="k">
            <span>{{ k }}</span><b>{{ n }}</b>
          </div>
        </div>
        <h4 v-if="stats && stats.neo4j.source_distribution" style="margin-top:16px;">{{ t('home.sourceDist') }}</h4>
        <div class="kv-grid" v-if="stats && stats.neo4j.source_distribution">
          <div class="kv" v-for="(n,k) in stats.neo4j.source_distribution" :key="k">
            <span>{{ k }}</span><b>{{ n }}</b>
          </div>
        </div>
        <h4 v-if="stats && stats.neo4j.rel_source_distribution" style="margin-top:16px;">{{ t('home.relSourceDist') }}</h4>
        <div class="kv-grid" v-if="stats && stats.neo4j.rel_source_distribution">
          <div class="kv" v-for="(n,k) in stats.neo4j.rel_source_distribution" :key="k">
            <span>{{ k }}</span><b>{{ n }}</b>
          </div>
        </div>
      </div>

      <div class="card">
        <h3>{{ t('home.mysqlData') }}</h3>
        <div class="kv-grid" v-if="stats">
          <div class="kv" v-for="(n,k) in stats.mysql" :key="k">
            <span>{{ k }}</span><b>{{ n }}</b>
          </div>
        </div>
      </div>
    </div>

    <div class="card">
      <h3>{{ t('home.conceptDef') }}</h3>
      <div v-if="schemaInfo">
        <h4>{{ t('home.conceptsFromTables') }}</h4>
        <div class="concept-list">
          <div v-for="c in schemaInfo.concepts" :key="c.name" class="concept-pill" :style="{ borderColor: c.color }">
            <span class="dot" :style="{ background: c.color }"></span>
            <b>{{ tField(c.label, c.name) }}</b>
            <span class="muted">{{ c.name }} · {{ c.table }}</span>
          </div>
        </div>
        <h4 style="margin-top:16px;">{{ t('home.conceptRelationsFromFK') }}</h4>
        <table class="rel-table">
          <thead>
            <tr><th>{{ t('home.thSource') }}</th><th>{{ t('home.thRelation') }}</th><th>{{ t('home.thTarget') }}</th><th>{{ t('home.thOrigin') }}</th></tr>
          </thead>
          <tbody>
            <tr v-for="r in schemaInfo.concept_relations" :key="r.name+r.via">
              <td>{{ r.source }}</td>
              <td><span class="tag">{{ tField(r.label, r.name) }}</span> {{ r.name }}</td>
              <td>{{ r.target }}</td>
              <td class="muted">{{ r.via }}</td>
            </tr>
          </tbody>
        </table>
      </div>
    </div>
  </div>
</template>

<script setup>
import { ref, onMounted } from 'vue'
import api from '../api.js'
import { t, tField } from '../i18n.js'

const stats = ref(null)
const schemaInfo = ref(null)
const busy = ref(false)
const message = ref('')
const messageType = ref('info')

async function loadStats() {
  try { stats.value = await api.stats() }
  catch (e) { showMessage(t('home.msgStatsError') + '：' + (e?.response?.data?.error || e.message), 'error') }
}

async function loadSchema() {
  try { schemaInfo.value = await api.schema() }
  catch (e) { showMessage(t('home.msgSchemaError') + '：' + e.message, 'error') }
}

async function run(action) {
  busy.value = true
  showMessage(t('home.msgRunning') + ': ' + action + ' ...', 'info')
  try {
    const res = await api[action]()
    showMessage(t('home.msgDone') + ': ' + JSON.stringify(res), 'success')
    await loadStats()
  } catch (e) {
    showMessage(t('home.msgFail') + '：' + (e?.response?.data?.error || e.message), 'error')
  } finally {
    busy.value = false
  }
}

function showMessage(m, type='info') {
  message.value = m
  messageType.value = type
}

onMounted(() => { loadSchema(); loadStats() })
</script>

<style scoped>
.page { display: flex; flex-direction: column; gap: 16px; }
h2 { font-size: 20px; margin-bottom: 4px; }
h3 { font-size: 16px; margin-bottom: 12px; }
h4 { font-size: 13px; color: #6b7280; margin-bottom: 8px; }
.hint { color: #6b7280; font-size: 13px; line-height: 1.6; }
.grid { display: grid; grid-template-columns: 1fr 1fr; gap: 16px; }
.kv-grid { display: grid; grid-template-columns: repeat(auto-fill, minmax(160px, 1fr)); gap: 8px; }
.kv {
  background: #f9fafb;
  padding: 8px 12px;
  border-radius: 6px;
  display: flex;
  justify-content: space-between;
  align-items: center;
  font-size: 13px;
}
.kv b { color: #2563eb; }
.message {
  margin-top: 12px;
  padding: 8px 12px;
  border-radius: 4px;
  font-size: 13px;
  word-break: break-all;
}
.message.info { background: #eff6ff; color: #1d4ed8; }
.message.success { background: #ecfdf5; color: #059669; }
.message.error { background: #fef2f2; color: #dc2626; }

.concept-list { display: flex; flex-wrap: wrap; gap: 8px; }
.concept-pill {
  display: inline-flex; align-items: center; gap: 6px;
  border: 2px solid #e5e7eb;
  padding: 6px 12px;
  border-radius: 999px;
  font-size: 13px;
}
.dot { display: inline-block; width: 10px; height: 10px; border-radius: 50%; }
.muted { color: #9ca3af; font-size: 12px; }

.rel-table { width: 100%; border-collapse: collapse; font-size: 13px; }
.rel-table th, .rel-table td { padding: 6px 8px; text-align: left; border-bottom: 1px solid #f3f4f6; }
.rel-table th { color: #6b7280; font-weight: 500; }
</style>
