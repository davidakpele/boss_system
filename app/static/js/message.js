

function openScheduleModal() {
  const content = document.getElementById('msgInput').value.trim();
  if (!content) { toast('Type your message first', 'error'); return; }
  document.getElementById('scheduleContent').value = content;
  // Default to 1 hour from now
  const d = new Date(Date.now() + 3600000);
  document.getElementById('scheduleTime').value = d.toISOString().slice(0, 16);
  openModal('scheduleModal');
}
 
async function confirmSchedule() {
  const content     = document.getElementById('scheduleContent').value.trim();
  const scheduledAt = document.getElementById('scheduleTime').value;
  if (!content || !scheduledAt) { toast('Content and time required', 'error'); return; }
 
  const r = await fetch('/messages/schedule', {
    method: 'POST', headers: {'Content-Type': 'application/json'},
    body: JSON.stringify({
      channel_id: currentChannelId,
      content, scheduled_at: new Date(scheduledAt).toISOString(),
    }),
  });
  if (r.ok) {
    toast('Message scheduled ✓', 'success');
    closeModal('scheduleModal');
    document.getElementById('msgInput').value = '';
    document.getElementById('msgInput').style.height = 'auto';
  } else {
    toast('Failed to schedule', 'error');
  }
}
 
async function loadScheduled() {
  if (!currentChannelId) return;
  const r = await fetch(`/messages/scheduled?channel_id=${currentChannelId}`);
  const items = await r.json();
  const list = document.getElementById('scheduledList');
  if (!items.length) {
    list.innerHTML = '<div style="padding:20px;text-align:center;color:var(--text3);font-size:12.5px;">No scheduled messages</div>';
    return;
  }
  list.innerHTML = items.map(s => {
    const dt = new Date(s.scheduled_at).toLocaleString([], {
      month: 'short', day: 'numeric', hour: '2-digit', minute: '2-digit'
    });
    return `<div style="display:flex;gap:10px;align-items:flex-start;padding:10px 0;border-bottom:1px solid var(--border);">
      <div style="flex:1;">
        <div style="font-size:13px;color:var(--text);margin-bottom:3px;">${escHtml(s.content)}</div>
        <div style="font-size:11px;color:var(--text3);font-family:monospace;">📅 ${dt}</div>
      </div>
      <button class="btn btn-ghost btn-xs" onclick="cancelScheduled(${s.id}, this)" style="color:var(--red);flex-shrink:0;">
        <i class="fa-solid fa-xmark"></i>
      </button>
    </div>`;
  }).join('');
}
 
async function cancelScheduled(id, btn) {
  btn.disabled = true;
  const r = await fetch(`/messages/scheduled/${id}`, { method: 'DELETE' });
  if (r.ok) { toast('Cancelled', 'info'); loadScheduled(); }
  else btn.disabled = false;
}
 
function openScheduledPanel() {
  openModal('scheduledModal');
  loadScheduled();
}
 
 
// ══════════════════════════════════════════════════════════════════════════════
//  9. PINNED MESSAGES
// ══════════════════════════════════════════════════════════════════════════════
 
async function pinMessage(msgId) {
  const r = await fetch(`/messages/${msgId}/pin`, { method: 'POST' });
  const d = await r.json();
  toast(d.status === 'pinned' ? '📌 Message pinned' : 'Unpinned', 'success');
}
 
async function loadPinned() {
  if (!currentChannelId) return;
  const r = await fetch(`/messages/channel/${currentChannelId}/pinned`);
  const pins = await r.json();
  const list = document.getElementById('pinnedList');
  const badge = document.getElementById('pinnedCountBadge');
  if (badge) { badge.textContent = pins.length || ''; badge.style.display = pins.length ? 'inline' : 'none'; }
  if (!pins.length) {
    list.innerHTML = '<div style="padding:20px;text-align:center;color:var(--text3);font-size:12.5px;">No pinned messages</div>';
    return;
  }
  list.innerHTML = pins.map(p => `
    <div style="display:flex;gap:10px;align-items:flex-start;padding:10px 0;border-bottom:1px solid var(--border);">
      <div class="msg-av" style="background:${p.avatar_color};width:26px;height:26px;font-size:8px;flex-shrink:0;">${getInitials(p.sender_name)}</div>
      <div style="flex:1;min-width:0;">
        <div style="font-size:11px;font-weight:700;color:var(--text3);margin-bottom:2px;">${escHtml(p.sender_name)}</div>
        <div style="font-size:13px;color:var(--text);white-space:nowrap;overflow:hidden;text-overflow:ellipsis;">${escHtml(p.content || '[file]')}</div>
      </div>
      <button onclick="jumpToMessage(${p.message_id})" class="btn btn-ghost btn-xs" style="flex-shrink:0;">View</button>
    </div>`).join('');
}
 
function openPinnedPanel() {
  openModal('pinnedModal');
  loadPinned();
}
 
// Handle pin_update from WebSocket
function applyPinUpdate(data) {
  toast(data.action === 'pinned'
    ? `📌 ${data.pinned_by} pinned a message`
    : `${data.pinned_by} unpinned a message`, 'info');
  loadPinned();
}
 
 
// ══════════════════════════════════════════════════════════════════════════════
//  10. MESSAGE EDIT
// ══════════════════════════════════════════════════════════════════════════════
 
let editingMsgId = null;
 
function startEdit(msgId) {
  const wrap = document.querySelector(`[data-msg-id="${msgId}"]`);
  const bubble = wrap?.querySelector('.msg-bubble');
  if (!bubble) return;
 
  editingMsgId = msgId;
  const current = wrap.dataset.content || '';
  const input = document.getElementById('msgInput');
  input.value = current;
  input.focus();
  input.style.height = 'auto';
  input.style.height = Math.min(input.scrollHeight, 120) + 'px';
 
  // Show edit indicator
  document.getElementById('replyBarSender').textContent = '✏️ Editing message';
  document.getElementById('replyBarText').textContent = current.slice(0, 80);
  document.getElementById('replyBar').classList.add('visible');
}
 
async function submitEdit() {
  const content = document.getElementById('msgInput').value.trim();
  if (!content || !editingMsgId) return;
 
  const r = await fetch(`/messages/${editingMsgId}/edit`, {
    method: 'POST', headers: {'Content-Type': 'application/json'},
    body: JSON.stringify({ content }),
  });
  if (r.ok) {
    clearEdit();
  } else {
    toast('Could not edit message', 'error');
  }
}
 
function clearEdit() {
  editingMsgId = null;
  document.getElementById('msgInput').value = '';
  document.getElementById('msgInput').style.height = 'auto';
  clearReply();
}
 
function applyMessageEdit(data) {
  const wrap = document.querySelector(`[data-msg-id="${data.message_id}"]`);
  if (!wrap) return;
  const bubble = wrap.querySelector('.msg-bubble');
  if (bubble) {
    bubble.innerHTML = renderContent(data.new_content) +
      `<span style="font-size:9.5px;color:var(--text3);margin-left:6px;opacity:.7;">(edited)</span>`;
  }
  wrap.dataset.content = data.new_content;
  wrap.dataset.preview = data.new_content;
}
 
// Hook send button to check if editing
const _origSend = sendMessage;
window.sendMessage = async function() {
  if (editingMsgId) { await submitEdit(); return; }
  await _origSend();
};
 
// Add message_edited handler to handleWsMessage
const _origWsHandler = handleWsMessage;
window.handleWsMessage = function(data) {
  if (data.type === 'message_edited') { applyMessageEdit(data); return; }
  if (data.type === 'pin_update') { applyPinUpdate(data); return; }
  _origWsHandler(data);
};
 
 
// ══════════════════════════════════════════════════════════════════════════════
//  11 & 12. GROUP AUDIO/VIDEO CALLS + SCREEN SHARING (WebRTC)
// ══════════════════════════════════════════════════════════════════════════════
 

async function startCall(type) {
  if (!currentChannelId) { toast('Open a channel or DM first', 'error'); return; }
  if (callActive)         { toast('Already in a call', 'error'); return; }
 
  callType      = type;
  callChannelId = currentChannelId;
  callActive    = true;
 
  try {
    localStream = await navigator.mediaDevices.getUserMedia({
      audio: true,
      video: type === 'video',
    });
  } catch(e) {
    toast('Camera/Microphone access denied', 'error');
    callActive = false;
    return;
  }
 
  // Show the call UI in "calling…" state
  showCallUI(type, 'calling');
 
  // Start ringing on caller's side (outgoing ring tone)
  startRinging('outgoing');
 
  // Signal everyone in the channel
  if (ws && ws.readyState === WebSocket.OPEN) {
    ws.send(JSON.stringify({
      type:        'call_start',
      call_type:   type,
      channel_id:  callChannelId,
      caller_name: ME.name,
      caller_color: ME.color,
    }));
  }
 
  // Auto-cancel if nobody answers in 45 seconds
  setTimeout(() => {
    if (callActive && Object.keys(peerConnections).length === 0) {
      toast('No answer', 'info');
      endCall();
    }
  }, 45000);
}
 

function showIncomingCall(data) {
  // Remove any existing incoming call banner
  document.getElementById('incomingCallBanner')?.remove();
 
  const banner = document.createElement('div');
  banner.id = 'incomingCallBanner';
  banner.style.cssText = `
    position:fixed;bottom:24px;right:24px;z-index:9999;
    background:var(--sidebar-bg);color:#fff;
    border-radius:16px;padding:18px 20px;
    box-shadow:0 8px 40px rgba(0,0,0,0.5);
    min-width:280px;max-width:320px;
    animation:slideUp .25s cubic-bezier(0.34,1.56,0.64,1);
    border:1px solid rgba(255,255,255,0.1);`;
 
  banner.innerHTML = `
    <style>@keyframes slideUp{from{transform:translateY(30px);opacity:0}to{transform:translateY(0);opacity:1}}</style>
    <div style="display:flex;align-items:center;gap:12px;margin-bottom:14px;">
      <div style="width:42px;height:42px;border-radius:50%;background:${data.caller_color||'#6366f1'};
           display:flex;align-items:center;justify-content:center;font-weight:700;font-size:14px;flex-shrink:0;">
        ${getInitials(data.caller_name)}
      </div>
      <div>
        <div style="font-weight:700;font-size:14px;">${escHtml(data.caller_name)}</div>
        <div style="font-size:12px;color:#a1a1aa;">
          Incoming ${data.call_type === 'video' ? '📹 Video' : '🎙️ Audio'} Call…
        </div>
      </div>
    </div>
    <div style="display:flex;gap:10px;">
      <button onclick="rejectCall(${data.caller_id})"
        style="flex:1;padding:10px;border-radius:10px;border:none;background:#dc2626;
               color:#fff;font-weight:700;cursor:pointer;font-size:13px;">
        <i class="fa-solid fa-phone-slash"></i> Decline
      </button>
      <button onclick="acceptCall(${data.caller_id}, '${data.call_type}')"
        style="flex:1;padding:10px;border-radius:10px;border:none;background:#25d366;
               color:#fff;font-weight:700;cursor:pointer;font-size:13px;">
        <i class="fa-solid fa-phone"></i> Accept
      </button>
    </div>`;
 
  document.body.appendChild(banner);
 
  // Ring on receiver's side
  startRinging('incoming');
 
  // Auto-dismiss after 45 seconds
  setTimeout(() => {
    banner.remove();
    stopRinging();
  }, 45000);
}
 
