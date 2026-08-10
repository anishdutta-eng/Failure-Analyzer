"""DAA (Dead After Arrival) Failure-Analysis Knowledge Base.

A domain-agnostic, citable body of PCB / electronics failure-analysis knowledge
used by the DAA FA engine to reason about *why* a rail or board is dead. It is
deliberately independent of any single product so it can be reused across
programs; the engine fuses it with a specific board's power tree (e.g. Snowbird)
to produce concrete hypotheses.

Structure
---------
- FAILURE_MECHANISMS : the catalogue of physics-of-failure mechanisms, each with
  symptoms, root causes, the electrical signature it produces, and the tests
  (nondestructive first) that confirm it, plus source references.
- ELECTRICAL_SIGNATURES : maps what you *measure* (e.g. "rail at 0 V, <1 Ohm to
  ground") to the ranked set of mechanisms that produce that signature.
- FA_METHODOLOGY : the ordered, nondestructive-before-destructive investigation
  workflow used in professional failure analysis.
- REFERENCES : the sources the knowledge was distilled from.

Compliance note: all descriptive text was paraphrased/summarized from the cited
public sources for licensing compliance; no source is quoted at length. Use the
reference links for the authoritative originals.
"""

from __future__ import annotations


# --------------------------------------------------------------------------- #
# References (id -> citation). Kept small and linkable.
# --------------------------------------------------------------------------- #
REFERENCES = {
    "esda_eos": {
        "title": "Industry Council on ESD Target Levels — EOS white paper",
        "url": "https://www.esda.org/assets/IndustryCouncilOnESDTargetLevels_WP4.pdf",
    },
    "siemens_eos": {
        "title": "Electrical Overstress Detection and Debugging (Siemens Calibre)",
        "url": "https://blogs.sw.siemens.com/calibre/2015/09/29/electrical-overstress-detection-and-debugging/",
    },
    "electronicdesign_eos_esd": {
        "title": "Identifying EOS and ESD Failures in Semiconductor Devices (Electronic Design)",
        "url": "https://www.electronicdesign.com/technologies/power/article/21799782/identifying-eos-and-esd-failures-in-semiconductor-devices",
    },
    "richtek_vin": {
        "title": "Analyzing VIN overstress in Power ICs (Richtek AN048)",
        "url": "https://richtek.com/Design%20Support/Technical%20Document/AN048",
    },
    "eepower_buck": {
        "title": "Troubleshooting 9 Common DC-DC Buck Converter Issues (EE Power, G. Biner)",
        "url": "https://eepower.com/technical-articles/troubleshooting-9-common-dc-dc-buck-converter-issues/",
    },
    "fluke_dmm": {
        "title": "Troubleshooting DC Power Supplies Using a Digital Multimeter (Fluke)",
        "url": "https://www.fluke.com/en/learn/blog/predictive-maintenance/troubleshooting-dc-power-supply-with-digital-multimeter",
    },
    "ipc_7095_xray": {
        "title": "X-Ray Inspection for BGA Packages (IPC-7095D context)",
        "url": "https://www.allpcb.com/allelectrohub/x-ray-inspection-for-bga-packages-a-comprehensive-guide",
    },
    "sjbist": {
        "title": "BGA Solder Joint Intermittency Detection (SJ BIST)",
        "url": "https://www.researchgate.net/publication/224314758_Ball_Grid_Array_BGA_Solder_Joint_Intermittency_Detection_SJ_BIST",
    },
    "jlcpcb_void": {
        "title": "BGA Void: Causes, IPC Standards, and Prevention (JLCPCB)",
        "url": "https://jlcpcb.com/blog/bga-void-ultimate-guide",
    },
    "nasa_mlcc_crack": {
        "title": "Cracking of MLCCs (NASA NEPP, Teverovsky)",
        "url": "https://nepp.nasa.gov/files/29931/NEPP-BOK-2018-Teverovsky-Paper-NEPPWeb-BOK-Cracking-MLCC-TN65668.pdf",
    },
    "nasa_mlcc_dendrite": {
        "title": "Dendrite growth in BME and PME ceramic capacitors (NASA NEPP)",
        "url": "https://nepp.nasa.gov/files/24618/Dendrite%20growth%20in%20BME%20and%20PME%20ceramic%20capacitors%20CARTS2013_n195.pdf",
    },
    "mlcc_overview": {
        "title": "Multilayer Ceramic Capacitors: Failure Mechanisms Overview (MDPI)",
        "url": "https://www.mdpi.com/2079-9292/12/6/1297/xml",
    },
    "ipc_ecm": {
        "title": "Cleaning prior to Conformal Coating / climatic reliability (IPC)",
        "url": "https://www.ipc.org/system/files/technical_resource/E12&S09_02.pdf",
    },
    "ecm_review": {
        "title": "Electrochemical Migration in Electronic Materials — Review (ResearchGate)",
        "url": "https://www.researchgate.net/publication/367418746_Review-Electrochemical_Migration_in_Electronic_Materials",
    },
    "caf_rca": {
        "title": "Root Cause Analysis of a PCB Failure — CAF case study (MDPI)",
        "url": "https://www.mdpi.com/2076-3417/12/2/640/xml",
    },
    "edfa_methodology": {
        "title": "Complex Systems Failure Analysis Challenges (ASM EDFA)",
        "url": "https://dl.asminternational.org/edfa-tech/article-pdf/10/4/6/622836/edfa.2008-4.p006.pdf",
    },
    "ansys_components": {
        "title": "How to Identify Common Electronic Component Failures (Ansys)",
        "url": "https://www.ansys.com/en-in/blog/how-to-identify-common-electronic-failures",
    },
}


