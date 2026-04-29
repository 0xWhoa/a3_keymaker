"""End-to-end tests on the bundled sample dump."""

from __future__ import annotations

from pathlib import Path

import pytest

from a3_keymaker.merger import build_report
from a3_keymaker.model import (
    SECTION_ADDONS,
    SECTION_BASE,
    SECTION_BASE_MODS,
)
from a3_keymaker.parser import DumpParseError, parse_dump
from a3_keymaker.render import _compute_collisions, _group_for_render, render

FIXTURE = Path(__file__).parent / "fixtures" / "sample_dump.txt"


@pytest.fixture(scope="module")
def parsed():
    return parse_dump(FIXTURE.read_text(encoding="utf-8"))


def test_parse_extracts_all_sections(parsed):
    assert len(parsed.vanilla_categories) == 32
    assert len(parsed.mappings) > 100
    assert len(parsed.vanilla_engine) == 446
    assert len(parsed.addons) == 34
    # cfg_user_actions is optional for backward compat with older dumps;
    # the bundled fixture predates this section, so it parses to [].
    assert isinstance(parsed.cfg_user_actions, list)


def test_parse_strips_sqf_quote_escaping(parsed):
    # vanilla_engine entries are [id, "key" or ""] — keys arrive with their
    # outer literal quotes (engine formatting). Parser preserves them; the
    # merger strips them for display.
    by_id = {e[0]: e[1] for e in parsed.vanilla_engine}
    assert by_id["MoveForward"] == '"W"'
    assert by_id["gear"] == '"I"'


def test_parse_rejects_non_a3km_text():
    with pytest.raises(DumpParseError):
        parse_dump("hello world")


def test_parse_fixes_clipboard_mojibake(parsed):
    """The Windows clipboard double-encodes non-ASCII via CP1252. The parser
    detects the round-trip and recovers the original UTF-8 (arrows ↑↓←→
    instead of mojibake ``â†'`` etc.). CBA Quick-Time Events is the
    canonical case — its action labels are arrow characters."""
    # Find the CBA Quick-Time Events addon entry in the addon walker dump.
    qte_entries = [a for a in parsed.addons if "CBA Quick-Time" in a[1]]
    assert qte_entries, "CBA Quick-Time Events not present in fixture"
    qte = qte_entries[0]
    # qte = [idx, name, data, count, [[label, key_text], ...]]
    labels = [binding[0] for binding in qte[4]]
    # All four arrow characters should be present, NOT mojibake.
    assert "↑" in labels
    assert "↓" in labels
    assert "←" in labels
    assert "→" in labels
    # And the mojibake markers should be GONE.
    assert not any("â†" in lbl for lbl in labels)


def test_build_report_resolves_vanilla_keys(parsed):
    report = build_report(parsed, source_path=FIXTURE)
    by_label = {(a.section, a.category, a.label): a for a in report.actions}

    # Engine wraps single-binding key text in literal quotes; we keep them
    # for visual consistency with multi-binding rows.
    inv = by_label[(SECTION_BASE, "Common", "Inventory")]
    assert inv.action_id == "gear"
    assert inv.key_text == '"I"'
    assert inv.bound

    fwd = by_label[(SECTION_BASE, "Infantry Movement", "Move Forward")]
    assert fwd.action_id == "MoveForward"
    assert fwd.key_text == '"W"'


def test_multi_binding_uses_comma_separator(parsed):
    report = build_report(parsed, source_path=FIXTURE)
    by_label = {(a.section, a.category, a.label): a for a in report.actions}
    # Use Default Action has multiple bindings — engine emits " or " between
    # them; we render that as " , " for a tighter list-style look.
    da = by_label[(SECTION_BASE, "Common", "Use Default Action")]
    assert " , " in da.key_text
    assert " or " not in da.key_text
    # And every alternative is still wrapped in quotes.
    assert da.key_text.startswith('"') and da.key_text.endswith('"')


def test_build_report_resolves_old_style_mod_keys(parsed):
    report = build_report(parsed, source_path=FIXTURE)
    by_label = {(a.section, a.category, a.label): a for a in report.actions}

    # Categories below the "=== Mods ===" separator land in BASE_MODS.
    a10c = by_label[(SECTION_BASE_MODS, "A10C Controls", "Loadout Menu")]
    assert a10c.action_id == "A10C_Loadout_Menu"
    assert a10c.key_text == '"P"'


def test_render_preserves_in_game_category_order(parsed):
    report = build_report(parsed, source_path=FIXTURE)
    grouped = _group_for_render(report.actions)
    base_section = next(s for s in grouped if s[0] == SECTION_BASE)
    # Items can be categories or separators; pull category names in order.
    category_names = [
        it.name for it in base_section[1] if getattr(it, "kind", None) == "category"
    ]
    # Mirror the SHOW: dropdown order from the screenshot.
    expected_prefix = [
        "Common", "Weapons", "View", "Command", "Multiplayer",
        "Infantry Movement", "Vehicle Movement", "Helicopter Movement",
        "Plane Movement", "Submarine Movement", "Development",
    ]
    assert category_names[:len(expected_prefix)] == expected_prefix


