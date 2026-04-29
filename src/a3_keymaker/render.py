"""Render a ``Report`` to a single self-contained static HTML keymap.

Layout: two top-level ``<details>`` (Configure Base, Configure Addons),
each containing one nested ``<details>`` per category. Each category's
table lists ``Action | Assigned Key`` rows. Two filter inputs at the top
narrow rows by action name and key text; section/category counts in the
``<summary>`` lines update as rows hide. Empty categories collapse out.
"""

from __future__ import annotations

import base64
import html
import json
import re
from dataclasses import asdict, dataclass
from importlib import resources

from jinja2 import Environment, select_autoescape
from markupsafe import Markup

from a3_keymaker.model import (
    SECTION_ADDONS,
    SECTION_BASE,
    SECTION_BASE_MODS,
    Action,
    Report,
)


@dataclass
class _CategoryItem:
    name: str
    actions: list[Action]
    kind: str = "category"


@dataclass
class _SeparatorItem:
    label: str
    kind: str = "separator"


# Render order, top to bottom. SECTION_BASE_MODS does not appear here — it
# is folded into SECTION_BASE behind a "=== Mods ===" separator.
_RENDER_SECTIONS = (SECTION_BASE, SECTION_ADDONS)


_TEMPLATE = """\
<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8">
<title>Arma 3 Keybindings</title>
<style>
* { box-sizing: border-box; }
/* Always reserve the scrollbar's gutter so adding/removing it doesn't shift
   centered content sideways when content height crosses the viewport. */
html { scrollbar-gutter: stable; }
body { font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif; margin: 0; padding: 0; color: #d4d4d4; background: #0d1117; }
.banner { max-width: 1360px; margin: 0 auto; }
.banner-image {
  display: block; width: 100%; height: auto;
  border-bottom: 1px solid #2a3a2a;
}
.title-band {
  background:
    linear-gradient(180deg, rgba(13,17,23,0) 0%, rgba(13,17,23,0.6) 100%),
    linear-gradient(135deg, #1a2620 0%, #2a3a30 100%);
  border-bottom: 1px solid #2a3a2a;
}
.title-band-inner {
  padding: 1.1em 1.5em;
  text-align: center;
}
.title-band h1 {
  margin: 0; padding: 0;
  font-family: ui-monospace, "Cascadia Mono", Consolas, monospace;
  font-size: 2.6em; font-weight: 700; letter-spacing: 0.18em;
  color: #c8d8c0; text-transform: uppercase;
  text-shadow: 0 2px 0 rgba(0,0,0,0.4);
}
.title-band h1 .accent { color: #8db478; }
main { max-width: 1400px; margin: 0 auto; padding: 1.5em; }
.controls-bar { display: flex; flex-wrap: wrap; gap: 0.5em 0.7em; align-items: center; position: sticky; top: 0; background: #0d1117; padding: 0.6em 0; z-index: 10; }
.filters { display: flex; gap: 0.7em; flex: 1; }
.filter-group { position: relative; flex: 0 0 480px; max-width: 480px; }
.filter-group input { width: 100%; padding: 0.5em 2.2em 0.5em 0.7em; font-size: 1em; background: #1a2028; color: #e8e8e8; border: 1px solid #2f3a48; border-radius: 4px; transition: border-color 0.15s ease; }
.filter-group input:focus { outline: none; border-color: #8db478; }
/* When the controls bar is stuck to the top (user scrolled past it), draw
   a thin green underline at the bottom via box-shadow (no layout shift) to
   visually mark the sticky boundary. The bar already auto-focuses the
   filter input on this transition; the override below suppresses the
   :focus green border in that state so the underline is the only green
   signal — focus on the input is still functional, just visually quiet. */
.controls-bar.stuck { box-shadow: 0 1px 0 #8db478; }
.controls-bar.stuck .filter-group input:focus { border-color: #2f3a48; }
.filter-group input::placeholder { color: #6a7280; }
/* ✕ inside the input (mobile-style). Inline SVG so the cross is geometrically
   centered. Disabled = dim grey, enabled = bright with a subtle hover fill. */
.filter-group .clear-btn { position: absolute; right: 0.5em; top: 50%; transform: translateY(-50%); width: 1.5em; height: 1.5em; border-radius: 50%; border: none; background: transparent; color: #c8d0db; cursor: pointer; padding: 0; display: flex; align-items: center; justify-content: center; transition: background 0.12s, color 0.12s; }
.filter-group .clear-btn svg { width: 1em; height: 1em; display: block; }
.filter-group .clear-btn:hover { background: rgba(255,255,255,0.12); color: #ffffff; }
.filter-group .clear-btn:disabled { color: #4a5560; cursor: default; pointer-events: none; }
.actions { display: flex; gap: 0.4em; align-items: center; }
.actions button { padding: 0.5em 0.9em; font-size: 0.9em; background: #1a2028; color: #c8d8c0; border: 1px solid #2f3a48; border-radius: 4px; cursor: pointer; font-family: inherit; }
.actions button:hover { background: #232a36; border-color: #8db478; color: #fff; }
.actions button:disabled { opacity: 0.4; cursor: default; }
.actions button:disabled:hover { background: #1a2028; border-color: #2f3a48; color: #c8d8c0; }
/* Thin vertical rule that separates the navigation pair (Collapse/Expand)
   from the pin pair (Show Pinned/Unpin all) so the bar reads as two groups. */
.actions-divider { width: 1px; align-self: stretch; background: #2f3a48; margin: 0.15em 0.25em; }
/* Ghost variant for secondary actions — borderless and dimmer at rest so
   they don't compete with the primary Show Pinned toggle; lights up on hover. */
.actions button.ghost { background: transparent; border-color: transparent; color: #8a95a3; }
.actions button.ghost:hover { background: #232a36; border-color: #3a4555; color: #e8e8e8; }
.actions button.ghost:disabled:hover { background: transparent; border-color: transparent; color: #8a95a3; }
details.section { margin-top: 1.6em; margin-left: 1.7em; }
/* Sticky section summary — pinned just under the controls-bar. Higher
   z-index than category summary so categories slide cleanly underneath it
   during scroll handoffs. The -1px is a deliberate 1px overlap with the
   controls-bar above to cover sub-pixel rounding gaps; the bar's higher
   z-index hides the overlap. */
details.section > summary { position: sticky; top: calc(var(--controls-h, 60px) - 1px); z-index: 6; background: #0d1117; font-size: 1.35em; font-weight: 600; color: #e8e8e8; padding: 0.3em 0; cursor: pointer; list-style-position: outside; }
details.section > summary:hover { color: #fff; }
details.category { margin: 0.6em 0 0.6em 0.4em; }
/* Sticky category summary — sits below the sticky section summary. --section-h
   is kept in sync with the rendered section-summary height by the JS below
   (font-size shifts on zoom/resize would otherwise misalign it). z-index sits
   below the controls-bar (z=10) and the section summary (z=6). The -1px
   overlaps the section summary above for the same sub-pixel gap reason. */
details.category > summary { position: sticky; top: calc(var(--controls-h, 60px) + var(--section-h, 42px) - 2px); z-index: 4; background: #0d1117; font-size: 1.0em; font-weight: 600; color: #8db478; padding: 0.25em 0; cursor: pointer; list-style: none; }
/* Categories that follow a "=== Mods ===" separator within the same section
   stick BELOW the separator instead of directly under the section summary,
   so the three-layer stack (section / separator / category) reads as nested. */
.separator ~ details.category > summary { top: calc(var(--controls-h, 60px) + var(--section-h, 42px) + var(--separator-h, 36px) - 3px); }
details.category > summary::-webkit-details-marker { display: none; }
details.category > summary > .cat-label::before { content: "▶"; display: inline-block; margin-right: 0.4em; font-size: 0.75em; color: #6a7480; vertical-align: 1px; }
details.category[open] > summary > .cat-label::before { content: "▼"; }
details.category > summary:hover { color: #b3d6a3; }
details.category > summary:hover > .cat-label::before { color: #8db478; }
.separator {
  /* Sticky within its parent details.section — naturally unsticks when the
   section ends, so "=== Mods ===" only follows the user inside Configure
   Base. Sits between the section summary above and any category summary
   below (categories after the separator stick lower via the rule above). */
  position: sticky;
  top: calc(var(--controls-h, 60px) + var(--section-h, 42px) - 2px);
  z-index: 5;
  background: #0d1117;
  margin: 1em 0 1em 0.4em;
  padding: 0.4em 0.6em;
  font-family: ui-monospace, "Cascadia Mono", Consolas, monospace;
  font-size: 0.95em; font-weight: 600; letter-spacing: 0.15em; text-transform: uppercase;
  color: #6a7480;
  text-align: left;
  cursor: default;
  user-select: none;
}
table { border-collapse: collapse; table-layout: fixed; width: 100%; margin: 0.3em 0 0.8em; }
col.col-action { width: 25%; }
col.col-key { width: auto; }
td { text-align: left; padding: 0.45em 0.8em; vertical-align: middle; }
tr { border-bottom: 1px solid #1f2630; }
tbody tr:hover td { background: #161c24; }
td.action-cell { display: flex; align-items: center; gap: 0.5em; word-break: break-word; }
.action-label { flex: 1; min-width: 0; }
tr[data-bound="false"] td { color: #666; }
.key { font-family: ui-monospace, "Cascadia Mono", Consolas, monospace; font-size: 0.9em; color: #b8d4ff; word-break: break-word; }
.key-collide.match { color: #f87171; }
tr[data-bound="false"] .key { color: #666; }
tr[data-bound="false"] .key em { font-style: normal; color: inherit; }
.collision-marker { display: inline-block; margin-left: 0.5em; padding: 0.05em 0.3em; color: #f4a455; cursor: pointer; font-size: 0.95em; user-select: none; border-radius: 4px; transition: background 0.12s, color 0.12s; }
.collision-marker:hover { color: #ffc587; }
/* Active-anchor chip: filled amber, dark glyph — flags which ⚠ to click
   again (or press Esc) to exit the collision view, since other ⚠'s on
   screen would switch to a different conflict group instead. */
.collision-marker.active-collision-anchor { background: #f4a455; color: #1a2028; font-size: 1.2em; padding: 0 0.2em; line-height: 1.1; }
.collision-marker.active-collision-anchor:hover { background: #ffc587; color: #1a2028; }
.empty-section { color: #777; font-style: italic; padding: 0.5em 0; }
.empty-results { text-align: left; margin: 1.6em 0 0; color: #6a7480; font-style: italic; font-size: 1.26em; }
/* Custom tooltip — anchored to the cursor, lifted card with rounded corners. */
.custom-tooltip { position: absolute; z-index: 1000; pointer-events: none; background: #1f2733; color: #b8c2d0; border: 1px solid #3a4555; border-radius: 10px; padding: 0.65em 1em; font-size: 0.85em; font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif; font-weight: 400; white-space: pre; max-width: 90vw; box-shadow: 0 6px 20px rgba(0,0,0,0.55); line-height: 1.5; opacity: 0; transition: opacity 0.12s ease; }
.custom-tooltip.visible { opacity: 1; }
/* Pin toggle: sits to the left of the item like a list bullet. Native
   checkbox is hidden; .pin-indicator renders an empty box when unchecked,
   a green pin icon when checked, a dash when indeterminate. */
.pin-toggle { display: inline-flex; align-items: center; cursor: pointer; user-select: none; flex-shrink: 0; vertical-align: middle; }
.pin-checkbox { position: absolute; opacity: 0; width: 1px; height: 1px; margin: 0; pointer-events: none; }
.pin-indicator { display: inline-flex; align-items: center; justify-content: center; width: 21px; height: 21px; border: 1px solid #4a5560; border-radius: 4px; background: #1a2028; color: transparent; opacity: 0; transition: color 0.12s ease, border-color 0.12s ease, background 0.12s ease, opacity 0.12s ease; }
/* Reveal the indicator when the row/summary is hovered, when it's pinned
   (checked or indeterminate), or when the underlying checkbox is focused. */
tr:hover .pin-indicator,
details.category > summary:hover .pin-indicator,
.pin-checkbox:checked + .pin-indicator,
.pin-checkbox:indeterminate + .pin-indicator,
.pin-checkbox:focus-visible + .pin-indicator { opacity: 1; }
.pin-indicator svg { display: block; width: 18px; height: 18px; }
.pin-toggle:hover .pin-indicator { border-color: #8db478; background: #232a36; }
.pin-checkbox:focus-visible + .pin-indicator { outline: 2px solid #8db478; outline-offset: 1px; }
.pin-checkbox:checked + .pin-indicator { border-color: transparent; background: transparent; color: #4ade80; }
.pin-toggle:hover .pin-checkbox:checked + .pin-indicator { color: #6ee892; }
.pin-checkbox:indeterminate + .pin-indicator { border-color: #4ade80; background: #1a2028; }
.pin-checkbox:indeterminate + .pin-indicator > svg { display: none; }
.pin-checkbox:indeterminate + .pin-indicator::after { content: ""; width: 11px; height: 3px; background: #4ade80; border-radius: 1px; }
details.category > summary .pin-toggle { margin-right: 0.4em; }
.cat-label { display: inline; }
/* Filter toggles ("Show Pinned", "Hide Unbound") — behave like checkboxes,
   look like ghost buttons at rest (transparent, dim grey) so they don't
   compete visually with the rest of the bar. When checked, switch to a
   filled "active" style (green border + tinted background) to signal the
   filter is on. Disabled when there's nothing to filter (no pins / no
   unbound rows). The Pin variant additionally renders a pin icon (red when
   inactive, taken over by the .pin-checkbox:checked rule above when active). */
.filter-pins-toggle, .filter-unbound-toggle { display: inline-flex; align-items: center; justify-content: center; gap: 0.35em; padding: 0.5em 0.75em 0.5em 0.5em; font-size: 0.9em; background: transparent; color: #8a95a3; border: 1px solid transparent; border-radius: 4px; cursor: pointer; user-select: none; position: relative; flex-shrink: 0; }
.filter-pins-toggle:hover, .filter-unbound-toggle:hover { background: #232a36; border-color: #3a4555; color: #e8e8e8; }
.filter-pins-toggle:has(input:checked), .filter-unbound-toggle:has(input:checked) { background: #1d2a23; border-color: #4ade80; color: #cce8c5; }
.filter-pins-toggle:has(input:checked):hover, .filter-unbound-toggle:has(input:checked):hover { background: #243528; }
.filter-pins-toggle .pin-indicator { display: inline-flex; opacity: 1; border-color: transparent; background: transparent; color: #f87171; width: 18px; height: 18px; }
.filter-pins-toggle:has(input:disabled), .filter-unbound-toggle:has(input:disabled) { opacity: 0.4; cursor: default; }
.filter-pins-toggle:has(input:disabled):hover, .filter-unbound-toggle:has(input:disabled):hover { background: transparent; border-color: transparent; color: #8a95a3; }
</style>
</head>
<body>
<svg style="display:none" aria-hidden="true"><symbol id="pin-icon" viewBox="0 0 24 24"><path fill="currentColor" d="M16 9V4l1-1V2H7v1l1 1v5l-2 2v2h5v7l1 1 1-1v-7h5v-2z"/></symbol></svg>
<div class="banner">
  <img class="banner-image" src="{{ banner_data_url }}" alt="Arma 3 Keymaker">
  <div class="title-band">
    <div class="title-band-inner">
      <h1>ARMA<span class="accent"> 3</span> Keybind Explorer</h1>
    </div>
  </div>
</div>
<main>
<div class="controls-bar">
  <div class="filter-group">
    <input id="filter" type="text" placeholder="Filter by category, action, or key… (multiple words AND'd)" autocomplete="off">
    <button type="button" class="clear-btn" id="clear-filter" data-tooltip="Clear filter" aria-label="Clear filter" disabled><svg viewBox="0 0 16 16" fill="none" stroke="currentColor" stroke-width="2.2" stroke-linecap="round"><path d="M4 4L12 12M12 4L4 12"/></svg></button>
  </div>
  <div class="actions">
    <button type="button" id="collapse-all" class="ghost">Collapse all</button>
    <button type="button" id="expand-all" class="ghost">Expand all</button>
    <span class="actions-divider" aria-hidden="true"></span>
    <label class="filter-pins-toggle">
      <input type="checkbox" id="filter-pins" class="pin-checkbox" disabled>
      <span class="pin-indicator" aria-hidden="true"><svg fill="currentColor"><use href="#pin-icon"/></svg></span>
      <span class="filter-pins-label">Show Pinned (0)</span>
    </label>
    <button type="button" id="clear-pins" class="ghost" disabled>Unpin all</button>
    <span class="actions-divider" aria-hidden="true"></span>
    <label class="filter-unbound-toggle">
      <input type="checkbox" id="hide-unbound" class="pin-checkbox">
      <span class="filter-unbound-label">Hide Unbound (0)</span>
    </label>
  </div>
</div>

<p id="empty-results" class="empty-results" hidden>No matching results.</p>

{% for section_name, items in sections %}
<details class="section" data-section="{{ section_name }}">
<summary data-label="{{ section_name }}">{{ section_name }} ({{ count_section_items(items) }})</summary>
{% if items %}
{% for item in items %}
{% if item.kind == "category" %}
<details class="category" data-category="{{ item.name }}">
<summary data-label="{{ item.name }}"><label class="pin-toggle" data-tooltip="Pin this category"><input type="checkbox" class="pin-checkbox" data-pin-kind="cat"><span class="pin-indicator" aria-hidden="true"><svg fill="currentColor"><use href="#pin-icon"/></svg></span></label><span class="cat-label">{{ item.name }} ({{ item.actions|length }})</span></summary>
<table>
<colgroup><col class="col-action"><col class="col-key"></colgroup>
<tbody>
{% for a in item.actions %}
<tr data-action-id="{{ a.action_id }}" data-pin-path="{{ a.path }}"
    data-action-search="{{ (a.label ~ ' ' ~ a.action_id ~ ' ' ~ a.category)|lower }}"
    data-key-text="{{ a.key_text|lower }}"
    data-bound="{{ 'true' if a.bound else 'false' }}">
<td class="action-cell"><label class="pin-toggle" data-tooltip="Pin this action"><input type="checkbox" class="pin-checkbox" data-pin-kind="row"><span class="pin-indicator" aria-hidden="true"><svg fill="currentColor"><use href="#pin-icon"/></svg></span></label><span class="action-label" data-tooltip="{{ a.path }}">{{ a.label }}</span></td>
<td class="key">{% if a.bound %}{{ key_text_marked[a.path]|safe }}{% else %}<em>(unbound)</em>{% endif %}{% if a.path in collisions %}<span class="collision-marker" data-tooltip="{{ collisions[a.path] }}" data-collision-group='{{ collision_groups[a.path]|tojson }}'>⚠</span>{% endif %}</td>
</tr>
{% endfor %}
</tbody>
</table>
</details>
{% elif item.kind == "separator" %}
<div class="separator">{{ item.label }}</div>
{% endif %}
{% endfor %}
{% else %}
<p class="empty-section">No actions in this section.</p>
{% endif %}
</details>
{% endfor %}
</main>

<script type="application/json" id="data">{{ data_json|safe }}</script>
<script>
(function () {
  var filterInput = document.getElementById('filter');
  var clearFilterBtn = document.getElementById('clear-filter');
  var clearPinsBtn = document.getElementById('clear-pins');
  var expandBtn = document.getElementById('expand-all');
  var collapseBtn = document.getElementById('collapse-all');
  var filterPinsInput = document.getElementById('filter-pins');
  var filterPinsLabel = document.querySelector('.filter-pins-label');
  var hideUnboundInput = document.getElementById('hide-unbound');
  var hideUnboundLabel = document.querySelector('.filter-unbound-label');
  var emptyResults = document.getElementById('empty-results');
  var rows = Array.prototype.slice.call(document.querySelectorAll('tr[data-action-id]'));
  var categories = Array.prototype.slice.call(document.querySelectorAll('details.category'));
  var sections = Array.prototype.slice.call(document.querySelectorAll('details.section'));
  var separators = Array.prototype.slice.call(document.querySelectorAll('.separator'));
  var collideSpans = Array.prototype.slice.call(document.querySelectorAll('.key-collide'));
  var allDetails = sections.concat(categories);
  // Pre-compute combined search haystack per row so applyFilter doesn't
  // re-concatenate on every keystroke.
  rows.forEach(function (r) {
    r._search = (r.getAttribute('data-action-search') || '') + ' ' + (r.getAttribute('data-key-text') || '');
  });

  // Pinned paths persist in localStorage. Pin survives across filters: a
  // pinned row stays visible even when it doesn't match. Source of truth
  // is the Set; row checkboxes mirror it. Category checkboxes are derived
  // (checked when all child rows are pinned, indeterminate when some).
  var STORAGE_KEY = 'a3km:pinned';
  var OPEN_STATE_KEY = 'a3km:open';
  var pinnedPaths;
  try {
    pinnedPaths = new Set(JSON.parse(localStorage.getItem(STORAGE_KEY) || '[]'));
  } catch (e) {
    pinnedPaths = new Set();
  }

  // Stable key per details element. Sections use their data-section name
  // (unique). Categories use "section/category" so a category name that
  // appears under multiple sections (e.g. "Common") doesn't bleed across.
  function detailsKey(d) {
    if (d.classList.contains('section')) return 's:' + d.getAttribute('data-section');
    var sec = d.closest('details.section');
    var sname = sec ? sec.getAttribute('data-section') : '';
    return 'c:' + sname + '/' + d.getAttribute('data-category');
  }

  // Remembers section/category open state at the moment a filter starts.
  // null when no filter is active. Captured on empty→active transition,
  // restored (and cleared) on active→empty transition. Manual open/close
  // changes the user makes while filtering are intentionally NOT preserved
  // — the filter is a transient view and clearing it returns the layout to
  // exactly what the user had before they started typing.
  var savedOpenState = null;

  // Click-to-isolate-conflict state. collisionGroupActive is null normally,
  // or a Set of paths when the user clicked a ⚠ to filter to that group.
  // collisionAnchor is the specific ⚠ element that started the view — it
  // gets the chip styling so the user knows which one to click again to
  // exit (other ⚠'s on screen switch to a different group instead).
  var collisionGroupActive = null;
  var collisionAnchor = null;

  function savePins() {
    try {
      localStorage.setItem(STORAGE_KEY, JSON.stringify(Array.from(pinnedPaths)));
    } catch (e) { /* quota or disabled — pins still work this session */ }
  }

  // Persist which sections/categories are open. Skipped while any filter is
  // active — the snapshot in savedOpenState (and the collision view) holds
  // the user's true layout in memory; auto-expansions from filtering are
  // transient and must NOT overwrite the saved baseline.
  function saveOpenState() {
    if (savedOpenState !== null || collisionGroupActive !== null) return;
    var open = [];
    for (var i = 0; i < allDetails.length; i++) {
      if (allDetails[i].open) open.push(detailsKey(allDetails[i]));
    }
    try { localStorage.setItem(OPEN_STATE_KEY, JSON.stringify(open)); } catch (e) {}
  }

  function updatePinControlsEnabled() {
    // Both pin-related controls are tied to "do we have any pins right now".
    // Show Pinned with no pins would always show an empty list, and Remove
    // all pins would be a no-op; disable both. If Show Pinned was on when
    // pins drop to 0, fold it back to a clean view (collapse + uncheck) to
    // mirror the manual-uncheck behaviour.
    var hasPins = pinnedPaths.size > 0;
    clearPinsBtn.disabled = !hasPins;
    filterPinsInput.disabled = !hasPins;
    filterPinsLabel.textContent = 'Show Pinned (' + pinnedPaths.size + ')';
    // If pins drop to 0 while Show Pinned was on, drop the filter. The
    // snapshot/restore in applyFilter takes care of the layout.
    if (!hasPins && filterPinsInput.checked) filterPinsInput.checked = false;
  }

  function syncCategoryCheckbox(cat) {
    // Reflect the state of currently visible rows only — when a filter is
    // active, the category checkbox is about what the user can see.
    var cb = cat.querySelector('summary .pin-checkbox');
    if (!cb) return;
    var visibleCount = 0;
    var pinnedCount = 0;
    cat.querySelectorAll('tr[data-pin-path]').forEach(function (r) {
      if (r.style.display === 'none') return;
      visibleCount++;
      if (pinnedPaths.has(r.getAttribute('data-pin-path'))) pinnedCount++;
    });
    if (visibleCount === 0 || pinnedCount === 0) {
      cb.checked = false; cb.indeterminate = false;
    } else if (pinnedCount === visibleCount) {
      cb.checked = true; cb.indeterminate = false;
    } else {
      cb.checked = false; cb.indeterminate = true;
    }
  }

  function rowMatches(row, tokens, pinsOnly, hideUnbound) {
    if (collisionGroupActive && !collisionGroupActive.has(row.getAttribute('data-pin-path'))) return false;
    if (pinsOnly && !pinnedPaths.has(row.getAttribute('data-pin-path'))) return false;
    if (hideUnbound && row.getAttribute('data-bound') === 'false') return false;
    for (var i = 0; i < tokens.length; i++) {
      if (row._search.indexOf(tokens[i]) === -1) return false;
    }
    return true;
  }

  // autoExpand=true means this run was triggered by the filter input itself
  // changing — surface matches by force-opening visible sections/categories.
  // Other triggers (pin toggles, clear-pins, etc.) pass false so they don't
  // override a manual collapse the user made while the filter is still on.
  function applyFilter(autoExpand) {
    var query = filterInput.value.trim().toLowerCase();
    var tokens = query ? query.split(/\s+/) : [];
    var pinsOnly = filterPinsInput.checked;
    var hideUnbound = hideUnboundInput.checked;
    var filterActive = tokens.length > 0 || pinsOnly || hideUnbound || collisionGroupActive !== null;
    var wasInFilter = savedOpenState !== null;
    // empty→active: snapshot the current open state before any auto-expand.
    if (filterActive && !wasInFilter) {
      savedOpenState = allDetails.map(function (d) { return d.open; });
    }
    rows.forEach(function (r) {
      r.style.display = rowMatches(r, tokens, pinsOnly, hideUnbound) ? '' : 'none';
    });
    categories.forEach(function (cat) {
      var visible = cat.querySelectorAll('tbody tr:not([style*="display: none"])').length;
      var summary = cat.querySelector('summary');
      var label = summary.getAttribute('data-label');
      summary.querySelector('.cat-label').textContent = label + ' (' + visible + ')';
      cat.style.display = visible === 0 ? 'none' : '';
      if (autoExpand && filterActive && visible > 0) cat.open = true;
      // Re-derive checkbox state from the rows that are visible right now.
      syncCategoryCheckbox(cat);
    });
    var totalVisible = 0;
    sections.forEach(function (sec) {
      var visible = sec.querySelectorAll('tbody tr:not([style*="display: none"])').length;
      totalVisible += visible;
      var summary = sec.querySelector(':scope > summary');
      var label = summary.getAttribute('data-label');
      summary.textContent = label + ' (' + visible + ')';
      sec.style.display = visible === 0 ? 'none' : '';
      if (autoExpand && filterActive && visible > 0) sec.open = true;
    });
    emptyResults.hidden = totalVisible > 0;
    // A separator (e.g. "=== Mods ===") should show only if at least one
    // category that follows it within the same section is still visible.
    separators.forEach(function (sep) {
      var hasFollowing = false;
      var node = sep.nextElementSibling;
      while (node) {
        if (node.classList.contains('separator')) break;
        if (node.classList.contains('category') && node.style.display !== 'none') {
          hasFollowing = true;
          break;
        }
        node = node.nextElementSibling;
      }
      sep.style.display = hasFollowing ? '' : 'none';
    });
    // active→empty: restore the snapshot so the page returns to exactly the
    // section/category layout the user had before they started filtering.
    if (!filterActive && wasInFilter) {
      allDetails.forEach(function (d, i) { d.open = savedOpenState[i]; });
      savedOpenState = null;
    }
    // Clear button is enabled whenever any filter mode is in effect.
    clearFilterBtn.disabled = filterInput.value.length === 0 && collisionGroupActive === null;
  }

  function exitCollisionMode() {
    if (collisionAnchor) collisionAnchor.classList.remove('active-collision-anchor');
    collisionAnchor = null;
    collisionGroupActive = null;
    // Drop the red-key highlight from every span; outside collision view,
    // colliding segments look like normal keys (the ⚠ is signal enough).
    for (var i = 0; i < collideSpans.length; i++) collideSpans[i].classList.remove('match');
  }

  function enterCollisionMode(marker, group) {
    // Collision view is exclusive — clear other filter modes so the result
    // is exactly the conflict group, nothing more.
    if (filterInput.value) filterInput.value = '';
    if (filterPinsInput.checked) filterPinsInput.checked = false;
    if (collisionAnchor) collisionAnchor.classList.remove('active-collision-anchor');
    collisionAnchor = marker;
    marker.classList.add('active-collision-anchor');
    // Highlight only the key segments shared between any visible row and
    // the anchor — i.e. the actual conflict points, not every collision
    // those rows participate in elsewhere.
    var anchorKeys = {};
    var anchorRow = marker.closest('tr');
    if (anchorRow) {
      anchorRow.querySelectorAll('.key-collide').forEach(function (sp) {
        anchorKeys[sp.getAttribute('data-key-segment')] = true;
      });
    }
    for (var i = 0; i < collideSpans.length; i++) {
      var sp = collideSpans[i];
      if (anchorKeys[sp.getAttribute('data-key-segment')]) sp.classList.add('match');
      else sp.classList.remove('match');
    }
    collisionGroupActive = new Set(group);
    applyFilter(true);
    window.scrollTo({ top: 0, behavior: 'smooth' });
  }

  function setAllOpen(open) {
    allDetails.forEach(function (d) { d.open = open; });
  }

  function clearInput(input) {
    input.value = '';
    applyFilter();
    input.focus();
  }

  // Restore pin state from localStorage onto row checkboxes, then derive
  // category checkboxes. Done before attaching change listeners (and
  // anyway, programmatic .checked= doesn't fire 'change').
  rows.forEach(function (r) {
    var cb = r.querySelector('.pin-checkbox');
    if (cb) cb.checked = pinnedPaths.has(r.getAttribute('data-pin-path'));
  });
  categories.forEach(syncCategoryCheckbox);
  updatePinControlsEnabled();

  // Restore open/closed layout from localStorage BEFORE attaching the
  // toggle listener. Setting .open synchronously here queues toggle events
  // that fire after the listener is attached — the saveOpenState handler
  // would re-write the same set, which is harmless but pointless. By doing
  // restoration first, the redundant writes are at worst N idempotent saves.
  try {
    var savedOpen = new Set(JSON.parse(localStorage.getItem(OPEN_STATE_KEY) || '[]'));
    if (savedOpen.size > 0) {
      allDetails.forEach(function (d) {
        if (savedOpen.has(detailsKey(d))) d.open = true;
      });
    }
  } catch (e) { /* malformed JSON — start with everything closed */ }
  allDetails.forEach(function (d) { d.addEventListener('toggle', saveOpenState); });

  // Hide Unbound — count is static (data-bound is set at render time and
  // doesn't change), so set the label once and disable when there's nothing
  // to filter. Mirrors the disabled-when-empty behaviour of Show Pinned.
  var unboundCount = 0;
  for (var i = 0; i < rows.length; i++) {
    if (rows[i].getAttribute('data-bound') === 'false') unboundCount++;
  }
  hideUnboundLabel.textContent = 'Hide Unbound (' + unboundCount + ')';
  if (unboundCount === 0) hideUnboundInput.disabled = true;

  // Row checkbox: toggle one path; bubble new state up to category.
  rows.forEach(function (r) {
    var cb = r.querySelector('.pin-checkbox');
    if (!cb) return;
    cb.addEventListener('change', function () {
      var path = r.getAttribute('data-pin-path');
      if (cb.checked) pinnedPaths.add(path); else pinnedPaths.delete(path);
      var cat = r.closest('details.category');
      if (cat) syncCategoryCheckbox(cat);
      savePins();
      updatePinControlsEnabled();
      applyFilter();
    });
  });

  // Category checkbox: pin/unpin every VISIBLE row in the category. With
  // a filter active that means just the filter results; with no filter it
  // means everything. Browsers treat a click on an indeterminate box as
  // moving to checked, giving "pin everything I currently see" behaviour.
  categories.forEach(function (cat) {
    var cb = cat.querySelector('summary .pin-checkbox');
    if (!cb) return;
    cb.addEventListener('change', function () {
      var shouldPin = cb.checked;
      cat.querySelectorAll('tr[data-pin-path]').forEach(function (r) {
        if (r.style.display === 'none') return;
        var rcb = r.querySelector('.pin-checkbox');
        var path = r.getAttribute('data-pin-path');
        if (shouldPin) pinnedPaths.add(path); else pinnedPaths.delete(path);
        if (rcb) rcb.checked = shouldPin;
      });
      cb.indeterminate = false;
      savePins();
      updatePinControlsEnabled();
      applyFilter();
    });
  });

  // Clicks on a pin-toggle inside a <summary> must NOT toggle the details.
  // The label still forwards the click to its input (default behaviour),
  // so the change handler above still fires.
  document.querySelectorAll('details.category > summary .pin-toggle').forEach(function (lbl) {
    lbl.addEventListener('click', function (e) { e.stopPropagation(); });
  });

  clearPinsBtn.addEventListener('click', function () {
    pinnedPaths.clear();
    rows.forEach(function (r) {
      var cb = r.querySelector('.pin-checkbox');
      if (cb) { cb.checked = false; cb.indeterminate = false; }
    });
    savePins();
    updatePinControlsEnabled();
    applyFilter();
  });

  filterInput.addEventListener('input', function () {
    if (collisionGroupActive) exitCollisionMode();
    applyFilter(true);
  });
  filterPinsInput.addEventListener('change', function () {
    if (collisionGroupActive) exitCollisionMode();
    if (filterPinsInput.checked) {
      // Activating Show Pinned clears any text filter — the user wants a
      // clean view of their pinned subset.
      filterInput.value = '';
      applyFilter(true);
    } else {
      // Turning it off relies on the snapshot/restore in applyFilter to
      // return the layout to exactly what it was before Show Pinned went on.
      applyFilter();
    }
  });
  // Hide Unbound — pure subtractive filter. Doesn't conflict with collision
  // view (collision rows are bound by definition), so we leave that mode
  // alone. Doesn't clear the text filter either; the two compose naturally.
  hideUnboundInput.addEventListener('change', function () {
    applyFilter(true);
  });
  // Hide Unbound — pure subtractive filter. Doesn't conflict with collision
  // view (collision rows are bound by definition), so we leave that mode
  // alone. Doesn't clear the text filter either; the two compose naturally.
  hideUnboundInput.addEventListener('change', function () {
    applyFilter(true);
  });
  clearFilterBtn.addEventListener('click', function () {
    if (collisionGroupActive) exitCollisionMode();
    clearInput(filterInput);
  });

  // Click any ⚠ marker → filter to that conflict group. Clicking the active
  // chip (the orange square ⚠) exits back to the pre-collision view; any
  // other ⚠ click re-anchors to that one's view.
  Array.prototype.forEach.call(document.querySelectorAll('.collision-marker'), function (m) {
    m.addEventListener('click', function (e) {
      e.stopPropagation();
      var group;
      try { group = JSON.parse(m.getAttribute('data-collision-group') || '[]'); }
      catch (err) { return; }
      if (!group.length) return;
      if (m === collisionAnchor) {
        exitCollisionMode();
        applyFilter();
        return;
      }
      enterCollisionMode(m, group);
    });
  });

  // Esc — cascading "back" gesture. First press clears any active filter
  // (text filter, Show Pinned, Hide Unbound, collision view). If no filter
  // is active, a press collapses all sections/categories instead. Lets the
  // user spam Esc to fully reset the page.
  document.addEventListener('keydown', function (e) {
    if (e.key !== 'Escape') return;
    var didSomething = false;
    if (collisionGroupActive) { exitCollisionMode(); didSomething = true; }
    if (filterInput.value) { filterInput.value = ''; didSomething = true; }
    if (filterPinsInput.checked) { filterPinsInput.checked = false; didSomething = true; }
    if (hideUnboundInput.checked) { hideUnboundInput.checked = false; didSomething = true; }
    if (didSomething) {
      applyFilter();
    } else {
      setAllOpen(false);
    }
  });

  // Custom tooltip: replaces the browser's native [title] tooltip — much
  // faster (150ms delay vs ~600ms native) and styled to match the page.
  // Single delegated mouseover/mouseout, single tooltip element reused.
  var tooltipEl = document.createElement('div');
  tooltipEl.className = 'custom-tooltip';
  document.body.appendChild(tooltipEl);
  var tooltipShowTimer = null;
  var tooltipTarget = null;
  var lastMouseX = 0, lastMouseY = 0;

  function positionTooltipAtCursor() {
    var ttRect = tooltipEl.getBoundingClientRect();
    var pad = 8;
    var offsetX = 16;
    var top = lastMouseY + window.scrollY - ttRect.height / 2;
    var left = lastMouseX + window.scrollX + offsetX;
    // If the right side would overflow, flip the tooltip to the left of the cursor.
    if (left + ttRect.width + pad > window.scrollX + window.innerWidth) {
      left = lastMouseX + window.scrollX - ttRect.width - offsetX;
    }
    // Clamp into viewport.
    top = Math.max(window.scrollY + pad, Math.min(top, window.scrollY + window.innerHeight - ttRect.height - pad));
    left = Math.max(window.scrollX + pad, left);
    tooltipEl.style.left = left + 'px';
    tooltipEl.style.top = top + 'px';
  }

  function showTooltip(target) {
    var content = target.getAttribute('data-tooltip');
    if (!content) return;
    tooltipEl.textContent = content;  // newlines preserved via CSS white-space
    tooltipEl.style.left = '0px';
    tooltipEl.style.top = '0px';
    positionTooltipAtCursor();
    tooltipEl.classList.add('visible');
  }

  function hideTooltip() {
    tooltipEl.classList.remove('visible');
    tooltipTarget = null;
    if (tooltipShowTimer) { clearTimeout(tooltipShowTimer); tooltipShowTimer = null; }
  }

  document.addEventListener('mousemove', function (e) {
    lastMouseX = e.clientX;
    lastMouseY = e.clientY;
  });
  document.addEventListener('mouseover', function (e) {
    var target = e.target.closest('[data-tooltip]');
    if (!target || target === tooltipTarget) return;
    if (tooltipShowTimer) clearTimeout(tooltipShowTimer);
    tooltipTarget = target;
    tooltipShowTimer = setTimeout(function () {
      if (tooltipTarget === target) showTooltip(target);
    }, 150);
  });
  document.addEventListener('mouseout', function (e) {
    var target = e.target.closest('[data-tooltip]');
    if (!target) return;
    // mouseout fires when crossing into a child; ignore those.
    if (target.contains(e.relatedTarget)) return;
    hideTooltip();
  });
  // Stale positions on scroll — just hide.
  window.addEventListener('scroll', hideTooltip, true);
  expandBtn.addEventListener('click', function () { setAllOpen(true); });
  collapseBtn.addEventListener('click', function () { setAllOpen(false); });

  // Detect when the sticky controls bar is "stuck" (user has scrolled past
  // its natural position). A 1px sentinel just above the bar is observed —
  // when it's out of the viewport, the bar is stuck. Adds a `.stuck` class
  // we use to light the filter border.
  var controlsBar = document.querySelector('.controls-bar');
  // Keep --controls-h, --section-h, --separator-h in sync with the rendered
  // heights of the controls-bar, the first section summary, and the first
  // separator. The category summary stacks under section (or under section
  // + separator when after the "=== Mods ===" divider). The bar can wrap
  // on narrow viewports, so heights aren't constant — observe via RO.
  var sectionSummary = document.querySelector('details.section > summary');
  var separatorEl = document.querySelector('.separator');
  if (controlsBar) {
    var syncStickyHeights = function () {
      // Round up sub-pixel heights so the sticky layers below have no gap
      // for scrolling content to leak through between them.
      document.documentElement.style.setProperty('--controls-h', Math.ceil(controlsBar.getBoundingClientRect().height) + 'px');
      if (sectionSummary) {
        document.documentElement.style.setProperty('--section-h', Math.ceil(sectionSummary.getBoundingClientRect().height) + 'px');
      }
      if (separatorEl) {
        document.documentElement.style.setProperty('--separator-h', Math.ceil(separatorEl.getBoundingClientRect().height) + 'px');
      }
    };
    syncStickyHeights();
    if ('ResizeObserver' in window) {
      var ro = new ResizeObserver(syncStickyHeights);
      ro.observe(controlsBar);
      if (sectionSummary) ro.observe(sectionSummary);
      if (separatorEl) ro.observe(separatorEl);
    } else {
      window.addEventListener('resize', syncStickyHeights);
    }
  }
  if (controlsBar && 'IntersectionObserver' in window) {
    var sentinel = document.createElement('div');
    sentinel.setAttribute('aria-hidden', 'true');
    sentinel.style.height = '1px';
    controlsBar.parentNode.insertBefore(sentinel, controlsBar);
    new IntersectionObserver(function (entries) {
      var nowStuck = !entries[0].isIntersecting;
      var wasStuck = controlsBar.classList.contains('stuck');
      controlsBar.classList.toggle('stuck', nowStuck);
      // On the not-stuck → stuck transition, jump focus into the filter so
      // the user can start typing immediately when it follows them down.
      if (nowStuck && !wasStuck) filterInput.focus();
    }).observe(sentinel);
  }

  // Drop the cursor into the filter on first paint so the user can start
  // typing immediately without having to click the input.
  filterInput.focus();
})();
</script>
</body>
</html>
"""


