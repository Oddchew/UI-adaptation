"""Platform-neutral snapshot of the SC UI model and adaptation policy.

PROPERTY_TYPES / COMPONENT_TYPES come from catalog.py (aligned with
ostis-ui-editor docs/catalog.md).
"""
from __future__ import annotations

import copy
from typing import Any

from .catalog import (
    ADAPTABLE_PROPERTIES,
    COMPONENT_TYPES,
    LINK_KINDS,
    PROPERTY_TYPES,
    component_allows_action_id,
    default_policy_allowed,
    validate_link,
)


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
        type_by_id = {}
        for item in result['components']:
            if not isinstance(item, dict):
                raise ValueError('invalid_component')
            if item.get('typeId') not in COMPONENT_TYPES or not isinstance(item.get('props'), dict):
                raise ValueError('invalid_component')
            type_by_id[item['id']] = item['typeId']
            for key, value in item['props'].items():
                if key not in PROPERTY_TYPES:
                    raise ValueError('unknown_property')
                expected = PROPERTY_TYPES[key]
                allowed_types = expected if isinstance(expected, tuple) else (expected,)
                if type(value) not in allowed_types:
                    raise ValueError(f'invalid_property_value:{key}')
            if 'action_id' in item['props'] and not component_allows_action_id(item['typeId']):
                raise ValueError('action_id_not_allowed')
        if not isinstance(result.get('links'), list):
            raise ValueError('invalid_links')
        for link in result['links']:
            if not isinstance(link, dict):
                raise ValueError('invalid_link')
            kind = link.get('kind')
            src, tgt = link.get('sourceId'), link.get('targetId')
            if kind not in LINK_KINDS or src not in ids or tgt not in ids:
                raise ValueError('invalid_link')
            err = validate_link(kind, type_by_id[src], type_by_id[tgt])
            if err:
                raise ValueError(err)
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
    """Explicit per-interface access; user data is never a writable UI property.

    Default policy for the tutor demo keeps the previous narrow allow-list.
    For interfaces loaded from design-time, use from_catalog(component_ids).
    """

    def __init__(self, allowed: dict[str, set[str]] | None = None) -> None:
        self.allowed = allowed if allowed is not None else {
            'hints_panel': {'visible'}, 'history_content': {'visible'}}

    @classmethod
    def from_catalog(cls, component_ids: list[str], extra: dict[str, set[str]] | None = None) -> "AdaptationPolicy":
        allowed = default_policy_allowed(component_ids)
        if extra:
            for cid, props in extra.items():
                allowed.setdefault(cid, set()).update(props & ADAPTABLE_PROPERTIES)
        return cls(allowed)

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
