<template>
  <div class="graph-wrap" ref="wrap">
    <svg ref="svg"></svg>
    <div class="legend" v-if="legend.length">
      <div v-for="l in legend" :key="l.name" class="legend-item">
        <span class="dot" :style="{ background: l.color }"></span>
        <span class="legend-label">{{ l.label }}</span>
      </div>
    </div>
    <div v-if="hover" class="tooltip" :style="{ left: hover.x+'px', top: hover.y+'px' }">
      <div class="tip-title">{{ hover.title }}</div>
      <div v-if="hover.subtitle" class="tip-sub">{{ hover.subtitle }}</div>
      <div v-for="(v,k) in hover.props" :key="k" class="tip-row">
        <span class="tip-key">{{ k }}</span>
        <span class="tip-val">{{ v }}</span>
      </div>
    </div>
  </div>
</template>

<script setup>
import { ref, watch, onMounted, onBeforeUnmount, nextTick } from 'vue'
import * as d3 from 'd3'

const props = defineProps({
  nodes:  { type: Array, default: () => [] },
  edges:  { type: Array, default: () => [] },
  // map of label -> color (for instance layer); if omitted, palette is used
  colorMap: { type: Object, default: null }
})

const wrap = ref(null)
const svg = ref(null)
const hover = ref(null)
const legend = ref([])

let simulation = null
let resizeObserver = null

const palette = d3.schemeTableau10

function getColor(label) {
  if (props.colorMap && props.colorMap[label]) return props.colorMap[label]
  // Stable hash to palette index
  let h = 0
  for (let i = 0; i < label.length; i++) h = (h * 31 + label.charCodeAt(i)) >>> 0
  return palette[h % palette.length]
}

function buildLegend() {
  const seen = new Map()
  for (const n of props.nodes) {
    if (!seen.has(n.label)) seen.set(n.label, getColor(n.label))
  }
  legend.value = [...seen.entries()].map(([label, color]) => ({ name: label, label, color }))
}

function render() {
  if (!svg.value || !wrap.value) return
  const el = svg.value
  const { width, height } = wrap.value.getBoundingClientRect()
  if (!width || !height) return

  const svgSel = d3.select(el)
  svgSel.selectAll('*').remove()
  svgSel.attr('viewBox', [0, 0, width, height])
       .attr('width', width).attr('height', height)

  // Clone arrays so D3 mutations don't pollute Vue reactive state
  const nodes = props.nodes.map(n => ({ ...n }))
  const edges = props.edges.map(e => ({ ...e }))

  // Arrow marker
  const defs = svgSel.append('defs')
  defs.append('marker')
    .attr('id', 'arrow')
    .attr('viewBox', '0 -5 10 10')
    .attr('refX', 22)
    .attr('refY', 0)
    .attr('markerWidth', 8)
    .attr('markerHeight', 8)
    .attr('orient', 'auto')
    .append('path')
    .attr('d', 'M0,-5L10,0L0,5')
    .attr('fill', '#9ca3af')

  const root = svgSel.append('g')

  svgSel.call(d3.zoom().scaleExtent([0.2, 4]).on('zoom', (e) => {
    root.attr('transform', e.transform)
  }))

  const link = root.append('g').selectAll('line').data(edges).join('line')
    .attr('stroke', '#9ca3af')
    .attr('stroke-width', 1.4)
    .attr('marker-end', 'url(#arrow)')

  const linkLabel = root.append('g').selectAll('text').data(edges).join('text')
    .attr('font-size', 11)
    .attr('fill', '#6b7280')
    .attr('text-anchor', 'middle')
    .text(d => d.label || d.name || d.type)

  const nodeG = root.append('g').selectAll('g').data(nodes).join('g')
    .style('cursor', 'pointer')
    .call(drag())

  nodeG.append('circle')
    .attr('r', 22)
    .attr('fill', d => getColor(d.label))
    .attr('stroke', '#fff')
    .attr('stroke-width', 2)

  nodeG.append('text')
    .attr('text-anchor', 'middle')
    .attr('dy', '.35em')
    .attr('font-size', 11)
    .attr('fill', '#fff')
    .style('pointer-events', 'none')
    .text(d => truncate(d.name || d.label, 6))

  nodeG.append('title').text(d => `${d.label}: ${d.name}`)

  nodeG.on('mouseover', (event, d) => {
    const rect = wrap.value.getBoundingClientRect()
    hover.value = {
      x: event.clientX - rect.left + 12,
      y: event.clientY - rect.top + 12,
      title: d.name,
      subtitle: d.label,
      props: extractDisplayProps(d.props || {})
    }
  }).on('mousemove', (event) => {
    if (hover.value) {
      const rect = wrap.value.getBoundingClientRect()
      hover.value.x = event.clientX - rect.left + 12
      hover.value.y = event.clientY - rect.top + 12
    }
  }).on('mouseout', () => { hover.value = null })

  simulation = d3.forceSimulation(nodes)
    .force('link', d3.forceLink(edges).id(d => d.id).distance(120))
    .force('charge', d3.forceManyBody().strength(-380))
    .force('center', d3.forceCenter(width / 2, height / 2))
    .force('collide', d3.forceCollide(28))
    .on('tick', () => {
      link
        .attr('x1', d => d.source.x).attr('y1', d => d.source.y)
        .attr('x2', d => d.target.x).attr('y2', d => d.target.y)
      linkLabel
        .attr('x', d => (d.source.x + d.target.x) / 2)
        .attr('y', d => (d.source.y + d.target.y) / 2)
      nodeG.attr('transform', d => `translate(${d.x},${d.y})`)
    })

  function drag() {
    return d3.drag()
      .on('start', (event, d) => {
        if (!event.active) simulation.alphaTarget(0.3).restart()
        d.fx = d.x; d.fy = d.y
      })
      .on('drag', (event, d) => { d.fx = event.x; d.fy = event.y })
      .on('end', (event, d) => {
        if (!event.active) simulation.alphaTarget(0)
        d.fx = null; d.fy = null
      })
  }
}

