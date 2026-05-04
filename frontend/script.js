/* ================================================================
   SAIDI — script.js
   Tasks (localStorage) · Sidebar · Chat panel + Drawer · /chat API
================================================================ */

'use strict';

/* ── CONFIG ──────────────────────────────────────────────────── */
const STORAGE_KEY = 'saidi_tasks';
const API_CHAT    = '/chat';
const API_TASKS   = '/api/tasks';
const API_TASKS_SYNC = '/api/tasks/sync';

/* ── STATE ───────────────────────────────────────────────────── */
let tasks        = [];           // [{ id, text, done, createdAt }]
let activeFilter = 'all';        // 'all' | 'active' | 'done'
let chatHistory  = [];           // [{ role: 'user'|'assistant', content }]
let isSending    = false;        // guard: prevent double-sends
let calendarDate = new Date();   // month shown in calendar view


/* ── DATA SHAPE HELPERS ─────────────────────────────────────── */
function normalizeTaskRecord(task) {
  if (typeof task === 'string') {
    const title = task.trim();
    if (!title) return null;
    return {
      id: crypto.randomUUID(),
      title,
      text: title,
      start_time: null,
      end_time: null,
      is_flexible: true,
      done: false,
      createdAt: Date.now(),
    };
  }

  if (!task || typeof task !== 'object') return null;

  const title = typeof task.title === 'string' && task.title.trim()
    ? task.title.trim()
    : (typeof task.text === 'string' ? task.text.trim() : '');

  if (!title) return null;

  const startTime = typeof task.start_time === 'string' && task.start_time.trim()
    ? task.start_time.trim()
    : null;
  const endTime = typeof task.end_time === 'string' && task.end_time.trim()
    ? task.end_time.trim()
    : null;

  return {
    id: typeof task.id === 'string' && task.id.trim() ? task.id.trim() : crypto.randomUUID(),
    title,
    text: title,
    start_time: startTime,
    end_time: endTime,
    is_flexible: typeof task.is_flexible === 'boolean' ? task.is_flexible : !(startTime || endTime),
    done: Boolean(task.done),
    createdAt: typeof task.createdAt === 'number' ? task.createdAt : Date.now(),
  };
}

function normalizeTaskList(rawTasks) {
  if (!Array.isArray(rawTasks)) return [];
  return rawTasks
    .map(normalizeTaskRecord)
    .filter(Boolean);
}

function toBackendEvent(task) {
  const normalized = normalizeTaskRecord(task);
  if (!normalized || normalized.done) return null;

  return {
    id: normalized.id,
    title: normalized.title,
    start_time: normalized.start_time,
    end_time: normalized.end_time,
    is_flexible: normalized.is_flexible,
  };
}

function toTaskApiPayload(task) {
  const normalized = normalizeTaskRecord(task);
  if (!normalized) return null;

  return {
    id: normalized.id,
    title: normalized.title,
    start_time: normalized.start_time,
    end_time: normalized.end_time,
    is_flexible: normalized.is_flexible,
    done: normalized.done,
    createdAt: normalized.createdAt,
  };
}

function readLocalTaskCache() {
  try {
    const raw = localStorage.getItem(STORAGE_KEY);
    return normalizeTaskList(raw ? JSON.parse(raw) : []);
  } catch {
    return [];
  }
}

async function fetchWithAuth(url, options = {}) {
  const token = localStorage.getItem('saidi_token');

  const headers = {
    'Content-Type': 'application/json',
    ...options.headers,
    'Authorization': `Bearer ${token}` // MUST BE BACKTICKS ` `
  };

  const response = await fetch(url, { ...options, headers });

  if (response.status === 401){
    logout();
    throw new Error("Session expired. Please log in again.");
  }

  return response;
}

async function readApiError(res) {
  try {
    const data = await res.json();
    if (typeof data?.detail === 'string' && data.detail.trim()) {
      return data.detail.trim();
    }
  } catch {
    // ignore JSON parse errors and fall through to status text
  }
  return `HTTP ${res.status}`;
}