async function acceptCall(callerId, type) {
  document.getElementById('incomingCallBanner')?.remove();
  stopRinging();
 
  callType   = type;
  callActive = true;
 
  try {
    localStream = await navigator.mediaDevices.getUserMedia({
      audio: true,
      video: type === 'video',
    });
  } catch(e) {
    toast('Media access denied', 'error');
    callActive = false;
    return;
  }
 
  showCallUI(type, 'connected');
  startCallTimer();
 
  // Create peer connection and send offer to caller
  await createPeerConnection(callerId, true);
}

 
function rejectCall(callerId) {
  document.getElementById('incomingCallBanner')?.remove();
  stopRinging();
  if (ws && ws.readyState === WebSocket.OPEN) {
    ws.send(JSON.stringify({
      type: 'call_reject',
      target_user_id: callerId,
    }));
  }
}

async function createPeerConnection(remoteUserId, createOffer) {
  const pc = new RTCPeerConnection(ICE_SERVERS);
  peerConnections[remoteUserId] = pc;
 
  // Add local tracks
  if (localStream) {
    localStream.getTracks().forEach(track => pc.addTrack(track, localStream));
  }
 
  // When remote track arrives → show in UI
  pc.ontrack = (e) => {
    addRemoteStream(remoteUserId, e.streams[0]);
    // Call is live — update UI status
    document.getElementById('callStatusLabel').textContent = 'Connected';
    document.getElementById('callStatusDot').style.background = '#25d366';
    stopRinging();
    startCallTimer();
  };
 
  // ICE candidates → forward via WS
  pc.onicecandidate = (e) => {
    if (e.candidate && ws && ws.readyState === WebSocket.OPEN) {
      ws.send(JSON.stringify({
        type:           'ice_candidate',
        candidate:      e.candidate,
        target_user_id: remoteUserId,
      }));
    }
  };
 
  pc.onconnectionstatechange = () => {
    if (['disconnected','failed','closed'].includes(pc.connectionState)) {
      removeRemoteStream(remoteUserId);
    }
  };
 
  if (createOffer) {
    const offer = await pc.createOffer({ offerToReceiveAudio: true, offerToReceiveVideo: callType === 'video' });
    await pc.setLocalDescription(offer);
    ws.send(JSON.stringify({
      type:           'call_offer',
      offer:          pc.localDescription,
      target_user_id: remoteUserId,
    }));
  }
 
  return pc;
}

async function joinCall(remoteUserId, offer) {
  if (!localStream) {
    try {
      localStream = await navigator.mediaDevices.getUserMedia({
        audio: true,
        video: callType === 'video',
      });
    } catch(e) {
      toast('Media access denied', 'error');
      return;
    }
  }
 
  const pc = new RTCPeerConnection(ICE_SERVERS);
  peerConnections[remoteUserId] = pc;
 
  localStream.getTracks().forEach(track => pc.addTrack(track, localStream));
 
  pc.ontrack = (e) => {
    addRemoteStream(remoteUserId, e.streams[0]);
  };
 
  pc.onicecandidate = (e) => {
    if (e.candidate && ws && ws.readyState === WebSocket.OPEN) {
      ws.send(JSON.stringify({
        type: 'ice_candidate',
        candidate: e.candidate,
        target_user_id: remoteUserId,
      }));
    }
  };
 
  if (offer) {
    await pc.setRemoteDescription(new RTCSessionDescription(offer));
    const answer = await pc.createAnswer();
    await pc.setLocalDescription(answer);
    ws.send(JSON.stringify({
      type: 'call_answer',
      answer: pc.localDescription,
      target_user_id: remoteUserId,
    }));
  } else {
    const offer = await pc.createOffer();
    await pc.setLocalDescription(offer);
    ws.send(JSON.stringify({
      type: 'call_offer',
      offer: pc.localDescription,
      target_user_id: remoteUserId,
    }));
  }
}
 
function addRemoteStream(userId, stream) {
  const container = document.getElementById('remoteVideos');
  if (!container) return;
  let vid = document.getElementById(`rv-${userId}`);
  if (!vid) {
    vid = document.createElement('video');
    vid.id = `rv-${userId}`;
    vid.autoplay = true;
    vid.playsInline = true;
    vid.style.cssText = 'width:100%;max-width:300px;border-radius:10px;background:#111;';
    container.appendChild(vid);
  }
  vid.srcObject = stream;
}
 
async function startScreenShare() {
  if (!callActive) { toast('Start a call first', 'error'); return; }
  try {
    screenStream = await navigator.mediaDevices.getDisplayMedia({
      video: true, audio: false,
    });
    const screenTrack = screenStream.getVideoTracks()[0];
 
    // Replace video track in all peer connections
    Object.values(peerConnections).forEach(pc => {
      const sender = pc.getSenders().find(s => s.track?.kind === 'video');
      if (sender) sender.replaceTrack(screenTrack);
    });
 
    // Show local screen preview
    const localVid = document.getElementById('localVideo');
    if (localVid) localVid.srcObject = screenStream;
 
    document.getElementById('screenShareBtn').innerHTML = '<i class="fa-solid fa-stop"></i> Stop Sharing';
    document.getElementById('screenShareBtn').onclick = stopScreenShare;
    toast('Screen sharing started', 'success');
 
    screenTrack.onended = stopScreenShare;
  } catch(e) {
    if (e.name !== 'NotAllowedError') toast('Screen share failed', 'error');
  }
}
 
async function stopScreenShare() {
  if (!screenStream) return;
  screenStream.getTracks().forEach(t => t.stop());
  screenStream = null;
 
  // Restore camera track
  const camTrack = localStream?.getVideoTracks()[0];
  if (camTrack) {
    Object.values(peerConnections).forEach(pc => {
      const sender = pc.getSenders().find(s => s.track?.kind === 'video');
      if (sender) sender.replaceTrack(camTrack);
    });
  }
 
  const localVid = document.getElementById('localVideo');
  if (localVid && localStream) localVid.srcObject = localStream;
 
  document.getElementById('screenShareBtn').innerHTML = '<i class="fa-solid fa-desktop"></i> Share Screen';
  document.getElementById('screenShareBtn').onclick = startScreenShare;
  toast('Screen sharing stopped', 'info');
}
 
function toggleMute() {
  if (!localStream) return;
  const audio = localStream.getAudioTracks()[0];
  if (audio) {
    audio.enabled = !audio.enabled;
    const btn = document.getElementById('muteBtn');
    btn.innerHTML = audio.enabled
      ? '<i class="fa-solid fa-microphone"></i>'
      : '<i class="fa-solid fa-microphone-slash"></i>';
    btn.style.background = audio.enabled ? 'var(--bg2)' : 'var(--red)';
  }
}
 
function toggleVideo() {
  if (!localStream) return;
  const video = localStream.getVideoTracks()[0];
  if (video) {
    video.enabled = !video.enabled;
    const btn = document.getElementById('videoToggleBtn');
    btn.innerHTML = video.enabled
      ? '<i class="fa-solid fa-video"></i>'
      : '<i class="fa-solid fa-video-slash"></i>';
    btn.style.background = video.enabled ? 'var(--bg2)' : 'var(--red)';
  }
}
 
function endCall() {
  Object.values(peerConnections).forEach(pc => pc.close());
  peerConnections = {};
  if (localStream) { localStream.getTracks().forEach(t => t.stop()); localStream = null; }
  if (screenStream) { screenStream.getTracks().forEach(t => t.stop()); screenStream = null; }
  callActive = false;
  callChannelId = null;
 
  if (ws && ws.readyState === WebSocket.OPEN) {
    ws.send(JSON.stringify({ type: 'call_end', channel_id: currentChannelId }));
  }
  closeModal('callModal');
  toast('Call ended', 'info');
}
 
function showCallUI(type) {
  const modal = document.getElementById('callModal');
  if (!modal) return;
  document.getElementById('callTypeLabel').textContent = type === 'video' ? '📹 Video Call' : '🎙️ Audio Call';
  document.getElementById('videoToggleBtn').style.display = type === 'video' ? 'flex' : 'none';
  document.getElementById('screenShareBtn').style.display = type === 'video' ? 'flex' : 'none';
  document.getElementById('localVideo').style.display = type === 'video' ? 'block' : 'none';
  modal.classList.add('open');
}
 
// Handle incoming call signals
function handleCallSignal(data) {
  switch(data.type) {
    case 'call_start':
      toast(`📞 ${data.caller_name} started a ${data.call_type} call. Click to join.`, 'info', 8000);
      callType = data.call_type;
      showCallUI(data.call_type);
      joinCall(data.caller_id, null);
      break;
    case 'call_offer':
      joinCall(data.from_user_id, data.offer);
      break;
    case 'call_answer':
      if (peerConnections[data.from_user_id]) {
        peerConnections[data.from_user_id].setRemoteDescription(new RTCSessionDescription(data.answer));
      }
      break;
    case 'ice_candidate':
      if (peerConnections[data.from_user_id]) {
        peerConnections[data.from_user_id].addIceCandidate(new RTCIceCandidate(data.candidate));
      }
      break;
    case 'call_end':
      toast('Call ended', 'info');
      endCall();
      break;
  }
}
 
// Extend the WS handler to support calls
const _origWsHandler2 = window.handleWsMessage;
window.handleWsMessage = function(data) {
  const callTypes = ['call_start','call_offer','call_answer','ice_candidate','call_end'];
  if (callTypes.includes(data.type)) { handleCallSignal(data); return; }
  _origWsHandler2(data);
};

const EMOJIS = ['👍','❤️','😂','😮','😢','🔥','👏','🎉','✅','💯','🚀','💡','👀','🙏','⚡','🤔'];

let WS_TOKEN = null, ws = null, wsReconnectTimer = null;
let currentChannelId = null, currentChatType = null, currentChatMeta = {};
let lastSenderId = null, typingTimer = null, typingUsers = {}, lastTypingSent = 0;
let replyTo = null, pendingFiles = [];
let currentThreadId = null;
let mediaRecorder = null, audioChunks = [], recordTimer = null, recordSeconds = 0;
let mentionDropdownActive = false, mentionQuery = '', mentionIndex = 0;
let searchDebounceTimer = null;
let mentionPanelOpen = false;

