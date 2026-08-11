"""Per-program Board Pack: the single source of truth for a program's hardware
definition (test points, schematic circuits, fault trees, power tree, specs).

WHY THIS EXISTS
---------------
Board data used to be hardcoded module-level constants in `debugger.py` and
`daa_fa_engine.py`. Because those constants were program-agnostic, EVERY program
(Merci, Jupiter, ...) displayed Snowbird's test points and specs — actively
dangerous, since a technician could probe the wrong pads or trust the wrong
spec limits. This module makes all board data per-program and explicit.

ARCHITECTURE
------------
Each program owns a pack on disk:

    programs/<slug>/board/board_pack.json      <- machine-readable definition
    programs/<slug>/board/schematics/          <- source PDFs/images (reference)
    programs/<slug>/<slug>_debug_bible.md      <- narrative debug bible

Design principles (standard config-driven / multi-tenant patterns):
  * Per-program configuration, never global.
  * Declared CAPABILITIES rather than assumed features.
  * GRACEFUL DEGRADATION: a program with no pack loses only the hardware-specific
    features and says so; it never silently shows another program's data.
  * VERSIONED + VALIDATED: every pack declares `pack_version` and is validated on
    load, so a malformed pack fails loudly instead of rendering wrong numbers.

The validator is dependency-free on purpose (no new package to vet), and the
schema is internal/trusted.
"""

from __future__ import annotations

import json
import os
from functools import lru_cache

PACK_VERSION = "1.0"
PACK_FILENAME = "board_pack.json"

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
PROGRAMS_DIR = os.path.join(BASE_DIR, "programs")

# Pack completeness states surfaced in the UI.
STATUS_COMPLETE = "complete"
STATUS_IN_PROGRESS = "in_progress"
STATUS_MISSING = "missing"

# Required keys for each test point (the ones the debugger/engine rely on).
_TP_REQUIRED = ("tp", "name", "unit", "lsl", "usl", "phase", "group", "step")


def _slug(program: str) -> str:
    return (program or "").lower().replace(" ", "_")


def pack_dir(program: str) -> str:
    """Directory holding a program's board pack + schematic sources."""
    return os.path.join(PROGRAMS_DIR, _slug(program), "board")


def pack_path(program: str) -> str:
    return os.path.join(pack_dir(program), PACK_FILENAME)


def schematics_dir(program: str) -> str:
    return os.path.join(pack_dir(program), "schematics")


def bible_path(program: str) -> str | None:
    """Return the program's debug bible path if present (checked in both the
    program root and the board/ subdirectory)."""
    s = _slug(program)
    candidates = [
        os.path.join(PROGRAMS_DIR, s, f"{s}_debug_bible.md"),
        os.path.join(pack_dir(program), f"{s}_debug_bible.md"),
        os.path.join(pack_dir(program), "debug_bible.md"),
    ]
    for c in candidates:
        if os.path.isfile(c):
            return c
    return None