async function fetchTasksFromBackend() {
  const res = await fetchWithAuth(API_TASKS);
  if (!res.ok) throw new Error(await readApiError(res));
  return normalizeTaskList(await res.json());
}

async function syncTasksToBackend(taskList) {
  const payloadTasks = taskList.map(toTaskApiPayload).filter(Boolean);
  const res = await fetchWithAuth(API_TASKS_SYNC, {
    method: 'POST',
    body: JSON.stringify({ tasks: payloadTasks, replace_existing: false }),
  });
  if (!res.ok) throw new Error(await readApiError(res));
  return normalizeTaskList(await res.json());
}

async function createTaskInBackend(taskPayload) {
  const res = await fetchWithAuth(API_TASKS, {
    method: 'POST',
    body: JSON.stringify(taskPayload),
  });
  if (!res.ok) throw new Error(await readApiError(res));
  return res.json();
}

async function updateTaskInBackend(taskId, patch) {
  const res = await fetchWithAuth(`${API_TASKS}/${encodeURIComponent(taskId)}`, {
    method: 'PATCH',
    body: JSON.stringify(patch),
  });
  if (!res.ok) throw new Error(await readApiError(res));
  return res.json();
}

async function deleteTaskInBackend(taskId) {
  const res = await fetchWithAuth(`${API_TASKS}/${encodeURIComponent(taskId)}`, {
    method: 'DELETE',
  });
  if (!res.ok) throw new Error(await readApiError(res));
  return res.json();
}

/* ── DOM REFS ────────────────────────────────────────────────── */
// Layout
const sidebar         = document.getElementById('sidebar');
const sidebarOverlay  = document.getElementById('sidebar-overlay');
const sidebarCloseBtn = document.getElementById('sidebar-close-btn');
const hamburgerBtn    = document.getElementById('hamburger-btn');
const dateLine        = document.getElementById('date-line');
const fontSelect      = document.getElementById('font-select');

// Tasks
const taskInput  = document.getElementById('task-input');
const addTaskBtn = document.getElementById('add-task-btn');
const taskList   = document.getElementById('task-list');
const emptyState = document.getElementById('empty-state');
const filterBtns = document.querySelectorAll('.filter-btn');

// Desktop chat panel
// const chatMessages = document.getElementById('chat-messages');
// const chatInput    = document.getElementById('chat-input');
// const sendBtn      = document.getElementById('send-btn');

// Mobile chat drawer
const chatDrawer      = document.getElementById('chat-drawer');
const drawerBackdrop  = document.getElementById('drawer-backdrop');
const drawerMessages  = document.getElementById('drawer-messages');
const drawerChatInput = document.getElementById('drawer-chat-input');
const drawerSendBtn   = document.getElementById('drawer-send-btn');
const chatFab         = document.getElementById('chat-fab');
//  const topbarChatBtn   = document.getElementById('topbar-chat-btn');
const drawerCloseBtn  = document.getElementById('drawer-close-btn');
const drawerHandle    = document.getElementById('drawer-handle');


/* ================================================================
   INIT
================================================================ */
async function init() {
  setDateLine();
  setSidebarCloseIcon();
  loadSettings();
  bindEvents();
  syncChatFabVisibility();
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
  habits:    'Habit Tracker',
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

    // Find scheduled events for this day.
    const dayEvents = tasks.filter(t => {
      if (t.done || !t.start_time) return false;
      const taskDate = new Date(t.start_time);
      if (Number.isNaN(taskDate.getTime())) return false;
      return taskDate.getDate() === d && taskDate.getMonth() === month && taskDate.getFullYear() === year;
    });

    // Render up to two event labels in each date cell.
    const visibleEvents = dayEvents.slice(0, 2);
    const hiddenCount = Math.max(0, dayEvents.length - visibleEvents.length);

    const eventsHtml = visibleEvents
      .map(t => {
        const title = t.title || t.text || 'Untitled event';
        return `<div style="font-size: 10px; color: var(--clr-green); overflow: hidden; text-overflow: ellipsis; white-space: nowrap;">• ${escapeHtml(title)}</div>`;
      })
      .join('');

    const moreHtml = hiddenCount > 0
      ? `<div style="font-size: 10px; color: var(--clr-text-muted);">+${hiddenCount} more</div>`
      : '';

    html += `
    <div class="cal-day${isToday ? ' today' : ''}" style="flex-direction: column; align-items: flex-start; padding: 4px;">
      <span>${d}</span>
      <div style="width: 100%; margin-top: 4px;">${eventsHtml}${moreHtml}</div>
    </div>
    `;
  }

  const totalCells = Math.ceil((startDow + daysInMonth) / 7) * 7;
  for (let d = 1; d <= totalCells - startDow - daysInMonth; d++)
    html += `<div class="cal-day other-month">${d}</div>`;

  grid.innerHTML = html;

  // Attach click handler to .cal-day elements for day view
  document.querySelectorAll('.cal-day:not(.other-month)').forEach(dayEl => {
    dayEl.addEventListener('click', () => {
      const dayNum = parseInt(dayEl.querySelector('span')?.textContent, 10);
      if (!isNaN(dayNum)) openDayView(dayNum, calendarDate);
    });
    dayEl.style.cursor = 'pointer';
  });
}

