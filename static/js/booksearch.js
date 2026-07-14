// Book search — talks to /api/book-search (which proxies Open Library)
// and fills the form when a result is picked.
(function () {
  const input = document.getElementById('book-search');
  if (!input) return;

  const results = document.getElementById('search-results');
  const status = document.getElementById('search-status');
  const fields = {
    title: document.getElementById('title'),
    author: document.getElementById('author'),
    cover: document.getElementById('cover_url'),
    preview: document.getElementById('cover-preview'),
  };

  let timer = null;
  let controller = null;

  function setStatus(msg) {
    status.hidden = !msg;
    status.textContent = msg || '';
  }

  function clearResults() {
    results.innerHTML = '';
    results.hidden = true;
  }

  async function search(q) {
    if (controller) controller.abort();
    controller = new AbortController();
    setStatus('Searching…');
    try {
      const resp = await fetch('/api/book-search?q=' + encodeURIComponent(q), {
        signal: controller.signal,
      });
      const data = await resp.json();
      if (data.error) { setStatus(data.error); clearResults(); return; }
      render(data.results || []);
      setStatus(data.results && data.results.length ? '' : 'No matches — you can type the details in below.');
    } catch (err) {
      if (err.name !== 'AbortError') {
        setStatus('Search failed — you can type the details in below.');
        clearResults();
      }
    }
  }

  function render(items) {
    clearResults();
    if (!items.length) return;
    for (const item of items) {
      const li = document.createElement('li');
      const btn = document.createElement('button');
      btn.type = 'button';
      btn.className = 'search-result';

      const img = document.createElement('img');
      img.className = 'search-thumb';
      img.alt = '';
      if (item.thumb) img.src = item.thumb; else img.classList.add('search-thumb-blank');

      const text = document.createElement('span');
      text.className = 'search-text';
      const t = document.createElement('strong');
      t.textContent = item.title;
      const a = document.createElement('span');
      a.textContent = item.author + (item.year ? ' · ' + item.year : '');
      text.append(t, a);

      btn.append(img, text);
      btn.addEventListener('click', () => pick(item));
      li.appendChild(btn);
      results.appendChild(li);
    }
    results.hidden = false;
  }

  function pick(item) {
    fields.title.value = item.title || '';
    fields.author.value = item.author || '';
    fields.cover.value = item.cover || '';
    if (item.cover) {
      fields.preview.src = item.cover;
      fields.preview.hidden = false;
    } else {
      fields.preview.hidden = true;
    }
    clearResults();
    setStatus('Filled in “' + item.title + '” — adjust anything you like, then set the dates.');
    input.value = '';
    document.dispatchEvent(new Event('booksearch:pick'));
  }

  input.addEventListener('input', () => {
    clearTimeout(timer);
    const q = input.value.trim();
    if (q.length < 2) { clearResults(); setStatus(''); return; }
    timer = setTimeout(() => search(q), 350);
  });

  // Live cover preview when the URL field is edited by hand
  fields.cover.addEventListener('change', () => {
    const url = fields.cover.value.trim();
    if (url) { fields.preview.src = url; fields.preview.hidden = false; }
    else fields.preview.hidden = true;
  });
})();