# --------------------------------------------------------------------------- #
# Signature vocabulary
# --------------------------------------------------------------------------- #
# The electrical "signature" a fault presents at a node. The engine derives
# these from voltage readings + optional resistance-to-ground probes.
SIG_DEAD_SHORT = "dead_short"        # ~0 V and low resistance to GND (<~1 Ohm)
SIG_DEAD_OPEN = "dead_open"          # ~0 V and high resistance to GND (>~5 Ohm)
SIG_LOW = "low"                      # present but below LSL (droop / overload)
SIG_HIGH = "high"                    # above USL (feedback/regulation fault)
SIG_RIPPLE = "ripple"                # excessive AC ripple on an otherwise-present rail
SIG_INTERMITTENT = "intermittent"    # comes and goes with stress/temperature/flex
SIG_LEAKAGE = "leakage"              # elevated leakage / degraded insulation resistance


# --------------------------------------------------------------------------- #
# Failure mechanisms catalogue
# --------------------------------------------------------------------------- #
# Each mechanism:
#   name, category, layer (which part of the system),
#   description (paraphrased), symptoms, root_causes,
#   signatures (list of SIG_* it can produce),
#   nondestructive_tests, destructive_tests,
#   environmental_drivers, refs (reference ids)
FAILURE_MECHANISMS = {
    "regulator_open": {
        "name": "Regulator / converter not switching (open output)",
        "category": "Power delivery",
        "layer": "IC / converter",
        "description": (
            "A DC/DC converter or LDO produces no output. Common causes are the "
            "enable pin not asserted, a missing power-good handshake, a failed "
            "controller, or an open in the inductor/output path."
        ),
        "symptoms": ["rail reads 0 V", "downstream domain dead", "no switching-node activity"],
        "root_causes": [
            "Enable pin not driven / pull-up missing",
            "Power-good (PGOOD) from upstream stage held low, blocking sequencing",
            "Controller IC failure (no switching)",
            "Open power inductor or open series ferrite bead",
            "Bootstrap capacitor failure (slow/absent switching edges)",
        ],
        "signatures": [SIG_DEAD_OPEN],
        "nondestructive_tests": [
            "Verify EN pin is asserted (driven or pulled up)",
            "Check PGOOD of the upstream stage",
            "Scope the switching node for the expected switching frequency",
            "Resistance to ground high (>~5 Ohm) confirms open, not short",
            "DCR check of the power inductor / continuity of series ferrite",
        ],
        "destructive_tests": ["Decapsulation + microprobe of controller if replacement does not restore"],
        "environmental_drivers": [],
        "refs": ["eepower_buck", "fluke_dmm", "richtek_vin"],
    },
    "downstream_short": {
        "name": "Downstream short pulling a rail down",
        "category": "Power delivery",
        "layer": "IC / capacitor / board",
        "description": (
            "A short on a rail forces the converter into current limit or "
            "collapses a shared bus. A large load capacitance can also mimic a "
            "short at start-up and trip the current limit."
        ),
        "symptoms": ["rail at 0 V or far below spec", "converter hot / current-limiting",
                     "whole shared bus down"],
        "root_causes": [
            "Shorted decoupling capacitor (cracked MLCC)",
            "IC die short (e.g. core supply shorted to ground)",
            "Solder bridge / conductive debris",
            "Excessive load capacitance tripping current limit at start-up",
        ],
        "signatures": [SIG_DEAD_SHORT, SIG_LOW],
        "nondestructive_tests": [
            "Resistance to ground low (<~1 Ohm) confirms short (board off)",
            "Isolate by lifting series ferrite beads one at a time to find the shorted branch",
            "Thermal camera under current-limited power to find the hot component",
            "Inspect for cracked ceramics / solder bridges under magnification",
        ],
        "destructive_tests": ["Cross-section of suspect short site", "Decap of IC to confirm die short"],
        "environmental_drivers": [],
        "refs": ["eepower_buck", "richtek_vin", "nasa_mlcc_crack"],
    },
    "eos": {
        "name": "Electrical Overstress (EOS)",
        "category": "Electrical stress",
        "layer": "IC",
        "description": (
            "Current or voltage beyond the device's safe limits melts junctions "
            "and metallization. EOS damage is the leading reported cause of IC "
            "field returns, and its burn signature points at the fault path."
        ),
        "symptoms": ["burn/discoloration on package", "cracked or holed mold compound",
                     "shorted or open pins", "localized charring"],
        "root_causes": [
            "Input over-voltage / surge (e.g. lightning, PoE surge)",
            "Reverse polarity or mis-applied supply",
            "Sustained over-current beyond ratings",
            "Latch-up leading to thermal runaway",
        ],
        "signatures": [SIG_DEAD_SHORT, SIG_DEAD_OPEN],
        "nondestructive_tests": [
            "Visual/microscope for burn marks, bulges, holes, discoloration in the package",
            "Curve-trace / characterize the damaged pins",
            "X-ray for internal metallization damage",
        ],
        "destructive_tests": [
            "Decapsulation to inspect melted metal / vaporized bond wires",
            "SEM/EMMI to localize junction burnout vs oxide rupture",
        ],
        "environmental_drivers": ["Surge exposure", "Poor grounding / transients"],
        "refs": ["esda_eos", "siemens_eos", "electronicdesign_eos_esd", "richtek_vin"],
    },
    "esd": {
        "name": "Electrostatic Discharge (ESD)",
        "category": "Electrical stress",
        "layer": "IC",
        "description": (
            "A fast, high-voltage discharge damages thin structures. Human-body "
            "model events tend to melt small regions, while charged-device model "
            "events tend to rupture gate dielectrics."
        ),
        "symptoms": ["pin leakage", "intermittent or marginal IC behavior", "gate/oxide damage"],
        "root_causes": ["Mishandling without ESD control", "Charged-device discharge during assembly"],
        "signatures": [SIG_LEAKAGE, SIG_DEAD_SHORT, SIG_INTERMITTENT],
        "nondestructive_tests": ["Pin leakage measurement", "Curve trace of suspect pins"],
        "destructive_tests": ["EMMI to find leakage site", "Deprocess + SEM of damaged junction/oxide"],
        "environmental_drivers": ["Low humidity handling", "Inadequate ESD protection"],
        "refs": ["electronicdesign_eos_esd", "esda_eos"],
    },
    "mlcc_crack": {
        "name": "Cracked multilayer ceramic capacitor (MLCC)",
        "category": "Passive component",
        "layer": "Capacitor",
        "description": (
            "Ceramic capacitors crack from board flex or soldering thermal shock. "
            "Cracks lower breakdown voltage and can progress to leakage, a short, "
            "or thermal runaway; the resulting behavior can even masquerade as a "
            "software fault."
        ),
        "symptoms": ["rail short or leakage", "intermittent power", "capacitor discoloration/crack"],
        "root_causes": [
            "Board flex during depaneling / handling / connector insertion",
            "Soldering or rework thermal shock",
            "Manufacturing defects (voids/delamination) plus in-use stress",
        ],
        "signatures": [SIG_DEAD_SHORT, SIG_LEAKAGE, SIG_INTERMITTENT],
        "nondestructive_tests": [
            "Resistance to ground on the affected rail (short hunt)",
            "Microscope inspection near board edges / connectors for flex cracks",
            "Thermal camera to find the leaking/short cap",
        ],
        "destructive_tests": ["Cross-section of the capacitor to confirm crack path"],
        "environmental_drivers": ["Thermal cycling", "Mechanical stress / vibration"],
        "refs": ["nasa_mlcc_crack", "mlcc_overview", "nasa_mlcc_dendrite"],
    },
    "solder_joint_fatigue": {
        "name": "Solder joint fatigue / BGA crack (thermal cycling)",
        "category": "Interconnect",
        "layer": "Solder / BGA",
        "description": (
            "Repeated thermal cycling drives crack growth at solder joints, worst "
            "at the outer balls of large BGAs. A fractured joint often keeps "
            "conducting for a while, then turns intermittent under stress."
        ),
        "symptoms": ["intermittent operation", "works cold then fails warm (or vice versa)",
                     "connection lost after handling"],
        "root_causes": [
            "CTE mismatch under thermal cycling (outdoor temperature swings)",
            "Voids in solder joints reducing strength (voiding >~25% is a concern)",
            "Head-in-pillow / non-wet balls from reflow issues",
            "Mechanical stress / vibration",
        ],
        "signatures": [SIG_INTERMITTENT, SIG_DEAD_OPEN],
        "nondestructive_tests": [
            "X-ray for cracks, voids, bridges, non-wet or head-in-pillow balls",
            "Freeze-spray / hot-air localization while monitoring the fault",
            "Flex/tap test while monitoring continuity",
        ],
        "destructive_tests": ["Dye-and-pry to reveal crack faces", "Cross-section + SEM of the joint"],
        "environmental_drivers": ["Thermal cycling", "Vibration", "Mechanical shock"],
        "refs": ["ipc_7095_xray", "sjbist", "jlcpcb_void"],
    },
    "electrochemical_migration": {
        "name": "Electrochemical migration / dendrites (moisture)",
        "category": "Environmental",
        "layer": "Board / surface",
        "description": (
            "Under moisture, bias and ionic contamination, metal ions migrate and "
            "grow conductive dendrites between conductors, causing leakage, "
            "intermittent behavior, or a hard short."
        ),
        "symptoms": ["leakage between adjacent nets", "intermittent shorts", "green/blue corrosion residue"],
        "root_causes": [
            "Moisture ingress plus ionic contamination (flux residue, salts)",
            "Loss of environmental seal / conformal-coating gaps",
            "Condensation cycling",
        ],
        "signatures": [SIG_LEAKAGE, SIG_DEAD_SHORT, SIG_INTERMITTENT],
        "nondestructive_tests": [
            "Visual/microscope for dendrites and corrosion residue",
            "Insulation-resistance / leakage measurement between suspect nets",
            "Ionic contamination / cleanliness testing",
        ],
        "destructive_tests": ["FTIR/EDX of residue to identify contaminant"],
        "environmental_drivers": ["High humidity", "Salt/pollutants", "Seal failure"],
        "refs": ["ipc_ecm", "ecm_review"],
    },
    "corrosion": {
        "name": "Corrosion / liquid ingress",
        "category": "Environmental",
        "layer": "Board / connector",
        "description": (
            "Moisture, oxygen and contaminants attack conductive metals, raising "
            "contact resistance and creating leakage paths, opens, or shorts, "
            "especially at connectors and exposed pads."
        ),
        "symptoms": ["corrosion residue", "high contact resistance", "intermittent/open connections"],
        "root_causes": ["Seal/gland failure", "Wrong mounting orientation", "Condensation", "Galvanic corrosion"],
        "signatures": [SIG_LEAKAGE, SIG_INTERMITTENT, SIG_DEAD_OPEN],
        "nondestructive_tests": [
            "Visual for corrosion / water marks / residue",
            "Contact-resistance measurement at connectors",
            "Seal-integrity inspection",
        ],
        "destructive_tests": ["EDX of corrosion product"],
        "environmental_drivers": ["Humidity", "Water ingress", "Salt spray"],
        "refs": ["ipc_ecm", "ansys_components"],
    },
    "caf": {
        "name": "Conductive Anodic Filament (CAF)",
        "category": "Board (laminate)",
        "layer": "PCB substrate",
        "description": (
            "A copper filament grows along glass fibres inside the laminate "
            "(often hole-to-hole) under humidity and bias, producing an internal "
            "short that surface inspection cannot see."
        ),
        "symptoms": ["internal short between vias/holes", "leakage that worsens with humidity"],
        "root_causes": ["Poor hole-wall quality / de-lamination", "Insufficient spacing", "Humidity + bias"],
        "signatures": [SIG_LEAKAGE, SIG_DEAD_SHORT],
        "nondestructive_tests": ["Leakage vs humidity trend", "TDR to locate the short along a net"],
        "destructive_tests": ["Cross-section between the affected holes to reveal the filament"],
        "environmental_drivers": ["Humidity", "Sustained bias"],
        "refs": ["caf_rca"],
    },
    "electrolytic_cap_wearout": {
        "name": "Electrolytic capacitor wear-out / high ESR",
        "category": "Passive component",
        "layer": "Capacitor",
        "description": (
            "Electrolyte dry-out raises ESR and lowers capacitance, causing rail "
            "ripple, instability, or brown-out, accelerated by high temperature."
        ),
        "symptoms": ["excessive ripple", "power instability / reboots", "bulging/leaking can"],
        "root_causes": ["Electrolyte dry-out (end of life)", "Temperature beyond rating", "Ripple-current stress"],
        "signatures": [SIG_RIPPLE, SIG_LOW],
        "nondestructive_tests": ["Scope ripple on the rail (AC-coupled, 20 MHz BW)", "ESR measurement",
                                 "Visual for bulging / leakage"],
        "destructive_tests": [],
        "environmental_drivers": ["High temperature", "Thermal cycling"],
        "refs": ["eepower_buck", "mlcc_overview"],
    },
    "feedback_regulation_fault": {
        "name": "Feedback / regulation fault (rail out of spec)",
        "category": "Power delivery",
        "layer": "IC / passives",
        "description": (
            "A wrong or drifted feedback network, or a failing controller, drives "
            "a rail above or below its target, risking damage downstream when high."
        ),
        "symptoms": ["rail above USL", "rail below LSL with no load short"],
        "root_causes": ["Feedback resistor open/wrong value", "Controller reference drift", "Compensation issue"],
        "signatures": [SIG_HIGH, SIG_LOW],
        "nondestructive_tests": ["Measure feedback divider resistors (board off)",
                                 "Compare rail to spec window under load"],
        "destructive_tests": [],
        "environmental_drivers": [],
        "refs": ["eepower_buck", "fluke_dmm"],
    },
    "sequencing_fault": {
        "name": "Power-sequencing / soft-start fault",
        "category": "Power delivery",
        "layer": "System",
        "description": (
            "Rails must come up in the correct order. If a dependent rail leads or "
            "lags its prerequisite (e.g. a memory word-line pump before the core "
            "rail), the subsystem fails to initialize even though each rail exists."
        ),
        "symptoms": ["all rails present but subsystem won't init", "boot hangs at a specific stage"],
        "root_causes": ["Sequencing logic fault", "Soft-start / enable timing", "PGOOD chaining error"],
        "signatures": [SIG_LOW, SIG_INTERMITTENT],
        "nondestructive_tests": ["Scope rails together to capture power-up order and timing",
                                 "Verify prerequisite rail is stable before the dependent rail enables"],
        "destructive_tests": [],
        "environmental_drivers": [],
        "refs": ["eepower_buck"],
    },
}