/* ================================================================
   HOURLY DAY VIEW
================================================================ */
function openDayView(day, refDate) {
  // Build selected date
  const year = refDate.getFullYear();
  const month = refDate.getMonth();
  const selectedDate = new Date(year, month, day);
  
  // Format title: "Friday, May 1"
  const dayName = selectedDate.toLocaleDateString('en-KE', { weekday: 'long' });
  const dateStr = selectedDate.toLocaleDateString('en-KE', { month: 'long', day: 'numeric' });
  const title = `${dayName}, ${dateStr}`;
  
  // Hide month view, show day view
  document.getElementById('calendar-container').hidden = true;
  const dayViewContainer = document.getElementById('day-view-container');
  dayViewContainer.hidden = false;
  document.getElementById('day-view-title').textContent = title;
  
  renderHourlySlots(selectedDate);
}

function closeDayView() {
  document.getElementById('calendar-container').hidden = false;
  document.getElementById('day-view-container').hidden = true;
}

function renderHourlySlots(date) {
  const hoursGrid = document.getElementById('hours-grid');
  hoursGrid.innerHTML = '';
  
  // Create 24 hourly slots
  for (let hour = 0; hour < 24; hour++) {
    const hourSlot = document.createElement('div');
    hourSlot.className = 'hour-slot empty';
    
    // Format: "09:00" or "14:00"
    const timeStr = String(hour).padStart(2, '0') + ':00';
    
    // Filter tasks for this hour
    const hourTasks = tasks.filter(t => {
      if (t.done || !t.start_time) return false;
      const taskDate = new Date(t.start_time);
      if (Number.isNaN(taskDate.getTime())) return false;
      return taskDate.getDate() === date.getDate() &&
             taskDate.getMonth() === date.getMonth() &&
             taskDate.getFullYear() === date.getFullYear() &&
             taskDate.getHours() === hour;
    });
    
    const hourLabel = document.createElement('div');
    hourLabel.className = 'hour-label';
    hourLabel.textContent = timeStr;
    
    const tasksContainer = document.createElement('div');
    tasksContainer.className = 'hour-tasks';
    
    if (hourTasks.length > 0) {
      hourSlot.classList.remove('empty');
      hourTasks.forEach(task => {
        const taskEl = document.createElement('div');
        taskEl.className = 'hour-task';
        taskEl.textContent = task.title || task.text || 'Untitled';
        tasksContainer.appendChild(taskEl);
      });
    }
    
    hourSlot.appendChild(hourLabel);
    hourSlot.appendChild(tasksContainer);
    hoursGrid.appendChild(hourSlot);
  }
}


/* ================================================================
   SETTINGS
================================================================ */
function loadSettings() {
  applyLightMode(localStorage.getItem('saidi_light_mode') === 'true');
  const savedFont = localStorage.getItem('saidi_font') || 'cursive';
  applyFontChoice(savedFont);
}