const readReceipts = {};
const myReadMessages = new Set();
const reactionsCache = {};

// ── EMOJI PICKER ─────────────────────────────────────────────────────────────
// Single flag that blocks the document click listener from firing on the
// same tick the picker was opened.
let emojiPickerTarget = null;
let emojiPickerJustOpened = false;

function openEmojiPicker(msgId, anchorEl) {
  const picker = document.getElementById('globalEmojiPicker');

  // If already open for this message → close it
  if (picker.classList.contains('open') && emojiPickerTarget === msgId) {
    closeEmojiPicker();
    return;
  }

  emojiPickerTarget = msgId;

  // Build emoji grid
  picker.innerHTML = EMOJIS.map(e =>
    `<div class="ep-emoji" data-emoji="${e}" title="${e}">${e}</div>`
  ).join('');

  // Attach click handlers directly on emoji elements (not on document)
  picker.querySelectorAll('.ep-emoji').forEach(el => {
  el.addEventListener('click', function(e) {
    e.stopPropagation();
    const emoji  = this.dataset.emoji;
    const target = emojiPickerTarget;  // capture before close nulls it
    closeEmojiPicker();                // close immediately
    if (!target) return;
    const fd = new FormData();
    fd.append('emoji', emoji);
    fetch(`/messages/${target}/react`, { method: 'POST', body: fd })
      .catch(() => toast('Reaction failed', 'error'));
  });
});

  // Position: measure anchor, then place picker above it
  const rect = anchorEl.getBoundingClientRect();
  picker.style.visibility = 'hidden';
  picker.style.display = 'flex';   // temporarily show to measure

  const pw = picker.offsetWidth  || 232;
  const ph = picker.offsetHeight || 160;

  // Prefer above the anchor; fall back below if not enough room
  let top = rect.top - ph - 8;
  if (top < 8) top = rect.bottom + 8;

  // Align right edge with anchor right, clamped to viewport
  let left = rect.right - pw;
  if (left < 8) left = 8;
  if (left + pw > window.innerWidth - 8) left = window.innerWidth - pw - 8;

  picker.style.top  = top  + 'px';
  picker.style.left = left + 'px';
  picker.style.visibility = '';
  picker.classList.add('open');

  // Mark as just-opened so the document listener ignores this tick
  emojiPickerJustOpened = true;
  requestAnimationFrame(() => { emojiPickerJustOpened = false; });
}

function closeEmojiPicker() {
  const picker = document.getElementById('globalEmojiPicker');
  picker.classList.remove('open');
  picker.style.display = '';
  picker.style.visibility = '';
  emojiPickerTarget = null;
}

// Close picker on any outside click (guarded by the just-opened flag)
document.addEventListener('click', function(e) {
  if (emojiPickerJustOpened) return;
  const picker = document.getElementById('globalEmojiPicker');
  if (picker.classList.contains('open') && !picker.contains(e.target)) {
    closeEmojiPicker();
  }
});

async function sendReaction(emoji) {
  const msgId = emojiPickerTarget;
  closeEmojiPicker();
  if (!msgId) return;
  const fd = new FormData();
  fd.append('emoji', emoji);
  try {
    const r = await fetch(`/messages/${msgId}/react`, { method: 'POST', body: fd });
    if (!r.ok) throw new Error('Failed');
  } catch(e) { toast('Reaction failed', 'error'); }
}

async function quickReact(emoji, msgId) {
  const fd = new FormData();
  fd.append('emoji', emoji);
  try { await fetch(`/messages/${msgId}/react`, { method: 'POST', body: fd }); } catch(e) {}
}

function applyReactionUpdate(data) {
  reactionsCache[data.message_id] = data.reactions;
  updateReactionsBar(data.message_id, data.reactions,
    document.querySelector(`#messagesList [data-msg-id="${data.message_id}"]`));
  updateReactionsBar(data.message_id, data.reactions,
    document.querySelector(`#threadMessages [data-msg-id="${data.message_id}"]`));
}

function updateReactionsBar(msgId, reactions, wrap) {
  if (!wrap) return;
  let bar = wrap.querySelector('.reactions-bar');
  if (!bar) {
    bar = document.createElement('div');
    bar.className = 'reactions-bar';
    wrap.querySelector('.msg-row')?.after(bar);
  }
  renderReactionsBar(bar, msgId, reactions);
}

function renderReactionsBar(bar, msgId, reactions) {
  if (!reactions || !reactions.length) { bar.innerHTML = ''; return; }
  bar.innerHTML = reactions.map(r =>
    `<div class="reaction-pill ${r.reacted_by_me ? 'mine' : ''}"
          data-emoji="${escAttr(r.emoji)}"
          data-msg-id="${msgId}"
          title="${r.reacted_by_me ? 'Remove' : 'React'} ${r.emoji}">
      ${r.emoji} <span class="r-count">${r.count}</span>
    </div>`
  ).join('') +
  `<div class="add-reaction-btn" data-msg-id="${msgId}" title="Add reaction">+</div>`;

  // Wire up pill clicks
  bar.querySelectorAll('.reaction-pill').forEach(pill => {
    pill.addEventListener('click', function(e) {
      e.stopPropagation();
      quickReact(this.dataset.emoji, parseInt(this.dataset.msgId));
    });
  });

  // Wire up the + button
  const addBtn = bar.querySelector('.add-reaction-btn');
  if (addBtn) {
    addBtn.addEventListener('click', function(e) {
      e.stopPropagation();
      openEmojiPicker(parseInt(this.dataset.msgId), this);
    });
  }
}
// ── END EMOJI PICKER ──────────────────────────────────────────────────────────

async function loadToken() {
  try { const r = await fetch('/auth/ws-token'); if (r.ok) { const d = await r.json(); WS_TOKEN = d.token; } } catch(e) {}
}
loadToken();



function switchTab(tab) {
  document.getElementById('tabDM').classList.toggle('active', tab === 'dm');
  document.getElementById('tabCh').classList.toggle('active', tab === 'channels');
  document.getElementById('dmPanel').style.display = tab === 'dm' ? 'block' : 'none';
  document.getElementById('channelsPanel').style.display = tab === 'channels' ? 'block' : 'none';
}
function filterConvs(q) {
  q = q.toLowerCase();
  document.querySelectorAll('.conv-item').forEach(el => {
    el.style.display = (el.dataset.name || '').toLowerCase().includes(q) ? '' : 'none';
  });
}

function openModal(id) { document.getElementById(id).classList.add('open'); }
function closeModal(id) { document.getElementById(id).classList.remove('open'); }

async function openDM(userId, name, color, isOnline) {
  setActive(`dm-item-${userId}`);
  currentChatType = 'dm';
  const av = document.getElementById('hdrAv');
  av.className = 'hdr-av'; av.style.background = color; av.style.borderRadius = '50%';
  av.textContent = getInitials(name);
  document.getElementById('hdrName').textContent = name;
  document.getElementById('hdrStatus').innerHTML = isOnline
    ? `<div class="dot-on"></div> Online` : `<div class="dot-off"></div> Offline`;
  document.getElementById('editChBtn').style.display = 'none';
  document.getElementById('msgInput').placeholder = `Message ${name}… (@ to mention)`;
  showChatUI(); clearMessages(); clearReply(); setWsStatus('connecting'); closeThread();
  try {
    const resp = await fetch(`/messages/dm/${userId}/init`);
    const data = await resp.json();
    currentChannelId = data.channel_id;
    currentChatMeta = { id: data.channel_id, name };
    data.messages.forEach(m => appendMessage(m, false));
    scrollBottom(); connectWS(data.channel_id);
    markLastRead();
  } catch(e) { toast('Could not open conversation: ' + e.message, 'error'); setWsStatus('disconnected'); }
}

async function openChannel(channelId, name, dept, createdBy) {
  setActive(`ch-item-${channelId}`); closeLeftPanel();
  currentChatType = 'channel'; currentChannelId = channelId;
  currentChatMeta = { id: channelId, name, dept, created_by: createdBy };
  const av = document.getElementById('hdrAv');
  av.className = 'hdr-av ch-av'; av.style.background = ''; av.style.borderRadius = '6px';
  av.innerHTML = '<i class="fa-solid fa-hashtag"></i>';
  document.getElementById('hdrName').textContent = '# ' + name;
  const depts = (dept || '').split(',').filter(d => d.trim());
  document.getElementById('hdrStatus').innerHTML = depts.length
    ? depts.map(d => `<span class="dept-tag">${d.trim()}</span>`).join(' ')
    : `<span style="color:var(--text3);font-size:11px;font-family:var(--msg-mono);">General</span>`;
  const canEdit = ['super_admin','admin'].includes(ME.role) || createdBy === ME.id;
  document.getElementById('editChBtn').style.display = canEdit ? 'flex' : 'none';
  document.getElementById('msgInput').placeholder = `Message #${name}… (@ to mention)`;
  showChatUI(); clearMessages(); clearReply(); setWsStatus('connecting'); closeThread();
  try {
    const resp = await fetch(`/messages/channel/${channelId}/history`);
    const msgs = await resp.json();
    msgs.forEach(m => appendMessage(m, false));
    scrollBottom();
  } catch(e) { console.error('History error', e); }
  connectWS(channelId);
  markLastRead();
}

function connectWS(channelId) {
  if (ws) { ws.onclose = null; ws.close(); ws = null; }
  clearTimeout(wsReconnectTimer);
  if (!WS_TOKEN) { wsReconnectTimer = setTimeout(() => connectWS(channelId), 500); return; }
  const proto = location.protocol === 'https:' ? 'wss' : 'ws';
  ws = new WebSocket(`${proto}://${location.host}/messages/ws/${channelId}?token=${encodeURIComponent(WS_TOKEN)}`);
  ws.onopen = () => {
    setWsStatus('connected');
    ws._ping = setInterval(() => { if (ws && ws.readyState === WebSocket.OPEN) ws.send(JSON.stringify({type:'ping'})); }, 25000);
  };
  ws.onmessage = (e) => { try { handleWsMessage(JSON.parse(e.data)); } catch(err) {} };
  ws.onerror = () => setWsStatus('disconnected');
  ws.onclose = () => {
    clearInterval(ws?._ping); setWsStatus('disconnected');
    if (currentChannelId === channelId)
      wsReconnectTimer = setTimeout(() => { if (currentChannelId === channelId) { setWsStatus('connecting'); connectWS(channelId); } }, 3000);
  };
}

