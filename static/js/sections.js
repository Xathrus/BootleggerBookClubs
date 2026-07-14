// Section editor: toggle between one meeting date and a list of
// date + chapters rows for books read across several meetings.
(function () {
  const checkbox = document.getElementById('sectioned');
  if (!checkbox) return;

  const single = document.getElementById('single-meeting');
  const editor = document.getElementById('sections-editor');
  const rows = document.getElementById('section-rows');
  const addBtn = document.getElementById('add-section');

  function addRow(date, portion) {
    const row = document.createElement('div');
    row.className = 'section-row';

    const d = document.createElement('input');
    d.type = 'date'; d.name = 'section_date'; d.value = date || '';

    const p = document.createElement('input');
    p.type = 'text'; p.name = 'section_portion'; p.value = portion || '';
    p.maxLength = 120; p.placeholder = 'e.g. Chapters 1–5';

    const x = document.createElement('button');
    x.type = 'button';
    x.className = 'btn btn-danger btn-icon section-remove';
    x.title = 'Remove section';
    x.innerHTML = '&times;';

    row.append(d, p, x);
    rows.appendChild(row);
  }

  function sync() {
    single.hidden = checkbox.checked;
    editor.hidden = !checkbox.checked;
    if (checkbox.checked && !rows.children.length) {
      addRow(); addRow();  // start with two rows — it's a split book after all
    }
  }

  checkbox.addEventListener('change', sync);
  addBtn.addEventListener('click', () => addRow());
  rows.addEventListener('click', (e) => {
    const btn = e.target.closest('.section-remove');
    if (btn) btn.closest('.section-row').remove();
  });
})();
