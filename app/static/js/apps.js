// Confirm helper
function confirmAction(msg, cb) {
  if (window.confirm(msg)) cb();
}

// Format date
function fmtDate(iso) {
  if (!iso) return '—';
  const d = new Date(iso);
  return d.toLocaleDateString('en-GB', { day:'2-digit', month:'short', year:'numeric' });
}

// Debounce
function debounce(fn, delay) {
  let t;
  return (...args) => { clearTimeout(t); t = setTimeout(() => fn(...args), delay); };
}

(function initTheme() {
  const saved = localStorage.getItem('boss-theme') || 'dark';
  applyTheme(saved);
})();
 
function applyTheme(theme) {
  document.documentElement.setAttribute('data-theme', theme);
  localStorage.setItem('boss-theme', theme);
 
  if (theme === 'light') {
    document.documentElement.style.setProperty('--bg',       '#ffffff');
    document.documentElement.style.setProperty('--bg2',      '#f4f4f5');
    document.documentElement.style.setProperty('--bg3',      '#e4e4e7');
    document.documentElement.style.setProperty('--surface',  '#ffffff');
    document.documentElement.style.setProperty('--surface2', '#f4f4f5');
    document.documentElement.style.setProperty('--border',   '#e4e4e7');
    document.documentElement.style.setProperty('--border2',  '#d4d4d8');
    document.documentElement.style.setProperty('--text',     '#18181b');
    document.documentElement.style.setProperty('--text2',    '#52525b');
    document.documentElement.style.setProperty('--text3',    '#a1a1aa');
    document.documentElement.style.setProperty('--sidebar-bg',    '#18181b');
    document.documentElement.style.setProperty('--sidebar-hover', '#27272a');
  } else {
    document.documentElement.style.setProperty('--bg',       '#0d1117');
    document.documentElement.style.setProperty('--bg2',      '#131d2e');
    document.documentElement.style.setProperty('--bg3',      '#1a2536');
    document.documentElement.style.setProperty('--surface',  '#151f2e');
    document.documentElement.style.setProperty('--surface2', '#1c2a3a');
    document.documentElement.style.setProperty('--border',   '#1f2d42');
    document.documentElement.style.setProperty('--border2',  '#2a3f5a');
    document.documentElement.style.setProperty('--text',     '#e2e8f0');
    document.documentElement.style.setProperty('--text2',    '#94a3b8');
    document.documentElement.style.setProperty('--text3',    '#64748b');
    document.documentElement.style.setProperty('--sidebar-bg',    '#080f1a');
    document.documentElement.style.setProperty('--sidebar-hover', '#0f1c2e');
  }
 
  // Update toggle button icon
  const btn = document.getElementById('themeToggleBtn');
  if (btn) btn.innerHTML = theme === 'light'
    ? '<i class="fa-solid fa-moon"></i>'
    : '<i class="fa-solid fa-sun"></i>';
}
 
function toggleTheme() {
  const current = localStorage.getItem('boss-theme') || 'dark';
  applyTheme(current === 'dark' ? 'light' : 'dark');
}
 
 
// ══════════════════════════════════════════════════════════════════════════════
//  8. KEYBOARD SHORTCUTS
// ══════════════════════════════════════════════════════════════════════════════
 
