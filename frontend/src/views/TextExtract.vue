<template>
  <div class="page">
    <div class="card header">
      <div>
        <h2>{{ t('extract.title') }}</h2>
        <p class="hint">{{ t('extract.hint') }}</p>
      </div>
    </div>

    <div class="extract-layout">
      <!-- 左侧输入区 -->
      <div class="input-panel card">
        <div class="tabs">
          <button :class="{active: mode==='text'}" @click="mode='text'">{{ t('extract.tabText') }}</button>
          <button :class="{active: mode==='file'}" @click="mode='file'">{{ t('extract.tabFile') }}</button>
        </div>

        <div v-if="mode==='text'" class="input-area">
          <input v-model="title" :placeholder="t('extract.titlePlaceholder')" class="title-input" />
          <textarea v-model="text" rows="10" :placeholder="t('extract.textPlaceholder')"></textarea>
        </div>
        <div v-else class="input-area">
          <input type="file" ref="fileInput" accept=".txt,.md" @change="onFileChange" />
          <p class="hint">{{ t('extract.fileHint') }}</p>
        </div>

        <label class="review-toggle">
          <input type="checkbox" v-model="reviewMode" />
          <span>{{ t('extract.reviewMode') }}</span>
        </label>

        <div class="toolbar" style="margin-top:12px;">
          <button :disabled="busy || !canSubmit" @click="reviewMode ? preview() : submit()">
            {{ reviewMode ? t('extract.preview') : t('extract.extract') }}
          </button>
        </div>
        <div v-if="message" class="message" :class="messageType">{{ message }}</div>
      </div>

      <!-- 右侧审核面板 -->
      <div class="review-panel card" v-if="reviewMode && hasPreview">
        <h3>{{ t('extract.reviewPanel') }}</h3>
        <p class="hint">{{ t('extract.reviewHint') }}</p>

        <!-- 概念 -->
        <div class="review-section">
          <h4>{{ t('extract.concepts') }} ({{ previewData.concepts.length }})</h4>
          <div v-for="(item, i) in previewData.concepts" :key="'c'+i" class="review-item">
            <div v-if="editingKey === 'c-'+i" class="edit-row">
              <input v-model="item.name" :placeholder="t('extract.ph.name')" />
              <input v-model="item.label" :placeholder="t('extract.ph.label')" />
              <input v-model="item.description" :placeholder="t('extract.ph.description')" />
              <button class="ghost small" @click="editingKey = null">{{ t('extract.done') }}</button>
            </div>
            <div v-else class="display-row">
              <span class="item-text"><b>{{ item.name }}</b> | {{ item.label }}</span>
              <div class="item-actions">
                <button class="ghost small" @click="editingKey = 'c-'+i">{{ t('extract.edit') }}</button>
                <button class="danger small" @click="removeItem('concepts', i)">{{ t('extract.delete') }}</button>
              </div>
            </div>
          </div>
          <div v-if="!previewData.concepts.length" class="empty-section">{{ t('extract.none') }}</div>
        </div>

        <!-- 概念关系 -->
        <div class="review-section">
          <h4>{{ t('extract.conceptRelations') }} ({{ previewData.concept_relations.length }})</h4>
          <div v-for="(item, i) in previewData.concept_relations" :key="'cr'+i" class="review-item">
            <div v-if="editingKey === 'cr-'+i" class="edit-row">
              <input v-model="item.source" :placeholder="t('extract.ph.source')" />
              <input v-model="item.target" :placeholder="t('extract.ph.target')" />
              <input v-model="item.name" :placeholder="t('extract.ph.relName')" />
              <input v-model="item.label" :placeholder="t('extract.ph.label')" />
              <button class="ghost small" @click="editingKey = null">{{ t('extract.done') }}</button>
            </div>
            <div v-else class="display-row">
              <span class="item-text">{{ item.source }} → <b>{{ item.name }}</b> → {{ item.target }}</span>
              <div class="item-actions">
                <button class="ghost small" @click="editingKey = 'cr-'+i">{{ t('extract.edit') }}</button>
                <button class="danger small" @click="removeItem('concept_relations', i)">{{ t('extract.delete') }}</button>
              </div>
            </div>
          </div>
          <div v-if="!previewData.concept_relations.length" class="empty-section">{{ t('extract.none') }}</div>
        </div>

        <!-- 实例 -->
        <div class="review-section">
          <h4>{{ t('extract.instances') }} ({{ previewData.instances.length }})</h4>
          <div v-for="(item, i) in previewData.instances" :key="'i'+i" class="review-item">
            <div v-if="editingKey === 'i-'+i" class="edit-row">
              <input v-model="item.label" :placeholder="t('extract.ph.conceptType')" />
              <input v-model="item.name" :placeholder="t('extract.ph.instanceName')" />
              <input v-model="item.propertiesStr" :placeholder="t('extract.ph.propsJson')" />
              <button class="ghost small" @click="saveProps('instances', i); editingKey = null">{{ t('extract.done') }}</button>
            </div>
            <div v-else class="display-row">
              <span class="item-text"><b>{{ item.name }}</b> ({{ item.label }})</span>
              <div class="item-actions">
                <button class="ghost small" @click="startEditInstance('instances', i)">{{ t('extract.edit') }}</button>
                <button class="danger small" @click="removeItem('instances', i)">{{ t('extract.delete') }}</button>
              </div>
            </div>
          </div>
          <div v-if="!previewData.instances.length" class="empty-section">{{ t('extract.none') }}</div>
        </div>

        <!-- 实例关系 -->
        <div class="review-section">
          <h4>{{ t('extract.instanceRelations') }} ({{ previewData.instance_relations.length }})</h4>
          <div v-for="(item, i) in previewData.instance_relations" :key="'ir'+i" class="review-item">
            <div v-if="editingKey === 'ir-'+i" class="edit-row">
              <input v-model="item.source_name" :placeholder="t('extract.ph.sourceInstance')" />
              <input v-model="item.source_label" :placeholder="t('extract.ph.sourceLabel')" />
              <input v-model="item.target_name" :placeholder="t('extract.ph.targetInstance')" />
              <input v-model="item.target_label" :placeholder="t('extract.ph.targetLabel')" />
              <input v-model="item.relation_type" :placeholder="t('extract.ph.relationType')" />
              <button class="ghost small" @click="editingKey = null">{{ t('extract.done') }}</button>
            </div>
            <div v-else class="display-row">
              <span class="item-text">{{ item.source_name }} → <b>{{ item.relation_type }}</b> → {{ item.target_name }}</span>
              <div class="item-actions">
                <button class="ghost small" @click="editingKey = 'ir-'+i">{{ t('extract.edit') }}</button>
                <button class="danger small" @click="removeItem('instance_relations', i)">{{ t('extract.delete') }}</button>
              </div>
            </div>
          </div>
          <div v-if="!previewData.instance_relations.length" class="empty-section">{{ t('extract.none') }}</div>
        </div>

        <div class="toolbar" style="margin-top:16px;">
          <button :disabled="busy" @click="confirm">{{ t('extract.confirm') }}</button>
          <button class="ghost" :disabled="busy" @click="clearPreview">{{ t('extract.clear') }}</button>
        </div>
      </div>

      <!-- 结果面板（非审核模式） -->
      <div class="result-panel card" v-if="!reviewMode && result">
        <h3>{{ t('extract.result') }}</h3>
        <div class="kv-grid">
          <div class="kv"><span>{{ t('extract.textSourceId') }}</span><b>#{{ textSourceId }}</b></div>
          <div class="kv"><span>{{ t('extract.conceptCreated') }}</span><b>{{ result.concepts.created }}/{{ result.concepts.updated }}</b></div>
          <div class="kv"><span>{{ t('extract.conceptRelCreated') }}</span><b>{{ result.concept_relations.created }}</b></div>
          <div class="kv"><span>{{ t('extract.instanceCreated') }}</span><b>{{ result.instances.created }}/{{ result.instances.updated }}</b></div>
          <div class="kv"><span>{{ t('extract.instanceRelCreated') }}</span><b>{{ result.instance_relations.created }}</b></div>
        </div>
        <h4 style="margin-top:12px;">{{ t('extract.llmStats') }}</h4>
        <div class="kv-grid">
          <div class="kv"><span>{{ t('extract.foundConcepts') }}</span><b>{{ result.raw_summary.concepts_found }}</b></div>
          <div class="kv"><span>{{ t('extract.foundConceptRels') }}</span><b>{{ result.raw_summary.concept_relations_found }}</b></div>
          <div class="kv"><span>{{ t('extract.foundInstances') }}</span><b>{{ result.raw_summary.instances_found }}</b></div>
          <div class="kv"><span>{{ t('extract.foundInstanceRels') }}</span><b>{{ result.raw_summary.instance_relations_found }}</b></div>
        </div>
      </div>

      <!-- 入库结果面板（审核模式确认后） -->
      <div class="result-panel card" v-if="reviewMode && confirmResult">
        <h3>{{ t('extract.persistResult') }}</h3>
        <div class="kv-grid">
          <div class="kv"><span>{{ t('extract.textSourceId') }}</span><b>#{{ textSourceId }}</b></div>
          <div class="kv"><span>{{ t('extract.conceptCreated') }}</span><b>{{ confirmResult.concepts.created }}/{{ confirmResult.concepts.updated }}</b></div>
          <div class="kv"><span>{{ t('extract.conceptRelCreated') }}</span><b>{{ confirmResult.concept_relations.created }}</b></div>
          <div class="kv"><span>{{ t('extract.instanceCreated') }}</span><b>{{ confirmResult.instances.created }}/{{ confirmResult.instances.updated }}</b></div>
          <div class="kv"><span>{{ t('extract.instanceRelCreated') }}</span><b>{{ confirmResult.instance_relations.created }}</b></div>
        </div>
      </div>
    </div>
  </div>
