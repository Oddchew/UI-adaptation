"""Read and update the editor's SC UI model through py-sc-client.

SC writes require external exclusive-writer coordination. A check followed by
set_link_contents is not an atomic compare-and-set across SC clients.
"""
from __future__ import annotations

import asyncio
import inspect
import os
import re
import time
import uuid
from dataclasses import dataclass
from typing import Any

from .catalog import COMPONENT_TYPES, PROPERTY_TYPES, SC_NREL_FOR_LINK_KIND, component_allows_action_id
from .model import component_by_id


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
        self._key_cache = {}

    async def connect(self) -> None:
        from sc_client.client import connect, is_connected
        if not is_connected():
            await asyncio.to_thread(connect, self.url)

    def _key(self, identifier: str):
        from sc_client.client import resolve_keynodes
        from sc_client.models import ScIdtfResolveParams
        cached = self._key_cache.get(identifier)
        if cached is not None:
            return cached
        addresses = resolve_keynodes(ScIdtfResolveParams(idtf=identifier, type=None))
        if not addresses or not addresses[0] or not addresses[0].is_valid():
            raise ScModelError(f'missing SC keynode: {identifier}')
        self._key_cache[identifier] = addresses[0]
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

    def _property(self, node, key: str, *, required: bool = True):
        from sc_client.client import search_by_template
        from sc_client.constants import sc_type
        from sc_client.models import ScTemplate
        if key not in PROPERTY_TYPES:
            raise ScModelError(f'unknown property: {key}')
        t = ScTemplate()
        t.triple(self._key('concept_ui_' + key), sc_type.VAR_PERM_POS_ARC, sc_type.VAR_NODE >> '_prop')
        t.triple('_prop', sc_type.VAR_PERM_POS_ARC, node)
        t.quintuple('_prop', sc_type.VAR_COMMON_ARC, sc_type.VAR_NODE_LINK >> '_value',
                    sc_type.VAR_PERM_POS_ARC, self._key('nrel_ui_value'))
        rows = search_by_template(t)
        if not rows:
            if required:
                raise ScModelError(f'property missing: {key}')
            return None, None
        if len(rows) != 1:
            raise ScAmbiguousModel(f'property ambiguous: {key}')
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
                debug = os.environ.get("UI_RUNTIME_DEBUG") == "1"
                started = time.monotonic()

                def trace(stage, **fields):
                    if debug:
                        details = " ".join(f"{key}={value}" for key, value in fields.items())
                        print(
                            "[debug][SC_READ]",
                            stage,
                            details,
                            "elapsed_ms=", int((time.monotonic() - started) * 1000),
                            flush=True,
                        )

                trace("interface_start")
                interface = self._interface(interface_id)
                trace("interface_done")
                nodes = self._relations(interface, 'nrel_ui_has_component')
                trace("components_found", count=len(nodes))
                components = []
                addresses = []
                ids = set()
                for index, node in enumerate(nodes):
                    component_started = time.monotonic()
                    identifier = self._id(node)
                    if identifier in ids:
                        raise ScAmbiguousModel('duplicate component ID')
                    ids.add(identifier)
                    type_id = self._component_type(node)
                    props = {}
                    trace("component_start", index=index, component=identifier, type=type_id)
                    for key in PROPERTY_TYPES:
                        if key == 'action_id' and not component_allows_action_id(type_id):
                            continue
                        value, _ = self._property(node, key, required=False)
                        if value is not None:
                            props[key] = value
                    trace(
                        "component_done",
                        component=identifier,
                        properties=len(props),
                        duration_ms=int((time.monotonic() - component_started) * 1000),
                    )
                    components.append({'id': identifier, 'typeId': type_id, 'props': props})
                    addresses.append((node, identifier))
                links = []
                # contains / input_target / output_target (catalog link kinds)
                for kind, nrel in SC_NREL_FOR_LINK_KIND.items():
                    trace("links_start", kind=kind)
                    for parent, parent_id in addresses:
                        for child in self._relations(parent, nrel):
                            matches = [identifier for addr, identifier in addresses if addr == child]
                            if len(matches) != 1:
                                raise ScAmbiguousModel(
                                    f'{kind} target is outside interface or ambiguous'
                                )
                            links.append({
                                'id': f'link_{len(links) + 1}',
                                'kind': kind,
                                'sourceId': parent_id,
                                'targetId': matches[0],
                            })
                    trace("links_done", kind=kind)
                title, _ = self._property(interface, 'name', required=False)
                trace("model_done", components=len(components), links=len(links))
                return {'id': interface_id, 'title': title or interface_id,
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
        allow_shared_session_model: bool = False,
    ) -> None:
        if not model_adapter.exclusive_writer:
            raise ScModelError('SC runtime requires an exclusive writer')
        self.model_adapter = model_adapter
        self.renderer = renderer
        self.scope_resolver = scope_resolver
        self.allow_shared_session_model = allow_shared_session_model
        # Prefer explicit ExclusiveScWriter; create one if omitted.
        if writer is None:
            from .sc_writer import ExclusiveScWriter
            writer = ExclusiveScWriter(model_adapter)
        self.writer = writer
        self._lock = asyncio.Lock()

    def commands(self, user_id, session_id):
        """Expose the renderer's pending browser commands to the HTTP bridge."""
        return self.renderer.commands(user_id, session_id)

    def acknowledge(self, token, success):
        """Forward browser confirmation to the renderer waiting for activation."""
        return self.renderer.acknowledge(token, success)

    async def activate(self, interface_id: str, model: dict, *, user_id=None, session_id=None) -> None:
        physical_id = interface_id
        if session_id:
            if self.scope_resolver:
                physical_id = self.scope_resolver(interface_id, user_id, session_id)
                if inspect.isawaitable(physical_id):
                    physical_id = await physical_id
                if not isinstance(physical_id, str) or not physical_id:
                    raise ScModelError('SC session-specific model is unavailable')
            elif not self.allow_shared_session_model:
                raise ScModelError('SC session-specific model routing is not configured')
            parameters = inspect.signature(self.renderer.activate).parameters
            if 'session_id' not in parameters or 'user_id' not in parameters:
                raise ScModelError('renderer does not support session routing')
        debug = os.environ.get("UI_RUNTIME_DEBUG") == "1"
        started = time.monotonic()
        if debug:
            print(
                "[debug][SC_RUNTIME] waiting_for_lock",
                "interface=", interface_id,
                "physical=", physical_id,
                "user=", user_id,
                "session=", session_id,
                flush=True,
            )
        async with self._lock:
            if debug:
                print(
                    "[debug][SC_RUNTIME] read_model_start",
                    "elapsed_ms=", int((time.monotonic() - started) * 1000),
                    flush=True,
                )
            current = await self.model_adapter.read_model(physical_id)
            if debug:
                print(
                    "[debug][SC_RUNTIME] read_model_done",
                    "elapsed_ms=", int((time.monotonic() - started) * 1000),
                    "components=", len(current.get("components", [])),
                    flush=True,
                )
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
            rollback = None
            if changes:
                component_id, key, old, new = changes[0]
                request_id = f'sc-runtime:{physical_id}:{component_id}:{key}:{uuid.uuid4().hex}'
                if debug:
                    print(
                        "[debug][SC_RUNTIME] writer_start",
                        "component=", component_id,
                        "property=", key,
                        "elapsed_ms=", int((time.monotonic() - started) * 1000),
                        flush=True,
                    )
                result = await self.writer.apply(
                    interface_id=physical_id,
                    component_id=component_id,
                    property=key,
                    expected=old,
                    new_value=new,
                    request_id=request_id,
                    expected_version=self.writer.current_version(physical_id, component_id, key),
                )
                if debug:
                    print(
                        "[debug][SC_RUNTIME] writer_done",
                        "ok=", result.ok,
                        "error=", result.error,
                        "duration_ms=", result.duration_ms,
                        "elapsed_ms=", int((time.monotonic() - started) * 1000),
                        flush=True,
                    )
                if not result.ok and result.error not in (None, 'no_change_required'):
                    raise ScModelError(f'SC write failed: {result.error}')
                if result.error != 'no_change_required':
                    rollback = (component_id, key, old, new)
            try:
                if debug:
                    print(
                        "[debug][SC_RUNTIME] renderer_start",
                        "elapsed_ms=", int((time.monotonic() - started) * 1000),
                        flush=True,
                    )
                if session_id:
                    await self.renderer.activate(interface_id, model, user_id=user_id, session_id=session_id)
                elif 'user_id' in inspect.signature(self.renderer.activate).parameters:
                    await self.renderer.activate(interface_id, model, user_id=user_id)
                else:
                    await self.renderer.activate(interface_id, model)
                if debug:
                    print(
                        "[debug][SC_RUNTIME] renderer_done",
                        "elapsed_ms=", int((time.monotonic() - started) * 1000),
                        flush=True,
                    )
            except Exception as render_error:
                if rollback is not None:
                    component_id, key, old, new = rollback
                    rollback_result = await self.writer.apply(
                        interface_id=physical_id,
                        component_id=component_id,
                        property=key,
                        expected=new,
                        new_value=old,
                        request_id=f'{request_id}:rollback',
                        expected_version=result.new_version,
                    )
                    if not rollback_result.ok:
                        raise ScModelError(
                            f'renderer failed and SC rollback failed; recovery required: {rollback_result.error}'
                        ) from render_error
                raise ScModelError('renderer failed; SC update was rolled back') from render_error
