# ARCHITECTURE.md — a3_keymaker

## Overview

`a3_keymaker` extracts every keybinding from a live Arma 3 session and
renders a single self-contained HTML keymap grouped the way the in-game
Controls dialog organizes them.

The project is split in two halves connected by the Windows clipboard:

```
┌────────────────────────────────────────────────────────────────────┐
│                         Arma 3 (live game)                          │
│                                                                    │
│   Debug Console ── runs ──► extract_all.sqf                       │
│                                  │                                  │
│                                  ├─► UI walks (Controls dialog)    │
│                                  ├─► configFile probes             │
│                                  └─► actionKeysNames queries       │
│                                                                    │
│                                  ▼                                  │
│                          copyToClipboard <dump>                    │
└────────────────────────────────────────────────────────────────────┘
                                   │
                            (paste to file)
                                   │
                                   ▼
┌────────────────────────────────────────────────────────────────────┐
│                       Python (a3_keymaker CLI)                     │
│                                                                    │
│   dump.txt ──► parser ──► merger ──► render ──► keymap.html       │
│                              │                                     │
│                              └── data/vanilla_actions.json (BIS    │
│                                  wiki: action_id ↔ label lookup)   │
└────────────────────────────────────────────────────────────────────┘
```

The SQF half is a one-shot extractor that you run inside Arma 3. The
Python half is a deterministic, offline transform from the dump text to a
single HTML file with no external dependencies.

---

## Why not parse `.Arma3Profile` or HEMTT-extract PBOs?

Both alternatives were tried in a predecessor project and rejected:

- **Profile parsing.** `.Arma3Profile` stores key bindings as packed
  compound integers — DIK code + modifier flags + device type packed in
  high/low bits. Decoding is awkward, joystick / HOTAS device codes are
  poorly documented, and the file gives action IDs (e.g. `MoveForward`)
  not labels — so a separate config-side lookup is still required to get
  the displayName the user actually sees.
