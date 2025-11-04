<template>
  <div ref="chartEl" style="width:100%;height:500px;"></div>
</template>

<script setup>
import { ref, watch, onMounted, onBeforeUnmount, nextTick } from 'vue'

const props = defineProps({
  type: { type: String, default: 'bar' },
  data: { type: Array, default: () => [] },
  activeMetric: { type: String, default: null },
  showThreshold: { type: Boolean, default: true }
})

const chartEl = ref(null)
let chart = null
let updateQueue = Promise.resolve()

const METRIC_CONFIG = {
  'Gula Darah Sewaktu': { color: '#8b5cf6', threshold: 140, label: 'Tinggi' },
  'Gula Darah Puasa': { color: '#a855f7', threshold: 100, label: 'Tinggi' },
  'Cholesterol': { color: '#06b6d4', threshold: 200, label: 'Tinggi' },
  'Asam Urat': { color: '#f59e0b', threshold: 7, label: 'Tinggi' },
  'Tekanan Darah': { color: '#ef4444', threshold: 140, label: 'Tinggi' }
}

function buildHealthOption(){
  if (!props.data.length) return {}
  const months = props.data.map(d => d.month)
  const keys = Object.keys(props.data[0]).filter(k => k !== 'month')
  const palette = ['#8b5cf6','#a855f7','#06b6d4','#f59e0b','#ef4444']
  const isArea = props.type === 'area'
  const series = keys.map((k,i)=>{
    const dim = props.data.map(d=> (d[k] ?? null))
    const active = !props.activeMetric || props.activeMetric === k
    const s = {
      name: k,
      type: isArea ? 'line' : (props.type || 'line'),
      data: dim,
      smooth: true,
      connectNulls: true,
      emphasis: { focus: 'series' },
      itemStyle: { opacity: active ? 1 : 0.3 },
      lineStyle: { width: 2, opacity: active ? 1 : 0.3 },
    }
    if (isArea) s.areaStyle = { opacity: 0.25 }
    if (props.showThreshold && props.activeMetric === k && METRIC_CONFIG[k]){
      const cfg = METRIC_CONFIG[k]
      s.markLine = {
        silent: true,
        symbol: 'none',
        lineStyle: { type: 'dashed', color: cfg.color },
        label: { formatter: cfg.label, color: '#fff', backgroundColor: cfg.color },
        data: [ { yAxis: cfg.threshold } ]
      }
    }
    return s
  })
  return {
    tooltip: { trigger: 'axis' },
    legend: { top: 10 },
    grid: { left: 40, right: 20, bottom: 40, top: 40 },
    xAxis: { type: 'category', data: months },
    yAxis: { type: 'value', splitLine: { lineStyle: { color: '#e5e7eb' } } },
    color: palette,
    series
  }
}

function buildWellOption(){
  if (!props.data.length) return {}
  const months = props.data.map(d => d.month)
  const isArea = props.type === 'area'
  const series = [
    {
      name: 'Well',
      type: isArea ? 'line' : (props.type || 'bar'),
      data: props.data.map(d => d.well || 0),
      smooth: true,
      connectNulls: true,
      ...(isArea ? { areaStyle: { opacity: 0.25 } } : {}),
      ...(props.type === 'bar' ? { labelLayout: { hideOverlap: true } } : {})
    },
    {
      name: 'Unwell',
      type: isArea ? 'line' : (props.type || 'bar'),
      data: props.data.map(d => d.unwell || 0),
      smooth: true,
      connectNulls: true,
      ...(isArea ? { areaStyle: { opacity: 0.25 } } : {}),
      ...(props.type === 'bar' ? { label: { show: true, position: 'top' }, labelLayout: { hideOverlap: true } } : {})
    }
  ]
  return {
    tooltip: { trigger: 'axis' },
    legend: { top: 10 },
    grid: { left: 40, right: 20, bottom: 40, top: 40 },
    xAxis: { type: 'category', data: months },
    yAxis: { type: 'value', splitLine: { lineStyle: { color: '#e5e7eb' } } },
    color: ['#16a34a', '#dc2626'],
    series
  }
}

async function initChart(){
  if (!chartEl.value) return
  if (typeof echarts === 'undefined') {
    console.warn('[EChartWrapper] echarts global not found; ensure CDN or bundler provides window.echarts')
    return
  }
  chart = echarts.init(chartEl.value)
  const option = props.showThreshold ? buildHealthOption() : buildWellOption()
  if (option && option.series && option.series.length){
    chart.setOption(option, true)
  }
}

function enqueueUpdate(fn){
  updateQueue = updateQueue.then(() => nextTick().then(fn))
}

watch([() => props.data, () => props.type, () => props.activeMetric], () => {
  if (!chart) return
  const option = props.showThreshold ? buildHealthOption() : buildWellOption()
  enqueueUpdate(() => { chart.setOption(option, true) })
})

onMounted(initChart)
onBeforeUnmount(() => {
  if (chart && typeof chart.dispose === 'function') chart.dispose()
  chart = null
})
</script>