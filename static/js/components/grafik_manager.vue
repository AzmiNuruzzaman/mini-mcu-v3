<template>
  <div id="grafik-manager" class="rounded-xl border border-slate-300 shadow-sm bg-white p-6">

    <!-- Header -->
    <div class="flex items-center justify-between mb-6">
      <div>
        <h2 class="text-xl font-bold text-slate-900">Grafik Riwayat Medical Check Up</h2>
        <p class="text-slate-600 text-sm">Pantau kondisi kesehatan karyawan dari waktu ke waktu</p>
      </div>
    </div>

    <!-- Subtabs -->
    <div class="flex border-b mb-4">
      <button
        :class="activeTab==='health' ? activeTabClass : inactiveTabClass"
        @click="switchTab('health')"
      >Health Metrics</button>
      <button
        :class="activeTab==='well' ? activeTabClass : inactiveTabClass"
        @click="switchTab('well')"
      >Well & Unwell</button>
    </div>

    <!-- Filters -->
    <div class="bg-white border shadow-sm rounded-lg mb-6 p-4">
      <form @submit.prevent="fetchData" class="grid grid-cols-1 md:grid-cols-4 gap-4 items-end">
        <div>
          <label class="text-sm font-medium mb-1">Start Month</label>
          <input v-model="filters.start" type="month" class="border px-2 py-1 rounded w-full" />
        </div>
        <div>
          <label class="text-sm font-medium mb-1">End Month</label>
          <input v-model="filters.end" type="month" class="border px-2 py-1 rounded w-full" />
        </div>
        <div>
          <label class="text-sm font-medium mb-1">Karyawan / Lokasi</label>
          <select v-model="filters.uid" class="border px-2 py-1 rounded w-full">
            <option value="all">Semua</option>
            <option v-for="emp in availableEmployees" :key="emp.uid" :value="emp.uid">{{ emp.nama }}</option>
          </select>
        </div>
        <div>
          <button type="submit" class="bg-blue-600 text-white px-3 py-1 rounded hover:bg-blue-700 w-full">
            Terapkan
          </button>
        </div>
      </form>
    </div>

    <!-- Chart Type Toggle (only for Health Metrics) -->
    <div v-if="activeTab==='health'" class="flex items-center justify-between mb-4">
      <div class="text-sm text-slate-600">Select chart type to visualize the data</div>
      <div class="flex gap-2">
        <button
          v-for="type in chartTypes"
          :key="type"
          :class="chartType===type ? activeBtn : inactiveBtn"
          @click="chartType = type"
        >
          <Icon :type="type" class="w-4 h-4 mr-1" /> {{ capitalize(type) }}
        </button>
      </div>
    </div>

    <!-- Metric Summary Cards (only Health Metrics) -->
    <div v-if="activeTab==='health'" class="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-4 gap-4 mb-6">
      <div
        v-for="m in metrics"
        :key="m.key"
        @click="selectMetric(m.key)"
        :class="['border-2 rounded-lg p-4 shadow-sm cursor-pointer transition-all hover:shadow-md', m.active ? 'border-blue-500 shadow-lg' : 'border-slate-200']"
      >
        <div class="flex justify-between mb-2">
          <p class="text-xs text-slate-500">{{ m.label }}</p>
          <span class="text-sm font-medium" :style="{ color: m.color }">{{ m.value }}</span>
        </div>
        <p class="text-xs text-slate-400">{{ m.unit }}</p>
        <div class="mt-2 space-y-1">
          <span v-if="m.status" class="inline-block px-2 py-0.5 rounded text-xs" :class="statusClass(m.status_color)">
            {{ m.status }}
          </span>
          <p v-if="m.threshold" class="text-xs text-slate-500">Threshold: {{ m.threshold }} {{ m.unit }}</p>
        </div>
      </div>
    </div>

    <!-- Chart Section -->
    <div v-if="chartData && chartData.length" class="border rounded-lg p-4 bg-slate-50/50">
      <ChartContainer
        :type="chartType"
        :data="chartData"
        :activeMetric="activeMetric"
        :showThreshold="activeTab==='health'"
      />
    </div>
    <div v-else class="p-12 text-center bg-slate-50 rounded-lg border-2 border-dashed border-slate-300">
      <p class="text-slate-600">Belum ada data grafik untuk range ini.</p>
      <p class="text-slate-500 text-sm mt-1">Coba sesuaikan filter di atas.</p>
    </div>
  </div>