def render(report: Report) -> str:
    """Render a Report to a complete HTML keymap document."""
    env = Environment(autoescape=select_autoescape(["html"]))
    template = env.from_string(_TEMPLATE)

    sections = _group_for_render(report.actions)
    data_json = _model_json(report)
    banner_data_url = _load_banner_data_url()
    collisions = _compute_collisions(report.actions)
    collision_groups = _compute_collision_groups(report.actions)
    key_text_marked = _compute_key_text_marked(report.actions)

    return template.render(
        report=report,
        sections=sections,
        count_section_items=_count_section_items,
        data_json=Markup(data_json),
        banner_data_url=banner_data_url,
        collisions=collisions,
        collision_groups=collision_groups,
        key_text_marked=key_text_marked,
    )


def _compute_collision_others(actions: list[Action]) -> dict[str, list[str]]:
    """Internal helper: for every action whose key collides with another,
    return a LIST of the OTHER paths sharing any key with it — ordered by
    each path's first appearance in ``actions`` so downstream consumers
    (tooltip text, click-to-isolate filter) match the in-game/page order
    the user sees, not alphabetical.

    Two actions collide when they share at least one individual key string.
    Multi-binding key text (e.g. ``"L" , "Joystick Btn. #3"``) is split on
    `` , `` and each part checked independently.
    """
    by_key: dict[str, list[str]] = {}
    for a in actions:
        if not a.key_text:
            continue
        for raw in a.key_text.split(" , "):
            piece = raw.strip()
            if not piece:
                continue
            by_key.setdefault(piece, []).append(a.path)

    # First-appearance index for each path so we can sort partners by
    # in-game order (the merger already walks actions in dropdown order).
    path_order: dict[str, int] = {}
    for i, a in enumerate(actions):
        path_order.setdefault(a.path, i)

    others_by_path: dict[str, set[str]] = {}
    for paths in by_key.values():
        unique = list(dict.fromkeys(paths))  # preserve order, dedupe
        if len(unique) <= 1:
            continue
        for p in unique:
            others_by_path.setdefault(p, set()).update(o for o in unique if o != p)
    return {
        path: sorted(others, key=lambda o: path_order.get(o, len(actions)))
        for path, others in others_by_path.items()
    }


