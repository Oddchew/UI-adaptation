const USER = 'user_demo';
const SESSION = crypto.randomUUID();
const params = new URLSearchParams(location.search);
const INTERFACE = params.get('interface_id') || 'python_tutor_model';
const CONTEXT = `user_id=${encodeURIComponent(USER)}&session_id=${encodeURIComponent(SESSION)}&interface_id=${encodeURIComponent(INTERFACE)}`;
const seen = new Set();
let currentModel = null;
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

function sendEvent(payload) {
  return api('/api/event', {
    method: 'POST',
    body: JSON.stringify({user_id: USER, interface_id: INTERFACE, session_id: SESSION, ...payload})
  }).then(refresh);
}

function applyStyle(element, props) {
  if (props.visible === false) element.hidden = true;
  if (props.enabled === false) element.setAttribute('aria-disabled', 'true');
  if (props.opacity !== undefined) element.style.opacity = String(props.opacity);
  if (props.width !== undefined) element.style.width = `${props.width}px`;
  if (props.height !== undefined) element.style.height = `${props.height}px`;
  if (props.background_color) element.style.backgroundColor = props.background_color;
  if (props.color) element.style.color = props.color;
  if (props.border_color) element.style.borderColor = props.border_color;
  if (props.border_width !== undefined) element.style.borderWidth = `${props.border_width}px`;
  if (props.border_style) element.style.borderStyle = props.border_style;
  if (props.corner_radius !== undefined) element.style.borderRadius = `${props.corner_radius}px`;
  if (props.font_size !== undefined) element.style.fontSize = `${props.font_size}px`;
  if (props.font_weight) element.style.fontWeight = props.font_weight;
  if (props.text_align) element.style.textAlign = props.text_align;
  if (props.padding !== undefined) element.style.padding = `${props.padding}px`;
  if (props.margin !== undefined) element.style.margin = `${props.margin}px`;
  if (props.tooltip) element.title = props.tooltip;
  if (element.tagName === 'P') element.style.whiteSpace = 'pre-wrap';
  if (element.classList.contains('sc-ui-scroll')) element.style.overflow = 'auto';
}

function createComponent(component) {
  const props = component.props || {};
  const text = props.text_value || props.name || component.id;
  let element;
  switch (component.typeId) {
    case 'text': element = document.createElement('p'); element.textContent = text; break;
    case 'image':
      element = document.createElement('div');
      element.className = 'sc-image-placeholder';
      element.textContent = text || '[image]';
      element.setAttribute('role', 'img');
      element.setAttribute('aria-label', text);
      break;
    case 'sound':
      element = document.createElement('div'); element.textContent = text || '[sound]'; break;
    case 'divider': element = document.createElement('hr'); break;
    case 'spacer': element = document.createElement('div'); element.style.minHeight = '16px'; break;
    case 'text_field':
      element = document.createElement('input'); element.type = 'text';
      element.value = props.text_value || ''; element.placeholder = props.tooltip || props.name || '';
      break;
    case 'text_area':
      element = document.createElement('textarea'); element.value = props.text_value || '';
      element.rows = 4; element.setAttribute('aria-label', props.name || component.id);
      break;
    case 'slider':
      element = document.createElement('input'); element.type = 'range'; break;
    case 'select': element = document.createElement('select'); break;
    case 'button':
    case 'menu_item':
      element = document.createElement('button'); element.type = 'button'; element.textContent = text; break;
    case 'list': element = document.createElement('ul'); break;
    case 'menu':
    case 'menu_bar': element = document.createElement('nav'); break;
    case 'scroll':
    case 'window': element = document.createElement('section'); break;
    default: element = document.createElement('div'); element.textContent = text;
  }
  element.dataset.componentId = component.id;
  element.classList.add('sc-ui-component', `sc-ui-${component.typeId}`);
  applyStyle(element, props);
  if (props.enabled === false && 'disabled' in element) element.disabled = true;
  if (props.enabled === false) element.setAttribute('aria-disabled', 'true');
  return element;
}

