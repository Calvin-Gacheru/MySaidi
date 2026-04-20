/* ================================================================
   SAIDI — script.js
   Tasks (localStorage) · Sidebar · Chat panel + Drawer · /chat API
================================================================ */

'use strict';

/* ── CONFIG ──────────────────────────────────────────────────── */
const STORAGE_KEY = 'saidi_tasks';
const API_CHAT    = '/chat';

/* ── STATE ───────────────────────────────────────────────────── */
let tasks        = [];           // [{ id, text, done, createdAt }]
let activeFilter = 'all';        // 'all' | 'active' | 'done'
let chatHistory  = [];           // [{ role: 'user'|'assistant', content }]
let isSending    = false;        // guard: prevent double-sends
let calendarDate = new Date();   // month shown in calendar view

/* ── DOM REFS ────────────────────────────────────────────────── */
// Layout
const sidebar         = document.getElementById('sidebar');
const sidebarOverlay  = document.getElementById('sidebar-overlay');
const sidebarCloseBtn = document.getElementById('sidebar-close-btn');
const hamburgerBtn    = document.getElementById('hamburger-btn');
const dateLine        = document.getElementById('date-line');

// Tasks
const taskInput  = document.getElementById('task-input');
const addTaskBtn = document.getElementById('add-task-btn');
const taskList   = document.getElementById('task-list');
const emptyState = document.getElementById('empty-state');
const filterBtns = document.querySelectorAll('.filter-btn');

// Desktop chat panel
const chatMessages = document.getElementById('chat-messages');
const chatInput    = document.getElementById('chat-input');
const sendBtn      = document.getElementById('send-btn');

// Mobile chat drawer
const chatDrawer      = document.getElementById('chat-drawer');
const drawerBackdrop  = document.getElementById('drawer-backdrop');
const drawerMessages  = document.getElementById('drawer-messages');
const drawerChatInput = document.getElementById('drawer-chat-input');
const drawerSendBtn   = document.getElementById('drawer-send-btn');
const chatFab         = document.getElementById('chat-fab');
const topbarChatBtn   = document.getElementById('topbar-chat-btn');
const drawerCloseBtn  = document.getElementById('drawer-close-btn');
const drawerHandle    = document.getElementById('drawer-handle');


/* ================================================================
   INIT
================================================================ */
function init() {
  setDateLine();
  loadTasks();
  renderTasks();
  setSidebarCloseIcon();
  loadSettings();
  bindEvents();
}


/* ================================================================
   DATE LINE
================================================================ */
function setDateLine() {
  dateLine.textContent = new Date().toLocaleDateString('en-KE', {
    weekday: 'long',
    day:     'numeric',
    month:   'long',
  });
}


/* ================================================================
   VIEW SWITCHING
================================================================ */
const VIEW_TITLES = {
  dashboard: "Today's Tasks",
  calendar:  'Calendar',
  settings:  'Settings',
  private:   'Private',
};

function switchView(view) {
  document.querySelectorAll('.view-section').forEach(sec => {
    const active = sec.id === `view-${view}`;
    sec.classList.toggle('active', active);
    sec.setAttribute('aria-hidden', String(!active));
  });

  document.querySelectorAll('.nav-item').forEach(item => {
    item.classList.toggle('active', item.dataset.view === view);
  });

  const titleEl = document.getElementById('view-title');
  if (titleEl) titleEl.textContent = VIEW_TITLES[view] ?? view;

  const dateLine = document.getElementById('date-line');
  if (dateLine) dateLine.style.display = view === 'dashboard' ? '' : 'none';

  if (view === 'calendar') renderCalendar();

  if (window.innerWidth <= 767) closeSidebar();
}