function truncate(s, n) {
  if (!s) return ''
  s = String(s)
  return s.length > n ? s.slice(0, n) + '…' : s
}

function extractDisplayProps(props) {
  const out = {}
  const skip = new Set(['id', 'display_name', 'created_at', 'updated_at'])
  for (const k of Object.keys(props)) {
    if (skip.has(k)) continue
    let v = props[k]
    if (v == null || v === '') continue
    if (typeof v === 'string' && v.length > 60) v = v.slice(0, 60) + '…'
    out[k] = v
  }
  return out
}

function refresh() {
  buildLegend()
  nextTick(render)
}

watch(() => props.nodes, refresh, { deep: false })
watch(() => props.edges, refresh, { deep: false })

onMounted(() => {
  refresh()
  resizeObserver = new ResizeObserver(() => render())
  resizeObserver.observe(wrap.value)
})

onBeforeUnmount(() => {
  if (simulation) simulation.stop()
  if (resizeObserver) resizeObserver.disconnect()
})
</script>

<style scoped>
.graph-wrap {
  position: relative;
  width: 100%;
  height: 100%;
  background: #fafafa;
  border-radius: 8px;
  overflow: hidden;
}
svg { display: block; width: 100%; height: 100%; }

.legend {
  position: absolute;
  top: 12px;
  left: 12px;
  background: rgba(255,255,255,0.92);
  padding: 8px 12px;
  border-radius: 6px;
  font-size: 12px;
  box-shadow: 0 1px 3px rgba(0,0,0,0.1);
  display: flex; flex-direction: column; gap: 4px;
  max-height: calc(100% - 24px);
  overflow-y: auto;
}
.legend-item { display: flex; align-items: center; gap: 6px; }
.dot { display: inline-block; width: 10px; height: 10px; border-radius: 50%; }

.tooltip {
  position: absolute;
  background: rgba(17, 24, 39, 0.95);
  color: #f9fafb;
  padding: 8px 10px;
  border-radius: 6px;
  font-size: 12px;
  pointer-events: none;
  max-width: 320px;
  z-index: 10;
}
.tip-title { font-weight: 600; margin-bottom: 2px; }
.tip-sub { color: #9ca3af; margin-bottom: 6px; font-size: 11px; }
.tip-row { display: flex; gap: 6px; }
.tip-key { color: #93c5fd; min-width: 70px; }
.tip-val { color: #f9fafb; word-break: break-all; }
</style>