# --------------------------------------------------------------------------- #
# Measurement signature -> ranked candidate mechanisms
# --------------------------------------------------------------------------- #
# Given an observed signature at a node, which mechanisms are most likely,
# most-probable first. The engine narrows further using the node's position in
# the power tree and any board-specific schematic notes.
ELECTRICAL_SIGNATURES = {
    SIG_DEAD_SHORT: {
        "label": "Rail dead with a short to ground (<~1 Ohm)",
        "meaning": "Something on this rail is shorting it. Do NOT power up until cleared.",
        "candidates": ["downstream_short", "mlcc_crack", "eos", "electrochemical_migration", "caf"],
        "first_action": "Board off: confirm <1 Ohm to GND, then isolate the shorted branch by "
                        "lifting series ferrites; thermal-image under limited power to find the hot part.",
    },
    SIG_DEAD_OPEN: {
        "label": "Rail dead with high resistance to ground (>~5 Ohm)",
        "meaning": "The source (regulator/LDO) is not producing output, or the path is open.",
        "candidates": ["regulator_open", "solder_joint_fatigue", "eos", "corrosion"],
        "first_action": "Check the regulator EN pin and upstream PGOOD, scope the switching node, "
                        "and verify the inductor/ferrite continuity.",
    },
    SIG_LOW: {
        "label": "Rail present but below its lower spec limit",
        "meaning": "Droop from overload, partial short, weak source, or degraded caps.",
        "candidates": ["downstream_short", "electrolytic_cap_wearout", "feedback_regulation_fault", "sequencing_fault"],
        "first_action": "Measure load current and resistance to ground; scope ripple; check the "
                        "feedback network.",
    },
    SIG_HIGH: {
        "label": "Rail above its upper spec limit",
        "meaning": "Regulation/feedback fault — risks damaging downstream loads.",
        "candidates": ["feedback_regulation_fault"],
        "first_action": "Remove load if possible; verify the feedback divider resistor values.",
    },
    SIG_RIPPLE: {
        "label": "Rail present but with excessive ripple",
        "meaning": "Output filtering degraded or converter instability.",
        "candidates": ["electrolytic_cap_wearout", "feedback_regulation_fault"],
        "first_action": "Scope AC-coupled at 20 MHz BW; ESR-check output caps; inspect for cracked ceramics.",
    },
    SIG_INTERMITTENT: {
        "label": "Comes and goes with stress / temperature / flex",
        "meaning": "Classic interconnect or crack signature; hardest to catch.",
        "candidates": ["solder_joint_fatigue", "mlcc_crack", "corrosion",
                       "electrochemical_migration", "esd"],
        "first_action": "Reproduce with freeze-spray/hot-air and flex/tap while monitoring; then X-ray.",
    },
    SIG_LEAKAGE: {
        "label": "Elevated leakage / degraded insulation",
        "meaning": "Moisture/contamination path, dendrite, CAF, or ESD pin leakage.",
        "candidates": ["electrochemical_migration", "corrosion", "caf", "esd", "mlcc_crack"],
        "first_action": "Measure insulation resistance between suspect nets; inspect for residue/dendrites.",
    },
}