def _compute_collisions(actions: list[Action]) -> dict[str, str]:
    """Tooltip text per colliding action — ``"Also bound to:\\n…"`` listing
    the OTHER colliding paths in in-game order. Actions with no collision
    aren't keys in the dict.
    """
    return {
        path: "Also bound to:\n" + "\n".join(others)
        for path, others in _compute_collision_others(actions).items()
    }


def _compute_key_text_marked(actions: list[Action]) -> dict[str, str]:
    """For each bound action, build an HTML-safe ``key_text`` where each
    individual key segment that collides with another action is wrapped in
    ``<span class="key-collide">…</span>``. Non-colliding segments come
    through HTML-escaped only. The renderer uses this so only the offending
    keys flash red, not the whole multi-binding string.
    """
    by_key: dict[str, list[str]] = {}
    for a in actions:
        if not a.key_text:
            continue
        for raw in a.key_text.split(" , "):
            piece = raw.strip()
            if not piece:
                continue
            by_key.setdefault(piece, []).append(a.path)
    colliding_keys = {
        k for k, paths in by_key.items() if len(dict.fromkeys(paths)) > 1
    }
    out: dict[str, str] = {}
    for a in actions:
        if not a.key_text:
            continue
        parts = []
        for raw in a.key_text.split(" , "):
            esc = html.escape(raw)
            piece = raw.strip()
            if piece in colliding_keys:
                attr = html.escape(piece, quote=True)
                parts.append(f'<span class="key-collide" data-key-segment="{attr}">{esc}</span>')
            else:
                parts.append(esc)
        out[a.path] = " , ".join(parts)
    return out