(function initKeyboardShortcuts() {
  let gPressed = false;
  let gTimer   = null;
 
  const GO_ROUTES = {
    'd': '/dashboard',
    'm': '/messages',
    'k': '/knowledge-base',
    'a': '/ask-boss',
    't': '/tasks',
    'n': '/announcements',
    'r': '/analytics',
    'b': '/bcc',
    'h': '/bcc/hr',
    'l': '/leave',
    's': '/settings',
    'p': '/platform',
  };
 
  document.addEventListener('keydown', (e) => {
    const tag = e.target.tagName.toLowerCase();
    const isInput = ['input','textarea','select'].includes(tag) || e.target.isContentEditable;
 
    // Cmd+K or Ctrl+K → Global Search
    if ((e.metaKey || e.ctrlKey) && e.key === 'k') {
      e.preventDefault();
      openGlobalSearch();
      return;
    }
 
    // Escape → close search / modals
    if (e.key === 'Escape') {
      closeGlobalSearch();
      return;
    }
 
    if (isInput) return;
 
    // G + letter navigation
    if (e.key === 'g' || e.key === 'G') {
      gPressed = true;
      clearTimeout(gTimer);
      gTimer = setTimeout(() => { gPressed = false; }, 1200);
      return;
    }
 
    if (gPressed) {
      const route = GO_ROUTES[e.key.toLowerCase()];
      if (route) {
        e.preventDefault();
        gPressed = false;
        clearTimeout(gTimer);
        window.location.href = route;
      }
    }
 
    // ? → show shortcut help
    if (e.key === '?') {
      openModal('shortcutsModal');
    }
  });
})();
 

// ══════════════════════════════════════════════════════════════════════════════
//  9. GLOBAL SEARCH
// ══════════════════════════════════════════════════════════════════════════════
 
let _searchOpen   = false;
let _searchTimer  = null;
let _searchIndex  = -1;
let _searchResults = [];
 
function openGlobalSearch() {
  _searchOpen = true;
  _searchIndex = -1;
  _searchResults = [];
 
  let overlay = document.getElementById('globalSearchOverlay');
  if (!overlay) {
    overlay = document.createElement('div');
    overlay.id = 'globalSearchOverlay';
    overlay.innerHTML = `
      <div id="globalSearchBox">
        <div style="display:flex;align-items:center;gap:10px;padding:14px 16px;border-bottom:1px solid var(--border);">
          <i class="fa-solid fa-magnifying-glass" style="color:var(--text3);font-size:14px;"></i>
          <input id="globalSearchInput" type="text" placeholder="Search messages, documents, users, tasks…"
            style="flex:1;background:none;border:none;outline:none;color:var(--text);font-size:15px;font-family:var(--font);"
            oninput="runGlobalSearch(this.value)"
            onkeydown="handleSearchKey(event)"/>
          <kbd style="font-size:11px;color:var(--text3);background:var(--bg3);padding:2px 6px;border-radius:4px;border:1px solid var(--border);">ESC</kbd>
        </div>
        <div id="globalSearchResults" style="max-height:420px;overflow-y:auto;padding:8px 0;"></div>
        <div style="padding:10px 16px;border-top:1px solid var(--border);display:flex;gap:16px;font-size:11px;color:var(--text3);">
          <span><kbd style="background:var(--bg3);padding:1px 5px;border-radius:3px;border:1px solid var(--border);">↑↓</kbd> Navigate</span>
          <span><kbd style="background:var(--bg3);padding:1px 5px;border-radius:3px;border:1px solid var(--border);">↵</kbd> Open</span>
          <span><kbd style="background:var(--bg3);padding:1px 5px;border-radius:3px;border:1px solid var(--border);">ESC</kbd> Close</span>
          <span style="margin-left:auto;"><kbd style="background:var(--bg3);padding:1px 5px;border-radius:3px;border:1px solid var(--border);">G</kbd> then letter for quick nav</span>
        </div>
      </div>`;
    overlay.style.cssText = `
      position:fixed;inset:0;z-index:9990;
      background:rgba(0,0,0,0.6);backdrop-filter:blur(4px);
      display:flex;align-items:flex-start;justify-content:center;padding-top:80px;`;
    overlay.addEventListener('click', (e) => {
      if (e.target === overlay) closeGlobalSearch();
    });
 
    // Inject styles
    if (!document.getElementById('gsStyle')) {
      const style = document.createElement('style');
      style.id = 'gsStyle';
      style.textContent = `
        #globalSearchBox {
          width:100%;max-width:640px;
          background:var(--bg);border:1px solid var(--border);
          border-radius:12px;box-shadow:0 20px 60px rgba(0,0,0,0.4);
          overflow:hidden;
        }
        .gs-result {
          display:flex;align-items:center;gap:12px;
          padding:11px 16px;cursor:pointer;transition:background .1s;
        }
        .gs-result:hover, .gs-result.selected { background:var(--bg2); }
        .gs-icon {
          width:32px;height:32px;border-radius:8px;
          display:flex;align-items:center;justify-content:center;
          font-size:13px;flex-shrink:0;
        }
        .gs-title  { font-size:13.5px;font-weight:500;color:var(--text); }
        .gs-sub    { font-size:11.5px;color:var(--text3);margin-top:1px; }
        .gs-type   { font-size:10px;font-weight:700;color:var(--text3);text-transform:uppercase;letter-spacing:.06em;margin-left:auto;flex-shrink:0; }
        .gs-empty  { text-align:center;padding:36px;color:var(--text3);font-size:13px; }
      `;
      document.head.appendChild(style);
    }
 
    document.body.appendChild(overlay);
  }
 
  overlay.style.display = 'flex';
  setTimeout(() => document.getElementById('globalSearchInput')?.focus(), 50);
 
  // Show quick nav hints on open
  document.getElementById('globalSearchResults').innerHTML = `
    <div style="padding:16px 16px 8px;font-size:11px;font-weight:700;color:var(--text3);text-transform:uppercase;letter-spacing:.08em;">Quick Navigation</div>
    ${[
      ['G + D', 'Dashboard',    '/dashboard'],
      ['G + M', 'Messages',     '/messages'],
      ['G + A', 'Ask BOSS',     '/ask-boss'],
      ['G + T', 'Tasks',        '/tasks'],
      ['G + B', 'Command Centre', '/bcc'],
      ['G + R', 'Analytics',   '/analytics'],
      ['G + S', 'Settings',    '/settings'],
    ].map(([keys,label,url]) => `
      <div class="gs-result" onclick="window.location.href='${url}'">
        <div class="gs-icon" style="background:var(--bg2);color:var(--text3);">
          <i class="fa-solid fa-arrow-right" style="font-size:11px;"></i>
        </div>
        <div style="flex:1;">
          <div class="gs-title">${label}</div>
        </div>
        <kbd style="font-size:10px;color:var(--text3);background:var(--bg3);padding:2px 7px;border-radius:4px;border:1px solid var(--border);">${keys}</kbd>
      </div>`).join('')}`;
}
 
