const USER = 'user_demo';
const SESSION = crypto.randomUUID();
const params = new URLSearchParams(location.search);
const INTERFACE = params.get('interface_id') || 'python_tutor_model';
const CONTEXT = 'user_id=' + encodeURIComponent(USER) +
  '&session_id=' + encodeURIComponent(SESSION) +
  '&interface_id=' + encodeURIComponent(INTERFACE);
const seen = new Set();
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
  }).then(async result => {
    if (result.model) {
      document.getElementById('model-view').textContent = JSON.stringify(result.model, null, 2);
    }
    document.getElementById('pkg-view').textContent = JSON.stringify(result.packages || [], null, 2);
    return result;
  });
}

function applyStyle(element, props) {
  if (props.visible === false) element.hidden = true;
  if (props.opacity !== undefined) element.style.opacity = String(props.opacity);
  if (props.width !== undefined) element.style.width = props.width + 'px';
  if (props.height !== undefined) element.style.height = props.height + 'px';
  if (props.min_width) element.style.minWidth = props.min_width + 'px';
  if (props.min_height) element.style.minHeight = props.min_height + 'px';
  if (props.max_width) element.style.maxWidth = props.max_width + 'px';
  if (props.max_height) element.style.maxHeight = props.max_height + 'px';
  if (props.background_color) element.style.backgroundColor = props.background_color;
  if (props.color) element.style.color = props.color;
  if (props.border_color) element.style.borderColor = props.border_color;
  if (props.border_width !== undefined) element.style.borderWidth = props.border_width + 'px';
  if (props.border_style) element.style.borderStyle = props.border_style;
  if (props.corner_radius !== undefined) element.style.borderRadius = props.corner_radius + 'px';
  if (props.font_size !== undefined) element.style.fontSize = props.font_size + 'px';
  if (props.font_weight) element.style.fontWeight = props.font_weight;
  if (props.text_align) element.style.textAlign = props.text_align;
  if (props.padding !== undefined) element.style.padding = props.padding + 'px';
  if (props.margin !== undefined) element.style.margin = props.margin + 'px';
  if (props.tooltip) element.title = props.tooltip;
  if (element.tagName === 'P') element.style.whiteSpace = 'pre-wrap';
  if (element.classList.contains('sc-ui-scroll')) element.style.overflow = 'auto';
}

function isResourceUrl(value) {
  if (typeof value !== 'string' || !value.trim()) return false;
  const source = value.trim();
  return /^(https?:\/\/|\/|\.\/|\.\.\/|data:image\/)/i.test(source);
}

function createComponent(component) {
  const props = component.props || {};
  const text = props.text_value ?? props.name ?? component.id;
  let element;

  switch (component.typeId) {
    case 'text':
      element = document.createElement('p');
      element.textContent = text;
      break;
    case 'image':
      if (isResourceUrl(props.text_value)) {
        element = document.createElement('img');
        element.src = props.text_value;
        element.alt = props.name || '';
        element.loading = 'lazy';
        element.draggable = false;
      } else {
        element = document.createElement('div');
        element.className = 'sc-image-placeholder';
        element.textContent = props.name || 'Изображение: ' + (props.text_value || 'ресурс не указан');
        element.setAttribute('role', 'img');
        element.setAttribute('aria-label', props.name || 'Изображение');
        if (props.text_value) element.dataset.resourceId = props.text_value;
      }
      break;
    case 'sound':
      if (isResourceUrl(props.text_value) &&
          !/^data:image\//i.test(props.text_value)) {
        element = document.createElement('audio');
        element.src = props.text_value;
        element.controls = true;
        element.preload = 'metadata';
      } else {
        element = document.createElement('div');
        element.className = 'sc-sound-placeholder';
        element.textContent = props.name || 'Аудиоресурс: ' + (props.text_value || 'не указан');
        element.setAttribute('role', 'group');
        element.setAttribute('aria-label', 'Звуковой компонент');
        if (props.text_value) element.dataset.resourceId = props.text_value;
      }
      break;
    case 'divider':
      element = document.createElement('hr');
      break;
    case 'spacer':
      element = document.createElement('div');
      element.setAttribute('aria-hidden', 'true');
      break;
    case 'text_field':
      element = document.createElement('input');
      element.type = 'text';
      element.value = props.text_value || '';
      element.placeholder = props.tooltip || '';
      element.setAttribute('aria-label', props.name || component.id);
      break;
    case 'text_area':
      element = document.createElement('textarea');
      element.value = props.text_value || '';
      element.rows = 4;
      element.setAttribute('aria-label', props.name || component.id);
      break;
    case 'slider': {
      element = document.createElement('input');
      element.type = 'range';
      element.min = '0';
      element.max = '100';
      const initial = Number(props.text_value);
      element.value = Number.isFinite(initial) ? String(Math.min(100, Math.max(0, initial))) : '50';
      element.setAttribute('aria-label', props.name || component.id);
      break;
    }
    case 'select':
      element = document.createElement('select');
      element.setAttribute('aria-label', props.name || component.id);
      break;
    case 'button':
    case 'menu_item':
      element = document.createElement('button');
      element.type = 'button';
      element.textContent = text;
      break;
    case 'list':
      element = document.createElement('ul');
      element.setAttribute('aria-label', props.name || 'Список');
      break;
    case 'menu':
    case 'menu_bar':
      element = document.createElement('nav');
      element.setAttribute('aria-label', props.name || 'Меню');
      break;
    case 'scroll':
    case 'window':
      element = document.createElement('section');
      if (props.name) element.setAttribute('aria-label', props.name);
      break;
    default:
      element = document.createElement('div');
      element.textContent = text;
  }

  element.dataset.componentId = component.id;
  element.classList.add('sc-ui-component', 'sc-ui-' + component.typeId);
  applyStyle(element, props);
  if (props.enabled === false && 'disabled' in element) element.disabled = true;
  if (props.enabled === false) element.setAttribute('aria-disabled', 'true');
  return element;
}