</template>

<script setup>
import { ref, reactive, onMounted } from 'vue'
import ChartContainer from './ChartContainer.vue'

// Chart type toggle icon component
import { h } from 'vue'
const Icon = (props) => {
  const map = { bar:'fas fa-chart-bar', line:'fas fa-chart-line', area:'fas fa-chart-area' }
  const cls = `${map[props.type] || 'fas fa-chart-bar'} ${props.class || ''}`
  return h('i', { class: cls })
}

// Tabs
const activeTab = ref('health')

// Filters
const filters = reactive({ start:'', end:'', uid:'all' })
const chartType = ref('bar')
const chartTypes = ['bar','line','area']

// Metrics and chart data
const metrics = ref([])
const chartData = ref([])
const activeMetric = ref(null)
const availableEmployees = ref([])

// Toggle button classes
const activeBtn = 'bg-blue-600 text-white px-3 py-1 rounded hover:bg-blue-700 flex items-center'
const inactiveBtn = 'bg-gray-100 text-gray-700 px-3 py-1 rounded hover:bg-gray-200 flex items-center'

// Subtab button classes
const activeTabClass = 'px-4 py-2 -mb-px border-b-2 border-[#0073fe] text-[#0073fe] font-medium'
const inactiveTabClass = 'px-4 py-2 -mb-px border-b-2 border-transparent text-gray-600 hover:text-gray-800'

// Methods
function capitalize(s){ return (s||'')[0].toUpperCase()+s.slice(1) }
function statusClass(color){ return { destructive:'bg-red-100 text-red-700', warning:'bg-yellow-100 text-yellow-700', success:'bg-green-100 text-green-700' }[color] || 'bg-slate-100 text-slate-700' }
function selectMetric(key){ metrics.value.forEach(m=>m.active=m.key===key); activeMetric.value=key }
function switchTab(tab){ activeTab.value=tab; fetchData() }

// Fetch data from server
async function fetchData(){
  const params = new URLSearchParams()
  if(filters.start) params.set('start_month', filters.start)
  if(filters.end) params.set('end_month', filters.end)
  if(filters.uid && filters.uid!=='all') params.set('uid', filters.uid)
  params.set('submenu','grafik')
  params.set('grafik_json','1')
  if(activeTab.value==='health') params.set('mode','individual')
  else params.set('mode','aggregate')

  const res = await fetch(`/manager/?${params.toString()}`, { credentials:'same-origin' })
  const json = await res.json()

  if(activeTab.value==='health'){
    // Individual metrics
    const keys = Object.keys(json.series || {})
    chartData.value = json.x_dates.map((month,idx)=>{
      const row = { month }
      keys.forEach(k=>row[k]=json.series[k]?.[idx]??null)
      return row
    })
    const latestIdx = Math.max(0, chartData.value.length-1)
    metrics.value = keys.map(k=>{
      const latest = chartData.value[latestIdx]?.[k] ?? null
      return { key:k,label:k,color:'#0ea5e9',unit:'',value:latest,threshold:null,status:'',status_color:'',active:false }
    })
    activeMetric.value = metrics.value[0]?.key || null
  } else {
    // Aggregate well/unwell
    const months = json.months || []
    const well = json.well || []
    const unwell = json.unwell || []
    chartData.value = months.map((m,i)=>({ month:m, well:well[i]||0, unwell:unwell[i]||0 }))
    metrics.value = [{ key:'well_unwell',label:'Well & Unwell',color:'#0ea5e9',unit:'orang',value:`${json.summary?.well||0}/${json.summary?.unwell||0}`,status:'',status_color:'',active:true }]
    activeMetric.value='well_unwell'
  }
}

// Populate employees from global variable
function hydrateEmployeesFromGlobal(){
  if(window.__AVAILABLE_EMPLOYEES__ && Array.isArray(window.__AVAILABLE_EMPLOYEES__)) availableEmployees.value = window.__AVAILABLE_EMPLOYEES__
}

onMounted(()=>{
  hydrateEmployeesFromGlobal()
  fetchData()
})
</script>
