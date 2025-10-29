// static/js/components/form.js
// Vue component: FormInput (Nurse data entry)
// Purpose: Move DOM logic (e.g., auto BMI calculation) into Vue while keeping Django form submission.

(function(){
  window.Components = window.Components || {};

  const FormInput = {
    name: 'form-input',
    template: '<div></div>', // Enhance existing form DOM
    mounted(){
      try {
        const root = this.$el.closest('#form-section') || document.querySelector('#form-section');
        if (!root) return;
        const tinggi = root.querySelector('input[name="tinggi"]');
        const berat = root.querySelector('input[name="berat"]');
        const bmi = root.querySelector('input[name="bmi"]');

        function calcBMI(){
          if (!tinggi || !berat || !bmi) return;
          const t = parseFloat(tinggi.value || '0');
          const b = parseFloat(berat.value || '0');
          if (t > 0 && b > 0){
            const meters = t / 100.0;
            const val = b / (meters * meters);
            bmi.value = isFinite(val) ? val.toFixed(2) : '';
          }
        }

        ;['input','change'].forEach(evt => {
          if (tinggi) tinggi.addEventListener(evt, calcBMI);
          if (berat) berat.addEventListener(evt, calcBMI);
        });

        // Initialize BMI on mount
        calcBMI();
      } catch(e) {
        console.warn('[FormInput] Initialization warning:', e);
      }
    }
  };

  window.Components.FormInput = FormInput;
})();