/* ================================================================
   CALENDAR
================================================================ */
function renderCalendar() {
  const grid  = document.getElementById('cal-grid');
  const label = document.getElementById('cal-month-label');
  if (!grid || !label) return;

  const year  = calendarDate.getFullYear();
  const month = calendarDate.getMonth();
  const today = new Date();

  label.textContent = calendarDate.toLocaleDateString('en-KE', { month: 'long', year: 'numeric' });

  // Mon-start offset
  let startDow = new Date(year, month, 1).getDay();
  startDow = (startDow + 6) % 7;

  const daysInMonth     = new Date(year, month + 1, 0).getDate();
  const daysInPrevMonth = new Date(year, month, 0).getDate();
  const DAY_NAMES = ['Mon','Tue','Wed','Thu','Fri','Sat','Sun'];

  let html = DAY_NAMES.map(d => `<div class="cal-day-name">${d}</div>`).join('');

  for (let i = startDow - 1; i >= 0; i--)
    html += `<div class="cal-day other-month">${daysInPrevMonth - i}</div>`;

  for (let d = 1; d <= daysInMonth; d++) {
    const isToday = d === today.getDate() && month === today.getMonth() && year === today.getFullYear();
    html += `<div class="cal-day${isToday ? ' today' : ''}">${d}</div>`;
  }

  const totalCells = Math.ceil((startDow + daysInMonth) / 7) * 7;
  for (let d = 1; d <= totalCells - startDow - daysInMonth; d++)
    html += `<div class="cal-day other-month">${d}</div>`;

  grid.innerHTML = html;
}


/* ================================================================
   SETTINGS
================================================================ */
function loadSettings() {
  applyLightMode(localStorage.getItem('saidi_light_mode') === 'true');
}

function applyLightMode(on) {
  document.body.classList.toggle('light-mode', on);
  const btn = document.getElementById('light-mode-toggle');
  if (btn) btn.setAttribute('aria-checked', String(on));
  localStorage.setItem('saidi_light_mode', String(on));
}

function toggleLightMode() {
  applyLightMode(!document.body.classList.contains('light-mode'));
}


/* ================================================================
   SIDEBAR
================================================================ */

/** Mobile: slide in as overlay */
function openSidebar() {
  sidebar.classList.add('mobile-open');
  sidebarOverlay.classList.add('visible');
  hamburgerBtn.setAttribute('aria-expanded', 'true');
}

/** Mobile: slide back out */
function closeSidebar() {
  sidebar.classList.remove('mobile-open');
  sidebarOverlay.classList.remove('visible');
  hamburgerBtn.setAttribute('aria-expanded', 'false');
}

/** Desktop: collapse to icon-only strip */
function toggleSidebarCollapse() {
  const isNowCollapsed = sidebar.classList.toggle('collapsed');
  // Flip the arrow to show current state
  sidebarCloseBtn.textContent = isNowCollapsed ? '›' : '‹';
  sidebarCloseBtn.setAttribute('aria-label', isNowCollapsed ? 'Expand sidebar' : 'Collapse sidebar');
}

/** Set the correct icon for the sidebar-close/toggle button on load */
function setSidebarCloseIcon() {
  if (window.innerWidth > 767) {
    sidebarCloseBtn.textContent = '‹';
    sidebarCloseBtn.setAttribute('aria-label', 'Collapse sidebar');
  }
}


/* ================================================================
   CHAT DRAWER (mobile / tablet)
================================================================ */
function openChatDrawer() {
  chatDrawer.classList.add('open');
  chatDrawer.setAttribute('aria-hidden', 'false');
  drawerBackdrop.classList.add('visible');
  chatFab.style.display = 'none';
  // Focus input after the slide-up transition finishes
  setTimeout(() => drawerChatInput.focus(), 360);
}

function closeChatDrawer() {
  chatDrawer.classList.remove('open');
  chatDrawer.setAttribute('aria-hidden', 'true');
  drawerBackdrop.classList.remove('visible');
  // Only restore FAB when not on desktop (where panel is visible instead)
  if (window.innerWidth <= 1023) {
    chatFab.style.display = '';
  }
}


/* ================================================================
   TASKS
================================================================ */