function applyFontChoice(font) {
  const normalized = font === 'normal' || font === 'system' ? font : 'cursive';
  document.body.dataset.font = normalized;
  localStorage.setItem('saidi_font', normalized);
  if (fontSelect) fontSelect.value = normalized;
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
  syncChatFabVisibility();
  // Focus input after the slide-up transition finishes
  setTimeout(() => drawerChatInput.focus(), 360);
}

function closeChatDrawer() {
  chatDrawer.classList.remove('open');
  chatDrawer.setAttribute('aria-hidden', 'true');
  drawerBackdrop.classList.remove('visible');
  syncChatFabVisibility();
}

function syncChatFabVisibility() {
  chatFab.style.display = chatDrawer.classList.contains('open') ? 'none' : 'flex';
}


/* ================================================================
   TASKS
================================================================ */

/** Load tasks array from localStorage */
async function loadTasks() {
  const cachedTasks = readLocalTaskCache();
  tasks = cachedTasks;

  try {
    const remoteTasks = await fetchTasksFromBackend();
    if (remoteTasks.length === 0 && cachedTasks.length > 0) {
      const syncedTasks = await syncTasksToBackend(cachedTasks);
      tasks = syncedTasks.length > 0 ? syncedTasks : cachedTasks;
    } else {
      tasks = remoteTasks;
    }
  } catch (err) {
    console.warn('[Saidi] Task DB sync unavailable, using local cache:', err);
    tasks = cachedTasks;
  }

  saveTasks();
}

/** Write tasks array back to localStorage */
function saveTasks() {
  localStorage.setItem(STORAGE_KEY, JSON.stringify(tasks));
}

/** Add a new task from the input field */
async function addTask() {
  const text = document.getElementById('task-input').value.trim();
  const startTime = document.getElementById('task-start').value;
  const endTime = document.getElementById('task-end').value;
  
  if (!text || !startTime) {
    alert('Task title and start time are required.');
    return;
  }

  const draftTask = {
    title: text,
    start_time: new Date(startTime).toISOString(),
    end_time: endTime ? new Date(endTime).toISOString() : null,
    is_flexible: false,
    done: false,
    createdAt: Date.now(),
  };

  try {
    const createdTask = await createTaskInBackend(draftTask);
    const normalizedCreated = normalizeTaskRecord(createdTask);
    if (!normalizedCreated) {
      throw new Error('Created task response was invalid.');
    }
    tasks.unshift(normalizedCreated);
  } catch (err) {
    console.warn('[Saidi] Failed to persist task to DB, using local fallback:', err);
    const fallbackTask = normalizeTaskRecord({
      id: crypto.randomUUID(),
      ...draftTask,
    });
    if (fallbackTask) {
      tasks.unshift(fallbackTask);
    }
  }

  saveTasks();
  renderTasks();
  renderCalendar();

  // Clear inputs
  document.getElementById('task-input').value = '';
  document.getElementById('task-start').value = '';
  document.getElementById('task-end').value = '';
}

/** Toggle a task's done state */
async function toggleTask(id) {
  const task = tasks.find(t => t.id === id);
  if (task) {
    const previousDone = task.done;
    task.done = !task.done;

    saveTasks();
    renderTasks();
    if (document.getElementById('view-calendar').classList.contains('active')) {
      renderCalendar();
    }

    try {
      await updateTaskInBackend(id, { done: task.done });
    } catch (err) {
      console.warn('[Saidi] Failed to persist task toggle, rolling back:', err);
      task.done = previousDone;
      saveTasks();
      renderTasks();
      if (document.getElementById('view-calendar').classList.contains('active')) {
        renderCalendar();
      }
    }
  }
}