# --------------------------------------------------------------------------- #
# Validation (dependency-free)
# --------------------------------------------------------------------------- #
def validate_pack(pack: dict) -> list:
    """Return a list of human-readable problems. Empty list == valid."""
    issues = []
    if not isinstance(pack, dict):
        return ["Pack is not a JSON object."]

    if not pack.get("program"):
        issues.append("Missing required field: 'program'.")
    pv = str(pack.get("pack_version", ""))
    if not pv:
        issues.append("Missing required field: 'pack_version'.")
    elif pv.split(".")[0] != PACK_VERSION.split(".")[0]:
        issues.append(f"Pack major version '{pv}' is incompatible with supported '{PACK_VERSION}'.")

    phases = pack.get("phases") or {}
    tps = pack.get("test_points") or {}
    if not isinstance(phases, dict):
        issues.append("'phases' must be an object keyed by phase number.")
        phases = {}
    if not isinstance(tps, dict):
        issues.append("'test_points' must be an object keyed by unique rail id.")
        tps = {}

    # Test point structure + referential integrity
    steps = {}
    for key, tp in tps.items():
        if not isinstance(tp, dict):
            issues.append(f"test_points['{key}'] must be an object.")
            continue
        for field in _TP_REQUIRED:
            if field not in tp:
                issues.append(f"test_points['{key}'] missing required field '{field}'.")
        lsl, usl = tp.get("lsl"), tp.get("usl")
        if isinstance(lsl, (int, float)) and isinstance(usl, (int, float)) and lsl > usl:
            issues.append(f"test_points['{key}']: lsl ({lsl}) is greater than usl ({usl}).")
        ph = tp.get("phase")
        if phases and ph is not None and str(ph) not in {str(k) for k in phases}:
            issues.append(f"test_points['{key}'] references unknown phase '{ph}'.")
        st = tp.get("step")
        if st is not None:
            steps.setdefault(st, []).append(key)
    for st, keys in steps.items():
        if len(keys) > 1:
            issues.append(f"Duplicate probe step {st} used by: {', '.join(keys)}.")

    # Power tree referential integrity + cycle detection
    tree = pack.get("power_tree") or {}
    if tree and not isinstance(tree, dict):
        issues.append("'power_tree' must be an object keyed by rail id.")
        tree = {}
    root = pack.get("power_tree_root", "__SOURCE__")
    for node, meta in (tree.items() if isinstance(tree, dict) else []):
        if not isinstance(meta, dict):
            issues.append(f"power_tree['{node}'] must be an object.")
            continue
        if tps and node not in tps:
            issues.append(f"power_tree['{node}'] is not a declared test point.")
        parent = meta.get("parent")
        if parent is None:
            issues.append(f"power_tree['{node}'] missing 'parent'.")
        elif parent != root and parent not in tree:
            issues.append(f"power_tree['{node}'] parent '{parent}' is not in the power tree.")
    # cycles
    for node in (tree if isinstance(tree, dict) else {}):
        seen, cur = set(), node
        while cur and cur != root:
            if cur in seen:
                issues.append(f"Cycle detected in power_tree at '{cur}'.")
                break
            seen.add(cur)
            cur = (tree.get(cur) or {}).get("parent")

    for k in (pack.get("boot_critical") or []):
        if tps and k not in tps:
            issues.append(f"boot_critical entry '{k}' is not a declared test point.")

    return issues


# --------------------------------------------------------------------------- #
# Loading
# --------------------------------------------------------------------------- #
@lru_cache(maxsize=32)
def _load_raw(path: str, mtime: float) -> tuple:
    """Cached JSON read keyed by path+mtime so edits are picked up automatically."""
    try:
        with open(path, encoding="utf-8") as f:
            return (json.load(f), None)
    except Exception as e:  # malformed JSON, permissions, etc.
        return (None, f"Could not read board pack: {e}")


def load_pack(program: str) -> dict | None:
    """Load and validate a program's board pack.

    Returns the pack dict, or None when the program has no pack. A pack that
    exists but fails validation is returned with '_issues' populated so the UI
    can warn instead of silently using bad data.
    """
    if not program:
        return None
    path = pack_path(program)
    if not os.path.isfile(path):
        return None
    pack, err = _load_raw(path, os.path.getmtime(path))
    if err or pack is None:
        return {"program": program, "pack_version": PACK_VERSION, "_issues": [err or "Unknown read error"],
                "status": STATUS_IN_PROGRESS, "phases": {}, "test_points": {}}
    issues = validate_pack(pack)
    pack = dict(pack)
    pack["_issues"] = issues
    pack["_path"] = path
    # Normalize phase keys to int for the debugger's sorted-phase logic.
    if isinstance(pack.get("phases"), dict):
        norm = {}
        for k, v in pack["phases"].items():
            try:
                norm[int(k)] = v
            except (TypeError, ValueError):
                norm[k] = v
        pack["phases"] = norm
    return pack


# --------------------------------------------------------------------------- #
# Accessors (always safe — empty defaults, never another program's data)
# --------------------------------------------------------------------------- #
def phases(program: str) -> dict:
    p = load_pack(program) or {}
    return p.get("phases") or {}


def test_points(program: str) -> dict:
    p = load_pack(program) or {}
    return p.get("test_points") or {}


def schematic(program: str) -> dict:
    p = load_pack(program) or {}
    return p.get("schematic") or {}


def fault_trees(program: str) -> dict:
    p = load_pack(program) or {}
    return p.get("fault_trees") or {}