</template>

<script setup>
import { ref, computed } from 'vue'
import api from '../api.js'
import { t } from '../i18n.js'

const mode = ref('text')
const title = ref('')
const text = ref('')
const file = ref(null)
const busy = ref(false)
const message = ref('')
const messageType = ref('info')
const reviewMode = ref(false)
const previewData = ref({ concepts: [], concept_relations: [], instances: [], instance_relations: [] })
const hasPreview = ref(false)
const result = ref(null)
const confirmResult = ref(null)
const editingKey = ref(null)
const textSourceId = ref(null)

const canSubmit = computed(() => {
  if (mode.value === 'text') return text.value.trim().length >= 10
  return file.value != null
})

function onFileChange(e) {
  file.value = e.target.files[0] || null
}

function showMessage(m, type='info') {
  message.value = m
  messageType.value = type
}

async function preview() {
  busy.value = true
  message.value = ''
  hasPreview.value = false
  confirmResult.value = null
  textSourceId.value = null
  try {
    let res
    if (mode.value === 'text') {
      res = await api.previewText({ text: text.value.trim(), title: title.value.trim() })
    } else {
      const fd = new FormData()
      fd.append('file', file.value)
      res = await api.extractFile(fd)
    }
    textSourceId.value = res.text_source_id || null
    // 为实例的 properties 准备字符串编辑字段
    if (res.instances) {
      res.instances.forEach(inst => {
        inst.propertiesStr = JSON.stringify(inst.properties || {})
      })
    }
    previewData.value = res
    hasPreview.value = true
    showMessage(t('extract.msgPreviewOk'), 'success')
  } catch (e) {
    showMessage(t('extract.msgPreviewFail') + ': ' + (e?.response?.data?.error || e.message), 'error')
  } finally {
    busy.value = false
  }
}

