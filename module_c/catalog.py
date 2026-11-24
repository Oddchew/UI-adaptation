"""Shared UI component/property catalog aligned with ostis-ui-editor docs/catalog.md.

Design-time source of truth: https://github.com/vodo4kin/ostis-ui-editor
Run-time modules import this module so type and property IDs stay consistent.
"""

from __future__ import annotations

from typing import Any

# --- Component types (concept_ui_<id> in SC) ---
COMPONENT_TYPES: frozenset[str] = frozenset(
    (
        "image",
        "sound",
        "text",
        "divider",
        "spacer",
        "menu",
        "menu_bar",
        "list",
        "scroll",
        "window",
        "text_field",
        "text_area",
        "slider",
        "select",
        "button",
        "menu_item",
    )
)

# --- Property types: key -> Python type(s) (concept_ui_<key> in SC) ---
PROPERTY_TYPES: dict[str, type | tuple[type, ...]] = {
    "name": str,
    "x": (int, float),
    "y": (int, float),
    "width": (int, float),
    "height": (int, float),
    "order": (int, float),
    "visible": bool,
    "enabled": bool,
    "opacity": (int, float),
    "text_value": str,
    "tooltip": str,
    "action_id": str,
    "background_color": str,
    "color": str,
    "border_color": str,
    "border_width": (int, float),
    "border_style": str,
    "corner_radius": (int, float),
    "font_size": (int, float),
    "font_weight": str,
    "text_align": str,
    "padding": (int, float),
    "margin": (int, float),
    "min_width": (int, float),
    "min_height": (int, float),
    "max_width": (int, float),
    "max_height": (int, float),
}

# Properties that adaptation is allowed to change by default (policy can narrow).
ADAPTABLE_PROPERTIES: frozenset[str] = frozenset(
    {
        "visible",
        "enabled",
        "opacity",
        "font_size",
        "tooltip",
        "background_color",
        "color",
        "border_width",
        "corner_radius",
        "padding",
        "margin",
    }
)

# Properties that must never be adapted (content / task state).
FORBIDDEN_ADAPTATION_PROPERTIES: frozenset[str] = frozenset(
    {
        "text_value",
        "action_id",
        "name",
        "x",
        "y",
        "width",
        "height",
        "order",
    }
)

# SC keynode names used by the editor and adapters.
SC_CONCEPT_INTERFACE = "concept_ui_interface"
SC_NREL_HAS_COMPONENT = "nrel_ui_has_component"
SC_NREL_CONTAINS = "nrel_ui_contains"
SC_NREL_ID = "nrel_ui_id"
SC_NREL_VALUE = "nrel_ui_value"

DEFAULT_PROPERTY_VALUES: dict[str, Any] = {
    "x": 24,
    "y": 24,
    "order": 1,
    "visible": True,
    "enabled": True,
    "opacity": 1,
    "text_value": "",
    "tooltip": "",
    "action_id": "",
    "background_color": "#f4f4f4",
    "color": "#1a1a1a",
    "border_color": "#6f6f6f",
    "border_width": 1,
    "border_style": "solid",
    "corner_radius": 0,
    "font_size": 13,
    "font_weight": "normal",
    "text_align": "left",
    "padding": 0,
    "margin": 0,
    "min_width": 0,
    "min_height": 0,
    "max_width": 0,
    "max_height": 0,
}


def sc_concept_for_component(type_id: str) -> str:
    if type_id not in COMPONENT_TYPES:
        raise ValueError(f"unknown component type: {type_id}")
    return f"concept_ui_{type_id}"


def sc_concept_for_property(key: str) -> str:
    if key not in PROPERTY_TYPES:
        raise ValueError(f"unknown property: {key}")
    return f"concept_ui_{key}"


def is_adaptable_property(key: str) -> bool:
    return key in ADAPTABLE_PROPERTIES and key not in FORBIDDEN_ADAPTATION_PROPERTIES


def default_policy_allowed(
    component_ids: list[str] | None = None,
) -> dict[str, set[str]]:
    """Build a default AdaptationPolicy map: every known component may change adaptable props."""
    ids = component_ids or []
    return {cid: set(ADAPTABLE_PROPERTIES) for cid in ids}
