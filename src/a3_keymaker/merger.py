"""Merge a parsed SQF dump + the wiki vanilla_actions.json into a flat
``list[Action]`` for the keymap.

For each row in the UI walk we produce one ``Action``:

* **Configure Base** rows whose category matches a wiki category
  (Common, Weapons, View, …) → resolve action_id via the (category, label)
  pair from ``vanilla_actions.json``, then key_text via ``vanilla_engine``.
* **Configure Base** rows in old-style mod categories
  (A10C Controls, F16V Controls, H-60 Cockpit, …) → resolve action_id
  by searching ``mappings`` for an id whose underscore-suffix matches
  the label, disambiguated by category prefix when multiple candidates
  exist.
* **Configure Addons** rows from the addon walker → label + key_text
  come paired directly; no id lookup needed.
"""

from __future__ import annotations

import json
import re
from datetime import datetime, timezone
from importlib import resources
from pathlib import Path

from a3_keymaker.model import (
    SECTION_ADDONS,
    SECTION_BASE,
    SECTION_BASE_MODS,
    Action,
    Report,
)
from a3_keymaker.parser import ParsedDump


def build_report(dump: ParsedDump, source_path: Path | None = None) -> Report:
    wiki = _load_vanilla_actions()
    # (category, label) → action_id for the wiki vanilla list.
    wiki_lookup = {(a["category"], a["label"]): a["action_id"] for a in wiki}
    # action_id → engine-formatted key text (current binding).
    engine_keys = {entry[0]: _strip_outer_quotes(entry[1]) for entry in dump.vanilla_engine}
    # action_id → key text from the merged Mappings dump (used for old-style mods).
    mappings_keys = {entry[0]: _strip_outer_quotes(entry[1]) for entry in dump.mappings}
    # All known mod-style ids, used for suffix matching.
    all_mapping_ids = list(mappings_keys.keys())
    # CfgUserActions: authoritative (id, displayName, key_text) tuples for
    # every mod-registered action class — including those with no preset
    # default. Unlocks Turret Enhanced, F16V Subsystems, etc.
    # displayName is NOT unique across mods (e.g. "Loadout Menu" exists in
    # both A10C and F16V), so we keep all candidates per displayName and
    # disambiguate at lookup time by category prefix.
    user_action_by_display: dict[str, list[tuple[str, str]]] = {}
    user_action_by_id: dict[str, str] = {}
    for entry in dump.cfg_user_actions:
        uid, display, key = entry[0], entry[1], _strip_outer_quotes(entry[2])
        user_action_by_id[uid] = key
        if display:
            user_action_by_display.setdefault(display, []).append((uid, key))

    actions: list[Action] = []

    # --- Configure Base / Configure Base - Mods ---
    # Walk vanilla_categories in dump order (= in-game SHOW dropdown order).
    # Categories before the "=== Mods ===" separator (lbData == "") are
    # vanilla engine actions → SECTION_BASE. Categories after the separator
    # are old-style mod actions → SECTION_BASE_MODS.
    seen_separator = False
    for cat_entry in dump.vanilla_categories:
        # cat_entry = [idx, name, lbData, count, [[row_idx, label, lbData], ...]]
        _, cat_name, cat_data, _, rows = cat_entry
        if not cat_data:
            # Separator row ("=== Mods ===") — has no actions; flips section.
            seen_separator = True
            continue

        section = SECTION_BASE_MODS if seen_separator else SECTION_BASE

        for row in rows:
            label = row[1]
            action_id = ""
            key_text = ""

            if section == SECTION_BASE:
                action_id = wiki_lookup.get((cat_name, label), "")
                if action_id and action_id in engine_keys:
                    key_text = engine_keys[action_id]
            else:
                # Old-style mod row.
                # 1) Authoritative lookup: CfgUserActions displayName,
                #    disambiguated by category prefix when ambiguous.
                hit = _pick_user_action(label, cat_name, user_action_by_display)
                if hit is not None:
                    action_id, key_text = hit
                else:
                    # 2) Fallback: derive id by suffix-matching mappings ids.
                    derived_id = _match_mod_id(label, cat_name, all_mapping_ids)
                    if derived_id:
                        action_id = derived_id
                        # Prefer CfgUserActions key_text if we can find the
                        # same id there (it's the user's current binding,
                        # not just a preset default).
                        key_text = user_action_by_id.get(
                            derived_id, mappings_keys.get(derived_id, "")
                        )

            actions.append(
                Action(
                    section=section,
                    category=cat_name,
                    label=label,
                    key_text=key_text,
                    action_id=action_id,
                )
            )

    # --- Configure Addons: every CBA-registered addon ---
    for addon_entry in dump.addons:
        # addon_entry = [idx, name, lbData, count, [[label, key_text], ...]]
        _, addon_name, _, _, bindings = addon_entry
        for binding in bindings:
            label, key_text = binding[0], _strip_outer_quotes(binding[1])
            actions.append(
                Action(
                    section=SECTION_ADDONS,
                    category=addon_name,
                    label=label,
                    key_text=key_text,
                    action_id="",
                )
            )

    return Report(
        generated_at_iso=datetime.now(timezone.utc).isoformat(timespec="seconds"),
        source_dump_path=str(source_path) if source_path else None,
        actions=actions,
    )


