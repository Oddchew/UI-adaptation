"""Platform-neutral snapshot of the SC UI model and adaptation policy."""
from __future__ import annotations

import copy
from typing import Any

PROPERTY_TYPES = {
    'name': str, 'x': (int, float), 'y': (int, float), 'width': (int, float),
    'height': (int, float), 'order': (int, float), 'visible': bool, 'enabled': bool,
    'opacity': (int, float), 'text_value': str, 'tooltip': str, 'action_id': str,
    'background_color': str, 'color': str, 'border_color': str,
    'border_width': (int, float), 'border_style': str, 'corner_radius': (int, float),
    'font_size': (int, float), 'font_weight': str, 'text_align': str,
    'padding': (int, float), 'margin': (int, float), 'min_width': (int, float),
    'min_height': (int, float), 'max_width': (int, float), 'max_height': (int, float),
}
COMPONENT_TYPES = frozenset(('image', 'sound', 'text', 'divider', 'spacer', 'menu',
    'menu_bar', 'list', 'scroll', 'window', 'text_field', 'text_area', 'slider',
    'select', 'button', 'menu_item'))


def tutor_model(interface_id: str = 'python_tutor_model') -> dict[str, Any]:
    return {'id': interface_id, 'title': 'Python tutor', 'components': [
        {'id': 'task_panel', 'typeId': 'window', 'props': {'visible': True}},
        {'id': 'code_editor', 'typeId': 'text_area', 'props': {'visible': True}},
        {'id': 'hints_panel', 'typeId': 'window', 'props': {'visible': False}},
        {'id': 'results_panel', 'typeId': 'window', 'props': {'visible': True}},
        {'id': 'history_panel', 'typeId': 'window', 'props': {'visible': True}},
        {'id': 'history_content', 'typeId': 'list', 'props': {'visible': True}},
        {'id': 'dialog_panel', 'typeId': 'window', 'props': {'visible': True}},
        {'id': 'advanced_panel', 'typeId': 'window', 'props': {'visible': True}},
    ], 'links': [{'id': 'history_contains', 'kind': 'contains',
                 'sourceId': 'history_panel', 'targetId': 'history_content'}]}


def normalize_model(model: dict, interface_id: str) -> dict:
    """Accept snapshots created by the previous local version without mutating them."""
    if 'components' in model:
        result = copy.deepcopy(model)
        if result.get('id') != interface_id:
            raise ValueError('interface_id_mismatch')
        ids = [item.get('id') for item in result['components']]
        if any(not isinstance(x, str) or not x for x in ids) or len(ids) != len(set(ids)):
            raise ValueError('ambiguous_component_id')
        if any(item.get('typeId') not in COMPONENT_TYPES or not isinstance(item.get('props'), dict) for item in result['components']):
            raise ValueError('invalid_component')
        if not isinstance(result.get('links'), list):
            raise ValueError('invalid_links')
        if any(link.get('kind') != 'contains' or link.get('sourceId') not in ids or link.get('targetId') not in ids for link in result['links']):
            raise ValueError('invalid_link')
        return result
    result = tutor_model(interface_id)
    for component in result['components']:
        values = model.get(component['id'])
        if isinstance(values, dict):
            component['props'].update({k: v for k, v in values.items() if k in PROPERTY_TYPES})
    old_history = model.get('history_panel', {})
    if 'collapsed' in old_history:
        component_by_id(result, 'history_content')['props']['visible'] = not old_history['collapsed']
    return result


def component_by_id(model: dict, component_id: str) -> dict | None:
    matches = [component for component in model['components'] if component.get('id') == component_id]
    if len(matches) > 1:
        raise ValueError('ambiguous_component_id')
    return matches[0] if matches else None


def display_state(model: dict) -> dict:
    """Compatibility view for the demonstration UI."""
    result = {c['id']: copy.deepcopy(c['props']) for c in model['components']}
    result.setdefault('history_panel', {})['collapsed'] = not result.get('history_content', {}).get('visible', True)
    return result


class AdaptationPolicy:
    """Explicit per-interface access; user data is never a writable UI property."""
    def __init__(self, allowed: dict[str, set[str]] | None = None) -> None:
        self.allowed = allowed if allowed is not None else {
            'hints_panel': {'visible'}, 'history_content': {'visible'}}

    def validate(self, component: dict, prop: str, value: Any) -> str | None:
        if prop not in PROPERTY_TYPES or prop not in self.allowed.get(component['id'], set()):
            return 'unsupported_property'
        expected = PROPERTY_TYPES[prop]
        types = expected if isinstance(expected, tuple) else (expected,)
        if type(value) not in types:
            return 'invalid_value'
        if prop not in component['props']:
            return 'missing_property'
        return None