def power_tree(program: str) -> dict:
    p = load_pack(program) or {}
    return p.get("power_tree") or {}


def power_tree_root(program: str) -> str:
    p = load_pack(program) or {}
    return p.get("power_tree_root") or "__SOURCE__"


def boot_critical(program: str) -> list:
    p = load_pack(program) or {}
    return p.get("boot_critical") or []


def complaint_branches(program: str) -> dict:
    p = load_pack(program) or {}
    return p.get("complaint_branches") or {}


def board_map(program: str) -> dict:
    p = load_pack(program) or {}
    return p.get("board_map") or {}


def product_specs(program: str) -> dict:
    p = load_pack(program) or {}
    return p.get("product") or {}


def led_codes(program: str) -> dict:
    p = load_pack(program) or {}
    return p.get("led_codes") or {}


def board_graph(program: str) -> dict:
    """Bundle the power-tree topology for the DAA engine. Empty tree == the
    program has no power model yet, and the engine will report that rather than
    silently using another program's topology."""
    p = load_pack(program) or {}
    return {
        "root": p.get("power_tree_root") or "__SOURCE__",
        "tree": p.get("power_tree") or {},
        "boot_critical": p.get("boot_critical") or [],
        "complaint_branches": p.get("complaint_branches") or {},
    }


def capabilities(program: str) -> dict:
    """What this program actually supports. The UI must branch on these instead
    of assuming hardware data exists."""
    pack = load_pack(program)
    if pack is None:
        return {
            "has_pack": False, "status": STATUS_MISSING, "issues": [],
            "has_test_points": False, "has_schematic": False, "has_fault_trees": False,
            "has_power_tree": False, "has_board_map": False, "has_product_specs": False,
            "has_led_codes": False, "has_bible": bible_path(program) is not None,
            "n_test_points": 0, "n_phases": 0, "n_schematic": 0,
            "pack_path": pack_path(program),
        }
    tps = pack.get("test_points") or {}
    return {
        "has_pack": True,
        "status": pack.get("status") or (STATUS_COMPLETE if tps else STATUS_IN_PROGRESS),
        "issues": pack.get("_issues") or [],
        "has_test_points": bool(tps),
        "has_schematic": bool(pack.get("schematic")),
        "has_fault_trees": bool(pack.get("fault_trees")),
        "has_power_tree": bool(pack.get("power_tree")),
        "has_board_map": bool((pack.get("board_map") or {}).get("test_point_positions")),
        "has_product_specs": bool(pack.get("product")),
        "has_led_codes": bool(pack.get("led_codes")),
        "has_bible": bible_path(program) is not None,
        "n_test_points": len(tps),
        "n_phases": len(pack.get("phases") or {}),
        "n_schematic": len(pack.get("schematic") or {}),
        "pack_path": pack.get("_path") or pack_path(program),
    }


def programs_with_packs() -> list:
    """All program slugs that currently ship a board pack."""
    out = []
    if not os.path.isdir(PROGRAMS_DIR):
        return out
    for entry in sorted(os.listdir(PROGRAMS_DIR)):
        if os.path.isfile(os.path.join(PROGRAMS_DIR, entry, "board", PACK_FILENAME)):
            out.append(entry)
    return out


