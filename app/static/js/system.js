let _notifOpen = false;
let _waAction = 'improve';
let _waCallback = null;

(function () {
    const sidebar = document.getElementById('sidebar');
    const overlay = document.getElementById('sidebarOverlay');
    const toggle  = document.getElementById('menuToggle');

    function openSidebar() {
    sidebar.classList.add('open');
    overlay.classList.add('open');
    document.body.style.overflow = 'hidden';
    }
    function closeSidebar() {
    sidebar.classList.remove('open');
    overlay.classList.remove('open');
    document.body.style.overflow = '';
    }

    toggle.addEventListener('click', () =>
    sidebar.classList.contains('open') ? closeSidebar() : openSidebar()
    );
    overlay.addEventListener('click', closeSidebar);

    sidebar.querySelectorAll('.nav-item').forEach(item =>
    item.addEventListener('click', () => {
        if (window.innerWidth <= 768) closeSidebar();
    })
    );
})();

function toast(msg, type = 'info') {
    const icons = { success:'check', error:'xmark', info:'info' };
    const el = document.createElement('div');
    el.className = `toast toast-${type}`;
    el.innerHTML = `<i class="fa-solid fa-${icons[type]}"></i> ${msg}`;
    document.getElementById('toast-container').appendChild(el);
    setTimeout(() => el.remove(), 4000);
}

function openModal(id)  { document.getElementById(id).classList.add('open');    }
function closeModal(id) { document.getElementById(id).classList.remove('open'); }

document.querySelectorAll('.modal-overlay').forEach(o => {
    o.addEventListener('click', e => { if (e.target === o) o.classList.remove('open'); });
});

// ── 1. Register Service Worker ────────────────────────────────────────────────
if ('serviceWorker' in navigator) {
    window.addEventListener('load', () => {
    navigator.serviceWorker.register('/sw.js', { scope: '/' })
        .then(r  => console.log('[BOSS SW] registered', r.scope))
        .catch(e => console.warn('[BOSS SW] failed', e));
    });
}

// ── 2. Push Notifications ─────────────────────────────────────────────────────
let _pushEnabled = false;

async function _getPushKey() {
    try {
    const r = await fetch('/push/vapid-public-key');
    const d = await r.json();
    return d.publicKey || null;
    } catch { return null; }
}

async function initPushNotifications() {
    if (!('Notification' in window && 'serviceWorker' in navigator && 'PushManager' in window)) return;
    const key = await _getPushKey();
    if (!key) return;   // VAPID not configured server-side

    const reg = await navigator.serviceWorker.ready;
    const sub = await reg.pushManager.getSubscription();
    if (sub) { _pushEnabled = true; _updatePushBtn(true); }
}

async function requestPushPermission() {
    const perm = await Notification.requestPermission();
    if (perm !== 'granted') { if (typeof toast !== 'undefined') toast('Notification permission denied', 'error'); return; }

    const key = await _getPushKey();
    if (!key) { if (typeof toast !== 'undefined') toast('Push not configured on server (no VAPID key)', 'error'); return; }

    const reg = await navigator.serviceWorker.ready;
    const sub = await reg.pushManager.subscribe({
    userVisibleOnly:      true,
    applicationServerKey: _urlB64ToUint8(key),
    });

    const r = await fetch('/push/subscribe', {
    method:  'POST',
    headers: { 'Content-Type': 'application/json' },
    body:    JSON.stringify(sub),
    });
    if (r.ok) {
    _pushEnabled = true;
    _updatePushBtn(true);
    if (typeof toast !== 'undefined') toast('Push notifications enabled 🔔', 'success');
    }
}

async function disablePush() {
    const reg = await navigator.serviceWorker.ready;
    const sub = await reg.pushManager.getSubscription();
    if (sub) {
    await fetch('/push/subscribe', {
        method:  'DELETE',
        headers: { 'Content-Type': 'application/json' },
        body:    JSON.stringify({ endpoint: sub.endpoint }),
    });
    await sub.unsubscribe();
    }
    _pushEnabled = false;
    _updatePushBtn(false);
    if (typeof toast !== 'undefined') toast('Push notifications disabled', 'info');
}