function closeGlobalSearch() {
  _searchOpen = false;
  const overlay = document.getElementById('globalSearchOverlay');
  if (overlay) overlay.style.display = 'none';
}
 
async function runGlobalSearch(q) {
  clearTimeout(_searchTimer);
  const container = document.getElementById('globalSearchResults');
  if (q.length < 2) {
    container.innerHTML = '<div class="gs-empty">Type at least 2 characters to search…</div>';
    return;
  }
  container.innerHTML = '<div class="gs-empty"><i class="fa-solid fa-spinner fa-spin"></i> Searching…</div>';
  _searchTimer = setTimeout(async () => {
    try {
      const r = await fetch(`/search?q=${encodeURIComponent(q)}`);
      const d = await r.json();
      _searchResults = d.results || [];
      _searchIndex = -1;
      renderSearchResults(_searchResults, q);
    } catch(e) {
      container.innerHTML = '<div class="gs-empty">Search error. Try again.</div>';
    }
  }, 250);
}
 
function renderSearchResults(results, q) {
  const container = document.getElementById('globalSearchResults');
  if (!results.length) {
    container.innerHTML = `<div class="gs-empty">No results for "<strong>${q}</strong>"</div>`;
    return;
  }
  const re = new RegExp(`(${q.replace(/[.*+?^${}()|[\]\\]/g,'\\$&')})`, 'gi');
  container.innerHTML = results.map((r, i) => `
    <div class="gs-result ${i === _searchIndex ? 'selected' : ''}"
         onclick="window.location.href='${r.url}'"
         data-idx="${i}">
      <div class="gs-icon" style="background:${r.color}18;color:${r.color};">
        <i class="fa-solid ${r.icon}"></i>
      </div>
      <div style="flex:1;min-width:0;">
        <div class="gs-title">${r.title.replace(re,'<mark style="background:rgba(245,158,11,.2);color:var(--yellow);border-radius:2px;">$1</mark>')}</div>
        <div class="gs-sub">${r.subtitle || ''}</div>
      </div>
      <span class="gs-type">${r.type}</span>
    </div>`).join('');
}
 