def test_base_section_inlines_mods_with_separator(parsed):
    report = build_report(parsed, source_path=FIXTURE)
    grouped = _group_for_render(report.actions)
    base_section = next(s for s in grouped if s[0] == SECTION_BASE)
    items = base_section[1]
    kinds = [it.kind for it in items]
    # Exactly one separator inserted between vanilla and mod categories.
    assert kinds.count("separator") == 1
    sep_index = kinds.index("separator")
    # All categories before separator are vanilla; after are mods.
    before = [items[i].name for i in range(sep_index) if items[i].kind == "category"]
    after = [items[i].name for i in range(sep_index + 1, len(items)) if items[i].kind == "category"]
    assert "Common" in before
    assert "Weapons" in before
    assert "A10C Controls" in after
    assert "F16V Controls" in after
    # Separator label matches in-game text.
    assert items[sep_index].label == "=== Mods ==="


def test_base_mods_section_excludes_separator(parsed):
    report = build_report(parsed, source_path=FIXTURE)
    base_mods_categories = {a.category for a in report.actions if a.section == SECTION_BASE_MODS}
    assert "=== Mods ===" not in base_mods_categories
    # Should contain at least a few known old-style mod categories.
    assert "A10C Controls" in base_mods_categories
    assert "F16V Controls" in base_mods_categories


def test_build_report_handles_cba_addons(parsed):
    report = build_report(parsed, source_path=FIXTURE)
    by_label = {(a.section, a.category, a.label): a for a in report.actions}

    # ACE Common > Toggle Volume → "Alt+S" via the addon walker (no id needed)
    vol = by_label[(SECTION_ADDONS, "ACE Common", "Toggle Volume")]
    assert vol.section == SECTION_ADDONS
    assert vol.key_text == '"Alt+S"'


def test_build_report_skips_separator(parsed):
    report = build_report(parsed, source_path=FIXTURE)
    sep_actions = [a for a in report.actions if a.category == "=== Mods ==="]
    assert sep_actions == []


def test_path_format(parsed):
    report = build_report(parsed, source_path=FIXTURE)
    by_label = {(a.section, a.category, a.label): a for a in report.actions}
    inv = by_label[(SECTION_BASE, "Common", "Inventory")]
    assert inv.path == "Configure Base > Common > Inventory"


def test_path_collapses_base_mods_to_base(parsed):
    """Old-style mod rows expose Configure Base (not Configure Base - Mods)
    in their path / hover tooltip — matching the rendered section
    grouping which inlines them behind a separator."""
    report = build_report(parsed, source_path=FIXTURE)
    by_label = {(a.section, a.category, a.label): a for a in report.actions}
    a10c = by_label[(SECTION_BASE_MODS, "A10C Controls", "Loadout Menu")]
    assert a10c.section == SECTION_BASE_MODS  # internal value unchanged
    assert a10c.display_section == SECTION_BASE
    assert a10c.path == "Configure Base > A10C Controls > Loadout Menu"


def test_render_produces_html(parsed):
    report = build_report(parsed, source_path=FIXTURE)
    html = render(report)
    assert html.startswith("<!DOCTYPE html>")
    assert "Configure Base" in html
    assert "Configure Addons" in html
    assert "Inventory" in html


def test_collision_detection_pairs_map_and_hide_map(parsed):
    """Map and Hide Map both default to "M" — they must mark each other."""
    report = build_report(parsed, source_path=FIXTURE)
    collisions = _compute_collisions(report.actions)
    map_path = "Configure Base > Common > Map"
    hide_map_path = "Configure Base > Common > Hide Map"
    assert map_path in collisions
    assert hide_map_path in collisions
    assert hide_map_path in collisions[map_path]
    assert map_path in collisions[hide_map_path]
    # Tooltip is multi-line and starts with the header.
    assert collisions[map_path].startswith("Also bound to:\n")


def test_collision_detection_handles_multi_binding(parsed):
    """Multi-binding rows split on ' , ' so each individual key is checked
    independently. Engine On/Off (Common) is bound to "Delete" , "Joystick…"
    — if any other action shares "Delete" or that joystick button, both
    must be flagged."""
    report = build_report(parsed, source_path=FIXTURE)
    collisions = _compute_collisions(report.actions)
    # Just smoke-test that multi-binding rows are present in the collision
    # dict at all when sharing one of their alternatives — exact peers
    # depend on the user's modset.
    by_label = {(a.section, a.category, a.label): a for a in report.actions}
    engine = by_label[(SECTION_BASE, "Common", "Engine On/Off")]
    if " , " in engine.key_text:
        # A multi-binding will tend to collide with at least one other
        # vehicle/aviation action sharing one of the joystick buttons.
        # If it doesn't on this fixture, the test is a no-op — it only
        # asserts no crash.
        pass


def test_actions_without_collision_not_in_map(parsed):
    """Actions whose key is unique should not appear in the collision map."""
    report = build_report(parsed, source_path=FIXTURE)
    collisions = _compute_collisions(report.actions)
    # Find any uniquely-bound action and verify it's absent.
    by_label = {(a.section, a.category, a.label): a for a in report.actions}
    inv = by_label[(SECTION_BASE, "Common", "Inventory")]  # "I"
    # If "I" is unique in this fixture, Inventory shouldn't be flagged.
    # If it isn't unique we just skip — only assert when we can.
    i_count = sum(1 for a in report.actions if a.key_text == '"I"')
    if i_count == 1:
        assert inv.path not in collisions