function _updatePushBtn(enabled) {
    const btn = document.getElementById('pushToggleBtn');
    if (!btn) return;
    btn.innerHTML = enabled
    ? '<i class="fa-solid fa-bell-slash"></i> Disable Notifications'
    : '<i class="fa-solid fa-bell"></i> Enable Notifications';
    btn.onclick = enabled ? disablePush : requestPushPermission;
}

function _urlB64ToUint8(b64) {
    const padding = '='.repeat((4 - b64.length % 4) % 4);
    const raw = atob((b64 + padding).replace(/-/g, '+').replace(/_/g, '/'));
    return Uint8Array.from([...raw].map(c => c.charCodeAt(0)));
}

// ── 3. PWA Install Prompt ─────────────────────────────────────────────────────
let _deferredInstall = null;
window.addEventListener('beforeinstallprompt', e => {
    e.preventDefault();
    _deferredInstall = e;
    const btn = document.getElementById('installPwaBtn');
    if (btn) { btn.style.display = 'flex'; }
    const na = document.getElementById('pwaNotAvailableBadge');
    if (na)  { na.style.display = 'none'; }
});

async function installPWA() {
    if (!_deferredInstall) return;
    _deferredInstall.prompt();
    const { outcome } = await _deferredInstall.userChoice;
    if (outcome === 'accepted' && typeof toast !== 'undefined')
    toast('BOSS installed on your device 🎉', 'success');
    _deferredInstall = null;
    const btn = document.getElementById('installPwaBtn');
    if (btn) btn.style.display = 'none';
}
async function loadNotifications() {
    const r = await fetch('/notifications');
    if (!r.ok) return;
    const d = await r.json();
    const badge = document.getElementById('notifBadge');
    if (badge) {
    badge.style.display = d.unread > 0 ? 'flex' : 'none';
    badge.textContent = d.unread > 9 ? '9+' : d.unread;
    }
    const list = document.getElementById('notifList');
    if (!list) return;
    if (!d.notifications.length) {
    list.innerHTML = '<div style="padding:30px;text-align:center;color:var(--text3);font-size:12.5px;"><i class="fa-solid fa-bell-slash" style="font-size:24px;opacity:.2;display:block;margin-bottom:8px;"></i>No notifications</div>';
    return;
    }
    list.innerHTML = d.notifications.map(n => `
    <div onclick="openNotif(${n.id}, '${n.link}')" style="display:flex;align-items:flex-start;gap:10px;padding:12px 16px;border-bottom:1px solid rgba(31,45,66,0.4);cursor:pointer;background:${n.is_read?'transparent':'rgba(59,130,246,0.04)'};transition:background .12s;" onmouseover="this.style.background='var(--surface)'" onmouseout="this.style.background='${n.is_read?'transparent':'rgba(59,130,246,0.04)'}'">
        <div style="width:8px;height:8px;border-radius:50%;background:${n.is_read?'transparent':'var(--accent)'};flex-shrink:0;margin-top:5px;"></div>
        <div style="flex:1;min-width:0;">
        <div style="font-size:13px;font-weight:${n.is_read?'400':'600'};color:var(--text);white-space:nowrap;overflow:hidden;text-overflow:ellipsis;">${n.title}</div>
        ${n.body?`<div style="font-size:11.5px;color:var(--text3);margin-top:2px;white-space:nowrap;overflow:hidden;text-overflow:ellipsis;">${n.body}</div>`:''}
        <div style="font-size:10px;color:var(--text3);margin-top:3px;">${new Date(n.created_at).toLocaleTimeString([],{hour:'2-digit',minute:'2-digit'})}</div>
        </div>
    </div>
    `).join('');
}

async function openNotif(id, link) {
    await fetch(`/notifications/${id}/read`, {method:'POST'});
    if (link) location.href = link;
    loadNotifications();
}

async function markAllRead() {
    await fetch('/notifications/read-all', {method:'POST'});
    loadNotifications();
}

function toggleNotifPanel() {
    const panel = document.getElementById('notifPanel');
    _notifOpen = !_notifOpen;
    panel.style.display = _notifOpen ? 'block' : 'none';
    if (_notifOpen) loadNotifications();
}

let _profileOpen = false;

function toggleProfileMenu() {
    _profileOpen = !_profileOpen;
    document.getElementById('profileMenu').style.display = _profileOpen ? 'block' : 'none';
}

