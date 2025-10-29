// static/js/components/grafik.js
// Vue component: GrafikKesehatan
// Purpose: Move inline chart interaction logic (Plotly) from Django templates into Vue component.
// Note: Uses global Vue (vue.global.prod.js) and global Plotly from CDN.

(function(){
  window.Components = window.Components || {};

  const GrafikKesehatan = {
    name: 'grafik-kesehatan',
    template: '<div></div>', // Non-intrusive; we enhance existing DOM
    mounted(){
      try {
        const root = this.$el.closest('#grafik-content') || document.querySelector('#grafik-content');
        const grafContainer = document.querySelector('#managerHealthChart .plotly-graph-div');
        const isPlotlyAvailable = typeof Plotly !== 'undefined' && Plotly && typeof Plotly.relayout === 'function';

        // Threshold values (same as original inline script)
        const thresholdValues = {
          'Gula Darah Puasa': 126,
          'Gula Darah Sewaktu': 200,
          'Asam Urat': 7,
          'Cholesterol': 200
        };

        // Bind legend click to draw threshold line
        if (grafContainer && isPlotlyAvailable) {
          if (typeof grafContainer.on === 'function') {
            grafContainer.on('plotly_legendclick', function(ev){
              try {
                const idx = ev.curveNumber;
                const d = ev.data || (ev.fullData || []);
                const name = (d && d[idx] && d[idx].name) ? d[idx].name : null;
                if (!name) return true;
                const thr = thresholdValues[name];
                const shapes = thr != null
                  ? [{ type: 'line', xref: 'paper', x0: 0, x1: 1, yref: 'y', y0: thr, y1: thr, line: { color: 'rgba(239,68,68,0.7)', width: 2, dash: 'dash' } }]
                  : [];
                Plotly.relayout(grafContainer, { shapes: shapes });
              } catch(e) {}
              return true;
            });
          }

          // Card clicks draw threshold line
          root && root.querySelectorAll('[data-metric]').forEach(card => {
            card.addEventListener('click', function(){
              const key = this.dataset.metric;
              const thr = thresholdValues[key];
              if (thr == null) return;
              const shape = [{ type: 'line', xref: 'paper', x0: 0, x1: 1, yref: 'y', y0: thr, y1: thr, line: { color: 'rgba(239,68,68,0.7)', width: 2, dash: 'dash' } }];
              try { Plotly.relayout(grafContainer, { shapes: shape }); } catch(e) {}
            });
          });

          // Responsive chart
          window.addEventListener('resize', function(){
            try { Plotly.Plots.resize(grafContainer); } catch(e) {}
          });
        }

        // Optional: If no server-rendered chart exists, we can later render from JSON.
        // For Phase 2, we avoid visual change and do not auto-fetch/replace the empty state.
      } catch (e) {
        console.warn('[GrafikKesehatan] Initialization warning:', e);
      }
    }
  };

  window.Components.GrafikKesehatan = GrafikKesehatan;
})();