function removeItem(key, index) {
  previewData.value[key].splice(index, 1)
}

function startEditInstance(key, index) {
  const item = previewData.value[key][index]
  item.propertiesStr = JSON.stringify(item.properties || {})
  editingKey.value = key[0] + '-' + index
}

function saveProps(key, index) {
  const item = previewData.value[key][index]
  try {
    item.properties = JSON.parse(item.propertiesStr || '{}')
  } catch {
    item.properties = {}
  }
}

async function confirm() {
  busy.value = true
  message.value = ''
  try {
    // 清理临时字段
    const data = {
      text_source_id: textSourceId.value,
      concepts: previewData.value.concepts.map(c => ({ name: c.name, label: c.label, description: c.description })),
      concept_relations: previewData.value.concept_relations.map(r => ({ source: r.source, target: r.target, name: r.name, label: r.label })),
      instances: previewData.value.instances.map(i => ({ label: i.label, name: i.name, properties: i.properties || {} })),
      instance_relations: previewData.value.instance_relations.map(r => ({
        source_name: r.source_name, source_label: r.source_label,
        target_name: r.target_name, target_label: r.target_label,
        relation_type: r.relation_type, properties: r.properties || {}
      })),
    }
    const res = await api.confirmExtract(data)
    confirmResult.value = res
    showMessage(t('extract.msgPersistOk', { id: textSourceId.value }), 'success')
  } catch (e) {
    showMessage(t('extract.msgPersistFail') + ': ' + (e?.response?.data?.error || e.message), 'error')
  } finally {
    busy.value = false
  }
}