function readInputValue(element) {
  if (!element) return null;
  if (element.type === 'checkbox') return element.checked;
  if (element.type === 'range' || element.type === 'number') return Number(element.value);
  return element.value;
}

function readLinkedInputs(root, targetIds) {
  const values = {};
  const elements = Array.from(root.querySelectorAll('[data-component-id]'));
  for (const targetId of targetIds) {
    const target = elements.find(element => element.dataset.componentId === targetId);
    values[targetId] = readInputValue(target);
  }
  return values;
}

function renderInterface(model) {
  if (!model || !Array.isArray(model.components) || !Array.isArray(model.links)) {
    throw new Error('Сервер вернул некорректную SC UI-модель');
  }

  const root = document.getElementById('interface-root');
  root.replaceChildren();
  const byId = new Map(model.components.map(component => [component.id, component]));
  const children = new Map();
  const childIds = new Set();
  const inputTargets = new Map();
  const outputTargets = new Map();

  for (const link of model.links) {
    if (!byId.has(link.sourceId) || !byId.has(link.targetId)) continue;
    if (link.kind === 'contains') {
      if (!children.has(link.sourceId)) children.set(link.sourceId, []);
      children.get(link.sourceId).push(link.targetId);
      childIds.add(link.targetId);
    } else if (link.kind === 'input_target') {
      if (!inputTargets.has(link.sourceId)) inputTargets.set(link.sourceId, []);
      inputTargets.get(link.sourceId).push(link.targetId);
    } else if (link.kind === 'output_target') {
      if (!outputTargets.has(link.sourceId)) outputTargets.set(link.sourceId, []);
      outputTargets.get(link.sourceId).push(link.targetId);
    }
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

  root.style.width = Math.max(bounds.width + 16, 320) + 'px';
  root.style.height = Math.max(bounds.height + 16, 180) + 'px';

  function mount(id, parent, parentOrigin = {x: 0, y: 0}) {
    const component = byId.get(id);
    if (!component || rendered.has(id)) return;
    rendered.add(id);
    const props = component.props || {};
    const element = createComponent(component);
    element.style.left = ((props.x || 0) - parentOrigin.x) + 'px';
    element.style.top = ((props.y || 0) - parentOrigin.y) + 'px';
    element.style.zIndex = String(props.order ?? 0);
    parent.append(element);

    if (component.typeId === 'select') {
      for (const childId of children.get(id) || []) {
        const child = byId.get(childId);
        if (!child) continue;
        if (child.typeId === 'menu_item' || child.typeId === 'text') {
          rendered.add(childId);
          const option = document.createElement('option');
          option.value = child.props?.text_value ?? child.props?.name ?? child.id;
          option.textContent = child.props?.name || child.props?.text_value || child.id;
          if (child.props?.enabled === false) option.disabled = true;
          element.append(option);
        } else {
          mount(childId, element, {x: props.x || 0, y: props.y || 0});
        }
      }
      if (props.text_value) element.value = props.text_value;
      if (element.selectedIndex < 0 && element.options.length) element.selectedIndex = 0;
    } else {
      for (const childId of children.get(id) || []) {
        mount(childId, element, {x: props.x || 0, y: props.y || 0});
      }
    }

    const linkedInputs = inputTargets.get(id) || [];
    const linkedOutputs = outputTargets.get(id) || [];
    if (linkedOutputs.length) element.dataset.outputTargets = linkedOutputs.join(',');

    if (component.typeId === 'button' || component.typeId === 'menu_item') {
      element.addEventListener('click', () => {
        const values = readLinkedInputs(root, linkedInputs);
        const event = {
          event_type: 'successful_action',
          element_id: id,
          action_id: props.action_id || undefined
        };
        if (linkedInputs.length || linkedOutputs.length) {
          event.property = 'action_context';
          event.new_value = {
            input_values: values,
            output_target_ids: linkedOutputs
          };
        }
        sendEvent(event).catch(error => feedback(error.message));
      });
    } else if (['text_field', 'text_area', 'slider', 'select'].includes(component.typeId)) {
      element.addEventListener('focus', () => sendEvent({event_type: 'focus', element_id: id}).catch(error => feedback(error.message)));
      element.addEventListener('blur', () => sendEvent({event_type: 'blur', element_id: id}).catch(error => feedback(error.message)));
      element.addEventListener('change', () => {
        const event = {
          event_type: 'successful_action',
          element_id: id,
          action_id: props.action_id || undefined,
          property: 'input_value',
          new_value: null
        };
        const inputValue = readInputValue(element);
        event.new_value = linkedInputs.length || linkedOutputs.length
          ? {
              value: inputValue,
              input_values: linkedInputs.length ? readLinkedInputs(root, linkedInputs) : {},
              output_target_ids: linkedOutputs
            }
          : inputValue;
        sendEvent(event).catch(error => feedback(error.message));
      });
    }
  }

  const roots = model.components.filter(component => !childIds.has(component.id));
  roots.sort((a, b) => (a.props?.order ?? 0) - (b.props?.order ?? 0));
  for (const component of roots) mount(component.id, root);
  for (const component of model.components) {
    if (!rendered.has(component.id)) mount(component.id, root);
  }

  document.getElementById('interface-title').textContent = model.title || model.id || INTERFACE;
  document.getElementById('empty-state').hidden = model.components.length !== 0;
  document.getElementById('ui-view').textContent = JSON.stringify(model, null, 2);
}

async function pollRuntime() {
  try {
    const {commands} = await api('/api/runtime/pending?' + CONTEXT);
    for (const command of commands) {
      if (seen.has(command.token)) continue;
      seen.add(command.token);
      let success = false;
      try {
        renderInterface(command.model);
        success = true;
      } catch (error) {
        console.error(error);
      }
      await api('/api/runtime/ack', {
        method: 'POST',
        body: JSON.stringify({token: command.token, success})
      });
    }
  } catch (error) {
    console.error('Ошибка связи с runtime', error);
  }
  setTimeout(pollRuntime, 200);
}

async function refresh() {
  const [health, userModel, state] = await Promise.all([
    api('/api/health'),
    api('/api/model/' + encodeURIComponent(USER)),
    api('/api/ui-state?' + CONTEXT)
  ]);

  const status = document.getElementById('health');
  status.innerHTML = health.ok ? '<i></i> Система активна' : '<i></i> Нет подключения';
  status.classList.toggle('offline', !health.ok);
  document.getElementById('interface-id').textContent = 'interface_id: ' + state.interface_id;
  document.getElementById('ui-version').textContent = state.version || '—';
  document.getElementById('ui-version').title = state.version || '';
  document.getElementById('model-view').textContent = userModel.model
    ? JSON.stringify(userModel.model, null, 2)
    : 'Пока нет событий пользователя';
  document.getElementById('pkg-view').textContent = JSON.stringify(state.packages || [], null, 2);
  renderInterface(state.model);
}

document.getElementById('btn-refresh').addEventListener('click', () => {
  refresh().catch(error => feedback(error.message));
});
document.getElementById('btn-reset-b').addEventListener('click', async () => {
  try {
    await api('/api/reset-b', {method: 'POST', body: '{}'});
    feedback('Ограничение повторов B сброшено.');
  } catch (error) {
    feedback(error.message);
  }
});
document.getElementById('theme').addEventListener('change', event => {
  document.body.classList.toggle('theme-dark', event.target.value === 'dark');
});
document.title = INTERFACE + ' — SC UI Runtime';
document.getElementById('interface-id').textContent = 'interface_id: ' + INTERFACE;

pollRuntime();
refresh().catch(error => {
  document.getElementById('health').classList.add('offline');
  feedback('Не удалось загрузить интерфейс ' + INTERFACE + ': ' + error.message);
});
