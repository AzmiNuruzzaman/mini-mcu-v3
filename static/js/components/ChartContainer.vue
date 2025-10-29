<template>
  <div style="width: 100%; height: 500px;">
    <ApexChart 
      v-if="showThreshold" 
      :options="chartOptions" 
      :series="chartSeries" 
      height="500" 
    />
    <ApexChart 
      v-else 
      :options="wellOptions" 
      :series="wellSeries" 
      height="500" 
    />
  </div>
  </template>

<script setup>
import { ref, watch } from 'vue'
import ApexChart from './ApexChart.js'

const props = defineProps({ 
  type: { type: String, default: 'bar' }, // bar|line|area 
  data: { type: Array, default: () => [] }, 
  activeMetric: { type: String, default: null }, 
  showThreshold: { type: Boolean, default: true } // true for health metrics 
}) 

const chartSeries = ref([]) 
const chartOptions = ref({}) 
const wellSeries = ref([]) 
const wellOptions = ref({}) 

const METRIC_CONFIG = { 
  'Gula Darah Sewaktu': { color: '#8b5cf6', threshold: 140, label: 'Tinggi' }, 
  'Gula Darah Puasa': { color: '#a855f7', threshold: 100, label: 'Tinggi' }, 
  'Cholesterol': { color: '#06b6d4', threshold: 200, label: 'Tinggi' }, 
  'Asam Urat': { color: '#f59e0b', threshold: 7, label: 'Tinggi' }, 
  'Tekanan Darah': { color: '#ef4444', threshold: 140, label: 'Tinggi' } 
} 

function buildHealthChart() { 
  if (!props.data.length) return 
  const months = props.data.map(d => d.month) 
  const keys = Object.keys(props.data[0]).filter(k => k !== 'month') 
  const colors = ['#8b5cf6','#a855f7','#06b6d4','#f59e0b','#ef4444'] 

  chartSeries.value = keys.map((k,i)=>({ 
    name: k, 
    data: props.data.map(d=>d[k] ?? 0), 
    color: colors[i%colors.length], 
    opacity: props.activeMetric && props.activeMetric!==k ? 0.3 : 1 
  })) 

  chartOptions.value = { 
    chart: { type: props.type, toolbar: { show: false } }, 
    xaxis: { categories: months }, 
    stroke: { width: 2, curve: 'smooth' }, 
    colors: colors.slice(0,keys.length), 
    legend: { position: 'top' }, 
    grid: { borderColor: '#e5e7eb' }, 
    tooltip: { theme: 'light' }, 
    dataLabels: { enabled: false }, 
    annotations: { 
      yaxis: props.activeMetric && METRIC_CONFIG[props.activeMetric] ? [{ 
        y: METRIC_CONFIG[props.activeMetric].threshold, 
        borderColor: METRIC_CONFIG[props.activeMetric].color, 
        strokeDashArray: 5, 
        label: { 
          text: METRIC_CONFIG[props.activeMetric].label, 
          style: { color: '#fff', background: METRIC_CONFIG[props.activeMetric].color } 
        } 
      }] : [] 
    } 
  } 
} 

function buildWellChart() { 
  if (!props.data.length) return 
  wellSeries.value = [ 
    { name: 'Well', data: props.data.map(d=>d.well || 0), color: '#16a34a' }, 
    { name: 'Unwell', data: props.data.map(d=>d.unwell || 0), color: '#dc2626' } 
  ] 
  wellOptions.value = { 
    chart: { type: 'bar', stacked: false, toolbar: { show: false } }, 
    xaxis: { categories: props.data.map(d=>d.month) }, 
    colors: ['#16a34a','#dc2626'], 
    legend: { position: 'top' }, 
    grid: { borderColor: '#e5e7eb' }, 
    tooltip: { theme: 'light' } 
  } 
} 

// Rebuild charts whenever props change (with diagnostics)
watch(() => [props.data, props.type, props.activeMetric], () => {
  try {
    console.log('[Diag ChartContainer] watcher triggered', { type: props.type, activeMetric: props.activeMetric, dataLen: (props.data||[]).length, showThreshold: props.showThreshold });
  } catch(e) {}
  if (props.showThreshold) {
    buildHealthChart()
    try {
      console.log('[Diag ChartContainer] health series', chartSeries.value);
    } catch(e) {}
  } else {
    buildWellChart()
    try {
      console.log('[Diag ChartContainer] well/unwell series', wellSeries.value);
    } catch(e) {}
  }
}, { immediate: true })
</script>