function handleSearchKey(e) {
  if (e.key === 'ArrowDown') {
    e.preventDefault();
    _searchIndex = Math.min(_searchIndex + 1, _searchResults.length - 1);
    updateSearchSelection();
  } else if (e.key === 'ArrowUp') {
    e.preventDefault();
    _searchIndex = Math.max(_searchIndex - 1, -1);
    updateSearchSelection();
  } else if (e.key === 'Enter' && _searchIndex >= 0) {
    const result = _searchResults[_searchIndex];
    if (result) window.location.href = result.url;
  }
}
 
function updateSearchSelection() {
  document.querySelectorAll('.gs-result').forEach((el, i) => {
    el.classList.toggle('selected', i === _searchIndex);
    if (i === _searchIndex) el.scrollIntoView({block:'nearest'});
  });
}
 
 
// ══════════════════════════════════════════════════════════════════════════════
//  10. DRAG-AND-DROP FILE UPLOADS
// ══════════════════════════════════════════════════════════════════════════════
 
(function initDragDrop() {
  let dragCounter = 0;
 
  const overlay = document.createElement('div');
  overlay.id = 'dropOverlay';
  overlay.style.cssText = `
    display:none;position:fixed;inset:0;z-index:8888;
    background:rgba(37,99,235,0.12);border:3px dashed var(--accent);
    align-items:center;justify-content:center;flex-direction:column;gap:12px;
    pointer-events:none;`;
  overlay.innerHTML = `
    <div style="width:72px;height:72px;border-radius:50%;background:var(--accent);display:flex;align-items:center;justify-content:center;font-size:28px;color:#fff;">
      <i class="fa-solid fa-cloud-arrow-up"></i>
    </div>
    <div style="font-size:18px;font-weight:700;color:var(--accent);">Drop files to upload</div>
    <div style="font-size:13px;color:var(--text2);">Files will be attached to the current conversation or document</div>`;
  document.body.appendChild(overlay);
 
  document.addEventListener('dragenter', (e) => {
    if (!e.dataTransfer?.types.includes('Files')) return;
    dragCounter++;
    overlay.style.display = 'flex';
  });
 
  document.addEventListener('dragleave', (e) => {
    dragCounter--;
    if (dragCounter <= 0) {
      dragCounter = 0;
      overlay.style.display = 'none';
    }
  });
 
  document.addEventListener('dragover', (e) => {
    e.preventDefault();
    e.dataTransfer.dropEffect = 'copy';
  });
 
  document.addEventListener('drop', (e) => {
    e.preventDefault();
    dragCounter = 0;
    overlay.style.display = 'none';
 
    const files = Array.from(e.dataTransfer?.files || []);
    if (!files.length) return;
 
    // Route to the appropriate handler based on current page
    const path = window.location.pathname;
 
    if (path.includes('/messages')) {
      // Messages page — attach to message input
      if (typeof handleFileSelect === 'function') {
        handleFileSelect(files);
        toast(`${files.length} file${files.length > 1 ? 's' : ''} attached to message`, 'success');
      }
    } else if (path.includes('/documents')) {
      // Documents page — trigger document upload
      const fileInput = document.querySelector('input[type="file"]');
      if (fileInput) {
        const dt = new DataTransfer();
        files.forEach(f => dt.items.add(f));
        fileInput.files = dt.files;
        fileInput.dispatchEvent(new Event('change', {bubbles: true}));
        toast(`${files.length} file${files.length > 1 ? 's' : ''} ready to upload`, 'success');
      }
    } else {
      // Anywhere else — show a toast and open file picker if available
      toast(`${files.length} file${files.length > 1 ? 's' : ''} dropped — navigate to Messages or Documents to upload`, 'info');
    }
  });
})();