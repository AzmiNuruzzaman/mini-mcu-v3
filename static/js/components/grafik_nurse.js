/*
  grafik_nurse.js
  Purpose: Provide a nurse-specific alias to the shared GrafikManager Vue component, so the nurse dashboard can
  reuse the exact same charts/UI logic as the manager dashboard without duplicating implementation.

  This file is intentionally lightweight: it simply creates an alias window.Components.GrafikNurse that points to
  window.Components.GrafikManager once it's available. The nurse template still mounts #grafik-manager to match
  the manager UI exactly, but keeping this alias helps future refactors where we may want nurse-specific behavior.
*/
(function () {
  try {
    window.Components = window.Components || {};
    if (window.Components.GrafikManager) {
      // Alias existing manager component for nurse usage
      window.Components.GrafikNurse = window.Components.GrafikManager;
      console.debug('[grafik_nurse] GrafikNurse aliased to GrafikManager');
    } else {
      // Defer alias creation until GrafikManager script loads
      const originalDefine = Object.defineProperty;
      try {
        // Create a getter/setter hook to alias when GrafikManager is defined later
        originalDefine(window.Components, 'GrafikManager', {
          configurable: true,
          enumerable: true,
          set: function (val) {
            // Store the value and immediately alias
            delete window.Components.GrafikManager;
            window.Components.GrafikManager = val;
            window.Components.GrafikNurse = val;
            console.debug('[grafik_nurse] GrafikManager loaded. Nurse alias set.');
          }
        });
      } catch (err) {
        // Fallback: poll briefly to alias after load
        let attempts = 0;
        const timer = setInterval(function () {
          attempts++;
          if (window.Components && window.Components.GrafikManager) {
            window.Components.GrafikNurse = window.Components.GrafikManager;
            clearInterval(timer);
            console.debug('[grafik_nurse] GrafikNurse aliased via polling');
          }
          if (attempts > 30) clearInterval(timer); // ~3s max
        }, 100);
      }
    }
  } catch (e) {
    // Non-fatal: alias is just a convenience
    console.warn('[grafik_nurse] Failed to set alias:', e);
  }
})();