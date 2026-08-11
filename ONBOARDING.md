# Onboarding a New Program

This is the repeatable process for adding a program (e.g. Merci, Jupiter) to
Failure Analyzer so it gets the same capabilities Snowbird has: PCB Debugger,
DAA Fault Localizer, schematic lookup, and program-specific triage.

## Why the process exists

Board data used to be hardcoded in `debugger.py`, so **every** program showed
Snowbird's test points and spec limits. That is a safety problem: a technician
could probe the wrong pads or accept the wrong KGU limits. Now every program owns
a **board pack**, and any feature without data says so instead of borrowing
another board's numbers.

## Directory layout per program

```
programs/<slug>/
├── board/
│   ├── board_pack.json          ← machine-readable hardware definition (required)
│   └── schematics/               ← source design docs (PDFs, PCB images)
├── data/                         ← field-return CSVs
├── ml_training/
│   ├── debug_reports/            ← saved FA reports (ML corpus)
│   └── debugger_ml_model.json    ← learned patterns
└── <slug>_debug_bible.md         ← narrative debug bible (optional but recommended)
```

## Capability model

The app reads capabilities from the pack and degrades gracefully:

| Pack contains | Unlocks |
|---|---|
| `product` | Triage product spec panel, serial/PSU pickers |
| `led_codes` | LED status reference + LED-based diagnosis |
| `phases` + `test_points` | **PCB Debugger** (guided, quick scan, deep dive) |
| `schematic` | Schematic circuit lookup + component diagnostic checklists |
| `fault_trees` | Deep-dive fault isolation steps |
| `power_tree` + `boot_critical` | **DAA Fault Localizer** (root-cause localization) |
| `board_map.test_point_positions` | Visual PCB reference map |
| `<slug>_debug_bible.md` | Debug bible reference |

Anything missing renders an explicit "not available yet" state with these steps.

---

## Step-by-step

### 1. Register the program (if new)
Use the app's program selector ("Register New Program"), or add it to
`programs/registry.json`. This creates `data/` and `ml_training/`.

### 2. Scaffold the board pack
```bash
python board_pack.py init Merci
```
Creates `programs/merci/board/board_pack.json` (a valid starter) and
`programs/merci/board/schematics/`.

### 3. Add the source design documents
Drop the reference material into `programs/merci/board/schematics/`:
- Schematic PDF (power tree pages especially)
- PCB top/bottom images (for test-point positions)
- Power-tree / block diagram
- KGU measurement report, if one exists

These are reference-only; the app reads the JSON pack, not the PDFs.

### 4. Fill in the pack

Work in this order — each section unlocks more of the app.

**a) `product`** — from the product spec sheet. Free-form keys are fine; add
`serial_format` and `power_adapters` to drive the triage inputs.

**b) `phases`** — the power-on sequence, in order. Mark `critical: true` for
phases the unit cannot boot without.
```json
"phases": {
  "1": {"name": "Input Power Stage", "icon": "🔌",
         "desc": "Verify input power and the main rail", "critical": true}
}
```

**c) `test_points`** — one entry per measurable rail. **This is the core.**
```json
"V_MAIN_5V": {
  "tp": "TP12",                    // silkscreen label
  "name": "5V System Rail",
  "unit": "V",
  "lsl": 4.75, "nom": 5.0, "usl": 5.25,   // KGU spec window
  "phase": 1,
  "group": "Input Power Stage",     // must match a fault_trees key
  "step": 1,                        // probe order, unique across the pack
  "subsystem": "U5 buck converter",
  "loc": "TP12 — left edge near the DC jack",
  "fail_action": "0V = converter not switching; check EN pin and input.",
  "monitor": false                  // true = informational only, never a FAIL
}
```
Rules the validator enforces: required fields present, `lsl <= usl`, `phase`
exists, and `step` values unique.

**d) `schematic`** — keyed by the `tp` value. Add `component_diagnostics`
entries (ref, component, location, priority, check, expected, if_fail, tools) to
get the component-level checklist.

**e) `fault_trees`** — keyed by `group`, with `title` and ordered `steps`.

**f) `power_tree`** — **this is what powers DAA localization.** For each rail,
name its power source:
```json
"power_tree_root": "__SOURCE__",
"power_tree": {
  "V_MAIN_5V":  {"parent": "__SOURCE__", "verified": true},
  "V_SOC_CORE": {"parent": "V_MAIN_5V",  "verified": true},
  "V_DDR_VPP":  {"parent": "V_MAIN_5V",  "verified": true,
                  "seq_after": "V_DDR_CORE"},
  "V_PHY_CORE": {"parent": "V_MAIN_5V",  "verified": false,
                  "co_requires": ["V_IO_1V8"]}
}
```
- `verified: true` = you confirmed the edge on the schematic. `false` = inferred;
  the UI lists these for engineer review.
- `seq_after` = must power up after that rail (sequencing faults).
- `co_requires` = also needs those rails to function.

**g) `boot_critical`** — rails that must pass or the unit is dead, ordered
top-down. This is the guided probe sequence for a "dead" complaint.

**h) `complaint_branches`** — optional per-symptom probe orders
(`DEAD`, `DOA`, `REBOOTS`, `NO_WIFI`, `NO_ETHERNET`, `NO_RF`).

**i) `board_map`** — optional. `regions` (labelled boxes) and
`test_point_positions` (`step`, `tp`, `signal`, `x`, `y`, `group`) on the
`viewbox` grid, plus `group_colors`.

### 5. Add the debug bible
Save narrative debug knowledge as `programs/merci/merci_debug_bible.md`.

### 6. Validate
```bash
python board_pack.py validate Merci     # one program
python board_pack.py validate-all       # everything
python board_pack.py status             # capability overview
```
Fix every reported issue. The validator checks schema, spec-limit sanity,
duplicate probe steps, unknown phase references, power-tree referential
integrity, and cycles.

### 7. Verify in the app
Reload, select the program, open **PCB Debugger**. The guided phases, board map,
and **🎯 DAA Fault Localizer** should all populate. Check the
"Power-tree model & edges to verify" panel and confirm the inferred edges.

---

## Suggested build order (fastest path to value)

1. `product` + `led_codes` → triage gets program-correct context (~30 min)
2. `phases` + `test_points` → PCB Debugger works (the bulk of the effort)
3. `power_tree` + `boot_critical` → DAA Fault Localizer works
4. `schematic` + `fault_trees` → deep diagnostics
5. `board_map` → visual reference
6. Debug bible → narrative knowledge

Set `"status": "in_progress"` while filling it in, and `"complete"` when the
board is fully modeled.

## Data hygiene

- Board packs describe **hardware**, not customers — no PII.
- Schematics and packs are confidential; keep them in access-controlled storage
  and out of any public repository or container image.
- Spec limits must come from the KGU/spec document, not from a single sample.
