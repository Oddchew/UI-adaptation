"""Read and update the editor's SC UI model through py-sc-client.

SC writes require external exclusive-writer coordination. A check followed by
set_link_contents is not an atomic compare-and-set across SC clients.
"""
from __future__ import annotations

import asyncio
import inspect
import re
from dataclasses import dataclass
from typing import Any

from .model import COMPONENT_TYPES, PROPERTY_TYPES, component_by_id


class ScModelError(RuntimeError):
    pass


class ScAmbiguousModel(ScModelError):
    pass


def _system_id(value: str) -> str:
    cleaned = re.sub(r'[^a-zA-Z0-9_]', '_', value) or 'node'
    return 'n_' + cleaned if cleaned[0].isdigit() else cleaned


def _decode_value(key: str, raw: str) -> Any:
    typ = PROPERTY_TYPES[key]
    if typ is bool:
        if raw.lower() in ('true', '1'): return True
        if raw.lower() in ('false', '0'): return False
        raise ScModelError(f'invalid boolean value for {key}')
    if typ == (int, float):
        try:
            number = float(raw)
            if not __import__('math').isfinite(number): raise ValueError()
            return int(number) if number.is_integer() else number
        except ValueError as exc:
            raise ScModelError(f'invalid numeric value for {key}') from exc
    return raw


@dataclass(frozen=True)
class ScProperty:
    interface_id: str
    component_id: str
    property: str
    value: Any
    link_address: Any


class ScUiModelAdapter:
    def __init__(self, url: str = 'ws://127.0.0.1:8090/ws_json', *, exclusive_writer: bool = False) -> None:
        self.url = url
        self.exclusive_writer = exclusive_writer
        self._lock = asyncio.Lock()

    async def connect(self) -> None:
        from sc_client.client import connect, is_connected
        if not is_connected():
            await asyncio.to_thread(connect, self.url)

    def _key(self, identifier: str):
        from sc_client.client import resolve_keynodes
        from sc_client.models import ScIdtfResolveParams
        addresses = resolve_keynodes(ScIdtfResolveParams(idtf=identifier, type=None))
        if not addresses or not addresses[0] or not addresses[0].is_valid():
            raise ScModelError(f'missing SC keynode: {identifier}')
        return addresses[0]

    @staticmethod
    def _content(addr) -> str:
        from sc_client.client import get_link_content
        content = get_link_content(addr)
        if not content:
            raise ScModelError('empty SC link')
        return str(content[0].data)

    def _relations(self, owner, relation: str) -> list:
        from sc_client.client import search_by_template
        from sc_client.constants import sc_type
        from sc_client.models import ScTemplate
        template = ScTemplate()
        template.quintuple(owner, sc_type.VAR_COMMON_ARC, sc_type.VAR_NODE >> '_target',
                           sc_type.VAR_PERM_POS_ARC, self._key(relation))
        return [row.get('_target') for row in search_by_template(template)]

    def _id(self, node) -> str:
        from sc_client.client import search_by_template
        from sc_client.constants import sc_type
        from sc_client.models import ScTemplate
        t = ScTemplate()
        t.quintuple(node, sc_type.VAR_COMMON_ARC, sc_type.VAR_NODE_LINK >> '_id',
                    sc_type.VAR_PERM_POS_ARC, self._key('nrel_ui_id'))
        rows = search_by_template(t)
        if len(rows) != 1: raise ScAmbiguousModel('expected exactly one nrel_ui_id')
        return self._content(rows[0].get('_id'))

    def _interface(self, interface_id: str):
        from sc_client.client import search_by_template
        from sc_client.constants import sc_type
        from sc_client.models import ScTemplate
        node = self._key(_system_id(interface_id))
        template = ScTemplate()
        template.triple(self._key('concept_ui_interface'), sc_type.VAR_PERM_POS_ARC, node)
        if not search_by_template(template) or self._id(node) != interface_id:
            raise ScModelError('interface not found or ID mismatch')
        return node

    def _component(self, interface, component_id: str):
        components = self._relations(interface, 'nrel_ui_has_component')
        matches = [node for node in components if self._id(node) == component_id]
        if len(matches) != 1: raise ScAmbiguousModel(f'component not found or ambiguous: {component_id}')
        return matches[0]

    def _property(self, node, key: str):
        from sc_client.client import search_by_template
        from sc_client.constants import sc_type
        from sc_client.models import ScTemplate
        if key not in PROPERTY_TYPES: raise ScModelError(f'unknown property: {key}')
        t = ScTemplate()
        t.triple(self._key('concept_ui_' + key), sc_type.VAR_PERM_POS_ARC, sc_type.VAR_NODE >> '_prop')
        t.triple('_prop', sc_type.VAR_PERM_POS_ARC, node)
        t.quintuple('_prop', sc_type.VAR_COMMON_ARC, sc_type.VAR_NODE_LINK >> '_value',
                    sc_type.VAR_PERM_POS_ARC, self._key('nrel_ui_value'))
        rows = search_by_template(t)
        if len(rows) != 1: raise ScAmbiguousModel(f'property missing or ambiguous: {key}')
        link = rows[0].get('_value')
        return _decode_value(key, self._content(link)), link

    def _component_type(self, node) -> str:
        from sc_client.client import search_by_template
        from sc_client.constants import sc_type
        from sc_client.models import ScTemplate
        matches = []
        for type_id in COMPONENT_TYPES:
            template = ScTemplate()
            template.triple(self._key('concept_ui_' + type_id), sc_type.VAR_PERM_POS_ARC, node)
            if search_by_template(template):
                matches.append(type_id)
        if len(matches) != 1:
            raise ScAmbiguousModel('component has no unique UI type')
        return matches[0]

    async def read_model(self, interface_id: str) -> dict:
        """Read an editor-compatible snapshot. Does not create SC keynodes."""
        async with self._lock:
            def read():
                interface = self._interface(interface_id)
                nodes = self._relations(interface, 'nrel_ui_has_component')
                components = []
                addresses = []
                ids = set()
                for node in nodes:
                    identifier = self._id(node)
                    if identifier in ids:
                        raise ScAmbiguousModel('duplicate component ID')
                    ids.add(identifier)
                    props = {key: self._property(node, key)[0] for key in PROPERTY_TYPES}
                    components.append({'id': identifier, 'typeId': self._component_type(node), 'props': props})
                    addresses.append((node, identifier))
                links = []
                for parent, parent_id in addresses:
                    for child in self._relations(parent, 'nrel_ui_contains'):
                        matches = [identifier for addr, identifier in addresses if addr == child]
                        if len(matches) != 1:
                            raise ScAmbiguousModel('contains target is outside interface or ambiguous')
                        links.append({'id': f'link_{len(links) + 1}', 'kind': 'contains',
                                      'sourceId': parent_id, 'targetId': matches[0]})
                return {'id': interface_id, 'title': self._property(interface, 'name')[0],
                        'components': components, 'links': links}
            return await asyncio.to_thread(read)

    async def read_property(self, interface_id: str, component_id: str, key: str) -> ScProperty:
        async with self._lock:
            def read():
                node = self._component(self._interface(interface_id), component_id)
                value, link = self._property(node, key)
                return ScProperty(interface_id, component_id, key, value, link)
            return await asyncio.to_thread(read)

    async def update_property(self, interface_id: str, component_id: str, key: str,
                              expected: Any, new: Any) -> None:
        if not self.exclusive_writer:
            raise ScModelError('SC writes require external exclusive-writer coordination')
        if type(expected) is not type(new):
            raise ScModelError('property types differ')
        async with self._lock:
            def update():
                from sc_client.client import set_link_contents
                from sc_client.models import ScLinkContent, ScLinkContentType
                node = self._component(self._interface(interface_id), component_id)
                current, link = self._property(node, key)
                if type(current) is not type(expected) or current != expected:
                    raise ScModelError('old_value_mismatch')
                raw = str(new).lower() if isinstance(new, bool) else str(new)
                if not set_link_contents(ScLinkContent(raw, ScLinkContentType.STRING, link)):
                    raise ScModelError('SC update failed')
            await asyncio.to_thread(update)