# --------------------------------------------------------------------------- #
# Failure-analysis methodology (nondestructive before destructive)
# --------------------------------------------------------------------------- #
FA_METHODOLOGY = [
    {
        "stage": "1. Reproduce & document",
        "nondestructive": True,
        "steps": [
            "Reliably reproduce the failure — an intermittent fault that clears itself will return.",
            "Change one variable at a time; note whether the fault follows the board, the chip, or the load.",
            "Record symptom, LED state, and any boot/UART output before touching hardware.",
        ],
        "refs": ["eepower_buck", "edfa_methodology"],
    },
    {
        "stage": "2. Visual & optical inspection",
        "nondestructive": True,
        "steps": [
            "Inspect under magnification for burns, bulges, cracks, corrosion, residue, solder bridges.",
            "Check board edges/connectors for flex-crack-prone ceramics.",
        ],
        "refs": ["siemens_eos", "ansys_components"],
    },
    {
        "stage": "3. Electrical characterization",
        "nondestructive": True,
        "steps": [
            "Verify supply presence and spec at each rail (KGU vs DUT).",
            "Resistance-to-ground per rail (board off) to separate opens from shorts.",
            "Scope switching nodes, ripple, and power-up sequencing; curve-trace suspect pins.",
        ],
        "refs": ["fluke_dmm", "eepower_buck"],
    },
    {
        "stage": "4. Nondestructive imaging",
        "nondestructive": True,
        "steps": [
            "X-ray for BGA/solder cracks, voids, bridges, non-wet balls.",
            "Scanning acoustic microscopy for delamination; TDR to locate a short along a net.",
        ],
        "refs": ["ipc_7095_xray", "edfa_methodology"],
    },
    {
        "stage": "5. Destructive analysis (last resort)",
        "nondestructive": False,
        "steps": [
            "Dye-and-pry for solder-joint crack faces.",
            "Decapsulation + SEM/EMMI/EDX to localize die damage, or cross-section for cracks/CAF.",
        ],
        "refs": ["edfa_methodology", "esda_eos"],
    },
]


def mechanism(mech_id: str) -> dict:
    """Return the mechanism record (with a resolved 'references' list) or {}."""
    m = FAILURE_MECHANISMS.get(mech_id)
    if not m:
        return {}
    out = dict(m)
    out["references"] = [REFERENCES[r] for r in m.get("refs", []) if r in REFERENCES]
    return out


def candidates_for_signature(signature: str) -> list:
    """Return the ranked list of mechanism records for an electrical signature."""
    sig = ELECTRICAL_SIGNATURES.get(signature)
    if not sig:
        return []
    return [mechanism(mid) for mid in sig["candidates"]]