function handleWsMessage(data) {
  switch(data.type) {
    case 'message':
      if (data.is_thread_reply && data.thread_id === currentThreadId) {
        appendThreadMessage(data);
        updateThreadCount(data.thread_id);
      } else if (!data.is_thread_reply) {
        appendMessage(data, true);
        markRead(data.id);
      }
      break;
    case 'typing': showTyping(data.user_id, data.user_name); break;
    case 'message_deleted': markDeleted(data.message_id); break;
    case 'reaction': applyReactionUpdate(data); break;
    case 'read_receipt': applyReadReceipt(data); break;
    case 'mention': handleMentionNotification(data); break;
  }
}

function setWsStatus(state) {
  const el = document.getElementById('wsStatus'); if (!el) return;
  el.className = `ws-status ${state}`;
  const labels = { connected:'Connected', connecting:'Connecting…', disconnected:'Offline' };
  el.innerHTML = `<i class="fa-solid fa-circle" style="font-size:5px;"></i> ${labels[state]}`;
}

async function sendMessage() {
  const input = document.getElementById('msgInput');
  const content = input.value.trim();
  if (!content && pendingFiles.length === 0) return;
  if (!ws || ws.readyState !== WebSocket.OPEN) { toast('Still connecting — please wait', 'error'); return; }
  if (pendingFiles.length > 0) {
    for (const file of pendingFiles) await uploadFile(file);
    pendingFiles = []; renderPendingFiles();
  }
  if (content) {
    const payload = { type: 'message', content };
    if (replyTo) { payload.reply_to_id = replyTo.id; payload.reply_to_sender = replyTo.sender_name; payload.reply_to_content = replyTo.content; }
    ws.send(JSON.stringify(payload));
    input.value = ''; input.style.height = 'auto'; clearReply(); closeMentionDropdown();
  }
}

async function uploadFile(file) {
  const fd = new FormData(); fd.append('file', file); fd.append('channel_id', currentChannelId);
  if (replyTo) { fd.append('reply_to_id', replyTo.id); fd.append('reply_to_sender', replyTo.sender_name); fd.append('reply_to_content', replyTo.content); }
  try { const resp = await fetch('/messages/upload', { method:'POST', body:fd }); if (!resp.ok) throw new Error('Upload failed'); }
  catch(e) { toast('File upload failed: ' + e.message, 'error'); }
}

function handleKey(e) {
  if (mentionDropdownActive) {
    if (e.key === 'ArrowDown') { e.preventDefault(); moveMentionIndex(1); return; }
    if (e.key === 'ArrowUp')   { e.preventDefault(); moveMentionIndex(-1); return; }
    if (e.key === 'Enter' || e.key === 'Tab') { e.preventDefault(); selectMention(mentionIndex); return; }
    if (e.key === 'Escape') { closeMentionDropdown(); return; }
  }
  if (e.key === 'Enter' && !e.shiftKey) { e.preventDefault(); sendMessage(); }
}
function autoResize(el) { el.style.height = 'auto'; el.style.height = Math.min(el.scrollHeight, 120) + 'px'; }
function sendTyping() {
  if (!ws || ws.readyState !== WebSocket.OPEN) return;
  const now = Date.now(); if (now - lastTypingSent > 2000) { lastTypingSent = now; ws.send(JSON.stringify({type:'typing'})); }
}
function showTyping(userId, userName) {
  if (userId === ME.id) return; typingUsers[userId] = userName; clearTimeout(typingTimer); renderTyping();
  typingTimer = setTimeout(() => { delete typingUsers[userId]; renderTyping(); }, 3000);
}
function renderTyping() {
  const names = Object.values(typingUsers); const el = document.getElementById('typingBar');
  if (!names.length) { el.innerHTML = ''; return; }
  el.innerHTML = `<div class="typing-dots"><span></span><span></span><span></span></div>&nbsp;${names.join(', ')} ${names.length===1?'is':'are'} typing…`;
}

function handleFileSelect(files) { for (const f of files) pendingFiles.push(f); renderPendingFiles(); document.getElementById('fileInput').value = ''; }
function renderPendingFiles() {
  const strip = document.getElementById('filePendingStrip');
  if (!pendingFiles.length) { strip.innerHTML = ''; strip.classList.remove('visible'); return; }
  strip.classList.add('visible');
  strip.innerHTML = pendingFiles.map((f,i) => `<div class="pending-file"><i class="fa-solid ${fileIcon(f.name)}" style="font-size:10px;color:var(--text3);"></i><span class="pending-file-name">${escHtml(f.name)}</span><button class="pending-remove" onclick="removePending(${i})"><i class="fa-solid fa-xmark"></i></button></div>`).join('');
}
function removePending(idx) { pendingFiles.splice(idx,1); renderPendingFiles(); }

function setReply(msgId, senderName, content) {
  replyTo = { id: msgId, sender_name: senderName, content };
  document.getElementById('replyBarSender').textContent = 'Replying to ' + senderName;
  document.getElementById('replyBarText').textContent = content;
  document.getElementById('replyBar').classList.add('visible');
  document.getElementById('msgInput').focus();
}
function clearReply() { replyTo = null; document.getElementById('replyBar').classList.remove('visible'); }

async function deleteMessage(msgId) {
  if (!confirm('Delete this message?')) return;
  try {
    const resp = await fetch(`/messages/${msgId}/delete`, { method:'POST' });
    if (resp.ok) {
      markDeleted(msgId);
      if (ws && ws.readyState === WebSocket.OPEN) ws.send(JSON.stringify({ type:'delete', message_id: msgId }));
    } else toast('Could not delete message', 'error');
  } catch(e) { toast('Error: ' + e.message, 'error'); }
}
function markDeleted(msgId) {
  document.querySelectorAll(`[data-msg-id="${msgId}"]`).forEach(el => {
    const bubble = el.querySelector('.msg-bubble');
    if (bubble) { bubble.className = 'msg-bubble deleted'; bubble.innerHTML = '<i class="fa-solid fa-ban" style="margin-right:6px;opacity:0.4;"></i>This message was deleted'; }
    const actions = el.querySelector('.msg-actions'); if (actions) actions.remove();
  });
}

// ── SEARCH ──
let searchVisible = false;

function toggleSearch() {
  searchVisible = !searchVisible;
  const bar = document.getElementById('chatSearchBar');
  const panel = document.getElementById('searchResultsPanel');
  bar.style.display = searchVisible ? 'flex' : 'none';
  if (!searchVisible) { panel.classList.remove('open'); document.getElementById('chatSearchInput').value = ''; }
  else document.getElementById('chatSearchInput').focus();
}

function closeSearch() { searchVisible = false; document.getElementById('chatSearchBar').style.display = 'none'; document.getElementById('searchResultsPanel').classList.remove('open'); }

function debounceSearch(q) {
  clearTimeout(searchDebounceTimer);
  if (!q.trim()) { document.getElementById('searchResultsPanel').classList.remove('open'); return; }
  searchDebounceTimer = setTimeout(() => runSearch(q), 350);
}

function searchKeydown(e) { if (e.key === 'Escape') closeSearch(); }

async function runSearch(q) {
  if (!currentChannelId) return;
  try {
    const r = await fetch(`/messages/search?channel_id=${currentChannelId}&q=${encodeURIComponent(q)}`);
    const data = await r.json();
    renderSearchResults(data.results, q);
  } catch(e) {}
}

function renderSearchResults(results, q) {
  const panel = document.getElementById('searchResultsPanel');
  const header = document.getElementById('searchResultsHeader');
  const list = document.getElementById('searchResultsList');
  panel.classList.add('open');
  header.textContent = results.length ? `${results.length} result${results.length===1?'':'s'} for "${q}"` : `No results for "${q}"`;
  list.innerHTML = results.map(m => {
    const hl = highlightText(m.content, q);
    const time = m.created_at ? new Date(m.created_at).toLocaleString([], {month:'short', day:'numeric', hour:'2-digit', minute:'2-digit'}) : '';
    return `<div class="search-result-item" onclick="jumpToMessage(${m.id})">
      <div class="sr-sender">${escHtml(m.sender_name)}</div>
      <div class="sr-content">${hl}</div>
      <div class="sr-time">${time}</div>
    </div>`;
  }).join('') || '<div style="padding:32px;text-align:center;color:var(--text3);font-size:13px;">No messages found</div>';
}

function highlightText(text, q) {
  const esc = q.replace(/[.*+?^${}()|[\]\\]/g, '\\$&');
  return escHtml(text).replace(new RegExp(`(${esc})`, 'gi'), '<span class="sr-hl">$1</span>');
}

function jumpToMessage(msgId) {
  closeSearch();
  const el = document.querySelector(`#messagesList [data-msg-id="${msgId}"]`);
  if (el) {
    el.scrollIntoView({ behavior:'smooth', block:'center' });
    el.classList.add('search-result');
    setTimeout(() => el.classList.remove('search-result'), 2000);
  }
}

// ── VOICE NOTES ──
function toggleRecording() {
  if (mediaRecorder && mediaRecorder.state === 'recording') stopAndSendRecording();
  else startRecording();
}

async function startRecording() {
  try {
    const stream = await navigator.mediaDevices.getUserMedia({ audio: true });
    audioChunks = []; recordSeconds = 0;
    mediaRecorder = new MediaRecorder(stream, { mimeType: getSupportedMimeType() });
    mediaRecorder.ondataavailable = e => { if (e.data.size > 0) audioChunks.push(e.data); };
    mediaRecorder.start(100);
    document.getElementById('voiceBtn').classList.add('recording');
    document.getElementById('recordBar').classList.add('visible');
    recordTimer = setInterval(() => {
      recordSeconds++;
      const m = String(Math.floor(recordSeconds/60)).padStart(1,'0');
      const s = String(recordSeconds%60).padStart(2,'0');
      document.getElementById('recordTime').textContent = `${m}:${s}`;
      if (recordSeconds >= 120) stopAndSendRecording();
    }, 1000);
  } catch(e) { toast('Microphone access denied', 'error'); }
}

function getSupportedMimeType() {
  for (const t of ['audio/webm;codecs=opus','audio/webm','audio/ogg;codecs=opus','audio/mp4'])
    if (MediaRecorder.isTypeSupported(t)) return t;
  return '';
}

function cancelRecording() {
  if (!mediaRecorder) return;
  clearInterval(recordTimer); mediaRecorder.stop();
  mediaRecorder.stream?.getTracks().forEach(t => t.stop());
  mediaRecorder = null; audioChunks = [];
  document.getElementById('voiceBtn').classList.remove('recording');
  document.getElementById('recordBar').classList.remove('visible');
}

