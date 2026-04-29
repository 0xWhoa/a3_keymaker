"""Data model for the keymaker.

One ``Action`` per row in the rendered HTML. Sections + categories drive the
two-level collapsible structure: ``Configure Base`` and ``Configure Addons``
at the top, categories under each.
"""

from __future__ import annotations

from dataclasses import dataclass, field

SECTION_BASE = "Configure Base"
SECTION_BASE_MODS = "Configure Base - Mods"
SECTION_ADDONS = "Configure Addons"

# Render order, top to bottom.
SECTION_ORDER = (SECTION_BASE, SECTION_BASE_MODS, SECTION_ADDONS)


@dataclass(frozen=True)
class Action:
    """One row of the keybindings keymap.

    ``key_text`` is the engine-formatted string the user sees in the dialog
    (e.g. ``"I"``, ``"Right Ctrl+M"``, ``"Joystick Btn. #7"``).
    Empty string means the action is unbound.

    ``action_id`` is the engine action ID for vanilla actions (e.g. ``gear``)
    or the Mappings preset id for old-style mod actions (e.g.
    ``A10C_Loadout_Menu``). Empty for CBA addon actions which don't expose
    a stable id via the UI.
    """

    section: str        # "Configure Base" or "Configure Addons"
    category: str       # category label as shown in the SHOW: / ADDON: dropdown
    label: str          # action label as shown in the ACTION column
    key_text: str       # formatted key text or "" if unbound
    action_id: str = "" # engine ID, mod-preset ID, or "" if unknown

    @property
    def bound(self) -> bool:
        return bool(self.key_text)

    @property
    def display_section(self) -> str:
        """User-facing section name. Old-style mods are stored internally
        as SECTION_BASE_MODS for semantic clarity, but render under
        SECTION_BASE in the HTML (they're inlined behind a ``=== Mods ===``
        separator)."""
        if self.section == SECTION_BASE_MODS:
            return SECTION_BASE
        return self.section

    @property
    def path(self) -> str:
        return f"{self.display_section} > {self.category} > {self.label}"


@dataclass
class Report:
    generated_at_iso: str
    source_dump_path: str | None = None
    actions: list[Action] = field(default_factory=list)
