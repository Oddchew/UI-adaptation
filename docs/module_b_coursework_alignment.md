# Module B coursework alignment

This change set applies the unambiguous Module B requirements from the coursework:

- Automatic adaptation requires at least three events in the observation package, including packages whose latest event is a successful action.
- Manual mode and `manual_override` are checked before legacy event-specific handling and veto automatic commands.
- Protected targets (`code_editor`, `code_editor.content`, `task_stage`, and `results_criteria`) are rejected for every interface, not only the legacy Python tutor.
- Rules marked `respect_hint_hidden` honor the per-interface/per-session `hint_hidden_sessions` state for every interface.
- The hint error-count rule counts errors across error codes; the specification does not require matching error codes.

## Rule 2 and Rule 3: specification conflict retained for review

The coursework describes different behaviors in its requirements section and in the later prototype section:

- Rule 2 is described as increasing label font size after at least three help requests within five actions. The current prototype rule instead targets `main_content.font_size`, is disabled by default, and has no five-action window.
- Rule 3 is described as collapsing a rarely used settings block when it has not been opened in the last ten sessions. The current prototype rule collapses `history_content` after repeated help requests without a successful check.

These behaviors are not interchangeable. This change deliberately does not silently choose one interpretation or invent new event/session semantics. The existing prototype rules remain unchanged until the coursework owner confirms which section is authoritative.

## Scope

The two rules above, the Module A event schema, and the corresponding UI component identifiers need a coordinated decision before implementation. Module C continues to validate and apply the resulting commands; this change does not alter its persistence or SC writer behavior.