- **HEMTT PBO unpack + config merge.** Works offline but ~3 minutes cold
  per modset (PBO extraction + ~1700 AST merge), needs HEMTT installed,
  and still misses the engine-formatted key strings (e.g. `Left Ctrl+M`
  vs the decoder's `Ctrl+M`, `2xJ` for double-tap, joystick button names)
  because those are computed by the engine at render time.

The SQF approach wins because the engine itself has already done all the
hard work — `actionKeysNames "<id>"` returns the exact string the
Controls dialog renders, including double-tap notation, modifier
ordering, and named joystick / HOTAS buttons. We just need to enumerate
the right action IDs and walk the right UI controls to discover them.

The trade-off is that the user has to launch Arma to capture a dump.
That's acceptable for a single-user "what's bound to what" keymap, which
is what `a3_keymaker` is.

---

## SQF extractor — `extract_all.sqf`

One spawned thread, run from the Debug Console. Runs silently — the
clipboard is only written once, at the end, with the full dump (prefixed
`A3KM_OK\n…` on success, `A3KM_OK_NO_ADDONS\n…` if Configure Addons was
skipped). On timeout / failure the clipboard is left untouched. Visible
progress is the in-game dropdown cycling through entries.

Six phases:

| # | Phase | Purpose |
|---|---|---|
| 1 | Wait for Controls dialog | Polls `allDisplays` for `CA_ControlsPage` (the SHOW: dropdown) with rows |
| 2 | Walk vanilla categories | For each entry in `CA_ControlsPage`: `lbSetCurSel`, `uiSleep 0.35`, capture `lbText` of every row in `CA_ValueKeys` (the action list) |
| 3 | Union `Mappings` across presets | Walks every sibling class under `CfgDefaultKeysPresets` (Arma3, Arma3Apex, A3_Alternative, Industry_Standard, …) and unions all their `Mappings` entries; dedupes by id, records provenance |
| 3.5 | Vanilla engine actions | Iterates a hard-coded list of 446 action IDs (sourced from <https://community.bistudio.com/wiki/inputAction/actions>) and emits `(id, actionKeysNames id)` for each |
| 3.6 | Walk `CfgUserActions` | Enumerates every old-style mod action class via `"true" configClasses`; emits `(id, displayName, actionKeysNames id)` per entry |
| 4–5 | Wait for Configure Addons + walk `AddonsList` | Polls for `AddonsList` to become `ctrlShown`. For each addon: `lbSetCurSel`, `uiSleep 0.7` (CBA needs longer to rebuild controls), then collect `EditButton` (label) and `AssignedKey` (key text) child controls in document order |
| 6 | Emit | `copyToClipboard format ["A3KM_OK%1vanilla_categories=%3%1mappings=%4%1vanilla_engine=%5%1cfg_user_actions=%6%1addons=%7", endl, …]` |

### Why those five sources?

| Source | Catches |
|---|---|
| UI walk of CONTROLS | Every label in every category, in dropdown order — provides the canonical category structure |
| `Mappings` union | Old-style mod IDs that have a default key in any preset (covers F16V_Loadout_Menu etc.) |
| `vanilla_engine` (wiki list + actionKeysNames) | All 446 engine action IDs, regardless of whether the user has them bound |
| `CfgUserActions` | Old-style mod IDs **without** any preset default (Turret Enhanced numpad bindings, F16V Subsystems switches, etc.) — Mappings would miss these entirely |
| UI walk of CONFIGURE ADDONS | CBA-registered modern mod bindings — CBA stores key text directly in widget `ctrlText`, so we can read it without needing IDs |

Each source covers a real gap:
- The UI walk gives labels but `lbTextRight`/`lbValue`/`lbData` are all
  empty for vanilla rows — the engine custom-draws the right column
  rather than putting it in standard listbox properties.
- `actionKeysNames` works for any valid action ID but we need an ID list
  to call it with.
- The engine doesn't expose a way to enumerate IDs from inside SQF, hence
  the wiki-derived hardcoded list.
- `Mappings` only contains actions with at least one preset default;
  unbound-by-default mod actions need `CfgUserActions`.
- CBA's keybinding system is parallel to the engine's — its actions
  don't appear in `actionKeysNames`, so we have to read them from the
  UI controls CBA renders.

---

## Python pipeline — `src/a3_keymaker/`

```
parser.py    # text dump → ParsedDump (one list per SQF section)
merger.py    # ParsedDump + vanilla_actions.json → list[Action]
render.py    # list[Action] → self-contained HTML string
cli.py       # argparse + file I/O
model.py     # Action, Report dataclasses + section constants
```

### Data model — `model.py`

Two dataclasses, intentionally minimal:

```python
@dataclass(frozen=True)
class Action:
    section: str        # SECTION_BASE | SECTION_BASE_MODS | SECTION_ADDONS
    category: str       # category as shown in SHOW: / ADDON: dropdown
    label: str          # action label as shown in ACTION column
    key_text: str       # engine-formatted key text, "" if unbound
    action_id: str = "" # internal id when known, "" otherwise

    @property
    def bound(self) -> bool: ...
    @property
    def display_section(self) -> str: ...   # collapses BASE_MODS → BASE
    @property
    def path(self) -> str: ...              # "Configure Base > A10C Controls > Loadout Menu"

@dataclass
class Report:
    generated_at_iso: str
    source_dump_path: str | None
    actions: list[Action]
```

`SECTION_BASE_MODS` is a separate model section for clarity — the merger
tags old-style mod rows with it so downstream code can distinguish them.
The renderer collapses `BASE_MODS → BASE` for display (inlines them
behind a `=== Mods ===` separator). Action paths already use
`display_section` so hover tooltips show "Configure Base" not
"Configure Base - Mods".

### Parser — `parser.py`

The SQF dump is mostly JSON-shaped but uses SQF string conventions:

- Sections are newline-separated key=value pairs: `vanilla_categories=[…]`
- Each value is an SQF array literal: `[[1, "Common", …], [2, "Weapons", …]]`
- SQF strings use `""` (doubled quote) as the inline escape for `"` —
  e.g. SQF text `"""W"""` is the 3-char Python string `"W"`.

The parser has two interesting bits:

1. **`_sqf_to_json`** walks the text character-by-character, finds SQF
   strings, applies `_try_fix_mojibake` to each string content, and emits
   a JSON-escaped equivalent so the whole result can be `json.loads`'d.
   We can't use a regex because we have to track whether we're inside a
   string (to disambiguate `""` as an escape vs. as two empty strings).

2. **`_try_fix_mojibake`** reverses the **UTF-8 → CP1252 → UTF-8** double
   encoding the Windows clipboard pipeline applies to non-ASCII
   characters. Arma writes UTF-8 to the clipboard; some app along the way
   reinterprets those bytes as CP1252 then re-emits as UTF-8. Result: the
   SQF arrow `↑` (UTF-8 `E2 86 91`) becomes `â†'` in the dump file.
   The fix uses a manually-built complete CP1252 byte map (CP1252 has
   five undefined positions — 0x81, 0x8D, 0x8F, 0x90, 0x9D — that
   Python's codec refuses to encode; we map them to themselves so the
   round-trip is symmetric and lossless). The roundtrip is only applied
   when it succeeds AND produces a different string, so genuine
   non-ASCII text passes through unchanged.

Older dumps without the `cfg_user_actions` section still parse — that
section is marked optional and defaults to `[]`.

### Merger — `merger.py`

Walks `dump.vanilla_categories` in dump order (= in-game dropdown order),
emitting one `Action` per row. Section assignment toggles when we hit
the `=== Mods ===` separator (`lbData == ""`):

- Categories before the separator → `SECTION_BASE`
- Categories after the separator → `SECTION_BASE_MODS`

Key resolution per row:

- **`SECTION_BASE`**: lookup `(category, label)` in the wiki JSON to get
  the engine action ID, then key text from `dump.vanilla_engine[id]`.
  Direct, no heuristics.
- **`SECTION_BASE_MODS`**: lookup `label` in `cfg_user_actions` (built
  from `dump.cfg_user_actions` indexed by `displayName`). When multiple
  candidates share a `displayName` (e.g. both A10C and F16V mods register
  a "Loadout Menu" action), `_pick_user_action` disambiguates by
  comparing the action ID's prefix against the category's first word
  ("A10C Controls" → prefer id starting with `A10C_`). Falls back to a
  suffix-match heuristic against `Mappings` IDs when CfgUserActions
  doesn't list the action.

CBA addon rows (`SECTION_ADDONS`) come from `dump.addons` — each is
already a paired `(label, key_text)` tuple from the addon walker, so the
merger just wraps them in `Action` instances.

### Renderer — `render.py`

Single Jinja template embedded as a Python string constant. Output is a
fully self-contained HTML file: banner image is base64-embedded as a
`data:image/png;base64,…` URL, all CSS is inline, all JS is inline, and
the parsed `Report` is also embedded as a `<script type="application/json">`
block for any future tooling.

Template structure:

```
<header class="banner">                    # 1360px wide, centered
  <img class="banner-image">               # base64-embedded PNG
  <div class="title-band"><h1>…</h1></div> # green strip with title
</header>

<main>
  <div class="controls-bar">               # sticky at top: 0
    <div class="filter-group">             # text filter + clear button
      <input id="filter">
      <button class="clear-btn" id="clear-filter">
    </div>
    <div class="actions">                  # action toggles + buttons
      <button id="collapse-all" class="ghost">
      <button id="expand-all" class="ghost">
      <span class="actions-divider">       # vertical hairline groups nav vs filters
      <label class="filter-pins-toggle">   # Show Pinned checkbox-as-button
      <button id="clear-pins" class="ghost">  # Unpin all
      <span class="actions-divider">
      <label class="filter-unbound-toggle"> # Hide Unbound checkbox-as-button
    </div>
  </div>

  for each section in [Configure Base, Configure Addons]:
    <details class="section">              # sticky summary at top: --controls-h - 1px
      <summary>Section name (count)</summary>

      for each item in section_items:
        if item.kind == "category":
          <details class="category">       # sticky summary at top: --controls-h + --section-h - 2px
            <summary>
              <label class="pin-toggle">…  # category pin (tri-state)
              Category (count)
            </summary>
            <table>                        # no <thead>, just rows
              <tr data-action-id data-pin-path data-bound>
                <td class="action-cell">
                  <label class="pin-toggle">…  # row pin
                  <span class="action-label" data-tooltip="path">
                </td>
                <td class="key">…<span class="collision-marker">⚠</span>…</td>
              </tr>
              …
            </table>
          </details>
        elif item.kind == "separator":     # === Mods === in Base only
          <div class="separator">           # sticky at top: --controls-h + --section-h - 2px
            within Configure Base only; categories that follow stick lower
            (top: --controls-h + --section-h + --separator-h - 3px)

  <script type="application/json">…full keymap as JSON…</script>
  <script>…interaction logic (~700 lines)…</script>
</main>
```

`_group_for_render` produces the section/item structure. Configure Base
contains: vanilla categories first → `_SeparatorItem("=== Mods ===")` →
old-style mod categories. Categories preserve insertion order (which
mirrors the SQF walker's dropdown order — Python dicts are
insertion-ordered since 3.7).

`_compute_collisions` builds a map `{path: tooltip_string}` and
`_compute_collision_groups` builds a `{path: [paths]}` group map for
inline collision markers and click-to-isolate. Two actions collide when
they share at least one individual key string; multi-binding cells
(`"L" , "Joystick #3"`) are split on ` , ` and each part checked
independently. `_compute_key_text_marked` HTML-escapes each binding
segment and wraps colliding ones in `<span class="key-collide" data-key-segment>`
so the JS can selectively highlight only the keys shared with a clicked
row, not every collision the row participates in elsewhere.

No smart filtering on collisions — every shared key flags both parties
(intentional, since context-mutually-exclusive overlaps like `Move Forward`
in Infantry vs Vehicle Movement are by design and only the user can judge
each one).

#### Inline JS — interaction model

The script is one IIFE (~700 lines) handling several composable concerns:

**Filtering.** A single `applyFilter(autoExpand)` function is the choke
point. It reads three filter sources and threads them through a
`rowMatches(row, tokens, pinsOnly, hideUnbound)` predicate:

- **Text filter** — tokens from the filter input, AND'd against a
  pre-computed `data-action-search` (label + id + category) +
  `data-key-text` haystack on each row.
- **Show Pinned toggle** — restricts to rows whose `data-pin-path` is in
  the in-memory `pinnedPaths` Set.
- **Hide Unbound toggle** — drops rows where `data-bound="false"`.
- **Collision view** — when a `collisionGroupActive` Set is non-null,
  only rows in that group pass.

Per-category and per-section row counts update in real time. Categories
and sections with zero visible rows hide via `style.display = 'none'`.
The Mods separator hides if no following category in its section is still
visible. With `autoExpand=true`, every visible category/section is
force-opened so the user sees results immediately.

**Manual layout snapshot/restore.** When a filter activates from a
fully-clear state, the open/closed state of every `<details>` is
snapshotted into `savedOpenState`. When all filters clear, the snapshot
is restored. Manual open/close changes the user makes *while* a filter is
active are intentionally not preserved — the filter is a transient view.

**Pinning.** Pinned paths persist as a JSON array under
`localStorage.a3km:pinned`. Pin sources of truth: row checkboxes mirror
the `pinnedPaths` Set; category checkboxes are derived (checked when all
visible child rows are pinned, indeterminate when some). Clicking a
category pin toggles every *visible* row in that category — combined
with text filter or Hide Unbound, this gives "pin everything I currently
see" behavior. Disabled state on Show Pinned and Unpin all auto-syncs
with `pinnedPaths.size > 0`.

**Open/closed state persistence.** Section/category open state persists
under `localStorage.a3km:open` keyed by stable identifiers
(`s:<section>` for sections, `c:<section>/<category>` for categories,
to avoid collisions between identically-named categories across
sections). The `toggle` listener gates writes on
`savedOpenState === null && collisionGroupActive === null` so
filter-driven auto-expansion doesn't overwrite the user's baseline
layout. Restoration runs at load time *before* the listener attaches,
so the load-time `.open = true` calls don't write redundantly.

**Collision view.** Clicking a `⚠` marker enters a mode where the page
filters to that conflict group and only key segments matching the
anchor row are highlighted red. The marker becomes an amber chip
(`.active-collision-anchor`). Clicking the same chip (or pressing Esc)
exits the mode. Clicking a different `⚠` re-anchors. Entering collision
view clears the text filter and Show Pinned for an exclusive view.
Hide Unbound is left alone since collision rows are bound by definition.

**Esc cascade.** Single keydown handler. First press clears any active
filter (text, Show Pinned, Hide Unbound, collision view) in one shot.
If no filter is active, Esc collapses every section and category. The
user can spam Esc to walk back to a fully-clean page state.

**Sticky stack.** Five layers stick to the top, each below the one above:

| Layer | top | z-index |
|---|---|---|
| `.controls-bar` | `0` | 10 |
| `details.section > summary` | `--controls-h - 1px` | 6 |
| `.separator` (Mods, in Base only) | `--controls-h + --section-h - 2px` | 5 |
| `details.category > summary` (default) | `--controls-h + --section-h - 2px` | 4 |
| `.separator ~ details.category > summary` (after Mods) | `--controls-h + --section-h + --separator-h - 3px` | 4 |

The `--controls-h`, `--section-h`, `--separator-h` CSS variables are kept
in sync with rendered heights via `ResizeObserver` (`Math.ceil` of
`getBoundingClientRect().height` to round up sub-pixel heights). The
`-1px` / `-2px` / `-3px` adjustments are deliberate 1px overlaps between
adjacent layers — the upper layer's higher z-index covers the overlap
visually, and it prevents sub-pixel-rounding gaps from showing scrolling
content between sticky layers. An `IntersectionObserver` toggles a
`.stuck` class on the controls bar (sentinel-based) so a 1px green
underline appears via `box-shadow`.

**Custom tooltip.** A single delegated `mouseover` listener attaches one
reusable `<div class="custom-tooltip">` to the body and shows it cursor-
anchored after a 150ms delay (vs the browser default ~600ms for
`title=`). Reads `data-tooltip` from any element. Hides on `mouseout`,
scroll, and tooltip-target removal.

**Auto-focus on load.** The filter input gets focus on first paint so
typing works immediately. Used to also auto-focus on the `.controls-bar`
becoming sticky, but that triggered the input's green `:focus` border
during scroll — focus is now load-only.

### CLI — `cli.py`

Thin argparse wrapper. Two modes:
- **No arguments** → copy the bundled `extract_all.sqf` to the OS clipboard
  and exit (Windows `clip` with UTF-16-LE, macOS `pbcopy`, Linux `xclip`
  or `xsel`). The SQF is loaded from package data first, falling back to
  the project root's `scripts/` for editable installs.
- **With `dump` positional** → render the keymap. Pipeline:
  read → `parse_dump` → `build_report` → `render` → write file. Handles
  `DumpParseError` with a friendly message.

Other flags:
- `-o / --output` (default `YYYY_MM_DD-Arma3_Keymaker.html`)
- `--json` (optional sibling JSON output)

---

## Bundled data — `data/`

| File | Purpose |
|---|---|
| `vanilla_actions.json` | 446 entries `[{category, action_id, label}, …]` extracted from the [BIS wiki][1]. Used by `merger._load_vanilla_actions` for the `(category, label) → action_id` lookup. |
| `keymaker_banner.png` | Banner embedded as base64 in every rendered keymap. |

Both files are also bundled inside the package
(`src/a3_keymaker/data/`) via `[tool.setuptools.package-data]` so the CLI
finds them when installed (not just in dev checkouts).

[1]: https://community.bistudio.com/wiki/inputAction/actions

---

## Testing — `tests/`

A single test module (`test_pipeline.py`) exercises the whole pipeline
against a real captured dump (`tests/fixtures/sample_dump.txt`) from a
heavily-modded install. Tests cover:

- All five SQF sections parse correctly
- SQF `""` quote-doubling unescapes correctly
- Clipboard mojibake gets reversed (CBA Quick-Time Events `↑↓←→`)
- Vanilla key resolution via wiki lookup
- Old-style mod key resolution via CfgUserActions
- displayName disambiguation across mods (A10C vs F16V "Loadout Menu")
- CBA addon walker output preserved
- `=== Mods ===` separator handled (skipped in walk, inserted in render)
- In-game category order preserved
- Path format collapses BASE_MODS → BASE
- Collision detection (Map / Hide Map both bound to "M")
- HTML renders without errors

Running with a real dump means the suite catches regressions in
end-to-end behavior, not just unit invariants.

---

## Known limitations

- **Requires Arma running.** No way to capture a dump without launching
  the game and walking the Controls dialog.
- **Some mods skip both `Mappings` and `CfgUserActions`** — e.g. the
  UH-60M Blackhawk addon (H-60 family categories). Their actions appear
  in the UI walk but we can't resolve action IDs to query
  `actionKeysNames`. If a user reports such a mod's bindings showing
  blank when they're set in-game, we'd need to find that mod's alternate
  registration path.
- **Clipboard mojibake fix is heuristic.** Triggers only on the specific
  UTF-8 → CP1252 → UTF-8 round-trip pattern. Other corruption modes
  would pass through unchanged.
- **Collision detection has no smart filtering** by design — flags every
  shared key including by-design mutually-exclusive overlaps (`Move Forward`
  in Infantry / Vehicle / Camera all on `W`). A typical heavily-modded
  install will show a few hundred collision markers; many are benign.

---

## Predecessor project

A separate predecessor project (package name `a3kex`) was the original
HEMTT-based extractor. The two projects are independent; the new SQF
approach is a from-scratch rewrite, not a migration. See the rejection
rationale in [Why not parse .Arma3Profile or HEMTT-extract PBOs?](#why-not-parse-arma3profile-or-hemtt-extract-pbos)
above.
