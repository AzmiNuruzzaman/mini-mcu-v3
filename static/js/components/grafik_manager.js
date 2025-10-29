// static/js/components/grafik_manager.js
(function(){
  window.Components = window.Components || {};
  const { reactive, ref, watch, computed } = Vue;
  const MAX_SAFE_POINTS = 5000;
  // Determine API base prefix based on current route (supports manager and nurse)
  const API_BASE = (function(){
    try {
      const p = window.location && window.location.pathname ? window.location.pathname : '';
      return (p.startsWith('/nurse') ? '/nurse' : '/manager');
    } catch(e) { return '/manager'; }
  })();

  // Month formatting helper
  function fmtMonthISO(d){
    const y = d.getFullYear();
    const m = String(d.getMonth()+1).padStart(2,'0');
    return `${y}-${m}`;
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

  // ApexCharts wrapper
  const ApexChart = {
    name:'ApexChart',
    props:{ options:Object, series:Array, height:[String,Number] },
    template:`<div ref="el" style="width:100%"></div>`,
    mounted(){
      if(typeof ApexCharts==='undefined'){ console.warn('[ApexChart] ApexCharts not found'); return; }
      try {
        const opts = Object.assign({}, this.options || {}, {
          series: this.series || [],
          chart: Object.assign({}, (this.options||{}).chart || {}, { height: this.height })
        });
        this._chart = new ApexCharts(this.$refs.el, opts);
        // initialize update queue to serialize ApexCharts updates
        this._updateQueue = Promise.resolve();
        // Defer initial render to allow UI to paint and avoid blocking
        try { setTimeout(() => { try { this._chart.render(); } catch(err){ console.error('[Diagnostic] Chart render error', err); try { fetch(`${API_BASE}/grafik/diagnostic-log/`, { method:'POST', headers:{'Content-Type':'application/json'}, body: JSON.stringify({ error: (err && err.message) || String(err), stage:'deferred-render' }) }); } catch(e){} } }, 0); }
        catch(err){
          console.error('[Diagnostic] Chart render error', err);
          try { fetch(`${API_BASE}/grafik/diagnostic-log/`, { method:'POST', headers:{'Content-Type':'application/json'}, body: JSON.stringify({ error: (err && err.message) || String(err) }) }); } catch(e){}
        }
      } catch(e) {
        console.warn('[ApexChart] render failed', e);
      }
    },
    methods:{
      // enqueue updates to avoid concurrent updateOptions/updateSeries calls inside ApexCharts
      enqueueUpdate(fn){
        this._updateQueue = (this._updateQueue || Promise.resolve()).then(() => new Promise((resolve) => {
          Vue.nextTick(async () => { try { const r = fn && fn(); if (r && typeof r.then==='function') { await r; } } finally { resolve(); } });
        }));
      },
      setType(type){
        try{
          if (!this._chart) return;
          const baseChart = Object.assign({}, (this.options||{}).chart || {}, { type });
          // serialize type change to prevent overlapping with series/options updates
          this.enqueueUpdate(() => this._chart.updateOptions({ chart: baseChart, animations: { enabled:false } }, false, true));
        }catch(e){ console.warn('[ApexChart] setType failed', e); }
      }
    },
    watch:{
      // Throttle deep updates to avoid overlapping re-renders
      options:{
        deep:true,
        handler(newVal){
          if (!this._chart) return;
          if (this._optsUpdatePending) return;
          this._optsUpdatePending = true;
          Vue.nextTick(()=>{
            try {
              // IMPORTANT: do not include series in updateOptions to avoid race with updateSeries
              const merged = Object.assign({}, newVal || {});
              this.enqueueUpdate(() => this._chart.updateOptions(merged, false, true));
            } catch(e) { console.warn('[ApexChart] updateOptions failed', e); }
            finally { this._optsUpdatePending = false; }
          });
        }
      },
      series:{
        deep:true,
        handler(newSeries){
          if (!this._chart) return;
          if (this._seriesUpdatePending) return;
          this._seriesUpdatePending = true;
          Vue.nextTick(()=>{
            try { this.enqueueUpdate(() => this._chart.updateSeries(newSeries || [], true)); }
            catch(e) { console.warn('[ApexChart] updateSeries failed', e); }
            finally { this._seriesUpdatePending = false; }
          });
        }
      },
      height(val){
        if (!this._chart) return;
        Vue.nextTick(()=>{
          try {
            this.enqueueUpdate(() => this._chart.updateOptions({ chart: Object.assign({}, (this.options||{}).chart || {}, { height: val }) }, false, true));
          } catch(e) { console.warn('[ApexChart] update height failed', e); }
        });
      }
    },
    unmounted(){ this._chart?.destroy(); this._chart=null; }
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
    components:{ ApexChart, ChartTypeToggle },
    data(){
      return {
        tab:'health', // 'health' | 'well'
        filters:{ start_month:'', end_month:'', lokasi:'', karyawan_uid:'' },
        // Allow pages to hide filters area (e.g., nurse profile context)
        showSelectors: true,
        chartType:'bar',
        activeMetric:null,
        metricsList:['Gula Darah Puasa','Gula Darah Sewaktu','Tekanan Darah','Cholesterol','Asam Urat'],
        // Card model for Health Metrics (rendered above the chart)
        healthMetrics:[],
        lokasiList:[],
        karyawanList:[],
        // Initialize charts as null to avoid rendering ApexCharts with empty config
        chartSeries:[],
        chartOptions:null,
        wellUnwellSeries:[],
        wellUnwellOptions:null
      };
    },
    async mounted(){
      try {
        // Read optional dataset flags from the mount element
        const rootEl = document.getElementById('grafik-manager');
        if (rootEl && rootEl.dataset) {
          const preUid = rootEl.dataset.preselectUid || '';
          const hideSel = rootEl.dataset.hideSelectors === 'true';
          if (preUid) { this.filters.karyawan_uid = String(preUid); }
          if (hideSel) { this.showSelectors = false; }
        }
        this.applyDefaultFilters();
        // Seed healthMetrics card model from metricsList
        this.buildHealthMetricsModel();
        // Fetch sequentially to avoid overlapping work on initial render
        await this.fetchLokasiList();
        await this.fetchKaryawanList();
        await this.fetchData();
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
      // Diagnostics: check ApexCharts DOM after initial render
      setTimeout(()=>{
        try{
          const el = document.querySelector('#grafik-manager .apexcharts-canvas');
          console.log('[Diag] ApexCharts canvas present?', !!el, el);
        }catch(e){ console.warn('[Diag] ApexCharts DOM check failed', e); }
      }, 800);
    },
    watch:{
      chartType(){ this.updateChartType(); },
      activeMetric(){ this.updateMetricOpacity(); }
    },
    methods:{
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
        this.filters.lokasi='';
      },
      async fetchLokasiList(){
        try{
          const res = await fetch(`${API_BASE}/grafik/lokasi-list/`,{ headers:{'Accept':'application/json'}});
          const json = await res.json();
          this.lokasiList = Array.isArray(json)? json: (json.lokasi||[]);
        }catch(e){ this.lokasiList = []; }
      },
      async fetchKaryawanList(){
        try{
          const res = await fetch(`${API_BASE}/grafik/karyawan-list/`,{ headers:{'Accept':'application/json'} });
          const json = await res.json();
          const arr = Array.isArray(json) ? json : (json.karyawan||[]);
          // Normalize shape to {uid,nama}
          this.karyawanList = arr.map(x=>({ uid: String(x.uid||''), nama: x.nama||String(x.name||'') })).filter(x=>x.uid && x.nama);
        }catch(e){ this.karyawanList = []; }
      },
      async fetchData(){
        const params = new URLSearchParams({
          month_from:this.filters.start_month||'',
          month_to:this.filters.end_month||'',
          lokasi:this.filters.lokasi||'',
          uid:this.filters.karyawan_uid||''
        });
        try{
          if(this.tab==='health'){ await this.fetchHealthMetrics(params); }
          else{ await this.fetchWellUnwellSummary(params); }
        }catch(e){ console.warn('[GrafikManager] fetch failed',e); }
      },
      async fetchHealthMetrics(params){
        try{
          const res = await fetch(`${API_BASE}/grafik/health-metrics-summary/?${params.toString()}`,{ headers:{'Accept':'application/json'}});
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
          this.sendDiagnosticLog({ filters:{ month_from:this.filters.start_month, month_to:this.filters.end_month, lokasi:this.filters.lokasi, uid:this.filters.karyawan_uid }, xDatesLength:xLen, seriesKeys:keys, nullCount:nulls, nonNumericCount:nonNums });
          // Render gating to avoid freeze on very large datasets
          const maxSeriesLen = keys.reduce((mx,k)=>{ const arr = (data.series||{})[k]||[]; return Math.max(mx, Array.isArray(arr)?arr.length:0); }, 0);
          if (xLen < MAX_SAFE_POINTS && maxSeriesLen < MAX_SAFE_POINTS) {
            this.prepareHealthChart(data);
          } else {
            console.warn('[Diagnostic] Chart data too large for Health Metrics, skipping render', { xLen, maxSeriesLen });
            // Keep placeholder visible; do not render chart options
            this.chartOptions = null;
            this.chartSeries = [];
          }
        }catch(e){ console.warn('[GrafikManager] health metrics unavailable',e); }
      },
      async fetchWellUnwellSummary(params){
        const res = await fetch(`${API_BASE}/grafik/well-unwell-summary/?${params.toString()}`,{ headers:{'Accept':'application/json'}});
        const data = await res.json();
        const months_len=(data.months||[]).length, well_len=(data.well_counts||[]).length, unwell_len=(data.unwell_counts||[]).length;
        console.log('[Diagnostic] grafik_manager init', { filters:this.filters, dataLength:{ well:well_len, unwell:unwell_len } });
        this.sendDiagnosticLog({ filters:{ month_from:this.filters.start_month, month_to:this.filters.end_month, lokasi:this.filters.lokasi, uid:this.filters.karyawan_uid }, wellDataLength:well_len, unwellDataLength:unwell_len });
        if (well_len < MAX_SAFE_POINTS && unwell_len < MAX_SAFE_POINTS) {
          this.prepareWellUnwellChart(data);
        } else {
          console.warn('[Diagnostic] Chart data too large for Well/Unwell, skipping render', { well_len, unwell_len });
          this.wellUnwellOptions = null;
          this.wellUnwellSeries = [];
        }
      },
      prepareHealthChart(data){
        const xDates = Array.isArray(data.x_dates) ? data.x_dates : [];
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
        // Build color mapping from METRIC_CONFIG to ensure specific colors per metric
        const METRIC_COLORS_MAP = Object.assign({}, ...this.metricsList.map((name)=>({ [name]: (METRIC_CONFIG[name] && METRIC_CONFIG[name].color) ? METRIC_CONFIG[name].color : '#0073fe' })));
        // Build entries from metricsList using the labeled keys present in raw; include all metrics like before
        const entries = this.metricsList.map(name => [name, normalizeLen((Array.isArray(raw[name]) ? raw[name] : (map[name]||[])), xDates.length)]);
        // Calculate total non-null points to decide rendering
        const totalPoints = entries.reduce((acc,[,_vals])=> acc + _vals.filter(v => v != null && typeof v === 'number' && !Number.isNaN(v)).length, 0);
        if (totalPoints === 0 || xDates.length === 0) {
          // Skip rendering if no actual data
          this.chartSeries = [];
          this.chartOptions = null;
          console.warn('[Diagnostic] grafik-manager | no health data to render charts', { xLen: xDates.length });
          this.sendDiagnosticLog({
            filters: { month_from: this.filters.start_month, month_to: this.filters.end_month, lokasi: this.filters.lokasi, uid: this.filters.karyawan_uid },
            note: 'no-health-data-render-skip',
            xDatesLength: xDates.length,
            seriesKeys: Object.keys(raw || {}),
          });
          return;
        }
        // Initialize chart series (all metrics) and options
        this.chartSeries = entries.map(([name,values],idx)=>({
          name,
          data: values,
          color: METRIC_COLORS_MAP[name] || '#0073fe',
          opacity: 1
        }));
        this.chartOptions={
          chart:{ type:this.chartType, toolbar:{show:false} },
          xaxis:{ categories:xDates },
          stroke:{ width:2, curve:'smooth' },
          colors:entries.map(([name])=> METRIC_COLORS_MAP[name] || '#0073fe'),
          legend:{ position:'top' },
          grid:{ borderColor:'#e5e7eb' },
          tooltip:{ theme:'light' },
          // Reduce animation overhead for smoother initial render
          animations: { enabled: false },
          annotations:{
            yaxis:[{
              y:METRIC_CONFIG['Gula Darah Puasa'].threshold,
              borderColor:METRIC_CONFIG['Gula Darah Puasa'].color,
              strokeDashArray:5,
              label:{ text:METRIC_CONFIG['Gula Darah Puasa'].label, style:{ color:'#fff', background:METRIC_CONFIG['Gula Darah Puasa'].color } }
            }]
          }
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
        const months = data.months || [];
        // Null-safe defaults for well/unwell
        const wellDataSafe = Array.isArray(data.well_counts) ? data.well_counts : [];
        const unwellDataSafe = Array.isArray(data.unwell_counts) ? data.unwell_counts : [];
        // Conditional render: only render if there is data
        if (wellDataSafe.length || unwellDataSafe.length) {
          this.wellUnwellSeries = [
            { name: 'Well', data: wellDataSafe },
            { name: 'Unwell', data: unwellDataSafe }
          ];
          this.wellUnwellOptions = {
            chart: { type: 'bar', stacked: false, toolbar: { show: false } },
            xaxis: { categories: months },
            colors: ['#22c55e', '#ef4444'],
            legend: { position: 'top' },
            grid: { borderColor: '#e5e7eb' },
            tooltip: { theme: 'light' },
            animations: { enabled: false }
          };
          // Optional debug log
          console.log('[Diagnostic] grafik-manager | render Well/Unwell', {
            filters: this.filters,
            wellDataLength: wellDataSafe.length,
            unwellDataLength: unwellDataSafe.length,
            xDates: months,
            seriesKeys: ['well_counts','unwell_counts']
          });
        } else {
          // No data → keep placeholder, do not render chart
          this.wellUnwellSeries = [];
          this.wellUnwellOptions = null;
          console.warn('[Diagnostic] grafik-manager | no data to render charts');
          // Also POST a diagnostic for backend visibility
          this.sendDiagnosticLog({
            filters: { month_from: this.filters.start_month, month_to: this.filters.end_month, lokasi: this.filters.lokasi, uid: this.filters.karyawan_uid },
            wellDataLength: 0,
            unwellDataLength: 0,
            note: 'no-data-render-skip'
          });
        }
      },
      updateChartType(){
        console.log('[Diag] Chart type changed', this.chartType, 'tab:', this.tab);
        setTimeout(()=>{ try{ console.log('[Diag] (deferred) Chart type change scheduled', { type:this.chartType, tab:this.tab }); }catch(e){} }, 0);
        const applyStyleTweaks = (opts)=>{
          if (!opts) return;
          // Common safety tweaks
          opts.animations = { enabled: false };
          opts.dataLabels = { enabled: false };
          // Adjust stroke/markers/fill for line/area
          if (this.chartType === 'line' || this.chartType === 'area') {
            opts.stroke = Object.assign({}, opts.stroke || {}, { width: 2, curve: 'straight' });
            opts.markers = Object.assign({}, opts.markers || {}, { size: 0 });
            if (this.chartType === 'area') {
              opts.fill = Object.assign({}, opts.fill || {}, { type: 'solid', opacity: 0.25 });
            }
          }
          if (this.chartType === 'bar') {
            // Minimal bar options
            opts.plotOptions = Object.assign({}, opts.plotOptions || {}, { bar: Object.assign({}, (opts.plotOptions||{}).bar || {}, { columnWidth: '60%' }) });
          }
        };
        if(this.tab==='health') {
          if (this.chartOptions) {
            this.chartOptions.chart = Object.assign({}, this.chartOptions.chart || {}, { type: this.chartType });
            applyStyleTweaks(this.chartOptions);
          }
          // Use component ref for minimal update to avoid deep reactive overhead
          const refComp = this.$refs.healthChart;
          if (refComp && typeof refComp.setType === 'function') {
            try { setTimeout(()=>{ refComp.setType(this.chartType); console.log('[Diag] setType applied via ref for health'); }, 0); } catch(e){}
          }
        } else {
          if (this.wellUnwellOptions) {
            this.wellUnwellOptions.chart = Object.assign({}, this.wellUnwellOptions.chart || {}, { type: this.chartType });
            applyStyleTweaks(this.wellUnwellOptions);
          }
          const refComp = this.$refs.wellChart;
          if (refComp && typeof refComp.setType === 'function') {
            try { setTimeout(()=>{ refComp.setType(this.chartType); console.log('[Diag] setType applied via ref for well'); }, 0); } catch(e){}
          }
        }
      },
      updateMetricOpacity(){
        console.log('[Diag] Active metric changed', this.activeMetric);
        if(!this.chartSeries) return;
        // Update per-series opacity flag
        this.chartSeries=this.chartSeries.map(s=>({ ...s, opacity:this.activeMetric && s.name!==this.activeMetric?0.3:1 }));
        // Also reflect translucent vs solid visually via fill.opacity array and color alpha
        const opacities = this.chartSeries.map(s => (this.activeMetric && s.name!==this.activeMetric) ? 0.3 : 1);
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
        if (this.chartOptions){
          // Apply fill opacity per series (affects area/bar)
          const fill = Object.assign({}, this.chartOptions.fill || {}, { opacity: opacities });
          this.chartOptions.fill = fill;
          // Adjust colors with alpha for non-active series (affects line stroke and bar/area fill)
          const colorsAdj = (this.chartSeries||[]).map((s)=>{
            const base = s.color || '#0073fe';
            const op = (this.activeMetric && s.name!==this.activeMetric) ? 0.3 : 1;
            return op===1 ? base : hexToRgba(base, op);
          });
          this.chartOptions.colors = colorsAdj;
        }
        if(this.chartOptions && this.chartOptions.annotations && this.activeMetric && METRIC_CONFIG[this.activeMetric]){
          this.chartOptions.annotations.yaxis=[{
            y:METRIC_CONFIG[this.activeMetric].threshold,
            borderColor:METRIC_CONFIG[this.activeMetric].color,
            strokeDashArray:5,
            label:{ text:METRIC_CONFIG[this.activeMetric].label, style:{ color:'#fff', background:METRIC_CONFIG[this.activeMetric].color } }
          }];
        } else if (this.chartOptions && this.chartOptions.annotations) { this.chartOptions.annotations.yaxis=[]; }
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
            <button :class="'flex items-center gap-2 px-3 py-2 rounded-md ' + (tab==='well' ? 'bg-white shadow-sm text-slate-900' : 'bg-slate-100 text-slate-600 hover:bg-slate-200')" @click="tab='well'; fetchData()">
              <i data-lucide="users" class="w-4 h-4"></i>
              <span>Well & Unwell</span>
            </button>
          </div>

          <!-- Filters -->
          <div class="bg-white border rounded-lg p-4 flex flex-wrap gap-4" v-show="showSelectors">
            <div><label class="text-sm font-medium block">Start Month</label><input type="month" v-model="filters.start_month" class="border rounded px-2 py-1" /></div>
            <div><label class="text-sm font-medium block">End Month</label><input type="month" v-model="filters.end_month" class="border rounded px-2 py-1" /></div>
            <div><label class="text-sm font-medium block">Lokasi</label>
              <select v-model="filters.lokasi" class="border rounded px-2 py-1">
                <option value="">Semua Lokasi</option>
                <option v-for="lok in lokasiList" :key="lok" :value="lok">{{ lok }}</option>
              </select>
            </div>
            <div><label class="text-sm font-medium block">Karyawan</label>
              <select v-model="filters.karyawan_uid" class="border rounded px-2 py-1 min-w-[220px]">
                <option value="">Semua Karyawan</option>
                <option v-for="p in karyawanList" :key="p.uid" :value="p.uid">{{ p.nama }}</option>
              </select>
            </div>
            <button @click="fetchData" class="bg-black hover:bg-black/90 text-white px-2 py-1 rounded w-auto text-sm">Terapkan</button>
          </div>

          <!-- Compact metric cards in a single horizontal row (scrollable if needed) -->
          <div v-if="tab==='health'" class="my-2">
            <div class="grid grid-cols-2 sm:grid-cols-3 md:grid-cols-4 lg:grid-cols-5 gap-2">
              <div v-for="metric in healthMetrics" :key="metric.title"
                   class="bg-white rounded-2xl shadow p-3 flex flex-col cursor-pointer w-44 h-36 transition-colors"
                   :class="activeMetric===metric.title ? 'bg-blue-50 ring-1 ring-blue-400' : 'hover:bg-slate-50'"
                   @click="activeMetric = metric.title; updateMetricOpacity()">
                <div class="flex items-center justify-between mb-1">
                  <h3 class="text-slate-900 font-medium text-xs">{{ metric.title }}</h3>
                  <i :data-lucide="metric.icon" class="w-4 h-4" :style="{ color: metric.iconHex }"></i>
                </div>
                <p class="text-slate-600 text-[11px] mb-2 line-clamp-2">{{ metric.description }}</p>
                <div v-if="metric.statusLabel"
                     :class="['inline-flex items-center text-[11px] font-medium rounded-full px-2 py-0.5 mb-2', metric.statusClass].join(' ')">
                  {{ metric.statusLabel }}
                </div>
                <div class="mt-auto text-slate-900 font-semibold text-sm">{{ metric.value ?? '-' }}</div>
              </div>
            </div>
          </div>

          <!-- Chart -->
          <div class="border rounded-lg p-4 bg-slate-50/50 min-h-[520px]">
            <!-- Chart type toggle positioned at the top-right of the graph area -->
            <div class="flex items-center justify-end mb-3">
              <chart-type-toggle :type="chartType" @update="chartType=$event" />
            </div>
            <!-- Render only when data is ready to avoid heavy initial chart render on empty config -->
            <apex-chart
              ref="healthChart"
              v-if="tab==='health' && chartOptions && chartSeries && chartSeries.length && chartOptions.xaxis && chartOptions.xaxis.categories && chartOptions.xaxis.categories.length"
              :options="chartOptions"
              :series="chartSeries"
              :height="500"
            />
            <apex-chart
              ref="wellChart"
              v-else-if="tab==='well' && wellUnwellOptions && wellUnwellSeries && wellUnwellSeries.length && wellUnwellOptions.xaxis && wellUnwellOptions.xaxis.categories && wellUnwellOptions.xaxis.categories.length"
              :options="wellUnwellOptions"
              :series="wellUnwellSeries"
              :height="500"
            />
            <div v-else class="flex items-center justify-center h-[480px]">
              <div class="text-center text-slate-600">
                <div class="text-lg font-semibold mb-1">Tidak ada data untuk filter ini</div>
                <div class="text-sm">Jika Anda sudah memilih karyawan, sistem akan menampilkan seluruh riwayat secara otomatis.</div>
              </div>
            </div>
          </div>
        </div>
      </div>
    `
  };

  window.Components.GrafikManager = GrafikManager;
})();
