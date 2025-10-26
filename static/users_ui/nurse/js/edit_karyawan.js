// Nurse History tab per-row edit helpers

function toggleEditRow(id) {
  try {
    const inputs = document.querySelectorAll(`[id$="-${id}"]`);
    inputs.forEach(inp => { if (inp) inp.disabled = false; });
    const editBtn = document.getElementById(`editbtn-${id}`);
    const saveBtn = document.getElementById(`savebtn-${id}`);
    if (editBtn) editBtn.classList.add("hidden");
    if (saveBtn) saveBtn.classList.remove("hidden");
  } catch (e) {
    console.error('toggleEditRow error:', e);
  }
}

function submitEditRow(id) {
  try {
    const form = document.createElement("form");
    form.method = "POST";
    form.action = window.location.pathname + window.location.search;
    const csrfInput = document.querySelector('[name=csrfmiddlewaretoken]');
    const csrf = csrfInput ? csrfInput.value : '';
    form.innerHTML = `
      <input type="hidden" name="csrfmiddlewaretoken" value="${csrf}">
      <input type="hidden" name="action" value="edit_row">
      <input type="hidden" name="checkup_id" value="${id}">
      <input type="hidden" name="save_changes" value="1">
    `;
    const fields = [
      "tanggal_checkup",
      "lingkar_perut",
      "gula_darah_puasa",
      "gula_darah_sewaktu",
      "cholesterol",
      "asam_urat",
      "tekanan_darah",
      "derajat_kesehatan"
    ];
    fields.forEach(f => {
      const el = document.getElementById(`${f}-${id}`);
      const val = el ? el.value : "";
      form.innerHTML += `<input type="hidden" name="${f}" value="${val}">`;
    });
    document.body.appendChild(form);
    form.submit();
  } catch (e) {
    console.error('submitEditRow error:', e);
  }
}