// static/js/components/grafik_manager.js
(function(){
  window.Components = window.Components || {};
  const { reactive, ref, watch, computed } = Vue;
  const MAX_SAFE_POINTS = 5000;
  // Hard cap window to avoid rendering extremely large histories that may freeze the UI
const SAFE_WINDOW_MONTHS = 24; // limit to last 24 months when datasets are large
  // Determine API base prefix based on current route (supports manager, nurse, and karyawan)
  const API_BASE = (function(){
    try {
      const p = window.location && window.location.pathname ? window.location.pathname : '';
      if (p.startsWith('/nurse')) return '/nurse';
      if (p.startsWith('/karyawan') || p.startsWith('/app_karyawan')) return '/karyawan';
      return '/manager';
    } catch(e) { return '/manager'; }
  })();

  // Month formatting helper
  function fmtMonthISO(d){
    const y = d.getFullYear();
    const m = String(d.getMonth()+1).padStart(2,'0');
    return `${y}-${m}`;
  }
  // Convert 'YYYY-MM' or similar to short month label 'Jan', 'Feb', ...
  function fmtMonthShortFromISO(s){
    try{
      if (!s || typeof s !== 'string') return s;
      // Accept formats like 'YYYY-MM', 'YYYY/MM'
      const parts = s.includes('-') ? s.split('-') : (s.includes('/') ? s.split('/') : []);
      const mm = parts.length>=2 ? parts[1] : s;
      // Indonesian short month labels
      const map = { '01':'Jan','1':'Jan','02':'Feb','2':'Feb','03':'Mar','3':'Mar','04':'Apr','4':'Apr','05':'Mei','5':'Mei','06':'Jun','6':'Jun','07':'Jul','7':'Jul','08':'Agu','8':'Agu','09':'Sep','9':'Sep','10':'Okt','11':'Nov','12':'Des' };
      return map[mm] || s;
    }catch(e){ return s; }
  }
  // Convert 'YYYY-MM' to 'Jan 2025'
  function fmtMonthFullFromISO(s){
    try{
      if (!s || typeof s !== 'string') return s;
      const parts = s.split('-');
      if (parts.length < 2) return s;
      const y = parts[0];
      const mm = parts[1];
      const map = { '01':'Jan','1':'Jan','02':'Feb','2':'Feb','03':'Mar','3':'Mar','04':'Apr','4':'Apr','05':'Mei','5':'Mei','06':'Jun','6':'Jun','07':'Jul','7':'Jul','08':'Agu','8':'Agu','09':'Sep','9':'Sep','10':'Okt','11':'Nov','12':'Des' };
      return `${map[mm]||mm} ${y}`;
    }catch(e){ return s; }
  }

  // Metric config for thresholds
  const METRIC_CONFIG = {
    // Color adjustments: Sewaktu = red, Puasa = light red
    'Gula Darah Puasa': { threshold:126, label:'Tinggi', color:'#f87171' }, // light red (red-400)
    'Gula Darah Sewaktu': { threshold:200, label:'Tinggi', color:'#dc2626' }, // red (red-600)
    'Tekanan Darah': { threshold:140, label:'Tinggi', color:'#ef4444' },
    'Cholesterol': { threshold:200, label:'Tinggi', color:'#06b6d4' },
    'Asam Urat': { threshold:7, label:'Tinggi', color:'#f59e0b' },
  };
  // Expose for diagnostics
  window.MANAGER_METRIC_CONFIG = METRIC_CONFIG;

// ECharts wrapper (robust): protect against DOM races, serialize updates
  // ECharts wrapper component
  const EChartWrapper = {
    name: 'EChartWrapper',
    props: { options: Object, series: Array, height: [String, Number] },
    template: `<div ref="el" :style="{width:'100%',height:height+'px'}"></div>`,
    mounted() {
      if (typeof echarts === 'undefined') {
        console.warn('[EChartWrapper] echarts not found');
        return;
      }
      this.chart = echarts.init(this.$refs.el);
      // Track last applied chart type to decide merge vs replace on updates
      try { this._lastChartType = (this.options && this.options.chartType) || 'line'; } catch(e) { this._lastChartType = 'line'; }
      this.updateChart(true);
      window.addEventListener('resize', this.resize);
    },
    methods: {
      scheduleUpdate(){
        if (this._updateScheduled) return;
        this._updateScheduled = true;
        requestAnimationFrame(()=>{ this._updateScheduled = false; this.updateChart(false); });
      },
      updateChart(initial) {
        if (!this.options || !Array.isArray(this.series)) return;
        const base = Object.assign({}, this.options);
        const chartType = base.chartType || 'line';
        base.series = this.series.map(s => ({
          name: s.name,
          type: chartType === 'area' ? 'line' : chartType,
          data: s.data,
          smooth: true,
          connectNulls: true,
          areaStyle: chartType === 'area' ? { opacity: 0.25 } : undefined,
          lineStyle: Object.assign({ width: 3 }, s.lineStyle || {}),
          itemStyle: { color: s.color || '#0073fe' },
          // Show value labels on top of every bar when chart type is 'bar'.
          // This ensures all parameters (other than 'Semua') display current checkup values above the columns.
          // Tooltip behavior remains unchanged.
          label: chartType === 'bar' ? { show: true, position: 'top' } : undefined,
          labelLayout: chartType === 'bar' ? { hideOverlap: true } : undefined,
          // Pass-through advanced properties when provided
          endLabel: s.endLabel,
          markLine: s.markLine,
          showSymbol: typeof s.showSymbol === 'boolean' ? s.showSymbol : undefined,
          emphasis: s.emphasis,
          symbol: s.symbol
        }));
        // Decide whether to fully replace the option to avoid stale artifacts on type change
        const typeChanged = this._lastChartType !== chartType;
        if (initial || typeChanged) {
          // Clear previous state to prevent lingering series (e.g., threshold line → bar) and area fills
          try { if (this.chart && typeof this.chart.clear === 'function') this.chart.clear(); } catch(e){}
          this.chart.setOption(base, true, true);
        } else {
          // Use merge for regular data updates
          this.chart.setOption(base, false, true);
        }
        this._lastChartType = chartType;
      },
      resize() { if (this.chart) this.chart.resize(); }
    },
    watch: {
      options: { deep: false, handler() { this.scheduleUpdate(); } },
      series: { deep: false, handler() { this.scheduleUpdate(); } },
      // React specifically to chartType changes inside options so toggling type is seamless
      'options.chartType': function(){ this.scheduleUpdate(); }
    },
    unmounted() {
      window.removeEventListener('resize', this.resize);
      if (this.chart) this.chart.dispose();
    }
  };

  // Chart type toggle (icons + text)
  const ChartTypeToggle = {
    name:'ChartTypeToggle',
    props:{ type:{ type:String, default:'bar' } },
    emits:['update'],
    template:`
      <div class="flex items-center gap-2">
        <button :class="btnClass('bar')" @click="$emit('update','bar')">
          <i data-lucide="chart-column" class="w-4 h-4 mr-2"></i>Bar
        </button>
        <button :class="btnClass('line')" @click="$emit('update','line')">
          <i data-lucide="chart-line" class="w-4 h-4 mr-2"></i>Line
        </button>
        <button :class="btnClass('area')" @click="$emit('update','area')">
          <i data-lucide="chart-area" class="w-4 h-4 mr-2"></i>Area
        </button>
      </div>
    `,
    methods:{
      btnClass(t){ return `px-3 py-2 rounded-md flex items-center gap-1 ${this.type===t ? 'bg-[#0073fe] text-white':'bg-gray-100 text-gray-700 hover:bg-gray-200'}`; }
    },
    mounted(){ try{ if(window.lucide){ if(typeof window.lucide.createIcons==='function'){ window.lucide.createIcons(); } else if(typeof window.lucide.replace==='function'){ window.lucide.replace(); } } }catch(e){} },
    updated(){ try{ if(window.lucide){ if(typeof window.lucide.createIcons==='function'){ window.lucide.createIcons(); } else if(typeof window.lucide.replace==='function'){ window.lucide.replace(); } } }catch(e){} }
  };

  const GrafikManager = {
    name:'GrafikManager',
    components:{ EChartWrapper, ChartTypeToggle },
    data(){
      return {
        tab:'health', // 'health' | 'well'
        // Allow hiding the Well/Unwell tab in profile contexts (Edit Master Data → Grafik)
        showWellTab: true,
        // Option to hide only Karyawan selector while keeping Parameter/Month filters visible
        hideKaryawanSelect: false,
        // Filters: select month range and a single karyawan; parameter optional
        // Default parameter set to 'Semua' to include all metrics by default
        filters:{ start_month:'', end_month:'', karyawan_uid:'', parameter:'Semua' },
        // Allow pages to hide filters area (e.g., nurse profile context)
        showSelectors: true,
        chartType:'area',
        activeMetric:null,
        metricsList:['Gula Darah Puasa','Gula Darah Sewaktu','Tekanan Darah','Cholesterol','Asam Urat'],
        // Card model for Health Metrics (rendered above the chart)
        healthMetrics:[],
        // lokasi filter removed per request
        karyawanList:[],
        // Initialize charts as null to avoid rendering ECharts with empty config
        chartSeries:[],
        chartOptions:null,
        wellUnwellSeries:[],
        wellUnwellOptions:null,
        // Health tab (overhauled): show exceedance counts per month for selected employee
        healthExceedSeries: [],
        healthExceedOptions: null,
        // Details table for Health tab: parameters exceeding thresholds per month
        healthExceedDetails: [],
        healthExceedTablePage: 1,
        healthExceedPageSize: 12,
        // Render guard: whether selected karyawan has medical data for the chosen window
        healthHasData: false,
        // No remount keys needed
        // Cached datasets for safe re-render lifecycle without refetch
        cachedUnwellData: null,
        // Small summary block: total Unwell in current window
        totalUnwellWindow: 0,
        // Details table (Unwell list per month)
        wellUnwellDetails: [],
        wellUnwellTablePage: 1,
        wellUnwellPageSize: 12, // Show all 12 months
        // Rendering lifecycle guard
        isRenderingChart: false,
        _chartTypeTimer: null,
        // Fetch control to avoid overlapping requests that can freeze UI
        _fetching: false,
        _wellAbortCtrl: null,
        _healthAbortCtrl: null,
        // Simple cache keys to bypass redundant network calls when filters unchanged
        _lastHealthKey: '',
        _lastWellKey: '',
        // Recommendations cache for selected employee
        recommendations: [],
        recByParam: {},
        // Global recommendations cache (per parameter)
        globalRecByParam: {},
        _globalRecLoaded: false
      };
    },
    computed:{
      wellTableRows(){
        try{
          const total = Array.isArray(this.wellUnwellDetails) ? this.wellUnwellDetails.length : 0;
          const size = Number(this.wellUnwellPageSize) || 5;
          const page = Number(this.wellUnwellTablePage) || 1;
          const start = Math.max(0, (page - 1) * size);
          const end = Math.min(total, start + size);
          return Array.isArray(this.wellUnwellDetails) ? this.wellUnwellDetails.slice(start, end) : [];
        }catch(e){ return []; }
      },
      healthTableRows(){
        try{
          const total = Array.isArray(this.healthExceedDetails) ? this.healthExceedDetails.length : 0;
          const size = Number(this.healthExceedPageSize) || 12;
          const page = Number(this.healthExceedTablePage) || 1;
          const start = Math.max(0, (page - 1) * size);
          const end = Math.min(total, start + size);
      return Array.isArray(this.healthExceedDetails) ? this.healthExceedDetails.slice(start, end) : [];
        }catch(e){ return []; }
      },
      // Compute current month exceed recommendations mapped to latest saved rekomendasi per parameter
      currentExceedRecommendations(){
        try{
          // Find the latest month (from the end) that actually has exceeded parameters
          const rows = Array.isArray(this.healthExceedDetails) ? this.healthExceedDetails : [];
          if (!rows.length) return [];
          let target = null;
          for (let i = rows.length - 1; i >= 0; i--) {
            const r = rows[i];
            const p = Array.isArray(r.parameters) ? r.parameters.filter(x => x && x.isExceed) : [];
            if (p.length) { target = { month: r.month, parameters: p }; break; }
          }
          if (!target) return [];
          const params = target.parameters;
          const out = [];
          for (const p of params){
            const name = p.name;
            const recs = this.recByParam && this.recByParam[name] ? this.recByParam[name] : [];
            let latest = Array.isArray(recs) && recs.length ? recs[0] : null;
            // Fallback to global recommendation if no per-employee entry
            if (!latest && this.globalRecByParam && this.globalRecByParam[name]) {
              latest = this.globalRecByParam[name];
            }
            if (latest && latest.rekomendasi_text){ out.push({ parameter:name, text:String(latest.rekomendasi_text||'') }); }
          }
          return out;
        }catch(e){ return []; }
      },
      // Expose the month ISO string that currentExceedRecommendations refers to
      latestExceedMonthISO(){
        try{
          const rows = Array.isArray(this.healthExceedDetails) ? this.healthExceedDetails : [];
          if (!rows.length) return '';
          for (let i = rows.length - 1; i >= 0; i--) {
            const r = rows[i];
            const p = Array.isArray(r.parameters) ? r.parameters.filter(x => x && x.isExceed) : [];
            if (p.length) { return r.month || ''; }
          }
          return '';
        }catch(e){ return ''; }
      },
      selectedEmployee(){
        try{
          const uid = String(this.filters.karyawan_uid||'');
          if (!uid) return null;
          return (this.karyawanList||[]).find(k=>String(k.uid)===uid) || null;
        }catch(e){ return null; }
      },
      // Fallback list: show all global recommendations when no exceed recommendations are available
      globalRecommendationList(){
        try{
          const map = this.globalRecByParam || {};
          const keys = Object.keys(map);
          return keys.map(k => ({ parameter: k, text: String((map[k] && map[k].rekomendasi_text) || '') }))
                     .filter(x => x.text && x.text.trim().length > 0);
        }catch(e){ return []; }
      }
    },
    async mounted(){
      try {
        // Read optional dataset flags from the mount element
        const rootEl = document.getElementById('grafik-manager');
        if (rootEl && rootEl.dataset) {
          const preUid = rootEl.dataset.preselectUid || '';
          const hideSel = rootEl.dataset.hideSelectors === 'true';
          const hideUnwell = rootEl.dataset.hideUnwell === 'true';
          const hideKSelect = rootEl.dataset.hideKaryawanSelect === 'true';
          if (preUid) { this.filters.karyawan_uid = String(preUid); }
          if (hideSel) { this.showSelectors = false; }
          if (hideUnwell) { this.showWellTab = false; this.tab = 'health'; }
          if (hideKSelect) { this.hideKaryawanSelect = true; }
        }
        this.applyDefaultFilters();
        // Seed healthMetrics card model from metricsList
        this.buildHealthMetricsModel();
        // Fetch lokasi and karyawan first to ensure selected karyawan is set,
        // then fetch data so Health tab shows data for the selected karyawan (not aggregated all employees)
        await Promise.all([
          this.fetchKaryawanList()
        ]);
        await this.fetchData();
        // Load global recommendations (per-parameter, not tied to a karyawan)
        try{ this.fetchGlobalRecommendations().catch(()=>{}); }catch(e){}
        // Hide legacy Plotly fallback (if present) after Vue chart is ready
        try { const legacy = document.getElementById('grafik-legacy'); if (legacy) legacy.classList.add('hidden'); } catch(e){}
      } catch(e) {
        console.warn('[GrafikManager] mounted sequence failed', e);
      }
      // Avoid a global icon replacement on the whole document during initial mount
      // If lucide is available, schedule a scoped replace for the grafik container only
      try {
        if (window.lucide) {
          console.log('[Lucide] init in GrafikManager.mounted, has createIcons?', typeof window.lucide.createIcons==='function');
          if(typeof window.lucide.createIcons==='function'){ window.lucide.createIcons(); }
          else if(typeof window.lucide.replace==='function'){ window.lucide.replace(); }
        } else {
          console.warn('[Lucide] global not found, injecting CDN script');
          const s=document.createElement('script');
          s.src='https://cdn.jsdelivr.net/npm/lucide@latest/dist/umd/lucide.min.js';
          s.async=true;
          s.onload=function(){ try{ if(window.lucide && window.lucide.createIcons) window.lucide.createIcons(); }catch(e){} };
          document.head.appendChild(s);
        }
      } catch(e) { /* noop */ }
      // Diagnostics: check ECharts canvas after initial render
      setTimeout(()=>{
        try{
          const el = document.querySelector('#grafik-manager .echarts');
          console.log('[Diag] ECharts canvas present?', !!el, el);
        }catch(e){ console.warn('[Diag] ECharts DOM check failed', e); }
      }, 800);
    },
    watch:{
      // Debounced chart type change watcher using cached data only
      chartType:{
        handler(newType, oldType){
          try { console.log(`[Diag] Chart type changed: ${newType} tab: ${this.tab} prev: ${oldType}`); } catch(e){}
          clearTimeout(this._chartTypeTimer);
          // Use a short debounce to batch rapid toggles
          this._chartTypeTimer = setTimeout(() => {
            try {
              // Do NOT refetch or remount; just adjust chart type and options
              this.updateChartType(newType, oldType);
            } catch(e) {
              console.warn('[Diag] updateChartType failed in watcher', e);
            }
          }, 120);
        },
        flush: 'post'
      },
      activeMetric(){ this.updateMetricOpacity(); },
      'filters.parameter'(){
        // Shared layout: reflect selected parameter as active metric on Well tab
        if (this.tab==='well'){
          this.activeMetric = this.filters.parameter;
          this.updateMetricOpacity();
        }
      }
    },
    methods:{
      async destroyChartSafe(){
        try {
          const refComp = this.tab === 'well' ? this.$refs.wellChart : this.$refs.healthChart;
          if (refComp && refComp.chart && typeof refComp.chart.dispose === 'function') {
            try {
              await new Promise(r => setTimeout(r, 50));
              refComp.chart.dispose();
              refComp.chart = null;
              console.log('[Diag] ECharts chart disposed safely');
            } catch(e) { console.warn('[Diag] ECharts chart dispose failed', e); }
          }
        } catch(e) { /* noop */ }
      },
      // Build initial card entries based on metricsList
      buildHealthMetricsModel(){
        try{
          const ICON_MAP = {
            'Gula Darah Puasa': 'droplet',
            'Gula Darah Sewaktu': 'droplet',
            'Tekanan Darah': 'activity',
            'Cholesterol': 'heart',
            'Asam Urat': 'flask-conical'
          };
          const UNITS_MAP = {
            'Gula Darah Puasa': 'mg/dL',
            'Gula Darah Sewaktu': 'mg/dL',
            'Tekanan Darah': 'mmHg',
            'Cholesterol': 'mg/dL',
            'Asam Urat': 'mg/dL'
          };
          const defaults = (this.metricsList || []).map((m)=>{
            const icon = ICON_MAP[m] || 'activity';
            const iconHex = (METRIC_CONFIG[m] && METRIC_CONFIG[m].color) ? METRIC_CONFIG[m].color : '#0073fe';
            return {
              title: m,
              description: `Rata-rata ${String(m).toLowerCase()} karyawan`,
              value: '-',
              icon,
              iconHex,
              units: UNITS_MAP[m] || '',
              statusLabel: '',
              statusClass: ''
            };
          });
          this.healthMetrics = defaults;
          // Render icons on next tick
          Vue.nextTick(() => { try { if (window.lucide && typeof window.lucide.createIcons==='function') window.lucide.createIcons(); } catch(e){} });
        }catch(e){ this.healthMetrics = []; }
      },
      // Compute average non-null numeric value for each metric from chartSeries
      updateHealthMetricsValues(){
        try{
          if (!Array.isArray(this.healthMetrics) || !Array.isArray(this.chartSeries)) return;
          // Create lookup by series name
          const byName = Object.fromEntries(this.chartSeries.map(s => [s.name, s]));
          const avgNonNull = (nums)=>{
            if (!Array.isArray(nums)) return null;
            let sum=0, count=0;
            for (const v of nums){ if (typeof v==='number' && !Number.isNaN(v)){ sum+=v; count++; } }
            return count? (sum/count) : null;
          };
          this.healthMetrics = this.healthMetrics.map(hm => {
            const s = byName[hm.title];
            const avg = s && Array.isArray(s.data) ? avgNonNull(s.data) : null;
            const formatted = (avg==null ? '-' : `${Number(avg.toFixed(1))} ${hm.units || ''}`);
            let statusLabel = '';
            let statusClass = '';
            const cfg = METRIC_CONFIG[hm.title];
            if (avg!=null && cfg && typeof cfg.threshold==='number'){
              if (avg < cfg.threshold){
                statusLabel = 'Well';
                statusClass = 'text-green-700 bg-green-100';
              } else {
                statusLabel = 'Unwell';
                statusClass = 'text-red-700 bg-red-100';
              }
            }
            return { ...hm, value: formatted, statusLabel, statusClass };
          });
          // Ensure Lucide icons render after DOM update
          Vue.nextTick(() => { try { if (window.lucide && typeof window.lucide.createIcons==='function') window.lucide.createIcons(); } catch(e){} });
        }catch(e){ /* noop */ }
      },
      sendDiagnosticLog(payload){
        try{
          fetch(`${API_BASE}/grafik/diagnostic-log/`,{
            method:'POST',
            headers:{ 'Content-Type':'application/json' },
            body: JSON.stringify(payload)
          }).catch(()=>{});
        }catch(e){ /* noop */ }
      },
      applyDefaultFilters(){
        // If a specific karyawan is preselected or selectors are hidden (profile context),
        // default to full history by leaving month range empty so backend returns all months.
        const hasPreselectedUID = !!(this.filters && this.filters.karyawan_uid);
        const selectorsHidden = this.showSelectors === false;
        if (hasPreselectedUID || selectorsHidden) {
          this.filters.start_month='';
          this.filters.end_month='';
        } else {
          const now=new Date(), past=new Date(); past.setMonth(past.getMonth()-5);
          this.filters.start_month=fmtMonthISO(past);
          this.filters.end_month=fmtMonthISO(now);
        }
        // lokasi filter removed
      },
      async fetchKaryawanList(){
        try{
          const res = await fetch(`${API_BASE}/grafik/karyawan-list/`,{ headers:{'Accept':'application/json'} });
          const json = await res.json();
          const arr = Array.isArray(json) ? json : (json.karyawan||[]);
          // Normalize shape to {uid,nama}
          this.karyawanList = arr.map(x=>({ uid: String(x.uid||''), nama: x.nama||String(x.name||''), lokasi: (x.lokasi!=null? String(x.lokasi): '') })).filter(x=>x.uid && x.nama);
          // Auto-select first karyawan for Health tab if none selected
          if (this.tab === 'health' && (!this.filters.karyawan_uid || this.filters.karyawan_uid === '')){
            const first = this.karyawanList[0];
            if (first && first.uid) {
              this.filters.karyawan_uid = first.uid;
              console.log('[Diag] Auto-selected first karyawan for Health tab:', first);
            }
          }
        }catch(e){ this.karyawanList = []; }
      },
      async fetchData(){
        // Guard against concurrent fetches
        if (this._fetching) {
          // Best-effort: abort previous in-flight request if any
          try { if (this.tab==='health' && this._healthAbortCtrl) this._healthAbortCtrl.abort(); else if (this.tab==='well' && this._wellAbortCtrl) this._wellAbortCtrl.abort(); } catch(e){}
        }
        this._fetching = true;
        // Always include month range; defer uid inclusion to health-only branch to decouple tabs
        const params = new URLSearchParams({
          month_from: this.filters.start_month || '',
          month_to: this.filters.end_month || ''
        });
        try{
          if(this.tab==='health'){
            // If no karyawan selected, do not fetch; mark as no data for health tab
            if (!this.filters.karyawan_uid) {
              this.healthExceedSeries = [];
              this.healthExceedOptions = null;
              this.healthExceedDetails = [];
              this.totalUnwellWindow = 0;
              this.healthHasData = false;
              return;
            }
            // Health metrics depend on selected karyawan → include uid
            params.set('uid', this.filters.karyawan_uid);
            const key = `H|${this.filters.start_month}|${this.filters.end_month}|${this.filters.karyawan_uid}`;
            // Recommendations are global per-parameter; ensure global recommendations are loaded
            try{ if(!this._globalRecLoaded) await this.fetchGlobalRecommendations(); }catch(e){}
            // If we already have raw data for these filters, reuse without refetch
            if (this._lastHealthKey === key && this._healthRaw) {
              this.prepareHealthExceedChart(this._healthRaw);
            } else {
              await this.fetchHealthMetrics(params);
              this._lastHealthKey = key;
            }
          } else {
            // Well/Unwell grafik respects parameter filter (including "Semua")
            const p = (this.filters.parameter || '').trim();
            if (p) params.set('parameter', p);
            // Decouple Well tab from karyawan uid
            const key = `W|${this.filters.start_month}|${this.filters.end_month}|${p}`;
            if (this._lastWellKey === key && this.cachedUnwellData) {
              this.prepareWellUnwellChart(this.cachedUnwellData);
            } else {
              await this.fetchWellUnwellSummary(params);
              this._lastWellKey = key;
            }
          }
        }catch(e){ console.warn('[GrafikManager] fetch failed',e); }
        finally { this._fetching = false; }
      },
      async fetchHealthMetrics(params){
        try{
          // Abort any previous health fetch to prevent overlapping updates
          try { if (this._healthAbortCtrl) this._healthAbortCtrl.abort(); } catch(e){}
          this._healthAbortCtrl = new AbortController();
          const res = await fetch(`${API_BASE}/grafik/health-metrics-summary/?${params.toString()}`,{ headers:{'Accept':'application/json'}, signal: this._healthAbortCtrl.signal });
          if(!res.ok) throw new Error(`HTTP ${res.status}`);
          const data = await res.json();
          const xLen=(data.x_dates||[]).length; const keys=Object.keys(data.series||{});
          // Detect suspicious null/undefined values across series
          let nulls=0, nonNums=0;
          keys.forEach(k=>{
            const arr = (data.series||{})[k]||[];
            if (Array.isArray(arr)) arr.forEach(v=>{ if (v == null) nulls++; else if (typeof v !== 'number') nonNums++; });
          });
          console.log('[Diagnostic] grafik_manager init', { filters:this.filters, dataLength:{ well:0, unwell:0 }, xDatesLength:xLen, seriesKeys:keys, nullCount:nulls, nonNumericCount:nonNums });
          this.sendDiagnosticLog({ filters:{ month_from:this.filters.start_month, month_to:this.filters.end_month, uid:this.filters.karyawan_uid }, xDatesLength:xLen, seriesKeys:keys, nullCount:nulls, nonNumericCount:nonNums });
          // Render gating: if dataset is huge, we will still render but downscale to a safe window
          const maxSeriesLen = keys.reduce((mx,k)=>{ const arr = (data.series||{})[k]||[]; return Math.max(mx, Array.isArray(arr)?arr.length:0); }, 0);
          if (xLen >= MAX_SAFE_POINTS || maxSeriesLen >= MAX_SAFE_POINTS) {
            console.warn('[Diagnostic] Chart data very large for Health Metrics, downscaling to last window', { xLen, maxSeriesLen, window: SAFE_WINDOW_MONTHS });
          }
          this.prepareHealthExceedChart(data);
          // Prefetch the well/unwell dataset in the background so switching tabs is instant
          try {
            if (!this.cachedUnwellData) {
              const p = new URLSearchParams();
              p.set('month_from', this.filters.start_month || '');
              p.set('month_to', this.filters.end_month || '');
              const param = (this.filters.parameter || '').trim();
              if (param) p.set('parameter', param);
              setTimeout(() => { this.fetchWellUnwellSummary(p).catch(()=>{}); }, 10);
            }
          } catch(e) { /* noop */ }
        }catch(e){
          if (e && e.name === 'AbortError') { console.warn('[GrafikManager] health metrics fetch aborted'); return; }
          console.warn('[GrafikManager] health metrics unavailable',e);
        }
      },
      // New: Prepare Health tab chart as exceedance counts per month for selected employee
      prepareHealthExceedChart(data){
        // Guard: need x_dates and series
        if (!data || (!Array.isArray(data.x_dates) || !(data.series && Object.keys(data.series||{}).length))) {
          console.warn('[Diag] prepareHealthExceedChart skipped — no data');
          this.healthHasData = false;
          this.healthExceedSeries = [];
          this.healthExceedOptions = null;
          this.healthExceedDetails = [];
          this.totalUnwellWindow = 0;
          return;
        }
        // Persist raw
        this._healthRaw = data;
        const raw = data.series || {};
        // Apply explicit month range filtering similar to Grafik Unwell
        let xDates = Array.isArray(data.x_dates) ? data.x_dates.slice() : [];
        const startIso = String(this.filters.start_month || '');
        const endIso = String(this.filters.end_month || '');
        const hasRange = !!(startIso && endIso);
        let idxs = xDates.map((_, i) => i);
        if (hasRange) {
          try {
            idxs = xDates.reduce((acc, iso, i) => { if (iso >= startIso && iso <= endIso) acc.push(i); return acc; }, []);
          } catch(e) { /* noop */ }
        }
        // Months returned by backend within selected range
        const xDatesFiltered = idxs.map(i => xDates[i]);
        // Build a complete month axis for the selected range (fill missing months with zeros)
        function enumerateMonthsISO(startIso, endIso){
          try{
            if (!startIso || !endIso) return [];
            const start = new Date(`${startIso}-01`);
            const end = new Date(`${endIso}-01`);
            if (isNaN(start) || isNaN(end) || start > end) return [];
            const out=[]; const cur=new Date(start.getTime());
            while(cur <= end){ out.push(fmtMonthISO(cur)); cur.setMonth(cur.getMonth()+1); }
            return out;
          }catch(e){ return []; }
        }
        const fullMonthsIso = hasRange ? enumerateMonthsISO(startIso, endIso) : xDatesFiltered.slice();
        // If month range specified but computed full list is empty, show no data
        if (hasRange && fullMonthsIso.length === 0) {
          console.warn('[Diag] Health: invalid month range — empty axis');
          this.healthHasData = false;
          this.healthExceedSeries = [];
          this.healthExceedOptions = null;
          this.healthExceedDetails = [];
          this.totalUnwellWindow = 0;
          return;
        }
        // Build per-metric arrays and filter them by idxs
        const seriesByMetricRaw = Object.fromEntries(this.metricsList.map(name => [name, Array.isArray(raw[name]) ? raw[name] : []]));
        const seriesByMetric = Object.fromEntries(Object.keys(seriesByMetricRaw).map(name => [name, idxs.map(i => seriesByMetricRaw[name][i])]));
        // Build per-month exceedance counts
        const monthsShort = (fullMonthsIso || []).map(fmtMonthShortFromISO);
        const metrics = this.filters && this.filters.parameter && this.filters.parameter !== 'Semua' ? [this.filters.parameter] : this.metricsList.slice();
        // Detect if selected karyawan has any medical data (any finite number present)
        let hasAnyValue = false;
        try {
          for (const name of this.metricsList) {
            const arr = seriesByMetric[name] || [];
            if (arr.some(v => Number.isFinite(typeof v === 'number' ? v : Number(v)))) { hasAnyValue = true; break; }
          }
        } catch(e) {}
        if (!hasAnyValue) {
          this.healthHasData = false;
          this.healthExceedSeries = [];
          this.healthExceedOptions = null;
          this.healthExceedDetails = [];
          this.totalUnwellWindow = 0;
          console.log('[Diag] No medical data for selected karyawan');
          return;
        }
        // Map month ISO to index in filtered arrays
        const monthToIdx = Object.fromEntries(xDatesFiltered.map((iso, i) => [iso, i]));
        const counts = fullMonthsIso.map((mIso) => {
          const idx = monthToIdx[mIso];
          if (idx == null) return 0;
          let c = 0;
          for (const name of metrics) {
            const cfg = METRIC_CONFIG[name];
            const arr = seriesByMetric[name] || [];
            const val = arr[idx];
            if (!cfg) continue;
            const num = typeof val === 'number' ? val : Number(val);
            if (Number.isFinite(num) && num >= cfg.threshold) c++;
          }
          return c;
        });
        // Decide chart mode: specific parameter → actual values with threshold; 'Semua' → exceedance counts
        const selectedParam = (this.filters && this.filters.parameter && this.filters.parameter !== 'Semua') ? this.filters.parameter : null;
        // Base window (months)
        let monthsWin = monthsShort.slice();
        if (monthsWin.length > SAFE_WINDOW_MONTHS) {
          const start = monthsWin.length - SAFE_WINDOW_MONTHS;
          monthsWin = monthsWin.slice(start);
        }
        if (selectedParam) {
          // Build actual per-month values for selected parameter
          const arrSel = seriesByMetric[selectedParam] || [];
          const valuesFull = (fullMonthsIso || []).map((mIso) => {
            const idx = monthToIdx[mIso];
            const v = (idx == null) ? null : arrSel[idx];
            const num = typeof v === 'number' ? v : Number(v);
            return Number.isFinite(num) ? num : null;
          });
          let valuesWin = valuesFull.slice();
          if (valuesWin.length > SAFE_WINDOW_MONTHS) {
            const start = valuesWin.length - SAFE_WINDOW_MONTHS;
            valuesWin = valuesWin.slice(start);
          }
          const cfg = METRIC_CONFIG[selectedParam] || {};
          const thr = typeof cfg.threshold === 'number' ? cfg.threshold : null;
          const unit = this.unitFor(selectedParam);
          const dataMax = valuesWin.filter(v => Number.isFinite(v)).reduce((mx, v) => Math.max(mx, v), 0);
          const baseMax = Math.max(dataMax, Number.isFinite(thr) ? thr : 0);
          const niceMax = (function(m){
            if (m <= 100) return Math.ceil(Math.max(10, m) / 10) * 10;
            if (m <= 200) return Math.ceil(m / 20) * 20;
            if (m <= 300) return Math.ceil(m / 50) * 50;
            return Math.ceil(m / 100) * 100;
          })(baseMax);
          const tickAmt = 10;
          const dataColor = (cfg.color || '#0ea5e9');
          const thrColor = '#f59e0b';
          const seriesArr = [ { name: selectedParam, data: valuesWin, color: dataColor } ];
          if (Number.isFinite(thr)) {
            // In bar mode, draw threshold as a horizontal markLine instead of a bar series
            if ((this.chartType || 'line') === 'bar') {
              seriesArr[0].markLine = {
                silent: true,
                symbol: 'none',
                lineStyle: { type: 'dashed', color: thrColor, width: 2 },
                label: { formatter: `${thr} ${unit}`, position: 'end' },
                data: [ { yAxis: thr } ]
              };
            } else {
              // Line/area: keep threshold as a dashed line series with end label
              seriesArr.push({
                name: 'Threshold',
                data: monthsWin.map(() => thr),
                color: thrColor,
                lineStyle: { width: 2, type: 'dashed' },
                showSymbol: false,
                endLabel: { show: true, formatter: `${thr} ${unit}` }
              });
            }
          }
          this.healthExceedSeries = seriesArr;
          this.healthExceedOptions = {
            chartType: this.chartType,
            tooltip: { trigger: 'axis' },
            legend: { top: 10 },
            grid: { left: 40, right: 20, bottom: 40, top: 40 },
            xAxis: { type: 'category', data: monthsWin },
            yAxis: { type: 'value', min: 0, max: niceMax, splitNumber: tickAmt, splitLine: { lineStyle: { color: '#e5e7eb' } } },
            color: seriesArr.map(s => s.color)
          };
        } else {
          // Default: exceedance counts per month
          let countsWin = counts.slice();
          if (monthsWin.length > SAFE_WINDOW_MONTHS) {
            const start = monthsWin.length - SAFE_WINDOW_MONTHS;
            monthsWin = monthsWin.slice(start);
            countsWin = countsWin.slice(start);
          }
          const maxVal = countsWin.length ? Math.max(...countsWin) : 0;
          const niceMax = (function(m){
            if (m <= 5) return 5;
            if (m <= 10) return 10;
            if (m <= 20) return 20;
            if (m <= 50) return 50;
            if (m <= 100) return 100;
            return Math.ceil(m / 50) * 50;
          })(maxVal);
          const tickAmt = niceMax <= 10 ? niceMax : (niceMax <= 50 ? 10 : 10);
          const strokeColor = '#ef4444';
          this.healthExceedSeries = [{ name: 'Unwell', data: countsWin, color: strokeColor }];
          this.healthExceedOptions = {
            chartType: this.chartType,
            tooltip: { trigger: 'axis' },
            legend: { top: 10 },
            grid: { left: 40, right: 20, bottom: 40, top: 40 },
            xAxis: { type: 'category', data: monthsWin },
            yAxis: { type: 'value', min: 0, max: niceMax, splitNumber: tickAmt, splitLine: { lineStyle: { color: '#e5e7eb' } } },
            color: [strokeColor]
          };
        }
        // Build Health details table: show ALL medical parameters per month for selected employee
        try {
          this.healthExceedDetails = (fullMonthsIso || []).map((mIso) => {
            const idx = monthToIdx[mIso];
            if (idx == null) {
              return { month: mIso, parameters: [] };
            }
            // Collect all metrics with available values (normal or exceeding)
            const allMetrics = this.metricsList.map(name => {
              const cfg = METRIC_CONFIG[name];
              const arr = seriesByMetric[name] || [];
              const val = arr[idx];
              const num = typeof val === 'number' ? val : Number(val);
              if (!Number.isFinite(num)) return null; // skip if no value
              const isExceed = cfg && num >= cfg.threshold;
              return { name, value: num, unit: this.unitFor(name), isExceed };
            }).filter(Boolean);
            const filtered = (this.filters && this.filters.parameter && this.filters.parameter !== 'Semua') ? allMetrics.filter(x => x.name === this.filters.parameter) : allMetrics;
            return { month: mIso, parameters: filtered };
          });
          // Reset table page and cap display via computed to max 12 rows
          this.healthExceedTablePage = 1;
        } catch(e) { this.healthExceedDetails = []; }
        // Total Unwell window: for 'Semua' sum counts; for specific parameter, count months exceeding threshold
        try {
          const selectedParam2 = (this.filters && this.filters.parameter && this.filters.parameter !== 'Semua') ? this.filters.parameter : null;
          if (selectedParam2) {
            const cfg2 = METRIC_CONFIG[selectedParam2] || {};
            const thr2 = typeof cfg2.threshold==='number' ? cfg2.threshold : null;
            const vals2 = (this.healthExceedSeries && this.healthExceedSeries[0] && Array.isArray(this.healthExceedSeries[0].data)) ? this.healthExceedSeries[0].data : [];
            this.totalUnwellWindow = (Number.isFinite(thr2) ? vals2.reduce((acc, v) => acc + ((Number.isFinite(v) && v >= thr2) ? 1 : 0), 0) : 0);
          } else {
            const series = this.healthExceedSeries && this.healthExceedSeries[0] ? this.healthExceedSeries[0].data : [];
            this.totalUnwellWindow = Array.isArray(series) ? series.reduce((acc, v) => acc + (Number.isFinite(v) ? v : 0), 0) : 0;
          }
        } catch(e) { this.totalUnwellWindow = 0; }
        console.log('[Diag] Health chart prepared', { months: monthsWin.length, mode: selectedParam ? 'metric-values' : 'counts', selectedParam: this.filters.parameter });
        this.healthHasData = true;
      },
      // Per-employee recommendations removed; recommendations are global per-parameter
      async fetchGlobalRecommendations(){
        try{
          const fetchList = async (base)=>{
            try{
              const res = await fetch(`${base}/api/rekomendasi_global/`, { headers:{'Accept':'application/json'} });
              if(!res.ok) return null;
              return await res.json();
            }catch(err){ return null; }
          };
          // Try current base first (supports manager, nurse, karyawan routes)
          let payload = await fetchList(API_BASE);
          // Fallback to manager API if nurse/karyawan route doesn't serve global recommendations
          if (!payload) {
            payload = await fetchList('/manager');
          }
          if (!payload) {
            console.warn('[GrafikManager] global rekomendasi fetch failed on all bases');
            this.globalRecByParam = {};
            this._globalRecLoaded = true; // Avoid repeated retries per fetch cycle
            return;
          }
          const items = Array.isArray(payload) ? payload : (Array.isArray(payload.items) ? payload.items : []);
          const map = {};
          for(const item of items){
            const p = String(item.parameter||''); if(!p) continue;
            const rec = { parameter:p, rekomendasi_text:item.rekomendasi_text||'', updated_at:item.updated_at||item.created_at||'' };
            if(!map[p]) map[p] = rec;
          }
          this.globalRecByParam = map;
          this._globalRecLoaded = true;
        }catch(e){ console.warn('[GrafikManager] fetchGlobalRecommendations error', e); this.globalRecByParam = {}; }
      },
      async fetchWellUnwellSummary(params){
        try{
          // Abort any previous well/unwell fetch to prevent overlapping updates
          try { if (this._wellAbortCtrl) this._wellAbortCtrl.abort(); } catch(e){}
          this._wellAbortCtrl = new AbortController();
          const res = await fetch(`${API_BASE}/grafik/well-unwell-summary/?${params.toString()}`,{ headers:{'Accept':'application/json'}, signal: this._wellAbortCtrl.signal });
          const data = await res.json();
        const months_len=(data.months||[]).length, well_len=(data.well_counts||[]).length, unwell_len=(data.unwell_counts||[]).length;
        console.log('[Diagnostic] grafik_manager init', { filters:this.filters, dataLength:{ well:well_len, unwell:unwell_len } });
        this.sendDiagnosticLog({ filters:{ month_from:this.filters.start_month, month_to:this.filters.end_month, uid:this.filters.karyawan_uid }, wellDataLength:well_len, unwellDataLength:unwell_len });
        if (well_len >= MAX_SAFE_POINTS || unwell_len >= MAX_SAFE_POINTS) {
          console.warn('[Diagnostic] Chart data very large for Well/Unwell, downscaling to last window', { well_len, unwell_len, window: SAFE_WINDOW_MONTHS });
        }
        this.prepareWellUnwellChart(data);
        // Store details for table and reset paginator
        this.wellUnwellDetails = Array.isArray(data.unwell_by_month) ? data.unwell_by_month : [];
        this.wellUnwellTablePage = 1;
        // Prefetch health metrics in the background so switching tabs is instant
        try {
          if (!this._healthRaw) {
            const p = new URLSearchParams();
            p.set('month_from', this.filters.start_month || '');
            p.set('month_to', this.filters.end_month || '');
            // Only prefetch health when a karyawan is selected (health depends on uid)
            if (this.filters.karyawan_uid) p.set('uid', this.filters.karyawan_uid);
            setTimeout(() => { this.fetchHealthMetrics(p).catch(()=>{}); }, 10);
          }
        } catch(e) { /* noop */ }
        }catch(e){
          if (e && e.name === 'AbortError') { console.warn('[GrafikManager] well/unwell fetch aborted'); return; }
          console.warn('[GrafikManager] well/unwell fetch failed', e);
        }
      },
      prepareHealthChart(data){
        // Guard: skip building when no data present
        if (!data || (!Array.isArray(data.x_dates) && !(data.series && Object.keys(data.series||{}).length))) {
          console.warn('[Diag] prepareHealthChart skipped — no data');
          return;
        }
        // Persist raw for type toggles
        this._healthRaw = data;
        // Also cache the last dataset for quick re-renders without refetching
        this.chartData = data;
        let xDates = Array.isArray(data.x_dates) ? data.x_dates.slice() : [];
        const raw = data.series || {};
        // Backend already returns series keyed by human-readable labels
        // Ensure null-safe arrays by reading using those labels directly
        const map = {
          'Gula Darah Puasa': Array.isArray(raw['Gula Darah Puasa']) ? raw['Gula Darah Puasa'] : [],
          'Gula Darah Sewaktu': Array.isArray(raw['Gula Darah Sewaktu']) ? raw['Gula Darah Sewaktu'] : [],
          'Tekanan Darah': Array.isArray(raw['Tekanan Darah']) ? raw['Tekanan Darah'] : [],
          'Cholesterol': Array.isArray(raw['Cholesterol']) ? raw['Cholesterol'] : [],
          'Asam Urat': Array.isArray(raw['Asam Urat']) ? raw['Asam Urat'] : [],
        };
        // Normalize length to match xDates to avoid mismatch freezes
        function normalizeLen(arr, len){
          const a = Array.isArray(arr) ? arr.slice() : [];
          if (a.length === len) return a;
          if (a.length > len) return a.slice(a.length - len);
          // pad with nulls to align
          return a.concat(Array(Math.max(0, len - a.length)).fill(null));
        }
        // Limit to a safe window (last N months) to avoid overload
        if (xDates.length > SAFE_WINDOW_MONTHS) {
          xDates = xDates.slice(xDates.length - SAFE_WINDOW_MONTHS);
        }
        // Build color mapping from METRIC_CONFIG to ensure specific colors per metric
        const METRIC_COLORS_MAP = Object.assign({}, ...this.metricsList.map((name)=>({ [name]: (METRIC_CONFIG[name] && METRIC_CONFIG[name].color) ? METRIC_CONFIG[name].color : '#0073fe' })));
        // Build entries from metricsList using the labeled keys present in raw; include all metrics like before, aligned to limited xDates
        const entries = this.metricsList.map(name => [name, normalizeLen((Array.isArray(raw[name]) ? raw[name] : (map[name]||[])), xDates.length)]);
        // Calculate total non-null points to decide rendering
        const totalPoints = entries.reduce((acc,[,_vals])=> acc + _vals.filter(v => v != null && typeof v === 'number' && !Number.isNaN(v)).length, 0);
        if (totalPoints === 0 || xDates.length === 0) {
          // Skip rendering if no actual data
          this.chartSeries = [];
          this.chartOptions = null;
          console.warn('[Diagnostic] grafik-manager | no health data to render charts', { xLen: xDates.length });
          this.sendDiagnosticLog({
            filters: { month_from: this.filters.start_month, month_to: this.filters.end_month, uid: this.filters.karyawan_uid },
            note: 'no-health-data-render-skip',
            xDatesLength: xDates.length,
            seriesKeys: Object.keys(raw || {}),
          });
          return;
        }
        // Build series/options for standard types only
        // Initialize chart series (all metrics) for ECharts wrapper
        this.chartSeries = entries.map(([name,values])=>({
          name,
          data: values,
          color: METRIC_COLORS_MAP[name] || '#0073fe',
          opacity: 1
        }));
        // ECharts-style options
        this.chartOptions = {
          chartType: this.chartType,
          tooltip: { trigger: 'axis' },
          legend: { top: 10 },
          grid: { left: 40, right: 20, bottom: 40, top: 40 },
          xAxis: { type: 'category', data: xDates },
          yAxis: { type: 'value', splitLine: { lineStyle: { color: '#e5e7eb' } } },
          color: entries.map(([name]) => METRIC_COLORS_MAP[name] || '#0073fe')
        };
        // Default active metric
        this.activeMetric = this.activeMetric || 'Gula Darah Puasa';
        console.log('[Diag] Health chart prepared', { series_count:this.chartSeries.length, months_count:xDates.length, activeMetric:this.activeMetric, points: totalPoints });
        try {
          const summary = this.metricsList.map(name => ({
            name,
            present: Array.isArray(map[name]) && map[name].filter(v=>v!=null).length > 0,
            thresholdApplied: !!METRIC_CONFIG[name],
            active: this.activeMetric === name
          }));
          console.table(summary);
        } catch(e) {}
        // Populate card values after chart series prepared
        this.updateHealthMetricsValues();
        this.updateMetricOpacity();
      },
      prepareWellUnwellChart(data){
        // Guard: skip building when no data present
        if (!data || (!Array.isArray(data.months) && !Array.isArray(data.unwell_counts))) {
          console.warn('[Diag] prepareWellUnwellChart skipped — no data');
          return;
        }
        // Core data: only Unwell counts per month
        const months = data.months || [];
        const unwellData = Array.isArray(data.unwell_counts) ? data.unwell_counts : [];
        // Persist raw for type toggles — only unwell
        this._wellRaw = { months, unwell: unwellData };
        // Cache the last dataset for quick re-renders without refetching
        this.chartData = { months, unwell_counts: unwellData };
        this.cachedUnwellData = { months, unwell_counts: unwellData };
        // Render only when months exist
        if ((months || []).length) {
          const strokeColor = '#ef4444';
          const gradientFrom = 0.3;
          const gradientTo = 0.0;
          let monthsShort = (months || []).map(fmtMonthShortFromISO);
          // Normalize series length to months and fill missing with 0 (ensure numeric)
          let seriesData = (function(arr, len){
            const a = Array.isArray(arr) ? arr.slice() : [];
            if (a.length < len) {
              // pad with zeros
              const pad = Array(len - a.length).fill(0);
              return a.concat(pad);
            }
            if (a.length > len) return a.slice(0, len);
            // convert values to numbers; replace invalid with 0
            return a.map(v => {
              const n = Number(v);
              return Number.isFinite(n) ? n : 0;
            });
          })(unwellData, monthsShort.length);
          // Limit to a safe window (last N months)
          if (monthsShort.length > SAFE_WINDOW_MONTHS) {
            const keep = SAFE_WINDOW_MONTHS;
            const start = monthsShort.length - keep;
            monthsShort = monthsShort.slice(start);
            seriesData = seriesData.slice(seriesData.length - keep);
          }
          // Total Unwell within current window
          try { this.totalUnwellWindow = (seriesData || []).reduce((acc, v) => acc + (typeof v === 'number' && !Number.isNaN(v) ? v : 0), 0); } catch(e) { this.totalUnwellWindow = 0; }
          // Y-axis scaling
          const values = seriesData.filter(v => typeof v === 'number' && !Number.isNaN(v));
          const maxVal = values.length ? Math.max(...values) : 0;
          const niceMax = (function(m){
            if (m <= 5) return 5;
            if (m <= 10) return 10;
            if (m <= 20) return 20;
            if (m <= 50) return 50;
            if (m <= 100) return 100;
            return Math.ceil(m / 50) * 50; // step by 50s beyond 100
          })(maxVal);
          const tickAmt = niceMax <= 10 ? niceMax : (niceMax <= 50 ? 10 : 10);
          // Precompute discrete markers for zero values to make them noticeable (grey dots)
          const zeroMarkers = (seriesData || []).map((v, i) => {
            return Number(v) === 0 ? { seriesIndex: 0, dataPointIndex: i, fillColor: '#9ca3af', strokeColor: '#6b7280', size: 6 } : null;
          }).filter(Boolean);

          // Chart rendering for ECharts
          this.wellUnwellSeries = [{ name: 'Unwell', data: seriesData, color: strokeColor }];
          this.wellUnwellOptions = {
            chartType: this.chartType,
            tooltip: { trigger: 'axis' },
            legend: { top: 10 },
            grid: { left: 40, right: 20, bottom: 40, top: 40 },
            xAxis: { type: 'category', data: monthsShort },
            yAxis: { type: 'value', min: 0, max: niceMax, splitNumber: tickAmt, splitLine: { lineStyle: { color: '#e5e7eb' } } },
            color: [strokeColor]
          };
          // Diagnostics
          console.log('[Diagnostic] grafik-manager | render Unwell', {
            filters: this.filters,
            unwellDataLength: unwellData.length,
            xDates: months,
            seriesKeys: ['unwell_counts'],
            chartType: this.chartType
          });
        } else {
          // No data → keep placeholder, do not render chart
          this.wellUnwellSeries = [];
          this.wellUnwellOptions = null;
          console.warn('[Diagnostic] grafik-manager | no data to render charts');
          // Also POST a diagnostic for backend visibility
          this.sendDiagnosticLog({
            filters: { month_from: this.filters.start_month, month_to: this.filters.end_month, uid: this.filters.karyawan_uid },
            unwellDataLength: 0,
            note: 'no-data-render-skip'
          });
        }
      },
      updateChartType(newType, oldType){
        // Simplified for ECharts: just switch reactive chartType; wrapper handles rendering
        this.chartType = newType;
        if (this.tab === 'well') {
          if (this.wellUnwellOptions) {
            this.wellUnwellOptions.chartType = newType;
            // Reassign to a new object to trigger shallow watchers immediately
            this.wellUnwellOptions = Object.assign({}, this.wellUnwellOptions);
          }
          // Rebuild well/unwell chart to apply type cleanly
          try {
            if (this._wellRaw) {
              this.prepareWellUnwellChart({ months: this._wellRaw.months, unwell_counts: this._wellRaw.unwell });
            }
          } catch(e) { console.warn('[Diag] updateChartType well rebuild failed', e); }
        } else {
          if (this.healthExceedOptions) {
            this.healthExceedOptions.chartType = newType;
            // Reassign to a new object to trigger shallow watchers immediately
            this.healthExceedOptions = Object.assign({}, this.healthExceedOptions);
          }
          // Rebuild health metrics series so threshold rendering matches the selected type
          try {
            if (this._healthRaw) {
              this.prepareHealthExceedChart(this._healthRaw);
            }
          } catch(e) { console.warn('[Diag] updateChartType health rebuild failed', e); }
        }
      },
      handleChartTypeUpdate(nextType){
        // Preserve current dataset (no refetch) but rebuild so thresholds follow bar/line rules
        this.chartType = nextType;
        try {
          if (this.tab === 'well') {
            if (this.wellUnwellOptions) this.wellUnwellOptions.chartType = nextType;
            if (this._wellRaw) this.prepareWellUnwellChart({ months: this._wellRaw.months, unwell_counts: this._wellRaw.unwell });
          } else {
            if (this.healthExceedOptions) this.healthExceedOptions.chartType = nextType;
            if (this._healthRaw) this.prepareHealthExceedChart(this._healthRaw);
          }
        } catch(e) { console.warn('[Diag] handleChartTypeUpdate rebuild failed', e); }
      },
      updateMetricOpacity(){
        console.log('[Diag] Active metric changed', this.activeMetric);
        // Only apply opacity/color changes when Health chart is active and series exist
        if(this.tab!=='health' || !Array.isArray(this.chartSeries)) return;
        const hexToRgba = (hex, a=1)=>{
          try{
            let h = (hex||'').replace('#','');
            if (h.length===3) h = h.split('').map(c=>c+c).join('');
            const r = parseInt(h.substring(0,2),16);
            const g = parseInt(h.substring(2,4),16);
            const b = parseInt(h.substring(4,6),16);
            return `rgba(${r}, ${g}, ${b}, ${a})`;
          }catch(e){ return hex; }
        };
        // Update series color alpha for non-active metrics; keep underlying data intact
        this.chartSeries = this.chartSeries.map(s => {
          const base = s.color || '#0073fe';
          const isDim = this.activeMetric && s.name !== this.activeMetric;
          const colorAdj = isDim ? hexToRgba(base, 0.3) : base;
          return { ...s, color: colorAdj, opacity: isDim ? 0.3 : 1 };
        });
        // Sync ECharts palette with adjusted colors
        if (this.chartOptions) {
          this.chartOptions.color = (this.chartSeries||[]).map(s => s.color || '#0073fe');
        }
      },
      // Expose month label formatter for template usage
      monthLabelFromISO(s){
        try { return fmtMonthFullFromISO(s); } catch(e) { return s; }
      },
      // Convert raw text to safe HTML with clickable links (http/https)
      linkifyText(raw){
        try{
          const text = String(raw||'');
          const escapeHtml = (str)=>str.replace(/[&<>"']/g, (ch)=>({
            '&':'&amp;', '<':'&lt;', '>':'&gt;', '"':'&quot;', "'":'&#39;'
          })[ch]);
          const urlRegex = /(https?:\/\/[^\s]+)/g;
          let result = '';
          let lastIndex = 0;
          for (const m of text.matchAll(urlRegex)){
            const idx = m.index || 0;
            const url = m[0];
            result += escapeHtml(text.slice(lastIndex, idx));
            const display = escapeHtml(url);
            result += `<a href="${url}" target="_blank" rel="noopener noreferrer" class="text-blue-600 hover:underline">${display}</a>`;
            lastIndex = idx + url.length;
          }
          result += escapeHtml(text.slice(lastIndex));
          return result;
        }catch(e){ return String(raw||''); }
      },
      // Units helper for consistent display across table and legend
      unitFor(name){
        try{
          const map = {
            'Gula Darah Puasa': 'mg/dL',
            'Gula Darah Sewaktu': 'mg/dL',
            'Tekanan Darah': 'mmHg',
            'Cholesterol': 'mg/dL',
            'Asam Urat': 'mg/dL'
          };
          return map[name] || '';
        }catch(e){ return ''; }
      },
      // Build legend list for thresholds tooltip
      thresholdLegendList(){
        try{
          return (this.metricsList||[]).map(name => {
            const cfg = METRIC_CONFIG[name] || {};
            const thr = typeof cfg.threshold==='number' ? cfg.threshold : null;
            return thr==null ? null : { name, threshold: thr, unit: this.unitFor(name), color: cfg.color || '#64748b' };
          }).filter(Boolean);
        }catch(e){ return []; }
      }
    },
    template:`
      <div id="grafik-manager" class="min-h-screen bg-gradient-to-br from-slate-50 via-blue-50 to-slate-100 p-4 md:p-8">
        <div class="max-w-7xl mx-auto">
          <!-- Header -->
          <div class="mb-8">
            <h1 class="text-slate-900 mb-2">Employee Health Dashboard</h1>
            <p class="text-slate-600">Monitor and track employee health metrics and wellness distribution over time</p>
          </div>

          <!-- Tabs List -->
          <div class="grid w-full max-w-md grid-cols-2 mb-6">
            <button :class="'flex items-center gap-2 px-3 py-2 rounded-md ' + (tab==='health' ? 'bg-white shadow-sm text-slate-900' : 'bg-slate-100 text-slate-600 hover:bg-slate-200')" @click="tab='health'; fetchData()">
              <i data-lucide="heart" class="w-4 h-4"></i>
              <span>Health Metrics</span>
            </button>
            <button v-if="showWellTab" :class="'flex items-center gap-2 px-3 py-2 rounded-md ' + (tab==='well' ? 'bg-white shadow-sm text-slate-900' : 'bg-slate-100 text-slate-600 hover:bg-slate-200')" @click="tab='well'; chartType='bar'; fetchData()">
              <i data-lucide="users" class="w-4 h-4"></i>
              <span>Grafik Unwell</span>
            </button>
          </div>

          <!-- Filters -->
          <div class="bg-white border rounded-lg p-4 flex flex-wrap gap-4" v-show="showSelectors">
            <!-- Health tab filters -->
            <template v-if="tab==='health'">
              <div>
                <label class="text-sm font-medium block">Parameter</label>
                <select v-model="filters.parameter" class="border rounded px-2 py-1 min-w-[220px]">
                  <option value="Semua">Semua</option>
                  <option v-for="m in metricsList" :key="m" :value="m">{{ m }}</option>
                </select>
              </div>
              <div><label class="text-sm font-medium block">Start Month</label><input type="month" v-model="filters.start_month" class="border rounded px-2 py-1" /></div>
              <div><label class="text-sm font-medium block">End Month</label><input type="month" v-model="filters.end_month" class="border rounded px-2 py-1" /></div>
              <!-- Lokasi filter removed -->
              <div><label class="text-sm font-medium block">Karyawan</label>
                <template v-if="!hideKaryawanSelect">
                  <select v-model="filters.karyawan_uid" class="border rounded px-2 py-1 min-w-[220px]">
                    <option v-for="p in karyawanList" :key="p.uid" :value="p.uid">{{ p.nama }}</option>
                  </select>
                </template>
              </div>
              <button @click="fetchData" class="bg-black hover:bg-black/90 text-white px-2 py-1 rounded w-auto text-sm">Terapkan</button>
            </template>
            <template v-else>
              <div>
                <label class="text-sm font-medium block">Parameter</label>
                <select v-model="filters.parameter" class="border rounded px-2 py-1 min-w-[220px]">
                  <option value="Semua">Semua</option>
                  <option v-for="m in metricsList" :key="m" :value="m">{{ m }}</option>
                </select>
              </div>
              <div><label class="text-sm font-medium block">Start Month</label><input type="month" v-model="filters.start_month" class="border rounded px-2 py-1" /></div>
              <div><label class="text-sm font-medium block">End Month</label><input type="month" v-model="filters.end_month" class="border rounded px-2 py-1" /></div>
              <!-- Lokasi filter removed -->
              <button @click="fetchData" class="bg-black hover:bg-black/90 text-white px-2 py-1 rounded w-auto text-sm">Terapkan</button>
            </template>
          </div>

          <!-- Metric cards removed per overhaul -->

          <!-- Chart -->
          <div class="border rounded-lg p-4 bg-slate-50/50 min-h-[520px]">
            <!-- Chart type toggle positioned at the top-right of the graph area -->
            <div class="flex items-start justify-between mb-3">
              <!-- Left column: blocks -->
              <div class="flex flex-col gap-2">
                <!-- Unwell total pill -->
                <div class="inline-flex items-center gap-2 bg-white border rounded-md px-3 py-1 text-sm text-slate-700 shadow-sm">
                  <i data-lucide="alert-triangle" class="w-4 h-4 text-red-600"></i>
                  <span>Total Unwell:</span>
                  <span class="font-semibold text-red-700">{{ totalUnwellWindow }}</span>
                </div>
                <!-- Selected karyawan block (Health tab only) -->
                <div v-if="tab==='health' && selectedEmployee" class="inline-flex items-center gap-3 bg-gradient-to-r from-blue-50 via-indigo-50 to-purple-50 border border-indigo-200 rounded-md px-3 py-2 shadow-sm">
                  <div class="flex items-center gap-2">
                    <i data-lucide="user" class="w-5 h-5 text-indigo-600"></i>
                    <span class="text-base font-semibold text-slate-900">{{ selectedEmployee.nama }}</span>
                  </div>
                  <div v-if="selectedEmployee.lokasi" class="flex items-center gap-1 text-sm text-slate-700">
                    <i data-lucide="map-pin" class="w-4 h-4 text-indigo-500"></i>
                    <span class="font-medium">{{ selectedEmployee.lokasi }}</span>
                  </div>
                </div>
              </div>
              <!-- Right: Chart type toggle -->
              <chart-type-toggle :type="chartType" @update="handleChartTypeUpdate($event)" />
            </div>
            <!-- Render only when data is ready to avoid heavy initial chart render on empty config -->
            <div v-if="tab==='health'" id="health-chart" class="w-full">
              <template v-if="healthHasData">
                <e-chart-wrapper
                  ref="healthChart"
                  :key="'health-chart'"
                  v-if="healthExceedOptions && healthExceedSeries && healthExceedSeries.length && healthExceedOptions.xAxis && healthExceedOptions.xAxis.data && healthExceedOptions.xAxis.data.length"
                  :options="healthExceedOptions"
                  :series="healthExceedSeries"
                  :height="500"
                />
              </template>
              <div v-else class="flex items-center justify-center h-[480px]">
                <div class="text-center text-slate-600">
                  <div class="text-lg font-semibold mb-1">Belum ada data</div>
                </div>
              </div>
            </div>
            <div v-else-if="showWellTab && tab==='well'" id="well-chart" class="w-full">
              <e-chart-wrapper
                ref="wellChart"
                :key="'well-chart'"
                v-if="wellUnwellOptions && wellUnwellSeries && wellUnwellSeries.length && wellUnwellOptions.xAxis && wellUnwellOptions.xAxis.data && wellUnwellOptions.xAxis.data.length"
                :options="wellUnwellOptions"
                :series="wellUnwellSeries"
                :height="500"
              />
            </div>
            <div v-else class="flex items-center justify-center h-[480px]">
              <div class="text-center text-slate-600">
                <div class="text-lg font-semibold mb-1">Tidak ada data untuk filter ini</div>
                <div class="text-sm">Jika Anda sudah memilih karyawan, sistem akan menampilkan seluruh riwayat secara otomatis.</div>
              </div>
            </div>
          </div>

          <!-- Recommendation snippet container: fancy section between graph and data table -->
          <div v-if="tab==='health' && currentExceedRecommendations.length" class="mt-4 bg-white border rounded-xl shadow-sm">
            <!-- Header -->
            <div class="px-4 pt-4">
              <div class="flex items-center gap-2">
                <i data-lucide="sparkles" class="w-4 h-4 text-amber-600"></i>
                <h3 class="text-slate-900 font-semibold">Rekomendasi Kesehatan</h3>
                <span class="ml-2 inline-flex items-center rounded-full bg-amber-100 text-amber-900 px-2 py-0.5 text-xs font-semibold border border-amber-200">{{ monthLabelFromISO(latestExceedMonthISO) }}</span>
              </div>
              <div class="mt-1 text-xs text-slate-500">Sumber: rekomendasi global per parameter</div>
              <div class="mt-2 h-px bg-gradient-to-r from-amber-200 via-amber-300 to-transparent"></div>
            </div>
            <!-- Body: stylized recommendation cards -->
            <div class="px-4 pb-4 mt-3">
              <div class="grid grid-cols-1 md:grid-cols-2 gap-3">
                <div
                  v-for="r in currentExceedRecommendations"
                  :key="r.parameter"
                  class="group relative rounded-lg border border-amber-200 bg-amber-50/60 hover:bg-amber-50 shadow-sm hover:shadow-md transition-shadow"
                >
                  <div class="flex items-start gap-3 px-3 py-2">
                    <div class="mt-0.5">
                      <i data-lucide="lightbulb" class="w-4 h-4 text-amber-600"></i>
                    </div>
                    <div class="flex-1">
                      <div class="flex items-center gap-2 mb-1">
                        <span class="inline-flex items-center gap-1 rounded-full bg-amber-100 text-amber-900 px-2 py-0.5 text-xs font-semibold border border-amber-200">{{ r.parameter }}</span>
                      </div>
                      <div class="text-sm leading-snug text-amber-900">
                        <span v-html="linkifyText(r.text)"></span>
                      </div>
                    </div>
                  </div>
                  <div class="absolute right-2 top-2 opacity-0 group-hover:opacity-100 transition-opacity">
                    <i data-lucide="external-link" class="w-3.5 h-3.5 text-amber-500"></i>
                  </div>
                </div>
              </div>
            </div>
          </div>
          <!-- Fallback: show global recommendations list when no exceed recommendations (public QR view) -->
          <div v-else-if="tab==='health' && globalRecommendationList.length" class="mt-4 bg-white border rounded-xl shadow-sm">
            <div class="px-4 pt-4">
              <div class="flex items-center gap-2">
                <i data-lucide="sparkles" class="w-4 h-4 text-amber-600"></i>
                <h3 class="text-slate-900 font-semibold">Rekomendasi Kesehatan (Global)</h3>
              </div>
              <div class="mt-1 text-xs text-slate-500">Ditampilkan untuk edukasi umum. Sumber: rekomendasi global per parameter.</div>
              <div class="mt-2 h-px bg-gradient-to-r from-amber-200 via-amber-300 to-transparent"></div>
            </div>
            <div class="px-4 pb-4 mt-3">
              <div class="grid grid-cols-1 md:grid-cols-2 gap-3">
                <div
                  v-for="g in globalRecommendationList"
                  :key="g.parameter"
                  class="group relative rounded-lg border border-amber-200 bg-amber-50/60 hover:bg-amber-50 shadow-sm hover:shadow-md transition-shadow"
                >
                  <div class="flex items-start gap-3 px-3 py-2">
                    <div class="mt-0.5">
                      <i data-lucide="lightbulb" class="w-4 h-4 text-amber-600"></i>
                    </div>
                    <div class="flex-1">
                      <div class="flex items-center gap-2 mb-1">
                        <span class="inline-flex items-center gap-1 rounded-full bg-amber-100 text-amber-900 px-2 py-0.5 text-xs font-semibold border border-amber-200">{{ g.parameter }}</span>
                      </div>
                      <div class="text-sm leading-snug text-amber-900">
                        <span v-html="linkifyText(g.text)"></span>
                      </div>
                    </div>
                  </div>
                  <div class="absolute right-2 top-2 opacity-0 group-hover:opacity-100 transition-opacity">
                    <i data-lucide="external-link" class="w-3.5 h-3.5 text-amber-500"></i>
                  </div>
                </div>
              </div>
            </div>
          </div>

          <!-- Health Details Table (Semua Data Medis per Bulan) -->
          <div v-if="tab==='health'" class="mt-4 bg-white border rounded-lg p-4">
            <div class="flex items-center justify-between mb-2">
              <h3 class="text-slate-900 font-semibold">Data Medis per Bulan</h3>
              <!-- Threshold legend tooltip -->
              <div class="group relative">
                <button class="inline-flex items-center gap-1 text-slate-600 hover:text-slate-900">
                  <i data-lucide="info" class="w-4 h-4"></i>
                  <span class="text-sm">Thresholds</span>
                </button>
                <div class="absolute right-0 mt-2 z-10 hidden group-hover:block bg-white border rounded-md shadow-lg p-3 w-[380px]">
                  <div class="text-xs text-slate-500 mb-2">Nilai ambang batas (legend)</div>
                  <div class="flex flex-wrap gap-2">
                    <span v-for="t in thresholdLegendList()" :key="t.name" class="inline-flex items-center gap-1 rounded-full border px-2 py-0.5" :style="{ borderColor: t.color, backgroundColor: '#f8fafc', color: '#334155' }">
                      <i data-lucide="info" class="w-3 h-3" :style="{ color: t.color }"></i>
                      <span class="font-medium">{{ t.name }}</span>
                      <span class="text-xs">≥ {{ t.threshold }} {{ t.unit }}</span>
                    </span>
                  </div>
                </div>
              </div>
            </div>
            <table class="w-full text-sm">
              <thead>
                <tr class="border-b">
                  <th class="text-left py-2 px-2 w-32">Bulan</th>
                  <th class="text-left py-2 px-2">Data Medis</th>
                </tr>
              </thead>
              <tbody>
                <tr v-for="row in healthTableRows" :key="row.month" class="border-b align-top">
                  <td class="py-2 px-2 text-slate-800">{{ monthLabelFromISO(row.month) }}</td>
                  <td class="py-2 px-2">
                    <span v-if="!row.parameters || !row.parameters.length" class="text-slate-500">-</span>
                    <div v-else class="grid grid-cols-1 md:grid-cols-2 gap-2">
                      <div
                        v-for="p in row.parameters"
                        :key="p.name + '-' + row.month"
                        :class="p.isExceed ? 'flex items-center justify-between rounded-md bg-red-50 text-red-700 border border-red-200 px-2 py-1' : 'flex items-center justify-between rounded-md bg-green-50 text-green-700 border border-green-200 px-2 py-1'"
                      >
                        <div class="flex items-center gap-1">
                          <i :data-lucide="p.isExceed ? 'alert-triangle' : 'check-circle'" class="w-3 h-3"></i>
                          <span class="font-medium">{{ p.name }}</span>
                        </div>
                        <div class="text-xs">{{ p.value }} {{ p.unit }}</div>
                      </div>
                    </div>
                  </td>
                </tr>
              </tbody>
            </table>
          </div>

          <!-- Unwell Details Table (Bulan vs Karyawan Unwell) -->
          <div v-if="showWellTab && tab==='well'" class="mt-4 bg-white border rounded-lg p-4">
            <div class="flex items-center justify-between mb-2">
              <h3 class="text-slate-900 font-semibold">Daftar Karyawan Unwell per Bulan</h3>
              <!-- Paginator Removed -->
            </div>
            <table class="w-full text-sm">
              <thead>
                <tr class="border-b">
                  <th class="text-left py-2 px-2 w-32">Bulan</th>
                  <th class="text-left py-2 px-2">Karyawan Unwell</th>
                </tr>
              </thead>
              <tbody>
                <tr v-for="row in wellTableRows" :key="row.month" class="border-b align-top">
                  <td class="py-2 px-2 text-slate-800">{{ monthLabelFromISO(row.month) }}</td>
                  <td class="py-2 px-2">
                    <span v-if="!row.employees || !row.employees.length" class="text-slate-500">-</span>
                    <span v-else class="flex flex-wrap gap-x-2 gap-y-1">
                      <a v-for="emp in row.employees" :key="emp.uid" :href="'/manager/employee/' + emp.uid + '/?submenu=data_karyawan&subtab=profile'" class="text-blue-600 hover:underline">{{ emp.nama || emp.uid }}</a>
                    </span>
                  </td>
                </tr>
              </tbody>
            </table>
            <!-- Paginator message removed -->
          </div>
        </div>
      </div>
    `
  };

  window.Components.GrafikManager = GrafikManager;
})();