async function stopAndSendRecording() {
  if (!mediaRecorder || mediaRecorder.state !== 'recording') return;
  clearInterval(recordTimer);
  const duration = recordSeconds;
  await new Promise(resolve => { mediaRecorder.onstop = resolve; mediaRecorder.stop(); });
  mediaRecorder.stream?.getTracks().forEach(t => t.stop());
  document.getElementById('voiceBtn').classList.remove('recording');
  document.getElementById('recordBar').classList.remove('visible');

  const mime = audioChunks[0]?.type || 'audio/webm';
  const blob = new Blob(audioChunks, { type: mime });
  const ext = mime.includes('ogg') ? 'ogg' : mime.includes('mp4') ? 'mp4' : 'webm';
  const file = new File([blob], `voice.${ext}`, { type: mime });

  const fd = new FormData(); fd.append('file', file); fd.append('channel_id', currentChannelId); fd.append('duration', duration);
  try {
    const r = await fetch('/messages/voice', { method:'POST', body:fd });
    if (!r.ok) throw new Error('Upload failed');
  } catch(e) { toast('Voice note upload failed', 'error'); }
  mediaRecorder = null; audioChunks = [];
}

function buildVoicePlayer(msg) {
  const url = absoluteUrl(msg.file_url);
  const dur = msg.voice_duration || 0;
  const id = `vp-${msg.id}`;
  return `<div class="voice-player" id="${id}">
    <button class="voice-play-btn" onclick="toggleVoicePlay('${id}')" title="Play">
      <i class="fa-solid fa-play" id="${id}-icon"></i>
    </button>
    <div class="voice-waveform" onclick="seekVoice('${id}',event)">
      <svg class="waveform-svg" viewBox="0 0 200 28" preserveAspectRatio="none">${generateWaveform()}</svg>
    </div>
    <span class="voice-time" id="${id}-time">${dur ? formatDur(dur) : '0:00'}</span>
    <audio id="${id}-audio" src="${url}" style="display:none;" onended="voiceEnded('${id}')" ontimeupdate="voiceTimeUpdate('${id}')"></audio>
  </div>`;
}

function generateWaveform() {
  let bars = '';
  for (let i = 0; i < 40; i++) {
    const h = 4 + Math.random() * 20;
    const y = (28 - h) / 2;
    bars += `<rect x="${i*5}" y="${y}" width="3" rx="1.5" height="${h}" fill="currentColor" opacity="0.35"/>`;
  }
  return bars;
}

function toggleVoicePlay(id) {
  const audio = document.getElementById(`${id}-audio`);
  const icon  = document.getElementById(`${id}-icon`);
  if (!audio) return;
  if (audio.paused) { audio.play(); icon.className = 'fa-solid fa-pause'; }
  else              { audio.pause(); icon.className = 'fa-solid fa-play'; }
}
function voiceEnded(id) {
  const icon  = document.getElementById(`${id}-icon`);  if (icon)  icon.className = 'fa-solid fa-play';
  const timeEl = document.getElementById(`${id}-time`);
  const audio  = document.getElementById(`${id}-audio`);
  if (audio && timeEl) timeEl.textContent = formatDur(audio.duration || 0);
}
function voiceTimeUpdate(id) {
  const audio  = document.getElementById(`${id}-audio`);
  const timeEl = document.getElementById(`${id}-time`);
  if (!audio || !timeEl) return;
  timeEl.textContent = formatDur(audio.currentTime);
}
function seekVoice(id, e) {
  const audio = document.getElementById(`${id}-audio`); if (!audio || !audio.duration) return;
  const rect = e.currentTarget.getBoundingClientRect();
  audio.currentTime = ((e.clientX - rect.left) / rect.width) * audio.duration;
}
function formatDur(s) { s = Math.floor(s||0); return `${Math.floor(s/60)}:${String(s%60).padStart(2,'0')}`; }

// ── READ RECEIPTS ──
function markRead(msgId) {
  if (myReadMessages.has(msgId) || !ws || ws.readyState !== WebSocket.OPEN) return;
  myReadMessages.add(msgId);
  ws.send(JSON.stringify({ type: 'read', message_id: msgId }));
}
function markLastRead() {
  setTimeout(() => {
    const msgs = document.querySelectorAll('#messagesList [data-msg-id]');
    if (msgs.length) markRead(parseInt(msgs[msgs.length - 1].dataset.msgId));
  }, 800);
}
function applyReadReceipt(data) {
  if (!readReceipts[data.message_id]) readReceipts[data.message_id] = [];
  if (!readReceipts[data.message_id].find(r => r.user_id === data.user_id))
    readReceipts[data.message_id].push({ user_id: data.user_id, user_name: data.user_name });
  updateReceiptsUI(data.message_id);
}
function updateReceiptsUI(msgId) {
  const receipts = readReceipts[msgId] || [];
  const wrap = document.querySelector(`#messagesList [data-msg-id="${msgId}"]`);
  if (!wrap) return;
  let el = wrap.querySelector('.msg-receipts');
  if (!el) { el = document.createElement('div'); el.className = 'msg-receipts'; wrap.querySelector('.msg-row')?.after(el); }
  el.innerHTML = receipts.slice(0, 5).map(r =>
    `<div class="receipt-av" style="background:${getUserColor(r.user_id)}" title="${escHtml(r.user_name)} read">${getInitials(r.user_name)}</div>`
  ).join('');
}
function getUserColor(userId) { const u = ALL_USERS.find(u => u.id === userId); return u ? u.color : '#6366f1'; }

// ── THREADS ──
function openThread(msgId, content, senderName, color, threadCount) {
  currentThreadId = msgId;
  document.getElementById('threadParent').innerHTML = `<div style="display:flex;gap:8px;align-items:flex-start;">
    <div class="msg-av" style="background:${color};width:28px;height:28px;font-size:9px;">${getInitials(senderName)}</div>
    <div>
      <div style="font-size:11px;font-weight:700;color:var(--text3);font-family:var(--msg-mono);text-transform:uppercase;margin-bottom:4px;">${escHtml(senderName)}</div>
      <div style="font-size:13px;color:var(--text);line-height:1.5;">${renderContent(content)}</div>
    </div>
  </div>`;
  document.getElementById('threadCount').textContent = threadCount ? `${threadCount} ${threadCount===1?'reply':'replies'}` : '';
  document.getElementById('threadMessages').innerHTML = '';
  document.getElementById('threadPanel').classList.add('open');
  document.getElementById('threadInput').focus();
  loadThreadReplies(msgId);
}

async function loadThreadReplies(threadId) {
  try {
    const r = await fetch(`/messages/channel/${currentChannelId}/history?thread_id=${threadId}`);
    const msgs = await r.json();
    document.getElementById('threadMessages').innerHTML = '';
    msgs.forEach(m => appendThreadMessage(m));
  } catch(e) {}
}

function appendThreadMessage(msg) {
  const container = document.getElementById('threadMessages');
  const isMine = Number(msg.sender_id) === Number(ME.id);
  const time = msg.created_at ? new Date(msg.created_at).toLocaleTimeString([], {hour:'2-digit',minute:'2-digit'}) : '';
  const div = document.createElement('div');
  div.className = 'msg-group'; div.dataset.msgId = msg.id;
  div.innerHTML = `<div class="msg-row ${isMine?'mine':''}">
    ${!isMine ? `<div class="msg-av" style="background:${msg.avatar_color||'#6366f1'}">${getInitials(msg.sender_name)}</div>` : ''}
    <div>
      ${!isMine ? `<div class="msg-sender">${escHtml(msg.sender_name)}</div>` : ''}
      <div class="msg-bubble ${isMine?'mine':'other'}">${renderContent(msg.content)}</div>
      <div class="msg-time">${time}</div>
    </div>
    ${isMine ? `<div class="msg-av" style="background:${ME.color}">${getInitials(ME.name)}</div>` : ''}
  </div>`;
  container.appendChild(div);
  container.scrollTop = container.scrollHeight;
}

async function sendThreadReply() {
  const input = document.getElementById('threadInput');
  const content = input.value.trim(); if (!content) return;
  if (!ws || ws.readyState !== WebSocket.OPEN) { toast('Not connected', 'error'); return; }
  ws.send(JSON.stringify({ type: 'message', content, thread_id: currentThreadId }));
  input.value = '';
}
function handleThreadKey(e) { if (e.key === 'Enter' && !e.shiftKey) { e.preventDefault(); sendThreadReply(); } }
function closeThread() { document.getElementById('threadPanel').classList.remove('open'); currentThreadId = null; }

function updateThreadCount(threadId) {
  const wrap = document.querySelector(`#messagesList [data-msg-id="${threadId}"]`);
  if (!wrap) return;
  const btn = wrap.querySelector('.thread-btn');
  if (btn) {
    const cur = parseInt(btn.dataset.count || '0') + 1;
    btn.dataset.count = cur;
    btn.innerHTML = `<i class="fa-solid fa-comments"></i> ${cur} ${cur===1?'reply':'replies'}`;
  }
}

// ── @MENTIONS ──
function handleMentionInput(textarea) {
  const val = textarea.value;
  const cursor = textarea.selectionStart;
  const before = val.slice(0, cursor);
  const match = before.match(/@([\w ]*)$/);
  if (match) {
    mentionQuery = match[1].toLowerCase();
    const filtered = ALL_USERS.filter(u => u.name.toLowerCase().includes(mentionQuery)).slice(0, 6);
    if (filtered.length) { showMentionDropdown(filtered); return; }
  }
  closeMentionDropdown();
}

function showMentionDropdown(users) {
  mentionDropdownActive = true; mentionIndex = 0;
  const dd = document.getElementById('mentionDropdown');
  dd.innerHTML = users.map((u, i) => `
    <div class="mention-option ${i===0?'active':''}" data-idx="${i}" data-name="${escAttr(u.name)}" onclick="selectMention(${i})">
      <div class="mention-av" style="background:${u.color}">${getInitials(u.name)}</div>
      <div><div class="mention-name">${escHtml(u.name)}</div><div class="mention-dept">${u.dept}</div></div>
    </div>`).join('');
  dd.dataset.users = JSON.stringify(users);
  dd.classList.add('open');
}

function moveMentionIndex(dir) {
  const dd = document.getElementById('mentionDropdown');
  const items = dd.querySelectorAll('.mention-option');
  if (!items.length) return;
  items[mentionIndex]?.classList.remove('active');
  mentionIndex = (mentionIndex + dir + items.length) % items.length;
  items[mentionIndex]?.classList.add('active');
}

function selectMention(idx) {
  const dd = document.getElementById('mentionDropdown');
  const users = JSON.parse(dd.dataset.users || '[]');
  const user = users[idx]; if (!user) return;
  const input = document.getElementById('msgInput');
  const val = input.value;
  const cursor = input.selectionStart;
  const before = val.slice(0, cursor).replace(/@[\w ]*$/, '');
  const after = val.slice(cursor);
  input.value = before + `@${user.name} ` + after;
  const newPos = (before + `@${user.name} `).length;
  input.setSelectionRange(newPos, newPos);
  closeMentionDropdown(); input.focus();
}
function closeMentionDropdown() { mentionDropdownActive = false; document.getElementById('mentionDropdown').classList.remove('open'); }