/** Load tasks array from localStorage */
function loadTasks() {
  try {
    const raw = localStorage.getItem(STORAGE_KEY);
    tasks = raw ? JSON.parse(raw) : [];
  } catch {
    tasks = [];
  }
}

/** Write tasks array back to localStorage */
function saveTasks() {
  localStorage.setItem(STORAGE_KEY, JSON.stringify(tasks));
}

/** Add a new task from the input field */
function addTask() {
  const text = taskInput.value.trim();
  if (!text) return;

  tasks.unshift({            // newest at top
    id:        crypto.randomUUID(),
    text,
    done:      false,
    createdAt: Date.now(),
  });

  saveTasks();
  renderTasks();
  taskInput.value = '';
  taskInput.focus();
}

/** Toggle a task's done state */
function toggleTask(id) {
  const task = tasks.find(t => t.id === id);
  if (task) {
    task.done = !task.done;
    saveTasks();
    renderTasks();
  }
}

/** Remove a task permanently */
function deleteTask(id) {
  tasks = tasks.filter(t => t.id !== id);
  saveTasks();
  renderTasks();
}

/** Rebuild the task list DOM from current state + filter */
function renderTasks() {
  const visible = tasks.filter(t => {
    if (activeFilter === 'active') return !t.done;
    if (activeFilter === 'done')   return  t.done;
    return true;
  });

  taskList.innerHTML = '';
  emptyState.hidden  = visible.length > 0;

  visible.forEach(task => {
    const li = document.createElement('li');
    li.className   = `task-item${task.done ? ' done' : ''}`;
    li.dataset.id  = task.id;

    li.innerHTML = `
      <button
        class="task-check${task.done ? ' checked' : ''}"
        aria-label="${task.done ? 'Mark incomplete' : 'Mark complete'}"
        aria-pressed="${task.done}"
      >${task.done ? '✓' : ''}</button>

      <span class="task-text">${escapeHtml(task.text)}</span>

      <button class="task-delete" aria-label="Delete task">
        <svg width="14" height="14" viewBox="0 0 24 24" fill="none"
             stroke="currentColor" stroke-width="2.5" stroke-linecap="round">
          <line x1="18" y1="6"  x2="6"  y2="18"></line>
          <line x1="6"  y1="6"  x2="18" y2="18"></line>
        </svg>
      </button>
    `;

    li.querySelector('.task-check').addEventListener('click',  () => toggleTask(task.id));
    li.querySelector('.task-delete').addEventListener('click', () => deleteTask(task.id));

    taskList.appendChild(li);
  });
}

/** Switch the active filter tab */
function setFilter(filter) {
  activeFilter = filter;
  filterBtns.forEach(btn => {
    const on = btn.dataset.filter === filter;
    btn.classList.toggle('active', on);
    btn.setAttribute('aria-selected', on);
  });
  renderTasks();
}


/* ================================================================
   CHAT
================================================================ */

/**
 * Append a message bubble to BOTH the desktop panel and mobile drawer,
 * keeping the two containers perfectly in sync.
 *
 * Returns { panelEl, drawerEl } so callers can remove thinking bubbles.
 */
function appendMessage(role, text) {
  const panelEl  = buildBubble(role, text);
  const drawerEl = buildBubble(role, text);

  chatMessages.appendChild(panelEl);
  drawerMessages.appendChild(drawerEl);

  scrollToBottom(chatMessages);
  scrollToBottom(drawerMessages);

  return { panelEl, drawerEl };
}

/**
 * Build a single message bubble element.
 * role: 'user' | 'saidi' | 'thinking'
 */
