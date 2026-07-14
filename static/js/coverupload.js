// Cover preview handling that works on both the add and edit forms:
// - picking a file previews it immediately and greys the URL box
// - editing the URL previews it (when no file is chosen)
// - picking a search result clears any chosen file
(function () {
  const file = document.getElementById('cover_file');
  const url = document.getElementById('cover_url');
  const preview = document.getElementById('cover-preview');
  if (!file || !url || !preview) return;

  function show(src) {
    if (src) { preview.src = src; preview.hidden = false; }
    else preview.hidden = true;
  }

  file.addEventListener('change', () => {
    if (file.files && file.files[0]) {
      show(URL.createObjectURL(file.files[0]));
      url.disabled = true;   // the upload wins; make that visible
    } else {
      url.disabled = false;
      show(url.value.trim());
    }
  });

  url.addEventListener('change', () => {
    if (!file.files || !file.files.length) show(url.value.trim());
  });

  // If the Open Library search fills the URL box, drop any chosen file
  // so the picked cover is what actually gets saved.
  document.addEventListener('booksearch:pick', () => {
    file.value = '';
    url.disabled = false;
  });

  // Re-enable the URL box before submit so its value still posts
  // (disabled inputs are excluded from form data).
  file.closest('form').addEventListener('submit', () => { url.disabled = false; });
})();