def _compute_collision_groups(actions: list[Action]) -> dict[str, list[str]]:
    """Full collision group per colliding action — list of every path in
    the conflict (including the action's own path) in in-game order. Used
    by the click-to-filter UI on the ⚠ marker; the JS uses it as a Set, so
    order is presentational only — kept consistent with the tooltip.
    """
    path_order: dict[str, int] = {}
    for i, a in enumerate(actions):
        path_order.setdefault(a.path, i)
    return {
        path: sorted([path, *others], key=lambda p: path_order.get(p, len(actions)))
        for path, others in _compute_collision_others(actions).items()
    }


def _load_banner_data_url() -> str:
    """Load the bundled banner PNG from the installed package data and
    return it as a ``data:image/png;base64,...`` URL.
    """
    img_bytes = (
        resources.files("a3_keymaker")
        .joinpath("data/keymaker_banner.png")
        .read_bytes()
    )
    return "data:image/png;base64," + base64.b64encode(img_bytes).decode("ascii")


def _group_for_render(actions: list[Action]) -> list[tuple[str, list]]:
    """Group actions into the rendered section structure.

    Returns ``[(section_name, [item, ...]), ...]`` where each item is either
    a ``_CategoryItem`` (collapsible) or a ``_SeparatorItem`` (visual
    divider). Categories preserve **insertion order** — mirroring the
    in-game SHOW: / ADDON: dropdown order, since the SQF walker iterates
    those dropdowns top-to-bottom and the merger appends Actions in the
    same order. Python ``dict`` is insertion-ordered (3.7+).

    SECTION_BASE_MODS is folded into the SECTION_BASE rendered section
    behind a non-collapsible ``"=== Mods ==="`` separator, matching the
    in-game dialog layout (vanilla categories, then mod categories).
    """
    by_section: dict[str, dict[str, list[Action]]] = {
        SECTION_BASE: {},
        SECTION_BASE_MODS: {},
        SECTION_ADDONS: {},
    }
    for a in actions:
        by_section.setdefault(a.section, {}).setdefault(a.category, []).append(a)

    out: list[tuple[str, list]] = []

    # Configure Base = vanilla categories + separator + mod categories.
    base_items: list = [
        _CategoryItem(name=name, actions=acts)
        for name, acts in by_section[SECTION_BASE].items()
    ]
    if by_section[SECTION_BASE_MODS]:
        base_items.append(_SeparatorItem(label="=== Mods ==="))
        base_items.extend(
            _CategoryItem(name=name, actions=acts)
            for name, acts in by_section[SECTION_BASE_MODS].items()
        )
    out.append((SECTION_BASE, base_items))

    # Configure Addons = CBA addons in walker order.
    addon_items: list = [
        _CategoryItem(name=name, actions=acts)
        for name, acts in by_section[SECTION_ADDONS].items()
    ]
    out.append((SECTION_ADDONS, addon_items))

    return out


def _count_section_items(items: list) -> int:
    """Total action count across all _CategoryItem entries (separators don't count)."""
    return sum(
        len(it.actions) for it in items if getattr(it, "kind", None) == "category"
    )


def _model_json(report: Report) -> str:
    """JSON-serialize the keymap for the embedded ``<script type="application/json">``.

    Escapes ``</`` so a stray ``</script>`` substring inside any string field
    cannot terminate the embed early.
    """
    raw = json.dumps(asdict(report), ensure_ascii=False)
    return raw.replace("</", "<\\/")