function handleMentionNotification(data) {
  const badge = document.getElementById('mentionCountBadge');
  const cur = parseInt(badge.textContent || '0') + 1;
  badge.textContent = cur; badge.classList.add('visible');
  toast(`@mentioned by ${data.sender_name}`, 'info', 4000);
}

async function toggleMentionPanel() {
  mentionPanelOpen = !mentionPanelOpen;
  document.getElementById('mentionPanel').classList.toggle('open', mentionPanelOpen);
  if (mentionPanelOpen) {
    await loadMentions();
    await fetch('/messages/mentions/read-all', { method:'POST' });
    const badge = document.getElementById('mentionCountBadge');
    badge.textContent = ''; badge.classList.remove('visible');
  }
}

async function loadMentions() {
  const list = document.getElementById('mentionPanelList');
  try {
    const r = await fetch('/messages/mentions');
    const mentions = await r.json();
    if (!mentions.length) { list.innerHTML = '<div class="mention-empty">No mentions yet</div>'; return; }
    list.innerHTML = mentions.map(m => {
      const time = m.created_at ? new Date(m.created_at).toLocaleString([], {month:'short',day:'numeric',hour:'2-digit',minute:'2-digit'}) : '';
      return `<div class="mention-item ${m.is_read?'':'unread'}" onclick="jumpToMention(${m.channel_id}, ${m.message_id})">
        <div class="mention-item-sender"><i class="fa-solid fa-at" style="margin-right:4px;"></i>${escHtml(m.sender_name)}</div>
        <div class="mention-item-content">${escHtml(m.content)}</div>
        <div class="mention-item-time">${time}</div>
      </div>`;
    }).join('');
  } catch(e) { list.innerHTML = '<div class="mention-empty">Failed to load</div>'; }
}

function jumpToMention(channelId, messageId) {
  mentionPanelOpen = false;
  document.getElementById('mentionPanel').classList.remove('open');
  const chItem = document.getElementById(`ch-item-${channelId}`);
  if (chItem && currentChannelId !== channelId) { chItem.click(); setTimeout(() => { jumpToMessage(messageId); }, 800); }
  else { jumpToMessage(messageId); }
}

