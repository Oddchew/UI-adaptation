const USER = 'user_demo';
const SESSION = crypto.randomUUID();
const INTERFACE = 'python_tutor_model';
const CONTEXT = `user_id=${encodeURIComponent(USER)}&session_id=${encodeURIComponent(SESSION)}`;
const seen = new Set();
const controls = [...document.querySelectorAll('#demo-form button, #btn-error, #btn-help, #hide-hint, #open-history, #theme')];
let feedbackTimer;

async function api(path, options = {}) {
  const res = await fetch(path, {headers: {'Content-Type': 'application/json'}, ...options});
  const data = await res.json();
  if (!res.ok) throw new Error(data.error || res.statusText);
  return data;
}

function feedback(message) {
  const toast = document.getElementById('feedback');
  toast.textContent = message;
  toast.hidden = false;
  clearTimeout(feedbackTimer);
  feedbackTimer = setTimeout(() => { toast.hidden = true; }, 4200);
}

function applyUi(ui) {
  if (!ui || !ui.hints_panel || !ui.history_panel) throw new Error('Некорректная модель интерфейса');
  if (typeof ui.hints_panel.visible !== 'boolean' || typeof ui.history_panel.collapsed !== 'boolean') throw new Error('Некорректные свойства интерфейса');
  document.getElementById('hints_panel').hidden = !ui.hints_panel.visible;
  document.getElementById('history_content').hidden = ui.history_panel.collapsed;
  document.getElementById('history-collapsed').hidden = !ui.history_panel.collapsed;
  document.getElementById('history-status').textContent = ui.history_panel.collapsed ? 'Свёрнута' : 'В этом сеансе';
  document.getElementById('stat-hint').textContent = ui.hints_panel.visible ? 'Открыта' : 'Скрыта';
  document.getElementById('ui-view').textContent = JSON.stringify(ui, null, 2);
}

function renderModel(model) {
  document.getElementById('model-view').textContent = model ? JSON.stringify(model, null, 2) : 'Пока нет событий';
  document.getElementById('stat-events').textContent = model?.counters?.total_events ?? '0';
  document.getElementById('stat-errors').textContent = model?.counters?.total_errors ?? '0';
}

function addHistory(label) {
  document.getElementById('history-empty').hidden = true;
  const li = document.createElement('li');
  const text = document.createElement('span');
  const time = document.createElement('time');
  text.textContent = label;
  time.textContent = new Date().toLocaleTimeString('ru-RU', {hour: '2-digit', minute: '2-digit'});
  li.append(text, time);
  document.getElementById('history-list').prepend(li);
}

async function pollRuntime() {
  try {
    const {commands} = await api(`/api/runtime/pending?${CONTEXT}`);
    for (const command of commands) {
      if (seen.has(command.token)) continue;
      seen.add(command.token);
      let success = false;
      try { applyUi(command.model); success = true; } catch (error) { console.error(error); }
      await api('/api/runtime/ack', {method: 'POST', body: JSON.stringify({token: command.token, success})});
    }
  } catch (error) {
    console.error('Ошибка связи с runtime', error);
  }
  setTimeout(pollRuntime, 200);
}

async function refresh() {
  const [health, model, state] = await Promise.all([api('/api/health'), api(`/api/model/${USER}`), api(`/api/ui-state?${CONTEXT}`)]);
  const status = document.getElementById('health');
  status.innerHTML = health.ok ? '<i></i> Система активна' : '<i></i> Нет подключения';
  status.classList.toggle('offline', !health.ok);
  renderModel(model.model);
  document.getElementById('pkg-view').textContent = JSON.stringify(state.packages, null, 2);
  const version = document.getElementById('ui-version');
  version.textContent = state.version || '—';
  version.title = state.version || '';
  applyUi(state.ui);
}

async function sendEvent(payload, historyLabel, message) {
  controls.forEach(control => { control.disabled = true; });
  try {
    await api('/api/event', {method: 'POST', body: JSON.stringify({user_id: USER, interface_id: INTERFACE, session_id: SESSION, ...payload})});
    if (historyLabel) addHistory(historyLabel);
    await refresh();
    if (message) feedback(message);
  } catch (error) {
    console.error(error);
    feedback(`Не удалось выполнить действие: ${error.message}`);
    const status = document.getElementById('health');
    status.innerHTML = '<i></i> Нет подключения';
    status.classList.add('offline');
  } finally {
    controls.forEach(control => { control.disabled = false; });
  }
}

document.getElementById('demo-form').addEventListener('submit', event => {
  event.preventDefault();
  sendEvent({event_type: 'successful_action', element_id: 'code_editor', action_id: 'check_run'}, 'Имитация успешной проверки', 'Событие успешной проверки отправлено в модуль A.');
});
document.getElementById('btn-error').addEventListener('click', () => sendEvent({event_type: 'error', element_id: 'code_editor', error_code: 'validation'}, 'Смоделирована ошибка проверки', 'Событие ошибки отправлено в модуль A.'));
document.getElementById('btn-help').addEventListener('click', () => sendEvent({event_type: 'help_request', element_id: 'hints_panel'}, 'Запрошена помощь', 'Запрос помощи отправлен в модуль A.'));
document.getElementById('hide-hint').addEventListener('click', () => sendEvent({event_type: 'hint_hide', element_id: 'hints_panel'}, 'Подсказка скрыта'));
document.getElementById('open-history').addEventListener('click', () => sendEvent({event_type: 'block_open', element_id: 'history_content'}, 'История развёрнута'));
document.getElementById('theme').addEventListener('change', event => {
  const theme = event.target.value;
  document.body.classList.toggle('theme-dark', theme === 'dark');
  sendEvent({event_type: 'manual_override', element_id: 'theme_select', property: 'theme', new_value: theme}, 'Изменено оформление');
});
document.getElementById('btn-refresh').addEventListener('click', () => refresh().catch(error => feedback(error.message)));
document.getElementById('btn-reset-b').addEventListener('click', async () => {
  try { await api('/api/reset-b', {method: 'POST', body: '{}'}); feedback('Ограничение повторов B сброшено.'); }
  catch (error) { feedback(error.message); }
});
pollRuntime();
refresh().catch(error => { document.getElementById('health').classList.add('offline'); feedback(`Не удалось подключиться: ${error.message}`); });
