<template>
  <div class="page">
    <div class="card header">
      <div>
        <h2>{{ t('textSources.title') }}</h2>
        <p class="hint">{{ t('textSources.hint') }}</p>
      </div>
    </div>

    <div class="sources-layout">
      <!-- 左侧列表 -->
      <div class="list-panel card">
        <h3>{{ t('textSources.list') }}</h3>
        <div v-if="loading" class="hint">{{ t('textSources.loading') }}</div>
        <div v-else-if="!sources.length" class="hint">{{ t('textSources.empty') }}</div>
        <div v-else class="source-list">
          <div
            v-for="s in sources"
            :key="s.id"
            class="source-item"
            :class="{ active: selected?.id === s.id }"
            @click="select(s)"
          >
            <div class="source-title">{{ s.title || t('textSources.untitled') }}</div>
            <div class="source-meta">
              <span>{{ s.source_type === 'upload' ? t('textSources.upload') : t('textSources.paste') }}</span>
              <span>{{ s.word_count }}{{ t('textSources.charUnit') }}</span>
              <span>{{ formatDate(s.created_at) }}</span>
            </div>
          </div>
        </div>
      </div>

      <!-- 右侧详情 -->
      <div class="detail-panel card" v-if="selected">
        <h3>{{ t('textSources.detail', { id: selected.id }) }}</h3>
        <div class="detail-meta">
          <span class="tag">{{ selected.source_type === 'upload' ? t('textSources.fileUpload') : t('textSources.textPaste') }}</span>
          <span v-if="selected.filename" class="tag">{{ selected.filename }}</span>
          <span class="tag">{{ selected.word_count }}{{ t('textSources.charUnit') }}</span>
          <span class="tag">{{ formatDate(selected.created_at) }}</span>
        </div>
        <div class="detail-content">
          <h4>{{ t('textSources.rawText') }}</h4>
          <pre>{{ selected.content }}</pre>
        </div>
      </div>
      <div class="detail-panel card empty" v-else>
        <p class="hint">{{ t('textSources.clickToView') }}</p>
      </div>
    </div>
  </div>
</template>

<script setup>
import { ref, onMounted } from 'vue'
import api from '../api.js'
import { t, locale } from '../i18n.js'

const sources = ref([])
const selected = ref(null)
const loading = ref(false)

function formatDate(d) {
  if (!d) return '-'
  const date = new Date(d)
  return date.toLocaleString(locale.value === 'zh' ? 'zh-CN' : 'en-US')
}

async function load() {
  loading.value = true
  try {
    sources.value = await api.textSources({ limit: 100 })
  } catch (e) {
    console.error(t('textSources.msgLoadFail'), e)
  } finally {
    loading.value = false
  }
}

async function select(s) {
  try {
    selected.value = await api.textSource(s.id)
  } catch (e) {
    console.error(t('textSources.msgDetailFail'), e)
  }
}

onMounted(load)
</script>

<style scoped>
.page { display: flex; flex-direction: column; gap: 16px; }
.header { display: flex; justify-content: space-between; align-items: center; }
h2 { font-size: 20px; }
.hint { color: #6b7280; font-size: 13px; }

.sources-layout {
  display: grid;
  grid-template-columns: 360px 1fr;
  gap: 16px;
  align-items: start;
}
@media (max-width: 1100px) {
  .sources-layout { grid-template-columns: 1fr; }
}

.list-panel { max-height: 80vh; overflow: auto; }
.list-panel h3 { font-size: 15px; margin-bottom: 10px; }

.source-list { display: flex; flex-direction: column; gap: 6px; }
.source-item {
  padding: 10px 12px;
  border-radius: 6px;
  border: 1px solid #e5e7eb;
  cursor: pointer;
  transition: background .2s;
}
.source-item:hover { background: #f9fafb; }
.source-item.active { background: #eff6ff; border-color: #2563eb; }
.source-title { font-size: 14px; font-weight: 500; color: #111827; }
.source-meta {
  margin-top: 4px;
  font-size: 12px;
  color: #6b7280;
  display: flex;
  gap: 10px;
}

.detail-panel { min-height: 60vh; }
.detail-panel.empty {
  display: flex; align-items: center; justify-content: center;
}
.detail-panel h3 { font-size: 15px; margin-bottom: 10px; }
.detail-meta {
  display: flex; flex-wrap: wrap; gap: 6px;
  margin-bottom: 12px;
}
.tag {
  background: #f3f4f6;
  color: #374151;
  padding: 3px 8px;
  border-radius: 4px;
  font-size: 12px;
}
.detail-content h4 {
  font-size: 13px; color: #6b7280;
  margin-bottom: 6px;
}
.detail-content pre {
  background: #f9fafb;
  padding: 12px;
  border-radius: 6px;
  font-size: 13px;
  line-height: 1.6;
  white-space: pre-wrap;
  word-break: break-word;
  max-height: 60vh;
  overflow: auto;
  border: 1px solid #e5e7eb;
}
</style>