function renderInterface(model) {
  if (!model || !Array.isArray(model.components) || !Array.isArray(model.links)) {
    throw new Error('Сервер вернул некорректную SC UI-модель');
  }
  currentModel = model;
  const root = document.getElementById('interface-root');
  root.replaceChildren();
  const byId = new Map(model.components.map(component => [component.id, component]));
  const children = new Map();
  const childIds = new Set();
  for (const link of model.links) {
    if (link.kind !== 'contains') continue;
    if (!children.has(link.sourceId)) children.set(link.sourceId, []);
    children.get(link.sourceId).push(link.targetId);
    childIds.add(link.targetId);
  }
  for (const ids of children.values()) {
    ids.sort((a, b) => (byId.get(a)?.props?.order ?? 0) - (byId.get(b)?.props?.order ?? 0));
  }
  const rendered = new Set();
  const bounds = model.components.reduce((size, component) => {
    const props = component.props || {};
    return {
      width: Math.max(size.width, (props.x || 0) + (props.width || 0)),
      height: Math.max(size.height, (props.y || 0) + (props.height || 0))
    };
  }, {width: 0, height: 0});
  root.style.position = 'relative';
  root.style.display = 'block';
  root.style.padding = '0';
  root.style.width = `${Math.max(bounds.width + 16, 320)}px`;
  root.style.height = `${Math.max(bounds.height + 16, 180)}px`;
  function mount(id, parent, parentOrigin = {x: 0, y: 0}) {
    const component = byId.get(id);
    if (!component || rendered.has(id)) return;
    rendered.add(id);
    const props = component.props || {};
    const element = createComponent(component);
    element.style.position = 'absolute';
    element.style.left = `${(props.x || 0) - parentOrigin.x}px`;
    element.style.top = `${(props.y || 0) - parentOrigin.y}px`;
    parent.append(element);
    for (const childId of children.get(id) || []) {
      mount(childId, element, {x: props.x || 0, y: props.y || 0});
    }
    if (component.typeId === 'button' || component.typeId === 'menu_item') {
      element.addEventListener('click', () => sendEvent({
        event_type: 'successful_action', element_id: id, action_id: props.action_id || undefined
      }).catch(error => feedback(error.message)));
    } else if (['text_field', 'text_area', 'select', 'slider'].includes(component.typeId)) {
      element.addEventListener('focus', () => sendEvent({event_type: 'focus', element_id: id}).catch(console.error));
      element.addEventListener('blur', () => sendEvent({event_type: 'blur', element_id: id}).catch(console.error));
    }
  }
  const roots = model.components.filter(component => !childIds.has(component.id));
  roots.sort((a, b) => (a.props?.order ?? 0) - (b.props?.order ?? 0));
  for (const component of roots) mount(component.id, root);
  for (const component of model.components) {
    if (!rendered.has(component.id)) mount(component.id, root);
  }
  document.getElementById('ui-view').textContent = JSON.stringify(model, null, 2);
  document.getElementById('interface-title').textContent = model.title || model.id;
}

function renderUserModel(model) {
  document.getElementById('model-view').textContent = model ? JSON.stringify(model, null, 2) : 'Пока нет событий';
  document.getElementById('stat-events').textContent = model?.counters?.total_events ?? '0';
  document.getElementById('stat-errors').textContent = model?.counters?.total_errors ?? '0';
}

async function pollRuntime() {
  try {
    const {commands} = await api(`/api/runtime/pending?${CONTEXT}`);
    for (const command of commands) {
      if (seen.has(command.token)) continue;
      seen.add(command.token);
      let success = false;
      try { renderInterface(command.model); success = true; }
      catch (error) { console.error(error); }
      await api('/api/runtime/ack', {method: 'POST', body: JSON.stringify({token: command.token, success})});
    }
  } catch (error) { console.error('Ошибка связи с runtime', error); }
  setTimeout(pollRuntime, 200);
}

async function refresh() {
  const [health, userModel, state] = await Promise.all([
    api('/api/health'), api(`/api/model/${USER}`), api(`/api/ui-state?${CONTEXT}`)
  ]);
  const status = document.getElementById('health');
  status.innerHTML = health.ok ? '<i></i> Система активна' : '<i></i> Нет подключения';
  status.classList.toggle('offline', !health.ok);
  renderUserModel(userModel.model);
  document.getElementById('pkg-view').textContent = JSON.stringify(state.packages, null, 2);
  const version = document.getElementById('ui-version');
  version.textContent = state.version || '—';
  version.title = state.version || '';
  renderInterface(state.model);
}

document.getElementById('btn-refresh').addEventListener('click', () => refresh().catch(error => feedback(error.message)));
document.getElementById('btn-reset-b').addEventListener('click', async () => {
  try { await api('/api/reset-b', {method: 'POST', body: '{}'}); feedback('Ограничение повторов B сброшено.'); }
  catch (error) { feedback(error.message); }
});
document.querySelector('.demo-card')?.setAttribute('hidden', 'hidden');
document.querySelector('.main-column').innerHTML = '<section class="task-card"><div class="task-top"><div class="section-kicker">SC UI MODEL</div></div><h2 id="interface-title">Загрузка интерфейса…</h2><div id="interface-root" class="sc-interface-root"></div></section>';
pollRuntime();
refresh().catch(error => {
  document.getElementById('health').classList.add('offline');
  feedback(`Не удалось загрузить интерфейс ${INTERFACE}: ${error.message}`);
});