function buildBubble(role, text) {
  const wrap = document.createElement('div');

  if (role === 'thinking') {
    wrap.className = 'message saidi thinking';
    wrap.innerHTML = `
      <div class="msg-avatar" aria-hidden="true">${saidiAvatarSvg(24)}</div>
      <div class="msg-bubble">
        Saidi is thinking
        <span class="thinking-dots" aria-hidden="true">
          <span></span><span></span><span></span>
        </span>
      </div>
    `;
    return wrap;
  }

  if (role === 'saidi') {
    wrap.className = 'message saidi';
    wrap.innerHTML = `
      <div class="msg-avatar" aria-hidden="true">${saidiAvatarSvg(24)}</div>
      <div class="msg-bubble">${formatSaidiText(text)}</div>
    `;
    return wrap;
  }

  // 'user'
  wrap.className = 'message user';
  wrap.innerHTML = `<div class="msg-bubble">${escapeHtml(text)}</div>`;
  return wrap;
}

/**
 * Build a compact, collapsible logs card from model tool actions.
 * This is shown right before Saidi's final response bubble.
 */
function buildLogsCard(actions) {
  const card = document.createElement('details');
  card.className = 'message-logs';

  const summary = document.createElement('summary');
  summary.className = 'message-logs-summary';
  summary.textContent = `Thought Process (${actions.length})`;
  card.appendChild(summary);

  const list = document.createElement('ul');
  list.className = 'message-logs-list';

  const lines = actions.map(formatActionLogLine);
  lines.forEach(line => {
    const item = document.createElement('li');
    item.className = 'message-logs-item';
    item.textContent = line;
    list.appendChild(item);
  });

  card.appendChild(list);
  return card;
}

/** Append logs card to desktop and drawer chat containers. */
function appendLogs(actions) {
  const panelCard = buildLogsCard(actions);
  const drawerCard = buildLogsCard(actions);

  chatMessages.appendChild(panelCard);
  drawerMessages.appendChild(drawerCard);

  scrollToBottom(chatMessages);
  scrollToBottom(drawerMessages);
}

/** Format one human-readable log line for a tool action. */
function formatActionLogLine(action) {
  const actionType = typeof action?.type === 'string' ? action.type : 'unknown_action';
  const taskTextRaw = action?.payload?.task_text;
  const taskText = typeof taskTextRaw === 'string' ? taskTextRaw.trim() : '';

  if (taskText) {
    return `Saidi executed ${actionType}: '${taskText}'`;
  }

  return `Saidi executed ${actionType}.`;
}

/** Inline SVG for Saidi's "S" avatar */
function saidiAvatarSvg(size) {
  const fs = Math.round(size * 0.46);
  const cy = Math.round(size * 0.66);
  return `
    <svg width="${size}" height="${size}" viewBox="0 0 ${size} ${size}" fill="none">
      <circle cx="${size/2}" cy="${size/2}" r="${size/2}" fill="#10b981"/>
      <text x="${size/2}" y="${cy}" text-anchor="middle"
            font-size="${fs}" font-weight="700" fill="#fff"
            font-family="Inter,sans-serif">S</text>
    </svg>`;
}

/** Send a message — shared by desktop + mobile inputs */
async function sendMessage(text) {
  if (!text || isSending) return;

  isSending = true;
  setInputsDisabled(true);

  // Render user bubble
  appendMessage('user', text);

  // Track history for context
  chatHistory.push({ role: 'user', content: text });

  // Show "Saidi is thinking..." with animated dots
  const { panelEl: thinkPanel, drawerEl: thinkDrawer } = appendMessage('thinking', '');

  try {
    const res = await fetch(API_CHAT, {
      method:  'POST',
      headers: { 'Content-Type': 'application/json' },
      body:    JSON.stringify({
        message:      text,
        history:      chatHistory.slice(-10),
        active_tasks: tasks.filter(t => !t.done).map(t => t.text),
      }),
    });

    if (!res.ok) throw new Error(`HTTP ${res.status}`);

    const data  = await res.json();

    // console log
    console.log("DEBUG - Received from /chat:", data);

    const hasActions = Array.isArray(data.actions) && data.actions.length > 0;
    const replyText = typeof data.reply === 'string' ? data.reply.trim() : '';
    const successMsg = hasActions ? 'Done, I have applied that update.' : '';
    const reply = replyText || successMsg || "Sorry, sir — I couldn't quite get that. Try again?";

    thinkPanel.remove();
    thinkDrawer.remove();

    if (hasActions) {
      appendLogs(data.actions);
    }

    appendMessage('saidi', reply);
    chatHistory.push({ role: 'assistant', content: reply });

    if (data.actions && data.actions.length > 0) {
      data.actions.forEach(action => {
        if (action.type === 'add_task') {
          createTaskProgrammatically(action.payload.task_text);
        } else if (action.type === 'remove_task') {
          removeTaskProgrammatically(action.payload.task_text);
        }
      });
    }

  } catch (err) {
    thinkPanel.remove();
    thinkDrawer.remove();

    const errMsg = navigator.onLine
      ? "Oops! Something went sideways on my end, Calvin. Give it another shot! 🙏"
      : "You seem to be offline, Calvin. Check your connection and try again. 📶";

    appendMessage('saidi', errMsg);
    console.error('[Saidi] chat error:', err);
  } finally {
    isSending = false;
    setInputsDisabled(false);
  }
}

