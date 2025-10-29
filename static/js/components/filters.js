// static/js/components/filters.js
// Vue component: FiltersSection
// Purpose: Manage filters state and convert server-side conditionals into Vue-driven state (progressive enhancement).

(function(){
  window.Components = window.Components || {};

  const FiltersSection = {
    name: 'filters-section',
    template: '<div></div>', // We only enhance existing DOM form
    setup(){
      const { reactive } = Vue;
      const state = reactive({
        activeTab: null,
        start_month: '',
        end_month: '',
        uid: ''
      });

      function initFromDOM(){
        const url = new URL(window.location.href);
        state.activeTab = url.searchParams.get('subtab') || 'grafik_kesehatan';
        const root = document.querySelector('#filters-section') || document.querySelector('#grafik-content');
        if (!root) return;
        const start = root.querySelector('input[name="start_month"]');
        const end = root.querySelector('input[name="end_month"]');
        const uidSel = root.querySelector('select[name="uid"]');
        state.start_month = start ? start.value : '';
        state.end_month = end ? end.value : '';
        state.uid = uidSel ? uidSel.value : '';
      }

      function bindSubmit(){
        const form = document.querySelector('#filters-section form');
        if (!form) return;
        form.addEventListener('submit', function(){
          // Sync Vue state back to form fields before submit
          const start = form.querySelector('input[name="start_month"]');
          const end = form.querySelector('input[name="end_month"]');
          const uidSel = form.querySelector('select[name="uid"]');
          if (start) start.value = state.start_month || start.value;
          if (end) end.value = state.end_month || end.value;
          if (uidSel && state.uid) uidSel.value = state.uid;
        });
      }

      function toggleVisibility(){
        // Mirror Django conditional via Vue state (non-destructive)
        const graf = document.querySelector('#grafik-content');
        if (!graf) return;
        const shouldShow = (state.activeTab === 'grafik_kesehatan');
        if (shouldShow) graf.classList.remove('hidden');
        else graf.classList.add('hidden');
      }

      return { state, initFromDOM, bindSubmit, toggleVisibility };
    },
    mounted(){
      try {
        this.initFromDOM();
        this.bindSubmit();
        this.toggleVisibility();
      } catch(e) {
        console.warn('[FiltersSection] Initialization warning:', e);
      }
    }
  };

  window.Components.FiltersSection = FiltersSection;
})();