class ScModelRuntime:
    """Apply one UI property in SC via ExclusiveScWriter, then confirm with a renderer.

    A scoped request requires a resolver for an existing per-session SC model
    and a renderer that accepts user_id and session_id.
    """
    def __init__(
        self,
        model_adapter: ScUiModelAdapter,
        renderer: Any,
        scope_resolver=None,
        writer: Any = None,
    ) -> None:
        if not model_adapter.exclusive_writer:
            raise ScModelError('SC runtime requires an exclusive writer')
        self.model_adapter = model_adapter
        self.renderer = renderer
        self.scope_resolver = scope_resolver
        # Prefer explicit ExclusiveScWriter; create one if omitted.
        if writer is None:
            from .sc_writer import ExclusiveScWriter
            writer = ExclusiveScWriter(model_adapter)
        self.writer = writer
        self._lock = asyncio.Lock()

    async def activate(self, interface_id: str, model: dict, *, user_id=None, session_id=None) -> None:
        physical_id = interface_id
        if session_id:
            if not self.scope_resolver:
                raise ScModelError('SC session-specific model routing is not configured')
            physical_id = self.scope_resolver(interface_id, user_id, session_id)
            if inspect.isawaitable(physical_id):
                physical_id = await physical_id
            if not isinstance(physical_id, str) or not physical_id:
                raise ScModelError('SC session-specific model is unavailable')
            parameters = inspect.signature(self.renderer.activate).parameters
            if 'session_id' not in parameters or 'user_id' not in parameters:
                raise ScModelError('renderer does not support session routing')
        async with self._lock:
            current = await self.model_adapter.read_model(physical_id)
            def links(snapshot):
                return {(link['kind'], link['sourceId'], link['targetId']) for link in snapshot['links']}
            if model['id'] != interface_id or current['title'] != model['title'] or links(current) != links(model):
                raise ScModelError('SC model structure differs')
            if {c['id'] for c in current['components']} != {c['id'] for c in model['components']}:
                raise ScModelError('SC model components differ')
            changes = []
            for existing in current['components']:
                updated = component_by_id(model, existing['id'])
                if updated is None or existing['typeId'] != updated['typeId'] or set(existing['props']) != set(updated['props']):
                    raise ScModelError('SC model component differs')
                for key, old in existing['props'].items():
                    new = updated['props'][key]
                    if old != new or type(old) is not type(new):
                        changes.append((existing['id'], key, old, new))
            if len(changes) > 1:
                raise ScModelError('SC runtime requires a single-property update')
            if changes:
                component_id, key, old, new = changes[0]
                result = await self.writer.apply(
                    interface_id=physical_id,
                    component_id=component_id,
                    property=key,
                    expected=old,
                    new_value=new,
                    request_id=f'sc-runtime:{physical_id}:{component_id}:{key}',
                )
                if not result.ok and result.error not in (None, 'no_change_required'):
                    raise ScModelError(f'SC write failed: {result.error}')
            if session_id:
                await self.renderer.activate(interface_id, model, user_id=user_id, session_id=session_id)
            else:
                await self.renderer.activate(interface_id, model)
