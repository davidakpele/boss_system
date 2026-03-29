// BOSS System — global utilities
// Most JS lives inline in templates for portability

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