/** Remove a task permanently */
async function deleteTask(id) {
  const previousTasks = tasks.slice();
  tasks = tasks.filter(t => t.id !== id);

  saveTasks();
  renderTasks();
  if (document.getElementById('view-calendar').classList.contains('active')) {
    renderCalendar();
  }

  try {
    await deleteTaskInBackend(id);
  } catch (err) {
    console.warn('[Saidi] Failed to delete task in DB, restoring local state:', err);
    tasks = previousTasks;
    saveTasks();
    renderTasks();
    if (document.getElementById('view-calendar').classList.contains('active')) {
      renderCalendar();
    }
  }
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


    const displayTitle = task.title || task.text || 'Untitled event';
    const taskStart = task.start_time ? new Date(task.start_time) : null;
    const hasValidStart = taskStart && !Number.isNaN(taskStart.getTime());
    const timeString = hasValidStart
      ? taskStart.toLocaleString('en-KE', { weekday: 'short', hour: 'numeric', minute: '2-digit' })
      : 'Flexible';

    li.innerHTML = `
      <button
        class="task-check${task.done ? ' checked' : ''}"
        aria-label="${task.done ? 'Mark incomplete' : 'Mark complete'}"
        aria-pressed="${task.done}"
      >${task.done ? '✓' : ''}</button>
      <div style="flex: 1; min-width: 0;">
        <div class="task-text">${escapeHtml(displayTitle)}</div>
        <div style="font-size: 0.75rem; color: var(--clr-green);">${timeString}</div>
      </div>
      <button class="task-delete" aria-label="Delete task">✕</button>
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
  const drawerEl = buildBubble(role, text);
  drawerMessages.appendChild(drawerEl);
  
  scrollToBottom(drawerMessages);
  
  return { panelEl: null, drawerEl };
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
  const drawerCard = buildLogsCard(actions);
  drawerMessages.appendChild(drawerCard);
  scrollToBottom(drawerMessages);
}

/** Format one human-readable log line for a tool action. */
function formatActionLogLine(action) {
  const actionType = typeof action?.type === 'string' ? action.type : 'unknown_action';
  const payload = action?.payload ?? {};

  const eventTitleRaw = payload?.title;
  const eventTitle = typeof eventTitleRaw === 'string' ? eventTitleRaw.trim() : '';
  const taskTextRaw = payload?.task_text;
  const taskText = typeof taskTextRaw === 'string' ? taskTextRaw.trim() : '';
  const eventIdRaw = payload?.id;
  const eventId = typeof eventIdRaw === 'string' ? eventIdRaw.trim() : '';
  const refText = eventTitle || taskText;

  if (refText && eventId) {
    return `Saidi executed ${actionType}: '${refText}' (id=${eventId})`;
  }

  if (refText) {
    return `Saidi executed ${actionType}: '${refText}'`;
  }

  if (eventId) {
    return `Saidi executed ${actionType} for id=${eventId}.`;
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
  const activeTasksPayload = tasks
    .map(toBackendEvent)
    .filter(Boolean);

  try {
    const res = await fetchWithAuth(API_CHAT, {
      method:  'POST',
      headers: { 'Content-Type': 'application/json' },
      body:    JSON.stringify({
        message:      text,
        history:      chatHistory.slice(-10),
        active_tasks: activeTasksPayload,
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

    thinkPanel?.remove();
    thinkDrawer?.remove();

    if (hasActions) {
      appendLogs(data.actions);
    }

    appendMessage('saidi', reply);
    chatHistory.push({ role: 'assistant', content: reply });

    // Overwrite frontend state with the backend's exact calendar state
    if (Array.isArray(data.updated_tasks)) {
      const syncedTasks = normalizeTaskList(data.updated_tasks);
      const syncedIds = new Set(syncedTasks.map(t => t.id));
      const preservedDone = tasks
        .filter(t => t.done && !syncedIds.has(t.id))
        .map(normalizeTaskRecord)
        .filter(Boolean);

      tasks = [...syncedTasks, ...preservedDone];

      saveTasks();
      renderTasks();
      if (document.getElementById('view-calendar')?.classList.contains('active')) {
        renderCalendar();
      }
    }

  } catch (err) {
    thinkPanel?.remove();
    thinkDrawer?.remove();

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
  //chatInput.disabled       = disabled;
  drawerChatInput.disabled = disabled;
  //sendBtn.disabled         = disabled;
  drawerSendBtn.disabled   = disabled;

  //sendBtn.style.opacity      = disabled ? '0.5' : '';
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

  /* ── Mobile chat drawer (Now Universal) ── */
  chatFab.addEventListener('click',       openChatDrawer);
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

  /* ── Day view navigation ── */
  document.getElementById('btn-back-month')?.addEventListener('click', closeDayView);

  /* ── Settings ── */
  document.getElementById('light-mode-toggle')?.addEventListener('click', toggleLightMode);
  fontSelect?.addEventListener('change', event => {
    applyFontChoice(event.target.value);
  });

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
    // if (window.innerWidth > 1023) {
    //   // Desktop: chat panel is visible, hide drawer + FAB
    //   chatDrawer.classList.remove('open');
    //   drawerBackdrop.classList.remove('visible');
    //   chatFab.style.display = 'none';
    // } else {
    //   // Tablet/mobile: show FAB if drawer is closed
    //   if (!chatDrawer.classList.contains('open')) {
    //     chatFab.style.display = '';
    //   }
    // }
    syncChatFabVisibility();
  });
}

/** Programmatically add a task from the AI */
function createTaskProgrammatically(text) {
  const created = normalizeTaskRecord({
    id: crypto.randomUUID(),
    title: text,
    done: false,
    start_time: null,
    end_time: null,
    is_flexible: true,
    createdAt: Date.now(),
  });

  if (!created) return;

  tasks.unshift(created);
  saveTasks();
  renderTasks();
}

/** Programmatically remove a task via fuzzy text match from the AI */
function removeTaskProgrammatically(searchText) {
  const lowerSearch = searchText.toLowerCase();
  const taskIndex = tasks.findIndex(t => 
    (t.title || t.text || '').toLowerCase().includes(lowerSearch) || 
    lowerSearch.includes((t.title || t.text || '').toLowerCase())
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
// if ('serviceWorker' in navigator) {
//   window.addEventListener('load', () => {
//     navigator.serviceWorker
//       .register('/sw.js')
//       .catch(() => { /* SW is optional — silent fail */ });
//   });
// }


/* ── Kick off ─────────────────────────────────────────────────── */
document.addEventListener('DOMContentLoaded', () => {
  init().catch(err => {
    console.error('[Saidi] init failed:', err);
  });
});

/* ================================================================
   HABITS
================================================================ */
let habits = []; // Will eventually come from Postgres API

const habitInput = document.getElementById('habit-input');
const habitType = document.getElementById('habit-type');
const habitQuota = document.getElementById('habit-quota');
const addHabitBtn = document.getElementById('add-habit-btn');
const habitList = document.getElementById('habit-list');

function addHabit() {
  const name = habitInput.value.trim();
  const type = habitType.value;
  const quota = parseInt(habitQuota.value, 10) || 1;

  if (!name) return;

  const newHabit = {
    id: crypto.randomUUID(),
    name: name,
    type: type,
    daily_quota: quota,
    today_completions: 0,
    history: generateMockHistory() // Placeholder for past 7 days data
  };

  habits.unshift(newHabit);
  renderHabits();
  
  habitInput.value = '';
  habitQuota.value = '1';
}

function logHabit(id) {
  const habit = habits.find(h => h.id === id);
  if (habit && habit.today_completions < habit.daily_quota) {
    habit.today_completions++;
    renderHabits();
    // In future: send API request to backend here
  }
}

function renderHabits() {
  if (!habitList) return;
  habitList.innerHTML = '';

  habits.forEach(habit => {
    const li = document.createElement('li');
    li.className = 'task-item habit-card';

    // Generate Quota Dots
    let dotsHtml = '';
    for (let i = 0; i < habit.daily_quota; i++) {
      const filled = i < habit.today_completions ? 'filled' : '';
      dotsHtml += `<div class="quota-dot ${filled}"></div>`;
    }

    // Generate Mini Grid (showing last 7 days for now to fit mobile cleanly)
    let gridHtml = '';
    habit.history.forEach(day => {
      let cellClass = '';
      let icon = '-';
      if (day.status === 'pass') { cellClass = 'pass'; icon = '✓'; }
      if (day.status === 'fail') { cellClass = 'fail'; icon = '✕'; }
      gridHtml += `<div class="habit-day-cell ${cellClass}">${icon}</div>`;
    });

    li.innerHTML = `
      <div class="habit-header">
        <div class="habit-title-row">
          <span class="habit-type-badge badge-${habit.type}">${habit.type}</span>
          <span class="task-text" style="font-weight: 600;">${escapeHtml(habit.name)}</span>
        </div>
        <div class="habit-controls">
          <div class="quota-dots">${dotsHtml}</div>
          <button class="btn-log-habit" onclick="logHabit('${habit.id}')">+ Log</button>
        </div>
      </div>
      <div class="habit-month-grid">
        ${gridHtml}
      </div>
    `;
    
    habitList.appendChild(li);
  });
}

// Temporary helper to show grid UI
function generateMockHistory() {
  const statuses = ['pass', 'fail', 'none'];
  return Array.from({length: 7}, () => ({ 
    status: statuses[Math.floor(Math.random() * statuses.length)] 
  }));
}

if (addHabitBtn) {
  addHabitBtn.addEventListener('click', addHabit);
  habitInput.addEventListener('keydown', e => {
    if (e.key === 'Enter') addHabit();
  });
}

// LOGIN LOGIC
// --- Authentication State Management ---
const authLanding = document.getElementById('auth-landing');
const appDashboard = document.getElementById('app-dashboard');
const authError = document.getElementById('auth-error');

// Check if user is already logged in on page load
function checkAuth() {
    const token = localStorage.getItem('saidi_token');
    if (token) {
        showDashboard();
    }
}

function showDashboard() {
    authLanding.style.display = 'none';
    appDashboard.style.display = 'block';
    // Call your existing function to load tasks here
    loadTasks().then(() => {
      renderTasks();
    }); 
}

function logout() {
    localStorage.removeItem('saidi_token');
    appDashboard.style.display = 'none';
    authLanding.style.display = 'flex';
}

document.getElementById('logout-btn')?.addEventListener('click', logout);

// --- Form Toggling Logic ---
let isLoginMode = true;
document.getElementById('toggle-auth').addEventListener('click', (e) => {
    e.preventDefault();
    isLoginMode = !isLoginMode;
    authError.style.display = 'none';
    
    if (isLoginMode) {
        document.getElementById('auth-title').innerText = 'Login to MySaidi';
        document.getElementById('login-form').style.display = 'block';
        document.getElementById('register-form').style.display = 'none';
        document.getElementById('toggle-msg').innerText = "Don't have an account?";
        e.target.innerText = "Sign up";
    } else {
        document.getElementById('auth-title').innerText = 'Create Account';
        document.getElementById('login-form').style.display = 'none';
        document.getElementById('register-form').style.display = 'block';
        document.getElementById('toggle-msg').innerText = "Already have an account?";
        e.target.innerText = "Login";
    }
});

// --Logout Button ---
document.getElementById('logout-btn').addEventListener('click', () => {
    // Replace 'token' with the actual key you use to store the JWT
    localStorage.removeItem('token'); 
    
    // 
    window.location.reload();
});

// --- API Calls ---
async function handleAuth(url, email, password) {
    authError.style.display = 'none';
    try {
        const response = await fetch(url, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ email, password })
        });

        const data = await response.json();

        if (!response.ok) {
            throw new Error(data.detail || 'Authentication failed');
        }

        if (url === '/login') {
            localStorage.setItem('saidi_token', data.access_token);
            showDashboard();
        } else {
            // If register is successful, automatically log them in
            handleAuth('/login', email, password);
        }
    } catch (error) {
        authError.textContent = error.message;
        authError.style.display = 'block';
    }
}

document.getElementById('login-form').addEventListener('submit', (e) => {
    e.preventDefault();
    handleAuth('/login', document.getElementById('login-email').value, document.getElementById('login-password').value);
});

document.getElementById('register-form').addEventListener('submit', (e) => {
    e.preventDefault();
    handleAuth('/register', document.getElementById('register-email').value, document.getElementById('register-password').value);
});

document.getElementById('peek-login').addEventListener('click', function() {
    const passInput = document.getElementById('login-password');
    if (passInput.type === 'password') {
        passInput.type = 'text';
        this.textContent = '🙈';
    } else {
        passInput.type = 'password';
        this.textContent = '👁️';
    }
});

// Run auth check immediately
checkAuth();

