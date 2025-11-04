// Global Vue mount script (CDN mode)
// Phase 2: Conditionally mount component apps for grafik, filters, and form sections

document.addEventListener('DOMContentLoaded', function(){
  if (!window.Vue) {
    console.warn('Vue global not found.');
    return;
  }

  const { createApp } = Vue;

  function mountIfExists(selector, component){
    const el = document.querySelector(selector);
    if (el && component) {
      try {
        const app = createApp(component);
        // ECharts does not require a Vue plugin; wrapper uses window.echarts
        app.mount(selector);
        return true;
      } catch(e) {
        console.warn('Failed to mount component at', selector, e);
        return false;
      }
    }
    return false;
  }

  const C = window.Components || {};
  // Gate Grafik mount behind ECharts availability to avoid race conditions on first load
  function whenEchartsReady(cb){
    const start = Date.now();
    const maxWait = 5000; // 5s timeout
    (function poll(){
      if (window.echarts) { cb(); }
      else if (Date.now() - start < maxWait) { setTimeout(poll, 100); }
      else { cb(); }
    })();
  }
  let mountedVueGrafik = false;
  const grafikElExists = !!document.querySelector('#grafik-manager');
  if (grafikElExists && (C.GrafikNurse || C.GrafikManager)) {
    const comp = C.GrafikNurse || C.GrafikManager;
    whenEchartsReady(()=>{ 
      mountedVueGrafik = mountIfExists('#grafik-manager', comp); 
    });
  }
  if (mountedVueGrafik) {
    const legacy = document.getElementById('grafik-legacy');
    if (legacy) legacy.classList.add('hidden');
  }
  mountIfExists('#grafik-content', C.GrafikKesehatan);
  mountIfExists('#filters-section', C.FiltersSection);
  mountIfExists('#form-section', C.FormInput);

  console.log('Vue is active on this page');
});