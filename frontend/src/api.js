import axios from 'axios'

const api = axios.create({ baseURL: '/api', timeout: 60000 })
const longApi = axios.create({ baseURL: '/api', timeout: 180000 })

export default {
  health:        () => api.get('/health').then(r => r.data),
  stats:         () => api.get('/stats').then(r => r.data),
  schema:        () => api.get('/schema').then(r => r.data),
  buildConcepts: () => api.post('/build/concepts').then(r => r.data),
  buildInstances:() => api.post('/build/instances').then(r => r.data),
  buildAll:      () => api.post('/build/all').then(r => r.data),
  clear:         () => api.post('/clear').then(r => r.data),
  migrateSource: () => api.post('/migrate/source').then(r => r.data),
  buildFunctions:() => api.post('/build/functions').then(r => r.data),
  functions:     (category) => api.get('/functions', { params: category ? { category } : {} }).then(r => r.data),
  functionGraph: () => api.get('/graph/functions').then(r => r.data),
  buildRules:    () => api.post('/build/rules').then(r => r.data),
  rules:         (category) => api.get('/rules', { params: category ? { category } : {} }).then(r => r.data),
  triggerRule:   (id) => api.post(`/rules/${id}/trigger`).then(r => r.data),
  extractText:   (data) => longApi.post('/extract/text', data).then(r => r.data),
  extractFile:   (formData) => longApi.post('/extract/file', formData, { headers: { 'Content-Type': 'multipart/form-data' } }).then(r => r.data),
  previewText:   (data) => longApi.post('/extract/preview', data).then(r => r.data),
  confirmExtract:(data) => longApi.post('/extract/confirm', data).then(r => r.data),
  ruleGraph:     () => api.get('/graph/rules').then(r => r.data),
  conceptGraph:  () => api.get('/graph/concepts').then(r => r.data),
  instanceGraph: (params={}) => api.get('/graph/instances', { params }).then(r => r.data),
  instanceLabels:() => api.get('/graph/instance-labels').then(r => r.data),
  textSources:   (params={}) => api.get('/text-sources', { params }).then(r => r.data),
  textSource:    (id) => api.get(`/text-sources/${id}`).then(r => r.data),
  askQuestion:   (data) => longApi.post('/qa/ask', data).then(r => r.data),
  analyzeReasoning:(data) => longApi.post('/reasoning/analyze', data).then(r => r.data),
}