/** Read desktop input and fire sendMessage */
function sendDesktop() {
  const text = chatInput.value.trim();
  if (!text) return;
  chatInput.value = '';
  sendMessage(text);
}

/** Read mobile drawer input and fire sendMessage */
function sendMobile() {
  const text = drawerChatInput.value.trim();
  if (!text) return;
  drawerChatInput.value = '';
  sendMessage(text);
}

/** Disable/re-enable all chat inputs while a request is in flight */
function setInputsDisabled(disabled) {
  chatInput.disabled       = disabled;
  drawerChatInput.disabled = disabled;
  sendBtn.disabled         = disabled;
  drawerSendBtn.disabled   = disabled;

  sendBtn.style.opacity      = disabled ? '0.5' : '';
  drawerSendBtn.style.opacity = disabled ? '0.5' : '';
}

/** Smooth-scroll a messages container to its bottom */
function scrollToBottom(el) {
  // rAF ensures DOM has been painted with the new bubble first
  requestAnimationFrame(() => { el.scrollTop = el.scrollHeight; });
}


/* ================================================================
   UTILITIES
================================================================ */

/** Escape user-supplied text to prevent XSS */
function escapeHtml(str) {
  return String(str)
    .replace(/&/g,  '&amp;')
    .replace(/</g,  '&lt;')
    .replace(/>/g,  '&gt;')
    .replace(/"/g,  '&quot;')
    .replace(/'/g,  '&#039;');
}

/**
 * Light formatting for Saidi's replies:
 *   **bold**   → <strong>
 *   \n         → <br>
 * (HTML-escaping happens first so the model can't inject tags)
 */
function formatSaidiText(text) {
  return escapeHtml(text)
    .replace(/\*\*(.*?)\*\*/g, '<strong>$1</strong>')
    .replace(/\n/g, '<br>');
}


/* ================================================================
   EVENT BINDING
================================================================ */
function bindEvents() {

  /* ── Sidebar ── */
  hamburgerBtn.addEventListener('click', openSidebar);
  sidebarOverlay.addEventListener('click', closeSidebar);

  // Same button: toggle-collapse on desktop, close overlay on mobile
  sidebarCloseBtn.addEventListener('click', () => {
    if (window.innerWidth <= 767) {
      closeSidebar();
    } else {
      toggleSidebarCollapse();
    }
  });

  // Nav items: switch view
  document.querySelectorAll('.nav-item').forEach(item => {
    item.addEventListener('click', () => switchView(item.dataset.view));
  });

  /* ── Tasks ── */
  addTaskBtn.addEventListener('click', addTask);
  taskInput.addEventListener('keydown', e => {
    if (e.key === 'Enter') addTask();
  });

  filterBtns.forEach(btn => {
    btn.addEventListener('click', () => setFilter(btn.dataset.filter));
  });

  /* ── Desktop chat ── */
  sendBtn.addEventListener('click', sendDesktop);
  chatInput.addEventListener('keydown', e => {
    if (e.key === 'Enter' && !e.shiftKey) {
      e.preventDefault();
      sendDesktop();
    }
  });

  /* ── Mobile chat drawer ── */
  chatFab.addEventListener('click',      openChatDrawer);
  topbarChatBtn.addEventListener('click', openChatDrawer);
  drawerCloseBtn.addEventListener('click', closeChatDrawer);
  drawerHandle.addEventListener('click',   closeChatDrawer);
  drawerBackdrop.addEventListener('click', closeChatDrawer);

  drawerSendBtn.addEventListener('click', sendMobile);
  drawerChatInput.addEventListener('keydown', e => {
    if (e.key === 'Enter' && !e.shiftKey) {
      e.preventDefault();
      sendMobile();
    }
  });

  /* ── Calendar navigation ── */
  document.getElementById('cal-prev')?.addEventListener('click', () => {
    calendarDate.setMonth(calendarDate.getMonth() - 1);
    renderCalendar();
  });
  document.getElementById('cal-next')?.addEventListener('click', () => {
    calendarDate.setMonth(calendarDate.getMonth() + 1);
    renderCalendar();
  });

  /* ── Settings ── */
  document.getElementById('light-mode-toggle')?.addEventListener('click', toggleLightMode);

  /* ── Ask widget ── */
  const askInput = document.getElementById('ask-input');
  const askSend  = document.getElementById('ask-send');
  if (askInput && askSend) {
    const submitAsk = () => {
      const text = askInput.value.trim();
      if (!text) return;
      askInput.value = '';
      sendMessage(text);
    };
    askSend.addEventListener('click', submitAsk);
    askInput.addEventListener('keydown', e => {
      if (e.key === 'Enter' && !e.shiftKey) { e.preventDefault(); submitAsk(); }
    });
  }

  /* ── Escape key closes any open overlay ── */
  document.addEventListener('keydown', e => {
    if (e.key !== 'Escape') return;
    closeSidebar();
    closeChatDrawer();
  });

  /* ── Resize: tidy up overlays that don't belong on the new size ── */
  window.addEventListener('resize', () => {
    if (window.innerWidth > 767) {
      // Desktop: sidebar is always in-flow, remove mobile classes
      sidebar.classList.remove('mobile-open');
      sidebarOverlay.classList.remove('visible');
      hamburgerBtn.setAttribute('aria-expanded', 'false');
      // Restore correct toggle icon
      setSidebarCloseIcon();
    }
    if (window.innerWidth > 1023) {
      // Desktop: chat panel is visible, hide drawer + FAB
      chatDrawer.classList.remove('open');
      drawerBackdrop.classList.remove('visible');
      chatFab.style.display = 'none';
    } else {
      // Tablet/mobile: show FAB if drawer is closed
      if (!chatDrawer.classList.contains('open')) {
        chatFab.style.display = '';
      }
    }
  });
}

/** Programmatically add a task from the AI */
function createTaskProgrammatically(text) {
  tasks.unshift({
    id: crypto.randomUUID(),
    text,
    done: false,
    createdAt: Date.now(),
  });
  saveTasks();
  renderTasks();
}

/** Programmatically remove a task via fuzzy text match from the AI */
function removeTaskProgrammatically(searchText) {
  const lowerSearch = searchText.toLowerCase();
  const taskIndex = tasks.findIndex(t => 
    t.text.toLowerCase().includes(lowerSearch) || 
    lowerSearch.includes(t.text.toLowerCase())
  );
  
  if (taskIndex > -1) {
    tasks.splice(taskIndex, 1);
    saveTasks();
    renderTasks();
  }
}


/* ================================================================
   PWA — Service Worker registration
================================================================ */
if ('serviceWorker' in navigator) {
  window.addEventListener('load', () => {
    navigator.serviceWorker
      .register('/sw.js')
      .catch(() => { /* SW is optional — silent fail */ });
  });
}


/* ── Kick off ─────────────────────────────────────────────────── */
document.addEventListener('DOMContentLoaded', init);