function setWaAction(action, btn) {
    _waAction = action;
    document.querySelectorAll('.wa-action-btn').forEach(b => {
    b.style.background = 'var(--surface)';
    b.style.borderColor = 'var(--border)';
    b.style.color = 'var(--text2)';
    });
    btn.style.background = 'var(--accent-glow)';
    btn.style.borderColor = 'rgba(59,130,246,.4)';
    btn.style.color = 'var(--accent2)';
    document.getElementById('waLangRow').style.display = action === 'translate' ? 'block' : 'none';
}

function openWritingAssistant(text, callback) {
    _waCallback = callback || null;
    document.getElementById('waInput').value = text || '';
    document.getElementById('waResult').style.display = 'none';
    // Default to improve
    const improveBtn = document.querySelector('[data-action="improve"]');
    if (improveBtn) setWaAction('improve', improveBtn);
    openModal('writingAssistantModal');
}

async function runWritingAssist() {
    const text = document.getElementById('waInput').value.trim();
    if (!text) { toast('Please enter some text first', 'error'); return; }
    const btn = document.getElementById('waRunBtn');
    btn.disabled = true;
    btn.innerHTML = '<i class="fa-solid fa-spinner fa-spin"></i> Thinking…';

    const r = await fetch('/ai/writing/assist', {
    method:'POST', headers:{'Content-Type':'application/json'},
    body: JSON.stringify({
        text,
        action: _waAction,
        language: _waAction === 'translate' ? document.getElementById('waLang').value : null,
    }),
    });
    const d = await r.json();
    btn.disabled = false;
    btn.innerHTML = '<i class="fa-solid fa-brain"></i> Generate';

    if (!r.ok) { toast(d.error || 'AI error', 'error'); return; }
    document.getElementById('waResult').style.display = 'block';
    document.getElementById('waResultText').textContent = d.result;
    document.getElementById('waResult').scrollIntoView({behavior:'smooth', block:'nearest'});
}

function useWaResult() {
    const result = document.getElementById('waResultText').textContent;
    if (_waCallback) {
    _waCallback(result);
    } else {
    // Try to put in the active message input
    const msgInput = document.getElementById('msgInput');
    if (msgInput) msgInput.value = result;
    }
    closeModal('writingAssistantModal');
}

function copyWaResult() {
    const text = document.getElementById('waResultText').textContent;
    navigator.clipboard.writeText(text).then(() => toast('Copied!', 'success'));
}

function toggleGroup(name) {
const group = document.querySelector(`[data-group="${name}"]`);
if (!group) return;
const isOpen = group.classList.contains('open');
// Close all
document.querySelectorAll('.nav-group.open').forEach(g => g.classList.remove('open'));
// Open clicked (unless it was already open)
if (!isOpen) group.classList.add('open');
}

// Auto-open the group that contains the active child
function autoOpenActiveGroup() {
document.querySelectorAll('.nav-child.active').forEach(child => {
const group = child.closest('.nav-group');
if (group) {
    group.classList.add('open', 'has-active');
}
});
}

document.addEventListener('DOMContentLoaded', autoOpenActiveGroup);
// Show float button on messages page
if (document.getElementById('msgInput')) {
    document.getElementById('waFloatBtn').style.display = 'block';
}

document.addEventListener('click', e => {
    if (_profileOpen &&
        !document.getElementById('profileChip').contains(e.target) &&
        !document.getElementById('profileMenu').contains(e.target)) {
    _profileOpen = false;
    document.getElementById('profileMenu').style.display = 'none';
    }
});

document.addEventListener('click', e => {
    if (_notifOpen && !document.getElementById('notifBtn').contains(e.target) &&
        !document.getElementById('notifPanel').contains(e.target)) {
    _notifOpen = false;
    document.getElementById('notifPanel').style.display = 'none';
    }
});



window.addEventListener('appinstalled', () => {
    _deferredInstall = null;
    if (typeof toast !== 'undefined') toast('BOSS is installed!', 'success');
});

// Poll for new notifications every 30s
loadNotifications();
setInterval(loadNotifications, 30000);
// Initialise on load
window.addEventListener('DOMContentLoaded', initPushNotifications);