# --------------------------------------------------------------------------- #
# Onboarding template
# --------------------------------------------------------------------------- #
def template(program: str = "NewProgram") -> dict:
    """A minimal, valid starter pack for onboarding a new program."""
    return {
        "pack_version": PACK_VERSION,
        "program": program,
        "status": STATUS_IN_PROGRESS,
        "product": {
            "product": f"{program} (fill in marketing name)",
            "type": "e.g. Indoor WiFi 7 Mesh Router",
            "power": "e.g. 45W USB-C PSU / PoE+",
            "notes": "Fill from the product spec sheet.",
        },
        "phases": {
            "1": {"name": "Input Power Stage", "icon": "🔌",
                  "desc": "Verify input power and the main system rail", "critical": True},
        },
        "test_points": {
            "V_EXAMPLE_RAIL": {
                "tp": "TP1", "name": "Example 5V Rail", "unit": "V",
                "lsl": 4.75, "nom": 5.0, "usl": 5.25,
                "phase": 1, "group": "Input Power Stage", "step": 1,
                "subsystem": "Main DC/DC", "loc": "TP1 — describe board location",
                "fail_action": "0V = converter not switching; check EN pin and input.",
            },
        },
        "schematic": {
            "TP1": {
                "circuit_name": "Example 5V Rail",
                "schematic_path": "Input → DC/DC → TP1 → system bus",
                "ic": "e.g. MPQxxxx",
                "description": "What this rail does and why it matters.",
                "key_components": ["Converter IC", "Inductor", "Output caps"],
                "failure_modes": {"0V output": "Converter not switching — check EN."},
                "component_diagnostics": [],
                "related_tps": [],
            },
        },
        "fault_trees": {
            "Input Power Stage": {
                "title": "Input Power Fault Isolation",
                "steps": ["1. Measure input voltage", "2. Measure main rail", "3. Check EN pin"],
            },
        },
        "power_tree_root": "__SOURCE__",
        "power_tree": {
            "V_EXAMPLE_RAIL": {"parent": "__SOURCE__", "verified": False},
        },
        "boot_critical": ["V_EXAMPLE_RAIL"],
        "complaint_branches": {"DEAD": ["V_EXAMPLE_RAIL"]},
        "board_map": {"regions": [], "test_point_positions": []},
        "led_codes": {},
    }


# --------------------------------------------------------------------------- #
# CLI: validate / scaffold
# --------------------------------------------------------------------------- #
def _cli():
    import sys
    args = sys.argv[1:]
    if not args or args[0] in ("-h", "--help"):
        print(__doc__)
        print("Usage:\n"
              "  python board_pack.py validate <Program>        Validate a program's pack\n"
              "  python board_pack.py validate-all              Validate every pack found\n"
              "  python board_pack.py init <Program>            Write a starter pack\n"
              "  python board_pack.py status                    Show capabilities per program")
        return 0
    cmd = args[0]

    if cmd == "validate" and len(args) == 2:
        prog = args[1]
        pack = load_pack(prog)
        if pack is None:
            print(f"❌ {prog}: no board pack at {pack_path(prog)}")
            return 1
        issues = pack.get("_issues") or []
        if issues:
            print(f"❌ {prog}: {len(issues)} issue(s)")
            for i in issues:
                print(f"   - {i}")
            return 1
        cap = capabilities(prog)
        print(f"✅ {prog}: valid pack — {cap['n_test_points']} test points, "
              f"{cap['n_phases']} phases, {cap['n_schematic']} schematic entries")
        return 0

    if cmd == "validate-all":
        rc = 0
        for slug in programs_with_packs():
            pack = load_pack(slug)
            issues = (pack or {}).get("_issues") or []
            if issues:
                rc = 1
                print(f"❌ {slug}: {len(issues)} issue(s)")
                for i in issues:
                    print(f"   - {i}")
            else:
                print(f"✅ {slug}: valid")
        if not programs_with_packs():
            print("No board packs found.")
        return rc

    if cmd == "init" and len(args) == 2:
        prog = args[1]
        d = pack_dir(prog)
        os.makedirs(os.path.join(d, "schematics"), exist_ok=True)
        p = pack_path(prog)
        if os.path.exists(p):
            print(f"Refusing to overwrite existing pack: {p}")
            return 1
        with open(p, "w", encoding="utf-8") as f:
            json.dump(template(prog), f, indent=2)
        print(f"Created starter pack: {p}\nNext: edit it, then run "
              f"`python board_pack.py validate {prog}`")
        return 0

    if cmd == "status":
        for slug in sorted(os.listdir(PROGRAMS_DIR)):
            if not os.path.isdir(os.path.join(PROGRAMS_DIR, slug)):
                continue
            cap = capabilities(slug)
            mark = "✅" if cap["has_pack"] and not cap["issues"] else ("⚠️" if cap["has_pack"] else "—")
            print(f"{mark} {slug:<12} status={cap['status']:<12} "
                  f"TPs={cap['n_test_points']:<3} schematic={cap['n_schematic']:<3} "
                  f"bible={'yes' if cap['has_bible'] else 'no'}")
        return 0

    print("Unrecognized command. Use --help.")
    return 1


if __name__ == "__main__":
    raise SystemExit(_cli())