// ── HELPERS ──
function escHtml(s) { return (s||'').replace(/&/g,'&amp;').replace(/</g,'&lt;').replace(/>/g,'&gt;'); }
function escAttr(s) {
  return String(s||'').replace(/&/g,'&amp;').replace(/"/g,'&quot;').replace(/'/g,'&#39;').replace(/</g,'&lt;').replace(/>/g,'&gt;').replace(/\n/g,' ').replace(/\r/g,'');
}
function getInitials(n) { return (n||'?').split(' ').map(w=>w[0]).join('').slice(0,2).toUpperCase(); }

function clearMessages() { document.getElementById('messagesList').innerHTML = ''; lastSenderId = null; }

function renderContent(text) {
  if (!text) return '';
  return escHtml(text)
    .replace(/@([\w ]+)/g, (_, name) => {
      const u = ALL_USERS.find(u => u.name.toLowerCase() === name.toLowerCase());
      return u ? `<span class="mention-tag">@${escHtml(name)}</span>` : `@${escHtml(name)}`;
    })
    .replace(/\n/g, '<br>');
}

function toggleDept(el) {
  const label = el.closest ? el.closest('.dept-check') : el;
  if (!label) return;
  label.classList.toggle('selected');
  const cb = label.querySelector('input');
  if (cb) cb.checked = label.classList.contains('selected');
}

function formatMsgTime(isoStr) {
  const d = new Date(isoStr);
  const now = new Date();
  const diffDays = Math.floor((now - d) / 86400000);
  const timeStr = d.toLocaleTimeString([], {hour:'2-digit', minute:'2-digit', hour12: true});
  if (diffDays === 0) return timeStr;
  if (diffDays === 1) return `Yesterday ${timeStr}`;
  if (diffDays < 7)  return `${d.toLocaleDateString([],{weekday:'short'})} ${timeStr}`;
  return `${d.toLocaleDateString([],{month:'short',day:'numeric'})} ${timeStr}`;
}

function appendMessage(msg, scroll=true) {
  const list = document.getElementById('messagesList');
  const isMine = msg.sender_id === ME.id;
  const showHeader = msg.sender_id !== lastSenderId;
  lastSenderId = msg.sender_id;

  const time  = msg.created_at ? formatMsgTime(msg.created_at) : '';
  const color = msg.avatar_color || '#6366f1';

  let replyHtml = '';
  if (msg.reply_to_id) {
    replyHtml = `<div class="reply-quote" onclick="scrollToMsg(${msg.reply_to_id})">
      <div class="reply-quote-sender">${escHtml(msg.reply_to_sender || 'Unknown')}</div>
      <div class="reply-quote-text">${escHtml(msg.reply_to_content || '')}</div>
    </div>`;
  }

  let bodyHtml = '';
  if (msg.is_deleted) {
    bodyHtml = '<i class="fa-solid fa-ban" style="margin-right:6px;opacity:0.4;"></i>This message was deleted';
  } else if (msg.message_type === 'voice') {
    bodyHtml = replyHtml + buildVoicePlayer(msg);
  } else if (msg.file_url && msg.message_type === 'file') {
    bodyHtml = buildFileBubble(msg, replyHtml);
  } else {
    bodyHtml = replyHtml + renderContent(msg.content);
  }

  const bubbleClass = msg.is_deleted ? 'deleted' : (isMine ? 'mine' : 'other');
  const isMedia = msg.message_type === 'voice' || msg.message_type === 'file';
  const wrapClass = `msg-bubble-wrap${isMedia ? ' media-wrap' : ''}`;

  const menuId = `menu-${msg.id}`;
  const canDelete = !Boolean(msg.is_deleted) && (isMine || ['super_admin','admin'].includes(ME.role));

  // Thread button stored via data attributes — no inline string injection
  const threadBtnHtml = (!msg.is_deleted && !msg.is_thread_reply)
    ? `<div class="thread-btn"
          data-thread-msg-id="${msg.id}"
          data-thread-sender="${escAttr(msg.sender_name)}"
          data-thread-color="${escAttr(color)}"
          data-count="${msg.thread_count || 0}">
          <i class="fa-solid fa-comments"></i>
          ${msg.thread_count ? `${msg.thread_count} ${msg.thread_count===1?'reply':'replies'}` : 'Reply in thread'}
        </div>` : '';

  const actionsHtml = msg.is_deleted ? '' : `
    <button class="msg-action-trigger" data-menu="${menuId}" title="More">
      <i class="fa-solid fa-angle-down"></i>
    </button>
    <div class="msg-action-menu" id="${menuId}">
      <button class="msg-action-menu-item" data-action="reply" data-msg-id="${msg.id}">
        <i class="fa-solid fa-reply"></i> Reply
      </button>
      <button class="msg-action-menu-item" data-action="react" data-msg-id="${msg.id}">
        <i class="fa-solid fa-face-smile"></i> React
      </button>
      <button class="msg-action-menu-item" data-action="thread" data-msg-id="${msg.id}">
        <i class="fa-solid fa-comments"></i> Thread
      </button>
        <button class="msg-action-menu-item" data-action="pin" data-msg-id="${msg.id}">
            <i class="fa-solid fa-thumbtack"></i> Pin
        </button>
        <button class="msg-action-menu-item" data-action="edit" data-msg-id="${msg.id}">
            <i class="fa-solid fa-pen"></i> Edit
        </button>
      ${canDelete ? `<button class="msg-action-menu-item danger" data-action="delete" data-msg-id="${msg.id}">
        <i class="fa-solid fa-trash"></i> Delete
      </button>` : ''}
    </div>`;

  const wrap = document.createElement('div');
  wrap.className = 'msg-group';
  wrap.dataset.msgId = msg.id;
  wrap.dataset.senderName = msg.sender_name || '';
  wrap.dataset.preview = msg.message_type === 'file' ? '[file]' : (msg.content || '');
  wrap.dataset.content  = msg.content || '';

  if (isMine) {
    wrap.innerHTML = `
      <div class="msg-row mine">
        <div class="${wrapClass}" data-mine="1" style="position:relative;">
          ${actionsHtml}
          <div class="msg-bubble ${bubbleClass}">${bodyHtml}</div>
          <span class="msg-time">${time}</span>
        </div>
        ${showHeader
          ? `<div class="msg-av" style="background:${ME.color};flex-shrink:0;">${getInitials(ME.name)}</div>`
          : `<div class="spacer-av"></div>`}
      </div>
      <div class="reactions-bar" style="justify-content:flex-end;"></div>
      ${threadBtnHtml ? `<div style="display:flex;justify-content:flex-end;padding-right:34px;">${threadBtnHtml}</div>` : ''}`;
  } else {
    wrap.innerHTML = `
      <div class="msg-row">
        ${showHeader
          ? `<div class="msg-av" style="background:${color};flex-shrink:0;">${getInitials(msg.sender_name||'?')}</div>`
          : `<div class="spacer-av"></div>`}
        <div class="${wrapClass}" style="position:relative;">
          ${actionsHtml}
          ${showHeader && currentChatType === 'channel'
            ? `<div class="msg-sender">${escHtml(msg.sender_name)}</div>`
            : ''}
          <div class="msg-bubble ${bubbleClass}">${bodyHtml}</div>
          <span class="msg-time">${time}</span>
        </div>
      </div>
      <div class="reactions-bar" style="padding-left:34px;"></div>
      ${threadBtnHtml ? `<div style="padding-left:34px;">${threadBtnHtml}</div>` : ''}`;
  }

  list.appendChild(wrap);

  // Wire up all action buttons via event delegation on the wrap (no inline JS)
  wireMessageActions(wrap, msg, color);

  if (msg.reactions && msg.reactions.length) {
    reactionsCache[msg.id] = msg.reactions;
    renderReactionsBar(wrap.querySelector('.reactions-bar'), msg.id, msg.reactions);
  }
  if (readReceipts[msg.id]) updateReceiptsUI(msg.id);
  if (scroll) { scrollBottom(); markRead(msg.id); }
}

// Wire all interactive elements on a message wrap via addEventListener (no innerHTML onclick)
function wireMessageActions(wrap, msg, color) {
  // Trigger button → open/close menu
  const trigger = wrap.querySelector('.msg-action-trigger');
  const menuId  = `menu-${msg.id}`;
  if (trigger) {
    trigger.addEventListener('click', function(e) {
      e.stopPropagation();
      toggleMsgMenu(menuId, e);
    });
  }

  // Menu items
  wrap.querySelectorAll('.msg-action-menu-item').forEach(btn => {
    btn.addEventListener('click', function(e) {
      e.stopPropagation();
      const action = this.dataset.action;
      const mid    = parseInt(this.dataset.msgId);
      closeMsgMenu(menuId);

      if (action === 'reply') {
        const w = document.querySelector(`[data-msg-id="${mid}"]`);
        setReply(mid, w?.dataset.senderName || '', w?.dataset.preview || '');
      } else if (action === 'react') {
        // Open picker anchored to the trigger button (visible in DOM)
        openEmojiPicker(mid, trigger || this);
      } else if (action === 'thread') {
        const threadBtn = wrap.querySelector('.thread-btn');
        if (threadBtn) openThreadById(threadBtn);
      } else if (action === 'delete') {
        deleteMessage(mid);
      } else if (action === 'pin') {
        pinMessage(mid);
      } else if (action === 'edit') {
        startEdit(mid);
      }
    });
  });

  // Thread button
  const threadBtn = wrap.querySelector('.thread-btn');
  if (threadBtn) {
    threadBtn.addEventListener('click', function(e) {
      e.stopPropagation();
      openThreadById(this);
    });
  }
}

function openThreadById(btn) {
  if (!btn) return;
  const msgId   = parseInt(btn.dataset.threadMsgId);
  const sender  = btn.dataset.threadSender || '';
  const color   = btn.dataset.threadColor  || '#6366f1';
  const count   = parseInt(btn.dataset.count || '0');
  const wrap    = btn.closest('[data-msg-id]');
  const content = wrap ? wrap.dataset.content : '';
  openThread(msgId, content, sender, color, count);
}

// ── FILE BUBBLE ──
function absoluteUrl(url) {
  if (!url) return '';
  if (url.startsWith('http')) return url;
  return window.location.origin + url;
}

function buildFileBubble(msg, replyHtml='') {
  const fname = msg.file_name || '';
  const isImage = /\.(png|jpe?g|gif|webp|svg)$/i.test(fname) || /\.(png|jpe?g|gif|webp|svg)$/i.test(msg.file_url||'');
  const absUrl = absoluteUrl(msg.file_url);
  if (isImage) return replyHtml + `<img class="img-preview" src="${absUrl}" alt="${escAttr(fname)}" onclick="openLightbox('${escAttr(absUrl)}','${escAttr(fname)}')" onerror="this.style.display='none'"/>`;
  const icon = fileIcon(fname); const size = msg.file_size ? formatSize(msg.file_size) : '';
  return replyHtml + `<a class="file-attach" href="${absUrl}" download="${escAttr(fname||'file')}" target="_blank" rel="noopener noreferrer">
    <div class="file-icon-box"><i class="fa-solid ${icon}"></i></div>
    <div class="file-attach-info"><div class="file-attach-name">${escHtml(fname||'file')}</div>${size?`<div class="file-attach-meta">${size} · Tap to download</div>`:''}</div>
    <div class="file-attach-dl"><i class="fa-solid fa-arrow-down"></i></div>
  </a>`;
}

function fileIcon(name) {
  const ext = (name||'').split('.').pop().toLowerCase();
  const map = {pdf:'fa-file-pdf',doc:'fa-file-word',docx:'fa-file-word',xls:'fa-file-excel',xlsx:'fa-file-excel',ppt:'fa-file-powerpoint',pptx:'fa-file-powerpoint',zip:'fa-file-zipper',rar:'fa-file-zipper',mp4:'fa-file-video',mov:'fa-file-video',mp3:'fa-file-audio',wav:'fa-file-audio',png:'fa-file-image',jpg:'fa-file-image',jpeg:'fa-file-image',gif:'fa-file-image',webp:'fa-file-image',txt:'fa-file-lines',csv:'fa-file-csv',js:'fa-file-code',ts:'fa-file-code',py:'fa-file-code',html:'fa-file-code',json:'fa-file-code'};
  return map[ext] || 'fa-file';
}
function formatSize(b) { if (b<1024) return b+' B'; if (b<1048576) return (b/1024).toFixed(1)+' KB'; return (b/1048576).toFixed(1)+' MB'; }

// ── LIGHTBOX ──
function openLightbox(url, name) { document.getElementById('lightboxImg').src = url; const dl = document.getElementById('lightboxDl'); dl.href = url; dl.download = name||'image'; document.getElementById('lightbox').classList.add('open'); }
function closeLightbox() { document.getElementById('lightbox').classList.remove('open'); }
function handleLightboxClick(e) { if (e.target === document.getElementById('lightbox')) closeLightbox(); }

// ── MISC ──
function scrollToMsg(msgId) { const el = document.querySelector(`#messagesList [data-msg-id="${msgId}"]`); if (el) { el.scrollIntoView({behavior:'smooth',block:'center'}); el.style.background='rgba(37,99,235,0.06)'; setTimeout(()=>el.style.background='',1600); } }
function scrollBottom() { const l = document.getElementById('messagesList'); l.scrollTop = l.scrollHeight; }

function showChatUI() {
  document.getElementById('emptyState').style.display = 'none';
  document.getElementById('chatHeader').style.display = 'flex';
  document.getElementById('messagesList').style.display = 'flex';
  document.getElementById('chatInputWrap').style.display = 'block';
  closeLeftPanel();
}
function setActive(id) { document.querySelectorAll('.conv-item').forEach(el=>el.classList.remove('active')); document.getElementById(id)?.classList.add('active'); }
function openLeftPanel()  { document.querySelector('.left-panel').classList.add('open'); document.getElementById('panelOverlay').classList.add('visible'); }
function closeLeftPanel() { document.querySelector('.left-panel').classList.remove('open'); document.getElementById('panelOverlay').classList.remove('visible'); }

// ── CHANNEL CRUD ──
async function createChannel() {
  const name = document.getElementById('nc-name').value.trim(); if (!name) { toast('Channel name is required','error'); return; }
  const depts = [...document.querySelectorAll('#nc-depts .selected')].map(l=>l.querySelector('input').value);
  const desc = document.getElementById('nc-desc').value; const fd = new FormData();
  fd.append('name',name); fd.append('description',desc); fd.append('departments',depts.join(','));
  const resp = await fetch('/messages/channel/create',{method:'POST',body:fd});
  if (resp.ok) { toast('Channel created!','success'); closeModal('newChannelModal'); setTimeout(()=>location.reload(),600); }
  else toast('Error creating channel','error');
}
async function joinChannel(channelId, e) {
  e.stopPropagation();
  const resp = await fetch(`/messages/channel/${channelId}/join`,{method:'POST'});
  if (resp.ok) { toast('Joined!','success'); setTimeout(()=>location.reload(),500); }
}
function openEditChannel() {
  const {id,name,dept} = currentChatMeta;
  document.getElementById('ec-id').value = id; document.getElementById('ec-name').value = name; document.getElementById('ec-desc').value = '';
  const currentDepts = (dept||'').split(',').map(d=>d.trim()).filter(Boolean);
  document.querySelectorAll('#ec-depts .dept-check').forEach(label => {
    const val = label.querySelector('input').value; const sel = currentDepts.includes(val);
    label.classList.toggle('selected',sel); label.querySelector('input').checked = sel;
  });
  openModal('editChannelModal');
}
async function saveChannel() {
  const id = document.getElementById('ec-id').value;
  const name = document.getElementById('ec-name').value.trim(); if (!name) { toast('Channel name required','error'); return; }
  const depts = [...document.querySelectorAll('#ec-depts .selected')].map(l=>l.querySelector('input').value);
  const desc = document.getElementById('ec-desc').value; const fd = new FormData();
  fd.append('name',name); fd.append('description',desc); fd.append('departments',depts.join(','));
  const resp = await fetch(`/messages/channel/${id}/update`,{method:'POST',body:fd});
  if (resp.ok) { toast('Updated!','success'); closeModal('editChannelModal'); setTimeout(()=>location.reload(),600); }
  else toast('Error updating channel','error');
}

// ── MSG CONTEXT MENU ──
let msgMenuJustOpened = false;

function toggleMsgMenu(menuId, e) {
  document.querySelectorAll('.msg-action-menu.open').forEach(m => {
    if (m.id !== menuId) m.classList.remove('open');
  });
  const menu = document.getElementById(menuId);
  if (!menu) return;
  if (menu.classList.contains('open')) { menu.classList.remove('open'); return; }

  menu.style.visibility = 'hidden';
  menu.style.position   = 'fixed';
  menu.style.top  = '-9999px';
  menu.style.left = '-9999px';
  menu.classList.add('open');

  const btn   = e.currentTarget;
  const rect  = btn.getBoundingClientRect();
  const menuW = menu.offsetWidth  || 170;
  const menuH = menu.offsetHeight || 148;

  let top  = rect.top - menuH - 6;
  if (top < 8) top = rect.bottom + 6;

  let left = rect.right - menuW;
  if (left < 8) left = 8;
  if (left + menuW > window.innerWidth - 8) left = window.innerWidth - menuW - 8;

  menu.style.top  = top  + 'px';
  menu.style.left = left + 'px';
  menu.style.visibility = '';

  msgMenuJustOpened = true;
  requestAnimationFrame(() => { msgMenuJustOpened = false; });
}

function closeMsgMenu(menuId) {
  document.getElementById(menuId)?.classList.remove('open');
}

// Close all menus on outside click
document.addEventListener('click', function() {
  if (msgMenuJustOpened) return;
  document.querySelectorAll('.msg-action-menu.open').forEach(m => m.classList.remove('open'));
});

// Auto mark-read on scroll
document.getElementById('messagesList')?.addEventListener('scroll', function() {
  if (this.scrollTop + this.clientHeight >= this.scrollHeight - 40) markLastRead();
});

// Close mention panel on outside click
document.addEventListener('click', e => {
  const panel = document.getElementById('mentionPanel');
  const btn   = document.querySelector('.mention-badge-btn');
  if (mentionPanelOpen && !panel?.contains(e.target) && !btn?.contains(e.target)) {
    mentionPanelOpen = false; panel.classList.remove('open');
  }
});

let _callSeconds = 0, _callTimerInterval = null;
 
function startCallTimer() {
  _callSeconds = 0;
  _callTimerInterval = setInterval(() => {
    _callSeconds++;
    const m = String(Math.floor(_callSeconds / 60)).padStart(2, '0');
    const s = String(_callSeconds % 60).padStart(2, '0');
    const el = document.getElementById('callTimer');
    if (el) el.textContent = `${m}:${s}`;
  }, 1000);
}
 
function stopCallTimer() {
  clearInterval(_callTimerInterval);
  _callSeconds = 0;
}


async function handleCallOffer(data) {
  const pc = await createPeerConnection(data.from_user_id, false);
  await pc.setRemoteDescription(new RTCSessionDescription(data.offer));
  const answer = await pc.createAnswer();
  await pc.setLocalDescription(answer);
  ws.send(JSON.stringify({
    type:           'call_answer',
    answer:         pc.localDescription,
    target_user_id: data.from_user_id,
  }));
}
 
async function handleCallAnswer(data) {
  const pc = peerConnections[data.from_user_id];
  if (pc) {
    await pc.setRemoteDescription(new RTCSessionDescription(data.answer));
  }
}
 
async function handleIceCandidate(data) {
  const pc = peerConnections[data.from_user_id];
  if (pc && data.candidate) {
    try {
      await pc.addIceCandidate(new RTCIceCandidate(data.candidate));
    } catch(e) {
      // Ignore — sometimes candidates arrive before remote desc
    }
  }
}
 
function addRemoteStream(userId, stream) {
  const container = document.getElementById('remoteVideos');
  if (!container) return;
  let vid = document.getElementById(`rv-${userId}`);
  if (!vid) {
    const wrapper = document.createElement('div');
    wrapper.id = `rvw-${userId}`;
    wrapper.style.cssText = 'position:relative;';
    vid = document.createElement('video');
    vid.id   = `rv-${userId}`;
    vid.autoplay = true;
    vid.playsInline = true;
    vid.style.cssText = 'width:280px;max-width:100%;border-radius:12px;background:#111;';
    wrapper.appendChild(vid);
    container.appendChild(wrapper);
  }
  vid.srcObject = stream;
  // If video-only, hide the audio icon
  document.getElementById('audioCallIcon')?.remove();
}
 
function removeRemoteStream(userId) {
  document.getElementById(`rvw-${userId}`)?.remove();
  delete peerConnections[userId];
}
 
 
// ── RINGING ───────────────────────────────────────────────────────────────────
 
function startRinging(direction) {
  stopRinging();
  // Create oscillator-based ring tone (no external file needed)
  try {
    const ctx  = new (window.AudioContext || window.webkitAudioContext)();
    const gain = ctx.createGain();
    gain.gain.setValueAtTime(0.3, ctx.currentTime);
    gain.connect(ctx.destination);
 
    ringAudio = { ctx, gain, oscillators: [], stop: function() {
      this.oscillators.forEach(o => { try { o.stop(); } catch(e){} });
      this.ctx.close();
    }};
 
    const playTone = (startTime, duration) => {
      const osc = ctx.createOscillator();
      osc.type = direction === 'incoming' ? 'sine' : 'triangle';
      osc.frequency.setValueAtTime(direction === 'incoming' ? 440 : 480, startTime);
      if (direction === 'incoming') {
        osc.frequency.setValueAtTime(480, startTime + 0.1);
        osc.frequency.setValueAtTime(440, startTime + 0.2);
      }
      osc.connect(gain);
      osc.start(startTime);
      osc.stop(startTime + duration);
      ringAudio.oscillators.push(osc);
    };
 
    // Ring pattern: tone + pause, repeat every 2 seconds
    for (let i = 0; i < 20; i++) {
      playTone(ctx.currentTime + i * 2, direction === 'incoming' ? 0.8 : 1.2);
    }
  } catch(e) {
    // AudioContext not supported — silently skip
  }
}
 
function stopRinging() {
  try { ringAudio?.stop(); } catch(e) {}
  ringAudio = null;
}
 
 
// ── SCREEN SHARING ────────────────────────────────────────────────────────────
 
async function startScreenShare() {
  if (!callActive) { toast('Start a call first', 'error'); return; }
  try {
    screenStream = await navigator.mediaDevices.getDisplayMedia({ video: true, audio: false });
    const screenTrack = screenStream.getVideoTracks()[0];
 
    Object.values(peerConnections).forEach(pc => {
      const sender = pc.getSenders().find(s => s.track?.kind === 'video');
      if (sender) sender.replaceTrack(screenTrack);
    });
 
    const localVid = document.getElementById('localVideo');
    if (localVid) localVid.srcObject = screenStream;
 
    const btn = document.getElementById('screenShareBtn');
    btn.innerHTML = '<i class="fa-solid fa-stop"></i> Stop';
    btn.style.background = 'var(--red)';
    btn.onclick = stopScreenShare;
 
    toast('Screen sharing started', 'success');
    screenTrack.onended = stopScreenShare;
  } catch(e) {
    if (e.name !== 'NotAllowedError') toast('Screen share failed', 'error');
  }
}
 
async function stopScreenShare() {
  if (!screenStream) return;
  screenStream.getTracks().forEach(t => t.stop());
  screenStream = null;
 
  const camTrack = localStream?.getVideoTracks()[0];
  if (camTrack) {
    Object.values(peerConnections).forEach(pc => {
      const sender = pc.getSenders().find(s => s.track?.kind === 'video');
      if (sender) sender.replaceTrack(camTrack);
    });
  }
 
  const localVid = document.getElementById('localVideo');
  if (localVid && localStream) localVid.srcObject = localStream;
 
  const btn = document.getElementById('screenShareBtn');
  btn.innerHTML = '<i class="fa-solid fa-desktop"></i>';
  btn.style.background = '';
  btn.onclick = startScreenShare;
}
 
// ── CALL CONTROLS ─────────────────────────────────────────────────────────────
 
function toggleMute() {
  const audio = localStream?.getAudioTracks()[0];
  if (!audio) return;
  audio.enabled = !audio.enabled;
  const btn = document.getElementById('muteBtn');
  btn.innerHTML = audio.enabled
    ? '<i class="fa-solid fa-microphone"></i>'
    : '<i class="fa-solid fa-microphone-slash"></i>';
  btn.style.background = audio.enabled ? '' : 'var(--red)';
  btn.style.color       = audio.enabled ? '' : '#fff';
}
 
function toggleVideo() {
  const video = localStream?.getVideoTracks()[0];
  if (!video) return;
  video.enabled = !video.enabled;
  const btn = document.getElementById('videoToggleBtn');
  btn.innerHTML = video.enabled
    ? '<i class="fa-solid fa-video"></i>'
    : '<i class="fa-solid fa-video-slash"></i>';
  btn.style.background = video.enabled ? '' : 'var(--red)';
  btn.style.color       = video.enabled ? '' : '#fff';
}
 
function endCall() {
  // Notify others
  if (ws && ws.readyState === WebSocket.OPEN && callChannelId) {
    ws.send(JSON.stringify({ type: 'call_end', channel_id: callChannelId }));
  }
 
  // Cleanup
  Object.entries(peerConnections).forEach(([id, pc]) => {
    try { pc.close(); } catch(e) {}
  });
  peerConnections = {};
 
  localStream?.getTracks().forEach(t => t.stop());
  localStream = null;
  screenStream?.getTracks().forEach(t => t.stop());
  screenStream = null;
 
  stopRinging();
  stopCallTimer();
 
  callActive    = false;
  callChannelId = null;
  callType      = null;
 
  document.getElementById('callModal')?.classList.remove('open');
  document.getElementById('incomingCallBanner')?.remove();
  toast('Call ended', 'info');
}
 
 
// ── CALL UI ───────────────────────────────────────────────────────────────────
 
function showCallUI(type, state) {
  const modal = document.getElementById('callModal');
  if (!modal) return;
 
  const isVideo = type === 'video';
 
  const typeLabel   = document.getElementById('callTypeLabel');
  const statusLabel = document.getElementById('callStatusLabel');
  const statusDot   = document.getElementById('callStatusDot');
  const videoBtn    = document.getElementById('videoToggleBtn');
  const screenBtn   = document.getElementById('screenShareBtn');
  const localVid    = document.getElementById('localVideo');
  const audioIcon   = document.getElementById('audioCallIcon');
 
  if (typeLabel)   typeLabel.textContent   = isVideo ? '📹 Video Call' : '🎙️ Audio Call';
  if (statusLabel) statusLabel.textContent = state === 'calling' ? 'Calling…' : 'Connecting…';
  if (statusDot)   statusDot.style.background = state === 'calling' ? 'var(--yellow)' : '#25d366';
 
  // Show/hide video controls
  if (videoBtn)  videoBtn.style.display  = isVideo ? 'flex' : 'none';
  if (screenBtn) screenBtn.style.display = isVideo ? 'flex' : 'none';
 
  // Local video preview
  if (localVid) {
    localVid.style.display = isVideo ? 'block' : 'none';
    if (isVideo && localStream) {
      localVid.srcObject = localStream;
      localVid.play().catch(() => {});
    }
  }
 
  // Audio-only icon
  if (audioIcon) audioIcon.style.display = isVideo ? 'none' : 'flex';
 
  modal.classList.add('open');
}
 
 
// ── CALL TIMER ────────────────────────────────────────────────────────────────
 
function startCallTimer() {
  callSeconds = 0;
  clearInterval(callTimerInterval);
  callTimerInterval = setInterval(() => {
    callSeconds++;
    const m = String(Math.floor(callSeconds / 60)).padStart(2, '0');
    const s = String(callSeconds % 60).padStart(2, '0');
    const el = document.getElementById('callTimer');
    if (el) el.textContent = `${m}:${s}`;
  }, 1000);
}
 
function stopCallTimer() {
  clearInterval(callTimerInterval);
  callSeconds = 0;
  const el = document.getElementById('callTimer');
  if (el) el.textContent = '00:00';
}
 
 
// ── WS CALL SIGNAL HANDLER ───────────────────────────────────────────────────
 
function handleCallSignal(data) {
  switch(data.type) {
    case 'call_start':
      // Someone is calling — show ringing banner
      showIncomingCall(data);
      break;
 
    case 'call_offer':
      // Offer from caller after we accepted
      handleCallOffer(data);
      break;
 
    case 'call_answer':
      // Answer from receiver
      handleCallAnswer(data);
      break;
 
    case 'ice_candidate':
      handleIceCandidate(data);
      break;
 
    case 'call_rejected':
      stopRinging();
      toast(`${data.rejected_by} declined the call`, 'info');
      if (Object.keys(peerConnections).length === 0) endCall();
      break;
 
    case 'call_end':
      stopRinging();
      document.getElementById('incomingCallBanner')?.remove();
      if (callActive) {
        toast(`${data.ended_by || 'Call'} ended`, 'info');
        endCall();
      }
      break;
  }
}
 
// Patch the global WS handler to include call signals
const _prevWsHandler = window.handleWsMessage;
window.handleWsMessage = function(data) {
  const callTypes = ['call_start','call_offer','call_answer','ice_candidate','call_rejected','call_end'];
  if (callTypes.includes(data.type)) {
    handleCallSignal(data);
    return;
  }
  if (typeof _prevWsHandler === 'function') _prevWsHandler(data);
};


// Extend endCall to stop timer
const _origEndCall = endCall;
window.endCall = function() { stopCallTimer(); _origEndCall(); };
const _origStartCall = startCall;
window.startCall = async function(type) { await _origStartCall(type); startCallTimer(); };