def _strip_outer_quotes(s: str) -> str:
    """Normalize an engine/CBA-formatted key text for display.

    The engine wraps every binding in literal double-quotes (e.g. ``"N"``,
    ``"Right Ctrl+M"``, multi-binding ``"A" or "B"``). We keep those quotes
    intact for visual consistency — every row reads the same shape, with
    or without alternatives.

    We DO normalize the multi-binding separator: the engine emits
    ``" or "`` between alternatives; we render that as ``" , "`` (a
    comma flanked by the existing closing+opening quotes of each binding,
    plus a space on each side of the comma) for a tighter, more list-like
    look. Empty stays empty.
    """
    if not s:
        return s
    return s.replace('" or "', '" , "')


_NON_WORD_RE = re.compile(r"[^A-Za-z0-9]+")


def _label_to_suffix(label: str) -> str:
    """Convert a UI label to the underscore-suffix form used by mod IDs.

    ``"Loadout Menu"`` → ``"Loadout_Menu"``. Strips parenthetical asides
    and other punctuation so ``"GPS (Toggle)"`` → ``"GPS_Toggle"``.
    """
    cleaned = label.replace("(", "").replace(")", "")
    return _NON_WORD_RE.sub("_", cleaned).strip("_")


def _pick_user_action(
    label: str,
    category: str,
    by_display: dict[str, list[tuple[str, str]]],
) -> tuple[str, str] | None:
    """Pick the right (action_id, key_text) for a UI row from CfgUserActions.

    displayName isn't unique across mods (``"Loadout Menu"`` exists in both
    A10C and F16V categories). When multiple candidates share a displayName,
    pick the one whose action_id starts with the same first word as the
    UI category — e.g. ``"A10C Controls"`` → prefer id starting with
    ``A10C_``. Single candidate: return as-is. None: return None.
    """
    candidates = by_display.get(label)
    if not candidates:
        return None
    if len(candidates) == 1:
        return candidates[0]
    if category:
        first_word = category.split()[0].lower()
        for uid, key in candidates:
            if uid.lower().startswith(first_word):
                return (uid, key)
    return candidates[0]


def _match_mod_id(label: str, category: str, ids: list[str]) -> str:
    """Find the mappings id that corresponds to a UI row in a mod category.

    Strategy: convert the label to underscored form, look for ids that end
    with that suffix. If multiple match, prefer the one whose prefix
    correlates with the category's first word (e.g. ``"A10C"`` for
    ``"A10C Controls"``).
    """
    suffix = _label_to_suffix(label)
    if not suffix:
        return ""
    candidates = [i for i in ids if i.endswith("_" + suffix) or i == suffix]
    if not candidates:
        return ""
    if len(candidates) == 1:
        return candidates[0]
    # Disambiguate by category prefix.
    first_word = category.split()[0] if category else ""
    if first_word:
        narrowed = [c for c in candidates if c.lower().startswith(first_word.lower())]
        if narrowed:
            return narrowed[0]
    return candidates[0]


def _load_vanilla_actions() -> list[dict]:
    """Load the bundled wiki vanilla_actions.json from the installed package data."""
    with resources.files("a3_keymaker").joinpath("data/vanilla_actions.json").open(
        encoding="utf-8"
    ) as f:
        return json.load(f)["actions"]