function clearPreview() {
  previewData.value = { concepts: [], concept_relations: [], instances: [], instance_relations: [] }
  hasPreview.value = false
  confirmResult.value = null
}

async function submit() {
  busy.value = true
  message.value = ''
  result.value = null
  textSourceId.value = null
  try {
    let res
    if (mode.value === 'text') {
      res = await api.extractText({ text: text.value.trim(), title: title.value.trim() })
    } else {
      const fd = new FormData()
      fd.append('file', file.value)
      res = await api.extractFile(fd)
    }
    textSourceId.value = res.text_source_id || null
    result.value = res
    showMessage(t('extract.msgExtractOk', { id: textSourceId.value }), 'success')
  } catch (e) {
    showMessage(t('extract.msgExtractFail') + ': ' + (e?.response?.data?.error || e.message), 'error')
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

.extract-layout { display: grid; grid-template-columns: 1fr 1fr; gap: 16px; }
@media (max-width: 1100px) { .extract-layout { grid-template-columns: 1fr; } }

.input-panel { display: flex; flex-direction: column; gap: 8px; }
.review-panel { max-height: 80vh; overflow: auto; }
.result-panel { }

.tabs { display: flex; gap: 4px; margin-bottom: 12px; }
.tabs button {
  padding: 6px 14px;
  border-radius: 6px;
  border: 1px solid #e5e7eb;
  background: #fff;
  font-size: 13px;
  cursor: pointer;
}
.tabs button.active { background: #2563eb; color: #fff; border-color: #2563eb; }

textarea {
  width: 100%;
  padding: 10px;
  border: 1px solid #e5e7eb;
  border-radius: 6px;
  font-size: 13px;
  resize: vertical;
  box-sizing: border-box;
}

.review-toggle {
  display: flex; align-items: center; gap: 8px;
  font-size: 13px; color: #374151;
  margin-top: 8px; cursor: pointer;
}
.review-toggle input { width: 16px; height: 16px; }

.review-section { margin-top: 12px; }
.review-section h4 {
  font-size: 13px; color: #6b7280; margin-bottom: 6px;
  border-bottom: 1px solid #f3f4f6; padding-bottom: 4px;
}
.review-item {
  background: #f9fafb;
  border-radius: 6px;
  padding: 6px 8px;
  margin-bottom: 4px;
  font-size: 12px;
}
.display-row {
  display: flex; justify-content: space-between; align-items: center; gap: 8px;
}
.edit-row {
  display: flex; flex-wrap: wrap; gap: 4px; align-items: center;
}
.edit-row input {
  padding: 4px 6px; border: 1px solid #d1d5db; border-radius: 4px;
  font-size: 12px; min-width: 60px; flex: 1;
}
.item-text { flex: 1; word-break: break-all; }
.item-actions { display: flex; gap: 4px; flex-shrink: 0; }
.empty-section { color: #9ca3af; font-size: 12px; padding: 4px 0; }

button.small { padding: 2px 8px; font-size: 11px; }
button.danger { background: #dc2626; color: #fff; border: none; }
button.danger:hover { background: #b91c1c; }

.kv-grid { display: grid; grid-template-columns: repeat(auto-fill, minmax(140px, 1fr)); gap: 8px; }
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
}
.title-input {
  width: 100%;
  padding: 8px 10px;
  border: 1px solid #e5e7eb;
  border-radius: 6px;
  font-size: 13px;
  margin-bottom: 8px;
  box-sizing: border-box;
}
.message.info { background: #eff6ff; color: #1d4ed8; }
.message.success { background: #ecfdf5; color: #059669; }
.message.error { background: #fef2f2; color: #dc2626; }
</style>
