// Lightweight ApexCharts wrapper component for Vue 3 (script setup compatible import)
export default {
  name: 'ApexChart',
  props: { options: Object, series: Array, height: [String, Number] },
  template: `<div ref="el" style="width:100%"></div>`,
  mounted() {
    if (typeof ApexCharts === 'undefined') {
      console.warn('[ApexChart] ApexCharts not found');
      return;
    }
    const base = this.options || {};
    const chart = Object.assign({}, base.chart || {}, { height: this.height });
    const opts = Object.assign({}, base, { series: this.series, chart });
    this._chart = new ApexCharts(this.$refs.el, opts);
    this._chart.render();
  },
  watch: {
    options: { deep: true, handler(newVal) { this._chart?.updateOptions(Object.assign({}, newVal, { series: this.series })); } },
    series: { deep: true, handler(newSeries) { this._chart?.updateSeries(newSeries); } },
    height(val) { this._chart?.updateOptions({ chart: Object.assign({}, (this.options||{}).chart || {}, { height: val }) }); }
  },
  unmounted() { this._chart?.destroy(); this._chart = null; }
};