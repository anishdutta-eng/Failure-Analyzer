"""PCB Interactive Debugger - KGU vs DUT comparison."""
import streamlit as st
import pandas as pd
import json
import os
from datetime import datetime, date
from program_config import get_reports_dir, get_ml_model_path, get_selected_program

PHASES = {
    1: {"name": "PoE Input Stage", "icon": "🔌", "desc": "Verify PoE power delivery and 5V system rail", "critical": True},
    2: {"name": "Miami SoC Core", "icon": "🧠", "desc": "SoC core voltages - unit won't boot without these", "critical": True},
    3: {"name": "DDR4 Memory", "icon": "💾", "desc": "DDR4 power - boot hangs at DDR training if failed", "critical": True},
    4: {"name": "Shared / Analog", "icon": "⚡", "desc": "Shared 1.8V = single point of failure for WiFi + Ethernet", "critical": True},
    5: {"name": "Ethernet PHY", "icon": "🌐", "desc": "Napa QCA8081 core supply", "critical": False},
    6: {"name": "WiFi / Waikiki / PCIe", "icon": "📡", "desc": "Waikiki radio and PCIe link supplies", "critical": False},
    7: {"name": "RF Power Amps", "icon": "📻", "desc": "5GHz FEM and 2.4GHz IPA supplies", "critical": False},
    8: {"name": "Standby / Misc", "icon": "🔋", "desc": "Standby, LED, USB-C, system power", "critical": False},
}


TP = {}
# step=probe order, loc=board location from PCB image
TP["V_POE_POWER_RAIL"] = {"tp": "PoE Input", "name": "PoE Power Rail", "unit": "V", "lsl": 42.5, "nom": None, "usl": 57.0, "phase": 1, "group": "PoE Input", "fail_action": "Check PoE injector, cable, bridge rectifier. 0V=open input. <42.5V=injector weak or cable too long.", "subsystem": "MPM3690GQJ-Z", "step": 1, "loc": "TP1207 — bottom-left edge, below TP1206"}
TP["POE_POWER_UBOOT"] = {"tp": "PoE Power", "name": "PoE Power at U-Boot", "unit": "W", "lsl": 1.6, "nom": None, "usl": 12.9, "phase": 1, "group": "PoE Input", "fail_action": "<1.6W=SPBM/converters not starting. >12.9W=short circuit, remove power.", "subsystem": "System Power Budget", "step": 2, "loc": "Read from PoE injector or bench PSU display"}
TP["V_TP1205_POE_5V"] = {"tp": "TP1205", "name": "POE 5V Rail", "unit": "V", "lsl": 4.75, "nom": 5.0, "usl": 5.25, "phase": 1, "group": "PoE Input", "fail_action": "0V=MPM3690 not switching (check ENABLE, class resistor). <4.75V=overloaded/cap degradation. >5.25V=feedback failure.", "subsystem": "MPM3690GQJ-Z PoE PD", "step": 3, "loc": "TP1205 — left edge, upper area (POE_5V)"}
TP["V_TP579_VDD_CX"] = {"tp": "TP579", "name": "VDD_CX (Miami Core)", "unit": "V", "lsl": 0.88, "nom": 0.9, "usl": 0.99, "phase": 2, "group": "Miami SoC Core", "fail_action": "MOST CRITICAL. 0V=Buck1/SPBM failure. Measure R to GND (>5ohm OK, <1ohm=Miami die short).", "subsystem": "Buck 1 -> Miami IPQ5332", "step": 4, "loc": "TP579 — top-center-right area (VDD_CX)"}
TP["V_TP27_VDD_SOC_CX"] = {"tp": "TP27", "name": "VDD_SOC_CX", "unit": "V", "lsl": 0.8, "nom": 0.85, "usl": 0.913, "phase": 2, "group": "Miami SoC Core", "fail_action": "SoC core. If differs from TP579=trace/filter issue. Check ferrite bead.", "subsystem": "Miami Core Domain", "step": 5, "loc": "TP27 — right side, mid-height (VDD_SOC_CX)"}
TP["V_TP29_VDD_SOC_MX"] = {"tp": "TP29", "name": "VDD_SOC_MX", "unit": "V", "lsl": 0.865, "nom": 0.865, "usl": 0.935, "phase": 2, "group": "Miami SoC Core", "fail_action": "Memory bus domain. Missing while VDD_CX OK=separate LDO failed.", "subsystem": "Miami Memory Bus", "step": 6, "loc": "TP29 — top-right corner (VDD_SOC_MX)"}
TP["V_TP578_VDD1V95_PMU"] = {"tp": "TP578", "name": "VDD1V95_PMU", "unit": "V", "lsl": 1.9, "nom": 1.961, "usl": 2.05, "phase": 2, "group": "Miami SoC Core", "fail_action": "PMU supply. Missing=upstream 5V/3.3V issue. Low=PMU LDO drooping.", "subsystem": "Miami PMU", "step": 7, "loc": "TP578 — top-center (VDD1V95_PMU)"}
TP["V_TP574_VDD_DDR"] = {"tp": "TP574", "name": "VDD_DDR (1.2V)", "unit": "V", "lsl": 1.14, "nom": 1.197, "usl": 1.26, "phase": 3, "group": "DDR4 Memory", "fail_action": "DDR4 core. 0V=Buck3 fail. Low=BGA short. Ripple>30mV=cap degradation. BGA crack RPN=162.", "subsystem": "Buck 3 -> DDR4", "step": 8, "loc": "TP574 — bottom-center (VDD_DDR), right of TP582"}
TP["V_TP576_VDD_LDO_2P5_VPP"] = {"tp": "TP576", "name": "VDD_LDO_2P5_VPP", "unit": "V", "lsl": 2.375, "nom": 2.52, "usl": 2.75, "phase": 3, "group": "DDR4 Memory", "fail_action": "DDR4 word-line pump. Must come AFTER VDD_DDR. Missing=LDO/sequencing issue.", "subsystem": "VPP LDO -> DDR4", "step": 9, "loc": "TP576 — top-center-left (VDD_LDO_2P5_VPP)"}
TP["V_TP503_VDD1P8_NAPA"] = {"tp": "TP503", "name": "VDD1.8 NAPA (Shared)", "unit": "V", "lsl": 1.7, "nom": 1.8, "usl": 1.9, "phase": 4, "group": "Shared / Analog", "fail_action": "SHARED RAIL: Waikiki analog + Napa PHY I/O. Missing=WiFi AND Ethernet dead. Check Buck 2.", "subsystem": "Buck 2 -> Waikiki+Napa", "step": 10, "loc": "TP503 — bottom-left (VDD1.8_NAPA)"}
TP["V_TP28_VAA_0P8"] = {"tp": "TP28", "name": "VAA_0P8", "unit": "V", "lsl": 0.805, "nom": 0.85, "usl": 0.895, "phase": 4, "group": "Shared / Analog", "fail_action": "0.8V analog ref. Missing=LDO failed. Check enable and input.", "subsystem": "0.8V Analog LDO", "step": 11, "loc": "TP28 — right side, upper-mid (VAA_0P8)"}
TP["V_TP36_VAA_1P2"] = {"tp": "TP36", "name": "VAA_1P2", "unit": "V", "lsl": 1.261, "nom": 1.3, "usl": 1.339, "phase": 4, "group": "Shared / Analog", "fail_action": "1.2V PLL analog reference. Out-of-spec may cause PLL jitter or clock drift. Monitor only — does not indicate board-level failure on its own.", "subsystem": "1.2V PLL Supply", "step": 12, "loc": "TP36 — right side, lower-mid (VAA_1P2)", "monitor": True}
TP["V_TP504_VDD1P05_NAPA"] = {"tp": "TP504", "name": "VDD1.05 NAPA Core", "unit": "V", "lsl": 0.95, "nom": 1.05, "usl": 1.1, "phase": 5, "group": "Ethernet PHY (Napa)", "fail_action": "Napa core. 0V=Buck5 fail. Needs both 1.05V AND 1.8V(TP503). Check SGMII/MDIO/magnetics.", "subsystem": "Buck 5 -> QCA8081", "step": 13, "loc": "TP504 — left side, mid-height (VDD1.05_NAPA)"}
TP["V_TP573_DVDD3P3"] = {"tp": "TP573", "name": "DVDD3.3 (Waikiki)", "unit": "V", "lsl": 3.14, "nom": 3.294, "usl": 3.46, "phase": 6, "group": "WiFi (Waikiki)", "fail_action": "Waikiki main digital. 0V=Buck6 fail. Present but no WiFi=check PCIe (PERST_N, clock).", "subsystem": "Buck 6 -> QCN9274", "step": 14, "loc": "TP573 — top-left area (DVDD3.3)"}
TP["V_TP535_DVDD5"] = {"tp": "TP535", "name": "DVDD5 (Waikiki 5V)", "unit": "V", "lsl": 4.75, "nom": 5.0, "usl": 5.25, "phase": 6, "group": "WiFi (Waikiki)", "fail_action": "5V to Waikiki. Missing=5V bus distribution issue. Low=excess load/cap degradation.", "subsystem": "5V -> Waikiki", "step": 15, "loc": "TP535 — left side, below TP586 (DVDD5)"}
TP["V_TP589_DVDD3P3_BZT"] = {"tp": "TP589", "name": "DVDD3.3_BZT", "unit": "V", "lsl": 3.14, "nom": 3.294, "usl": 3.46, "phase": 6, "group": "WiFi (Waikiki)", "fail_action": "Should track TP573. Different=isolation component open/shorted.", "subsystem": "3.3V BZT", "step": 16, "loc": "TP589 — top-left corner (DVDD3.3_BZT)"}
TP["V_TP34_VDD_PCIE_0P925"] = {"tp": "TP34", "name": "VDD_PCIE_0P925", "unit": "V", "lsl": 0.881, "nom": 0.925, "usl": 0.971, "phase": 6, "group": "WiFi (Waikiki)", "fail_action": "PCIe SerDes analog supply. Out-of-spec may degrade PCIe link margin. Monitor only — WiFi failure more likely caused by DVDD3.3 or PERST_N.", "subsystem": "PCIe SerDes LDO", "step": 17, "loc": "TP34 — right side, mid (VDD_PCIE_0P925)", "monitor": True}
TP["V_TP30_VDD_PCIE_1P8"] = {"tp": "TP30", "name": "VDD_PCIE_1P8", "unit": "V", "lsl": 1.71, "nom": 1.8, "usl": 1.89, "phase": 6, "group": "WiFi (Waikiki)", "fail_action": "PCIe I/O. Missing=no Miami-Waikiki communication.", "subsystem": "PCIe I/O LDO", "step": 18, "loc": "TP30 — right side, lower-mid (VDD_PCIE_1P8)"}
TP["V_TP31_VDD_1V8_PX3"] = {"tp": "TP31", "name": "VDD_1V8_PX3", "unit": "V", "lsl": 1.71, "nom": 1.8, "usl": 1.89, "phase": 6, "group": "WiFi (Waikiki)", "fail_action": "1.8V PX3. Missing while other 1.8V OK=local LDO issue.", "subsystem": "1.8V PX3", "step": 19, "loc": "TP31 — right side, upper-mid (VDD_1V8_PX3)"}
TP["V_TP569_VDD_XPA"] = {"tp": "TP569", "name": "VDD_XPA (5G PA)", "unit": "V", "lsl": 4.0, "nom": 4.22, "usl": 4.43, "phase": 7, "group": "RF Power Amps", "fail_action": "HIGHEST RAIL. Feeds SKY85500 FEMs (8.4W peak). 0V=Buck8 fail. Low=FEM PA short.", "subsystem": "Buck 8 -> SKY85500 FEM x2", "step": 20, "loc": "TP569 — far right, upper area (VDD_XPA)"}
TP["V_TP577_AVDD3P3_2G"] = {"tp": "TP577", "name": "AVDD3.3_2G (2.4G IPA)", "unit": "V", "lsl": 3.13, "nom": 3.294, "usl": 3.48, "phase": 7, "group": "RF Power Amps", "fail_action": "2.4G internal PA. 0V=Buck7 fail. Present but no 2.4G=Miami IPA or SAW filter damaged.", "subsystem": "Buck 7 -> Miami IPA", "step": 21, "loc": "TP577 — far left, top corner (AVDD3.3_2G)"}
TP["V_TP55_STBY"] = {"tp": "TP55", "name": "STBY_VDD3.3", "unit": "V", "lsl": 3.14, "nom": 3.294, "usl": 3.46, "phase": 8, "group": "Standby / Misc", "fail_action": "Standby 3.3V always-on. Missing=early power failure before SPBM.", "subsystem": "Standby LDO", "step": 22, "loc": "TP55 — bottom-center (STBY_VDD3.3)"}
TP["V_TP590_LED"] = {"tp": "TP590", "name": "LED_5V_3V3", "unit": "V", "lsl": 3.0, "nom": 3.3, "usl": 3.6, "phase": 8, "group": "Standby / Misc", "fail_action": "LED driver supply. 0V=no LED. Present but dark=I2C bus or KTD2027B failure.", "subsystem": "KTD2027B LED", "step": 23, "loc": "TP590 — bottom-right corner (LED_5V_3V3)"}
TP["V_TP56_USB_A"] = {"tp": "TP56", "name": "USB-C Orient (A)", "unit": "V", "lsl": 0.0, "nom": None, "usl": 0.6, "phase": 8, "group": "Standby / Misc", "fail_action": "USB-C CC detection pin. Out-of-spec indicates FUSB15201MX orientation detect issue. Monitor only — does not affect core board function.", "subsystem": "FUSB15201MX", "step": 24, "loc": "TP56 — bottom edge, center-left (USBC_ORIENT)", "monitor": True}
TP["V_TP56_USB_B"] = {"tp": "TP56", "name": "USB-C Orient (B)", "unit": "V", "lsl": 2.7, "nom": None, "usl": 3.6, "phase": 8, "group": "Standby / Misc", "fail_action": "USB-C CC alternate orientation. Out-of-spec indicates CC resistor network issue. Monitor only — does not affect core board function.", "subsystem": "FUSB15201MX", "step": 25, "loc": "TP56 — same pad as step 24, measure with cable flipped", "monitor": True}
TP["POE_POWER_QSDK"] = {"tp": "System", "name": "PoE Power QSDK", "unit": "W", "lsl": 3.0, "nom": None, "usl": 12.9, "phase": 8, "group": "Standby / Misc", "fail_action": "<3W=subsystems not running. >12.9W=abnormal, thermal camera for short.", "subsystem": "Full System", "step": 26, "loc": "Read from PoE injector or bench PSU display"}
TEST_POINTS = TP

# Schematic circuit lookup — maps TP names to detailed circuit info from schematics
SCHEMATIC_DB = {
    "PoE Input": {
        "circuit_name": "PoE Power Delivery (MPM3690GQJ-Z)",
        "schematic_path": "RJ45 → PoE Magnetics → Bridge Rectifier → MPM3690GQJ-Z → 5V/6A System Bus",
        "ic": "MPS MPM3690GQJ-Z",
        "description": "Fully integrated PoE PD controller. Converts 37-57V DC from Ethernet cable to 5V system bus at up to 6A (30W). 802.3at Class 4 classification. 300KHz fixed-frequency switching. PGOOD signal feeds SPBM for sequencing.",
        "key_components": ["MPM3690GQJ-Z (PoE PD)", "Bridge rectifier", "Classification resistor (24.9K, Class 4)", "Output caps (22uF x4)", "PGOOD → SPBM"],
        "failure_modes": {"0V output": "Input diode short or FET failure. Check Vin at bridge output.", "Low output": "Cap degradation or excessive load. Measure 5V under load.", "Oscillation": "Feedback loop instability. Scope 5V rail for ripple >50mV pk-pk.", "Overtemp shutdown": "Poor thermal pad solder. Thermal image MPM3690 pad area.", "Classification fail": "Wrong classification resistor value. Verify 24.9K for Class 4."},
        "component_diagnostics": [
            {"ref": "J1 / RJ45", "component": "RJ45 connector + magnetics center taps",
             "location": "Bottom-left corner of PCB", "priority": "High",
             "check": "DMM continuity: pins 4,5 (V+) and pins 7,8 (V-) to bridge rectifier input. Visually inspect for bent pins, corrosion, water residue.",
             "expected": "Continuity OK, no corrosion/oxidation",
             "if_fail": "Replace RJ45 jack. Check magnetics for open winding (DCR ~1Ω each pair).",
             "tools": "DMM (continuity), 10x loupe"},
            {"ref": "D1-D4 / Bridge", "component": "Bridge rectifier diodes",
             "location": "Adjacent to RJ45, between magnetics and MPM3690", "priority": "High",
             "check": "With PoE applied, measure DC voltage at bridge output (cathode side). Diode test in-circuit (one direction conducts ~0.4V, reverse open).",
             "expected": "37–57V DC at bridge output. Diode drop 0.3–0.7V forward, OL reverse.",
             "if_fail": "Shorted diode → 0V at TP1207. Replace failed diode. Common cause: ESD/lightning surge.",
             "tools": "DMM (V-DC + diode test)"},
            {"ref": "U? / MPM3690GQJ-Z", "component": "MPM3690GQJ-Z PoE PD controller",
             "location": "Center-left, large QFN package near TP1205", "priority": "High",
             "check": "1) ENABLE pin (post-classification) should be HIGH (~3V). 2) Touch test top of IC — should be warm but not >80°C. 3) Scope SW pin: 300kHz square wave when running.",
             "expected": "EN ≈ 3V, SW pin = 300kHz switching, package <70°C steady-state",
             "if_fail": "EN low → classification rejected by PSE (check classification resistor next). No SW switching → IC dead, replace MPM3690. Hot >85°C → thermal pad solder void, reflow or rework.",
             "tools": "Oscilloscope (≥50MHz), DMM, thermal camera"},
            {"ref": "RCLS / 24.9K", "component": "Class 4 classification resistor",
             "location": "Near MPM3690 RCLASS pin", "priority": "Medium",
             "check": "With board powered OFF and PoE disconnected, measure resistance from RCLASS pin to GND.",
             "expected": "24.9 kΩ ±1% (Class 4 / 802.3at)",
             "if_fail": "Wrong value → PSE classifies incorrectly, may not deliver full 30W. Replace with 24.9K 1% 0402.",
             "tools": "DMM (resistance, board off)"},
            {"ref": "L1 / 4.7uH", "component": "Power inductor (MPM3690 SW → output)",
             "location": "Largest inductor near MPM3690, between SW pin and TP1205", "priority": "Medium",
             "check": "DCR check (board off): should be <50mΩ. Visual: no cracks, no scorching, solder joints intact.",
             "expected": "DCR 10–40 mΩ, no visible damage",
             "if_fail": "Open inductor → 0V at TP1205. Cracked core → low/oscillating output. Replace with same part (saturation current ≥8A).",
             "tools": "DMM (mΩ range or 4-wire), microscope"},
            {"ref": "C1-C4 / 22uF x4", "component": "Output bulk capacitors on 5V rail",
             "location": "Around TP1205, ceramic 1210 package", "priority": "Medium",
             "check": "Visual: cracks, lifted pads, solder bridges. Scope 5V at TP1205 AC-coupled, 20MHz BW: ripple should be <50mV pk-pk.",
             "expected": "No visible damage, ripple <50mV pk-pk at full load",
             "if_fail": "Cracked ceramic = capacitance loss → high ripple, possible oscillation. Replace all 4 caps as a set.",
             "tools": "Oscilloscope (AC-coupled), 10x loupe"},
            {"ref": "PGOOD trace", "component": "PGOOD signal to SPBM",
             "location": "Trace from MPM3690 PGOOD pin to SPBM input", "priority": "Low",
             "check": "With 5V rail healthy at TP1205, PGOOD pin should go HIGH (~3.3V) ~10ms after 5V settles.",
             "expected": "PGOOD = HIGH (3.0–3.3V) when 5V rail is in regulation",
             "if_fail": "PGOOD stuck LOW → SPBM blocks downstream sequencing → no Buck converters start, even if 5V is OK. Check pull-up resistor and trace continuity to SPBM.",
             "tools": "DMM, oscilloscope"},
        ],
        "related_tps": ["TP1207 (PoE Input)", "TP1205 (5V Output)"],
    },
    "TP1207": {
        "circuit_name": "PoE Input Voltage Sense",
        "schematic_path": "RJ45 Center Taps (pins 4,5=V+; 7,8=V-) → Bridge Rectifier → TP1207",
        "ic": "MPS MPM3690GQJ-Z (input side)",
        "description": "Measures the raw PoE voltage after the bridge rectifier, before the DC/DC conversion. This is the 37-57V DC rail from the Goldfinch PSU via Ethernet cable. 0V here means no PoE power is reaching the board at all.",
        "key_components": ["RJ45 connector", "PoE magnetics (center taps)", "Bridge rectifier diodes", "Input bulk capacitors"],
        "failure_modes": {"0V": "No PoE power. Check cable, injector, RJ45 connector, magnetics center taps.", "<42.5V": "Weak injector or long cable run (>100m). Check cable resistance.", ">57V": "Non-compliant PSU. Risk of overvoltage damage."},
        "component_diagnostics": [
            {"ref": "External / PSE", "component": "PoE injector (Goldfinch) and Ethernet cable",
             "location": "External — wall outlet to RJ45", "priority": "High",
             "check": "Measure injector output at the cable head (pins 4,5 vs 7,8) with no load. Then with the unit connected. Try a known-good cable <30m.",
             "expected": "≥48V no-load, ≥44V loaded",
             "if_fail": "Bad injector or cable. Swap to a known-good Class 4 PSE before suspecting the board.",
             "tools": "DMM (V-DC), spare cable"},
            {"ref": "J1 / RJ45", "component": "RJ45 jack pins and PCB solder joints",
             "location": "Bottom-left of PCB", "priority": "High",
             "check": "Inspect jack under microscope: bent center-tap pins (4,5,7,8), cold solder, water/corrosion. Wiggle test under load — voltage should stay rock-steady.",
             "expected": "All pins straight, solder fillets clean, no corrosion",
             "if_fail": "Re-solder pins, or replace jack if pins are damaged. Corrosion → field exposure issue, log as IP66 seal failure.",
             "tools": "Microscope, soldering iron"},
            {"ref": "T1 / Magnetics", "component": "PoE magnetics module (center-tapped transformer)",
             "location": "Inline between RJ45 and bridge rectifier", "priority": "Medium",
             "check": "DCR each winding (board off): both pairs ~1Ω. Inter-winding isolation should be >100MΩ.",
             "expected": "DCR 0.5–1.5Ω per pair, isolation >100MΩ",
             "if_fail": "Open winding → 0V at TP1207. Shorted to data pairs → fries the magnetics. Replace module.",
             "tools": "DMM (resistance), megohmmeter"},
            {"ref": "D1-D4", "component": "Bridge rectifier diodes (4x)",
             "location": "Between magnetics and MPM3690 input cap", "priority": "Medium",
             "check": "Diode test in-circuit, board off. Forward 0.3–0.7V each, reverse OL. Look for cracked package after a surge event.",
             "expected": "All 4 diodes show forward drop and reverse open",
             "if_fail": "One shorted diode = full bridge collapse → 0V at TP1207. Replace failed diode (check the others — surges often kill multiple).",
             "tools": "DMM (diode mode), 10x loupe"},
            {"ref": "C-IN", "component": "Input bulk capacitor (high-voltage)",
             "location": "Largest cap at MPM3690 VIN pin (typically 1uF/100V or 2.2uF/100V)", "priority": "Low",
             "check": "Visual inspect for bulging, cracks, lifted pads. Out-of-circuit ESR / capacitance check if available.",
             "expected": "No bulging, ESR <0.5Ω at 100kHz",
             "if_fail": "Open cap → input ringing, possible MPM3690 damage. Replace with same rating (≥80V).",
             "tools": "ESR meter, microscope"},
        ],
        "related_tps": ["TP1205 (5V output downstream)"],
    },
    "TP1205": {
        "circuit_name": "5V System Bus (MPM3690 Output)",
        "schematic_path": "MPM3690GQJ-Z SW pin → L (inductor) → TP1205 → 5V bus → All Buck converters",
        "ic": "MPS MPM3690GQJ-Z (output)",
        "description": "Main 5V system rail. Output of the PoE PD converter. Feeds ALL downstream buck converters (Buck 1-8). This is the single most important power rail — if this is dead, nothing works.",
        "key_components": ["MPM3690GQJ-Z output stage", "Power inductor", "Output capacitors (22uF ceramic x4)", "PGOOD signal to SPBM", "Ferrite bead to 5V bus"],
        "failure_modes": {"0V": "MPM3690 not switching. Check ENABLE pin (should be HIGH from classification). Check input voltage at TP1207.", "<4.75V": "Overloaded (downstream short) or output cap degradation. Measure current draw. Check for shorted buck converter.", ">5.25V": "Feedback resistor divider failure. Check FB pin network."},
        "component_diagnostics": [
            {"ref": "5V rail at TP1205", "component": "Direct short to GND check",
             "location": "TP1205, board powered OFF", "priority": "High",
             "check": "Resistance from TP1205 to GND, board OFF. Healthy = ~10kΩ falling slowly (cap charge). Short = <1Ω.",
             "expected": ">1kΩ rising as caps charge",
             "if_fail": "Hard short → DO NOT power up. A downstream Buck IC (1-8) is shorted. Lift the ferrite beads one at a time to isolate which Buck is shorted.",
             "tools": "DMM (resistance, board off)"},
            {"ref": "U? / MPM3690", "component": "MPM3690 ENABLE pin",
             "location": "EN pin on MPM3690 QFN", "priority": "High",
             "check": "With PoE applied, measure EN pin voltage. Should be HIGH (~3V) after PSE classification (~50ms after plug-in).",
             "expected": "EN = 2.5–3.3V after classification settles",
             "if_fail": "EN stuck LOW → classification failed (check 24.9K class resistor) or MPM3690 internal damage. EN HIGH but no SW = MPM3690 dead.",
             "tools": "Oscilloscope (capture transient), DMM"},
            {"ref": "MPM3690 SW pin", "component": "Switching node activity",
             "location": "SW pin on MPM3690", "priority": "High",
             "check": "Scope SW pin (10x probe, AC-couple). Should see clean 300kHz square wave with sharp edges.",
             "expected": "300 kHz ±10%, 0V to ~Vin square wave, rise time <50ns",
             "if_fail": "No switching → IC failure, replace MPM3690. Slow edges → bootstrap cap (CBOOT) failed, replace 100nF cap on BST pin.",
             "tools": "Oscilloscope (≥100MHz)"},
            {"ref": "L1", "component": "Power inductor",
             "location": "Largest inductor between SW pin and TP1205", "priority": "Medium",
             "check": "Board OFF: DCR <50mΩ. Visual: cracked ferrite, scorching, lifted solder. Under load: not >Curie temp (~120°C).",
             "expected": "DCR 10–40mΩ, no cracks, runs <100°C at full load",
             "if_fail": "Open → 0V at TP1205. Saturated/cracked → high ripple, MPM3690 may shut down on overcurrent. Replace.",
             "tools": "DMM, thermal camera"},
            {"ref": "C-OUT (22uF x4)", "component": "5V output bulk capacitance",
             "location": "Cluster of 1210 ceramics around TP1205", "priority": "Medium",
             "check": "Scope ripple at TP1205 under full load. Visual: cracked dielectrics. Pull and measure cap value if suspicious.",
             "expected": "Ripple <50mV pk-pk at 30W load, all caps within 20% of nominal",
             "if_fail": "Cracked ceramic = ESR jumps, ripple >100mV, MPM3690 may oscillate. Replace all 4 as a set (X5R/X7R, ≥10V rated).",
             "tools": "Oscilloscope, ESR meter"},
            {"ref": "RFB1/RFB2", "component": "Feedback resistor divider",
             "location": "Two 0402 resistors near MPM3690 FB pin", "priority": "Medium",
             "check": "Board OFF: measure RFB1 (top) and RFB2 (bottom). Expected ratio sets 5.0V output.",
             "expected": "Per datasheet for 5V output (typically RFB1≈40.2K, RFB2≈10K — verify against schematic)",
             "if_fail": "Wrong/lifted resistor → output too high (>5.25V can damage downstream) or too low. Replace bad resistor.",
             "tools": "DMM (resistance, board off)"},
            {"ref": "Downstream Bucks", "component": "Shorted downstream Buck converter",
             "location": "Buck 1-8 ICs scattered across PCB", "priority": "Medium",
             "check": "If TP1205 reads <4.75V, measure each Buck input ferrite bead to GND. The shorted one will read <1Ω.",
             "expected": "All Buck inputs read >100Ω to GND (board off)",
             "if_fail": "The shorted Buck is your culprit — it's pulling the 5V rail down. Common causes: overcurrent stress, BGA solder short under SoC.",
             "tools": "DMM (resistance, board off)"},
        ],
        "related_tps": ["TP1207 (input)", "TP579 (Buck 1 output)", "TP574 (Buck 3 output)"],
    },
    "TP579": {
        "circuit_name": "VDD_CX — Miami SoC Core (Buck 1)",
        "schematic_path": "5V Bus → Buck 1 (0.9V/8A, 700KHz) → TP579 → Miami IPQ5332 VCC_CX pins",
        "ic": "Buck 1 converter (controlled by SPBM SLG4R44724TR)",
        "description": "MOST CRITICAL RAIL. 0.9V core supply for Miami IPQ5332 SoC. Powers ARM cores, DSP, and all digital logic. 8A max at 700KHz switching. Without this rail, the SoC is completely dead — no boot, no LED, no UART.",
        "key_components": ["Buck 1 converter IC", "SPBM enable signal", "Power inductor (0.47uH)", "Output caps (100uF + 22uF x4)", "Ferrite bead to VCC_CX", "Miami IPQ5332 (load)"],
        "failure_modes": {"0V": "Buck 1 or SPBM failure. Measure resistance VCC_CX to GND: >5Ω = open (converter dead), <1Ω = Miami die short.", "<0.88V": "Buck 1 drooping under load. Check inductor, output caps. Possible Miami excess current draw.", ">0.99V": "Feedback network failure. Overvoltage risk to SoC."},
        "related_tps": ["TP27 (VDD_SOC_CX, filtered version)", "TP29 (VDD_SOC_MX, memory bus domain)"],
    },
    "TP27": {
        "circuit_name": "VDD_SOC_CX — Miami Core (Filtered)",
        "schematic_path": "TP579 (VDD_CX) → Ferrite Bead → TP27 → Miami IPQ5332 VDD_SOC_CX pins",
        "ic": "Miami IPQ5332 (core domain)",
        "description": "Filtered version of VDD_CX. Passes through a ferrite bead for noise filtering before reaching the SoC core pins. Should track TP579 closely. A significant delta between TP579 and TP27 indicates a filter component issue.",
        "key_components": ["Ferrite bead (between TP579 and TP27)", "Decoupling caps at SoC pins", "Miami IPQ5332 core power pins"],
        "failure_modes": {"Differs from TP579": "Ferrite bead open or high-resistance. Check continuity between TP579 and TP27.", "0V while TP579 OK": "Ferrite bead completely open. Replace.", "Both 0V": "Upstream Buck 1 failure — debug at TP579 first."},
        "related_tps": ["TP579 (unfiltered source)", "TP29 (VDD_SOC_MX)"],
    },
    "TP29": {
        "circuit_name": "VDD_SOC_MX — Miami Memory Bus Domain",
        "schematic_path": "Internal LDO (from VCC_CX domain) → TP29 → Miami IPQ5332 VDD_SOC_MX pins",
        "ic": "Miami IPQ5332 (internal LDO)",
        "description": "Separate voltage domain for Miami's memory bus interface. Generated by an internal LDO inside the SoC from the VCC_CX domain. If VDD_CX is present but VDD_SOC_MX is missing, the internal LDO has failed.",
        "key_components": ["Miami internal LDO", "Decoupling caps", "Miami memory bus interface"],
        "failure_modes": {"0V while VDD_CX OK": "Miami internal LDO failure. SoC may need replacement.", "0V with VDD_CX also 0V": "Upstream power issue — debug Buck 1 first.", "Low voltage": "Excessive memory bus current. Check DDR4 signals."},
        "related_tps": ["TP579 (VDD_CX source)", "TP574 (VDD_DDR)"],
    },
    "TP578": {
        "circuit_name": "VDD1V95_PMU — Miami PMU Supply",
        "schematic_path": "5V Bus → LDO → TP578 → Miami IPQ5332 PMU input pins",
        "ic": "PMU LDO (feeds Miami internal power management)",
        "description": "1.95V supply for Miami's internal Power Management Unit. The PMU generates several internal LDO outputs for the SoC. If this rail is missing, Miami's internal regulators cannot function even if VCC_CX is present.",
        "key_components": ["PMU LDO regulator", "Input from 5V or 3.3V bus", "Decoupling caps", "Miami PMU input pins"],
        "failure_modes": {"0V": "Upstream 5V/3.3V bus issue or PMU LDO failure. Check 5V rail first.", "Low (<1.9V)": "LDO drooping — check input voltage and load current.", "High (>2.05V)": "LDO feedback failure."},
        "related_tps": ["TP1205 (5V source)", "TP579 (VDD_CX)"],
    },
    "TP574": {
        "circuit_name": "VDD_DDR — DDR4 Memory Core (Buck 3)",
        "schematic_path": "5V Bus → Buck 3 (1.2V/2A, 1MHz) → TP574 → DDR4 Nanya NT5AD512M16C4 VDD pins",
        "ic": "Buck 3 converter",
        "description": "1.2V core supply for DDR4 SDRAM. Must be stable before Miami releases DDR reset. Ripple >30mV indicates cap degradation. DDR4 BGA solder joint cracking is the #3 risk item (RPN=162) in failure analysis.",
        "key_components": ["Buck 3 converter IC", "Power inductor", "Output caps (47uF + 22uF x3)", "DDR4 Nanya NT5AD512M16C4-JRI (BGA package)", "DDR4 VDD pins"],
        "failure_modes": {"0V": "Buck 3 converter failure. Check enable signal from SPBM.", "<1.14V": "Possible BGA short pulling rail down. Measure resistance to GND.", "Ripple >30mV": "Output cap degradation. Replace ceramic caps on 1.2V rail.", "DDR training fail": "Rail present but noisy. Scope AC-coupled, 20MHz BW. Also check BGA solder joints (X-ray if available)."},
        "related_tps": ["TP576 (VPP, must come after VDD_DDR)"],
    },
    "TP576": {
        "circuit_name": "VDD_LDO_2P5_VPP — DDR4 Word Line Pump (Buck 4)",
        "schematic_path": "5V Bus → Buck 4 (2.5V/0.6A, 1MHz) → TP576 → DDR4 VPP pins",
        "ic": "Buck 4 converter (or LDO)",
        "description": "2.5V word-line pump voltage for DDR4. Required for DDR4 activation. MUST come up AFTER VDD_DDR (1.2V) is stable — power sequencing is critical. If VPP is missing while VDD_DDR is present, the DDR4 will fail initialization.",
        "key_components": ["Buck 4 / VPP LDO", "Sequencing logic (after VDD_DDR)", "DDR4 VPP pins"],
        "failure_modes": {"0V": "LDO/Buck 4 failure or sequencing issue. Check if VDD_DDR came up first.", "Low": "LDO drooping. Check input supply.", "Present but DDR fails": "Sequencing problem — VPP may be coming up before VDD_DDR."},
        "related_tps": ["TP574 (VDD_DDR, must be stable first)"],
    },
    "TP503": {
        "circuit_name": "VDD1.8V NAPA — Shared Analog Rail (Buck 2)",
        "schematic_path": "5V Bus → Buck 2 (1.8V/2A, 1MHz) → TP503 → Waikiki QCN9274 VDDA + Napa QCA8081 VDD_IO",
        "ic": "Buck 2 converter",
        "description": "CRITICAL SHARED RAIL. 1.8V supply shared between Waikiki WiFi analog (QCN9274 VDDA) and Napa Ethernet PHY I/O (QCA8081 VDD_IO). This is a SINGLE POINT OF FAILURE — if this rail dies, BOTH WiFi AND Ethernet are dead simultaneously.",
        "key_components": ["Buck 2 converter IC", "SPBM enable", "Output caps", "Waikiki QCN9274 analog pins", "Napa QCA8081 I/O pins", "Ferrite beads to each load"],
        "failure_modes": {"0V": "Buck 2 failure. Check SPBM enable signal. This kills WiFi AND Ethernet.", "<1.7V": "Overloaded — one of the loads may have a short. Disconnect Waikiki/Napa to isolate.", "WiFi+Ethernet both dead": "Almost certainly this rail. Check TP503 first."},
        "related_tps": ["TP504 (Napa core, also needs 1.8V)", "TP573 (Waikiki digital, separate rail)"],
    },
    "TP28": {
        "circuit_name": "VAA_0P8 — 0.8V Analog Reference LDO",
        "schematic_path": "1.8V or 3.3V → LDO → TP28 → Miami analog reference pins",
        "ic": "0.8V Analog LDO",
        "description": "0.8V analog reference voltage. Used by Miami's internal ADCs and analog circuits. Generated by a dedicated LDO from the 1.8V or 3.3V rail.",
        "key_components": ["0.8V LDO regulator", "Input from 1.8V/3.3V bus", "Decoupling caps", "Miami analog reference pins"],
        "failure_modes": {"0V": "LDO failure. Check enable pin and input supply voltage.", "Low": "LDO drooping or excessive load."},
        "related_tps": ["TP36 (VAA_1P2, similar analog LDO)", "TP503 (1.8V source)"],
    },
    "TP36": {
        "circuit_name": "VAA_1P2 — 1.2V PLL Analog Supply (Monitor Only)",
        "schematic_path": "1.8V or 3.3V → LDO → TP36 → Miami PLL analog pins",
        "ic": "1.2V PLL LDO",
        "description": "1.2V analog supply for Miami's PLL (Phase-Locked Loop) circuits. Used for clock generation and frequency synthesis. MONITOR ONLY — out-of-spec may cause PLL jitter or clock drift but does not indicate board-level failure on its own.",
        "key_components": ["1.2V PLL LDO", "Decoupling caps", "Miami PLL analog pins"],
        "failure_modes": {"Out of spec": "May cause clock jitter. Monitor only — not a board failure indicator."},
        "related_tps": ["TP28 (VAA_0P8, similar analog LDO)"],
    },
    "TP504": {
        "circuit_name": "VDD1.05V NAPA Core — Ethernet PHY (Buck 5)",
        "schematic_path": "5V Bus → Buck 5 (1.05V/2A, 1MHz) → TP504 → Napa QCA8081 VDD_CORE pins",
        "ic": "Buck 5 converter → QCA8081",
        "description": "1.05V digital core supply for Napa QCA8081 2.5GBASE-T Ethernet PHY. Needs BOTH this rail AND the 1.8V shared rail (TP503) to function. If 1.05V is present but 1.8V is dead, Ethernet still won't work.",
        "key_components": ["Buck 5 converter IC", "Napa QCA8081 (BGA)", "SGMII interface to Miami", "MDIO management bus", "RJ45 magnetics"],
        "failure_modes": {"0V": "Buck 5 failure. Check enable from SPBM.", "Present but no Ethernet": "Check TP503 (1.8V shared). Also check RJ45 connector (bent pins, corrosion), magnetics continuity (<2Ω per winding), SGMII/MDIO signals."},
        "related_tps": ["TP503 (1.8V I/O, also required)"],
    },
    "TP573": {
        "circuit_name": "DVDD3.3 — Waikiki Main Digital (Buck 6)",
        "schematic_path": "5V Bus → Buck 6 (3.3V/3A, 700KHz) → TP573 → Waikiki QCN9274 DVDD pins",
        "ic": "Buck 6 converter → QCN9274",
        "description": "3.3V main digital supply for Waikiki QCN9274 WiFi 7 radio. Powers digital I/O and PCIe interface. If present but no WiFi, the issue is likely PCIe link (check PERST_N signal, 100MHz reference clock).",
        "key_components": ["Buck 6 converter IC", "Waikiki QCN9274 digital pins", "PCIe interface (PERST_N, REFCLK)", "3.3V bus distribution"],
        "failure_modes": {"0V": "Buck 6 failure. Check SPBM enable.", "Present but no WiFi": "PCIe link issue. Check PERST_N (should go HIGH after power stable). Scope 100MHz PCIe reference clock. Via UART: lspci should show QCN9274."},
        "related_tps": ["TP535 (DVDD5)", "TP589 (DVDD3.3_BZT, should track)", "TP34 (PCIe SerDes)"],
    },
    "TP535": {
        "circuit_name": "DVDD5 — Waikiki 5V Supply",
        "schematic_path": "5V Bus → Distribution → TP535 → Waikiki QCN9274 5V input",
        "ic": "5V bus distribution to Waikiki subsystem",
        "description": "5V supply to the Waikiki WiFi subsystem. Distributed from the main 5V bus. If missing, the entire Waikiki subsystem loses its primary power input.",
        "key_components": ["5V bus ferrite bead/filter", "Distribution trace to Waikiki", "Waikiki 5V input pins"],
        "failure_modes": {"0V": "5V bus distribution issue. Check main 5V at TP1205 first. Then check ferrite bead/fuse to Waikiki.", "<4.75V": "Excess load or cap degradation on Waikiki 5V input."},
        "related_tps": ["TP1205 (5V source)", "TP573 (DVDD3.3)"],
    },
    "TP589": {
        "circuit_name": "DVDD3.3_BZT — Waikiki 3.3V (Filtered)",
        "schematic_path": "TP573 (DVDD3.3) → Filter/Isolation → TP589",
        "ic": "Passive filter network",
        "description": "Filtered version of the 3.3V Waikiki supply. Should track TP573 closely. A significant difference indicates an isolation component (ferrite bead, fuse, or filter cap) has failed.",
        "key_components": ["Ferrite bead or filter between TP573 and TP589", "Local decoupling caps"],
        "failure_modes": {"Differs from TP573": "Isolation component open or shorted. Check ferrite bead continuity.", "Both 0V": "Upstream Buck 6 failure — debug at TP573."},
        "related_tps": ["TP573 (source)"],
    },
    "TP34": {
        "circuit_name": "VDD_PCIE_0P925 — PCIe SerDes Analog (Monitor Only)",
        "schematic_path": "LDO → TP34 → Miami/Waikiki PCIe SerDes analog pins",
        "ic": "PCIe SerDes LDO",
        "description": "0.925V analog supply for PCIe SerDes (Serializer/Deserializer). Powers the high-speed analog circuits in the PCIe link between Miami and Waikiki. MONITOR ONLY — WiFi failure is more likely caused by DVDD3.3 or PERST_N issues.",
        "key_components": ["PCIe SerDes LDO", "Miami PCIe TX/RX analog", "Waikiki PCIe TX/RX analog"],
        "failure_modes": {"Out of spec": "May degrade PCIe link margin. Monitor only — check DVDD3.3 and PERST_N first for WiFi issues."},
        "related_tps": ["TP30 (PCIe 1.8V I/O)", "TP573 (DVDD3.3)"],
    },
    "TP30": {
        "circuit_name": "VDD_PCIE_1P8 — PCIe I/O Supply",
        "schematic_path": "LDO → TP30 → Miami/Waikiki PCIe I/O level shifters",
        "ic": "PCIe I/O LDO",
        "description": "1.8V supply for PCIe I/O interface between Miami and Waikiki. Required for the digital signaling layer of the PCIe link. Without this, Miami and Waikiki cannot communicate even if both are powered.",
        "key_components": ["PCIe I/O LDO", "Level shifters", "PCIe TX/RX differential pairs"],
        "failure_modes": {"0V": "PCIe I/O LDO failure. No Miami-Waikiki communication possible.", "Low": "LDO drooping. Check input supply."},
        "related_tps": ["TP34 (PCIe SerDes analog)", "TP31 (1.8V PX3)"],
    },
    "TP31": {
        "circuit_name": "VDD_1V8_PX3 — 1.8V PX3 Domain",
        "schematic_path": "LDO → TP31 → PX3 domain I/O",
        "ic": "1.8V PX3 LDO",
        "description": "Additional 1.8V domain for PX3 interface. Separate from the shared 1.8V rail (TP503). If this is missing while other 1.8V rails are OK, it's a local LDO issue.",
        "key_components": ["PX3 LDO", "Local decoupling caps"],
        "failure_modes": {"0V while other 1.8V OK": "Local PX3 LDO failure. Check enable and input.", "0V with TP503 also 0V": "Upstream 1.8V bus issue."},
        "related_tps": ["TP503 (shared 1.8V)", "TP30 (PCIe 1.8V)"],
    },
    "TP569": {
        "circuit_name": "VDD_XPA — 5GHz PA Supply (Buck 8)",
        "schematic_path": "5V Bus → Buck 8 (4.2V/2A, 500KHz) → TP569 → SKY85500-11 FEM x2 VCC pins",
        "ic": "Buck 8 converter → SKY85500-11 x2",
        "description": "HIGHEST VOLTAGE RAIL on the board. 4.2V supply for two SKY85500-11 5GHz Front End Modules (FEMs). Peak power draw is 8.4W (4.2V × 2A). Each FEM draws ~300mA during TX. If a PA is shorted, this rail will be pulled low.",
        "key_components": ["Buck 8 converter IC", "SKY85500-11 FEM #1 (VCC pin)", "SKY85500-11 FEM #2 (VCC pin)", "5GHz bandpass filters (DF1508-R5R5NAB)", "RF matching networks"],
        "failure_modes": {"0V": "Buck 8 failure. Check SPBM enable.", "<4.0V": "FEM excess current — one PA may be shorted. Measure current at each FEM VCC (~300mA during TX). 0mA = PA open (burned out).", "Present but no 5G": "FEM or SAW/BPF filter issue. Check diplexer path. Compare TX power to KGU (>3dB below = degradation)."},
        "related_tps": ["TP577 (2.4G PA, separate rail)"],
    },
    "TP577": {
        "circuit_name": "AVDD3.3_2G — 2.4GHz Internal PA (Buck 7)",
        "schematic_path": "5V Bus → Buck 7 (3.3V/2A, 700KHz) → TP577 → Miami IPQ5332 internal 2.4G PA",
        "ic": "Buck 7 converter → Miami IPA",
        "description": "3.3V supply for Miami's internal 2.4GHz power amplifier (IPA). Unlike 5GHz which uses external FEMs, the 2.4GHz PA is integrated inside the Miami SoC. If this rail is present but 2.4G is dead, the issue is the IPA circuit or SAW filters.",
        "key_components": ["Buck 7 converter IC", "Miami IPQ5332 internal PA", "2.4GHz SAW filters (Murata SAFFB2G49MN0F0A x2)", "RF matching network"],
        "failure_modes": {"0V": "Buck 7 failure. Check SPBM enable.", "Present but no 2.4G": "Miami internal PA damaged or SAW filter failure. SAW filters may vary between batches. Check diplexer path."},
        "related_tps": ["TP569 (5G PA, separate rail)"],
    },
    "TP55": {
        "circuit_name": "STBY_VDD3.3 — Standby 3.3V (Always-On)",
        "schematic_path": "PoE Input → Standby LDO → TP55 → Always-on peripherals",
        "ic": "Standby LDO regulator",
        "description": "3.3V standby rail that is always present whenever PoE power is connected, even before the SPBM starts the main power sequence. If this is missing, it indicates a very early power failure in the input stage.",
        "key_components": ["Standby LDO", "Input from PoE rectified voltage", "Always-on peripherals (reset logic, etc.)"],
        "failure_modes": {"0V": "Very early power failure. PoE input may be present but standby LDO is dead. Check input to LDO."},
        "related_tps": ["TP1207 (PoE input)"],
    },
    "TP590": {
        "circuit_name": "LED_5V_3V3 — LED Driver Supply",
        "schematic_path": "3.3V Bus → TP590 → KTD2027B LED Driver → RGB LED",
        "ic": "KTD2027B (Kinetic Technologies)",
        "description": "3.3V supply for the KTD2027B I2C-controlled RGB LED driver. If this rail is present but the LED is dark, the issue is the I2C bus communication or the KTD2027B IC itself.",
        "key_components": ["KTD2027B LED driver IC", "I2C bus (SDA/SCL from Miami)", "RGB LED", "Current-limiting resistors"],
        "failure_modes": {"0V": "No LED at all. 3.3V bus distribution issue.", "Present but LED dark": "I2C bus failure or KTD2027B IC dead. Check I2C pull-ups and bus signals."},
        "related_tps": ["TP55 (standby 3.3V)"],
    },
    "TP56": {
        "circuit_name": "USB-C Orientation Detect (FUSB15201MX)",
        "schematic_path": "USB-C Connector CC pins → FUSB15201MX → TP56 → Miami GPIO",
        "ic": "ON Semi FUSB15201MX",
        "description": "USB-C CC (Configuration Channel) pin voltage indicating cable orientation. The FUSB15201MX detects which way the USB-C cable is inserted and routes signals accordingly. MONITOR ONLY — does not affect core board function. Used for debug UART access via USB-C SBU pins.",
        "key_components": ["FUSB15201MX USB-C mux", "USB-C connector", "CC1/CC2 resistors", "SBU pin routing for UART"],
        "failure_modes": {"Out of spec": "CC resistor network issue. Monitor only — does not affect core board function."},
        "related_tps": [],
    },
}


FAULT_TREES = {
    "PoE Input": {"title": "PoE Input Stage Fault Isolation", "steps": [
        "1. Measure PoE input at cable center taps (pins 4,5=V+; 7,8=V-)",
        "2. If 0V: Check cable continuity, PoE injector output, magnetics",
        "3. If 42.5-57V present: Check MPM3690 ENABLE pin (should be HIGH)",
        "4. Measure 5V output at TP1205. If 0V, MPM3690 not switching",
        "5. Check classification resistor (~24.9K for Class 4 / 802.3at)",
        "6. Scope 5V rail for ripple: >50mV pk-pk = cap degradation",
        "7. Check TMP709 thermal switch (TP1211): if LOW, thermal shutdown"]},
    "Miami SoC Core": {"title": "Miami SoC Core Fault Isolation", "steps": [
        "1. Verify 5V rail OK (Phase 1) before debugging Miami rails",
        "2. Check SPBM (SLG4R44724TR) enable output for 0.9V buck",
        "3. If TP579 VDD_CX=0V: Measure resistance VCC_CX to GND (>5ohm OK)",
        "4. If <1ohm: Miami die short. If >5ohm: Buck 1 converter failure",
        "5. Check TP27 vs TP579: should be close. Delta=series filter issue",
        "6. Check TP29 VDD_SOC_MX: separate domain, own regulator",
        "7. Check TP578 PMU 1.95V: needed for Miami internal LDOs",
        "8. Connect UART (USB-C SBU pins, 115200 baud): any output=alive"]},
    "DDR4 Memory": {"title": "DDR4 Memory Fault Isolation", "steps": [
        "1. Check TP574 VDD_DDR first: DDR4 core power",
        "2. Check TP576 VPP: must come up AFTER VDD_DDR is stable",
        "3. If both present: connect UART, look for DDR training messages",
        "4. DDR training failed: Scope VDD_DDR ripple (AC coupled, 20MHz BW)",
        "5. Ripple >30mV: Output cap degradation on 1.2V rail",
        "6. Ripple OK: DDR4 BGA solder joint suspect (RPN=162, #3 risk)",
        "7. X-ray DDR4 BGA if available: look for cracked balls",
        "8. Thermal cycle test: heat 55C / cool 0C, monitor boot"]},
    "Shared / Analog": {"title": "Shared 1.8V Rail Fault Isolation", "steps": [
        "1. TP503 should read ~1.8V",
        "2. If dead: Buck 2 failure. Check enable from SPBM.",
        "3. WARNING: This rail feeds Waikiki analog AND Napa PHY I/O",
        "4. If 1.8V dead: expect BOTH WiFi and Ethernet non-functional",
        "5. Check TP28 (0.8V) and TP36 (1.2V): separate analog LDOs",
        "6. If 0.8V or 1.2V missing: respective LDO failed",
        "7. Check enable pins and input supply for failed LDO"]},
    "Ethernet PHY (Napa)": {"title": "Ethernet PHY Fault Isolation", "steps": [
        "1. Verify TP504 (1.05V core) AND TP503 (1.8V I/O) both present",
        "2. If 1.05V missing: Buck 5 failure",
        "3. Both present but no Ethernet: check RJ45 (bent pins, corrosion)",
        "4. Check magnetics continuity (<2ohm per winding)",
        "5. Via UART: ethtool eth0 -> check link status and speed",
        "6. Link: no -> Check MDI signals with scope at Napa pins",
        "7. Link up but no data: Check SGMII between Miami and Napa",
        "8. Speed stuck at 100M: Cable issue (only 2 pairs working)"]},
    "WiFi (Waikiki)": {"title": "WiFi / Waikiki / PCIe Fault Isolation", "steps": [
        "1. Check TP573 DVDD3.3 first: Waikiki main digital supply",
        "2. Check TP535 DVDD5: 5V to Waikiki subsystem",
        "3. Check PCIe rails: TP34 (0.925V SerDes) and TP30 (1.8V I/O)",
        "4. All present: Via UART lspci should show QCN9274",
        "5. Not listed: Check PERST_N signal (should go HIGH after power)",
        "6. Scope PCIe reference clock (100MHz differential)",
        "7. PCIe link up but no WiFi: Driver issue or Waikiki firmware",
        "8. Check TP31 VDD_1V8_PX3: additional 1.8V domain"]},
    "RF Power Amps": {"title": "RF Power Amplifier Fault Isolation", "steps": [
        "1. Check TP569 VDD_XPA (4.2V): 5GHz FEM supply (HIGHEST RAIL)",
        "2. If 0V: Buck 8 failure. If <4.0V: FEM excess current (PA short)",
        "3. Check TP577 AVDD3.3_2G: 2.4GHz internal PA supply",
        "4. 5G dead: Measure current at each FEM VCC (~300mA during TX)",
        "5. 0mA during TX: PA open (burned out). Replace SKY85500-11.",
        "6. 2.4G dead: Check SAW filters (part may vary between batches)",
        "7. Check diplexer paths with network analyzer if available",
        "8. Compare TX power to KGU: >3dB below=component degradation"]},
    "Standby / Misc": {"title": "Standby / Misc Fault Isolation", "steps": [
        "1. TP55 STBY_VDD3.3 should be present whenever PoE connected",
        "2. If missing: Very early power failure, before SPBM starts",
        "3. TP590 LED supply: if 0V, no LED (unit may work but dark)",
        "4. Check I2C bus to KTD2027B if LED supply present but LED off",
        "5. TP56 USB-C orientation: depends on cable, for debug port",
        "6. POE_POWER_QSDK: total system power at full OS, 3-12.9W",
        "7. If >12.9W: abnormal draw, thermal camera for shorted component"]},
}

CSS = """<style>
.ph{background:linear-gradient(135deg,#38363F,#31303C);color:#F3F1F8;padding:12px 18px;border-radius:10px;margin:10px 0 6px;font-size:1.1em;font-weight:600;border-left:4px solid #8B6CFF}
.ph-c{border-left:4px solid #E879F9}
.tp-pass{background:#2b4a3f;border-left:4px solid #34D399;padding:8px 14px;border-radius:8px;margin:4px 0;color:#c7f0e0;font-family:'DM Mono',monospace}
.tp-fail{background:#4a2c3c;border-left:4px solid #F472B6;padding:8px 14px;border-radius:8px;margin:4px 0;color:#f7d3e4;font-family:'DM Mono',monospace}
.tp-warn{background:#4a4127;border-left:4px solid #FBBF24;padding:8px 14px;border-radius:8px;margin:4px 0;color:#fbeccb;font-family:'DM Mono',monospace}
.tp-skip{background:#38363F;border-left:4px solid #524F5E;padding:8px 14px;border-radius:8px;margin:4px 0;color:#9A94A8;font-family:'DM Mono',monospace}
.tp-monitor{background:#4a4127;border-left:4px solid #e67e22;padding:8px 14px;border-radius:8px;margin:4px 0;color:#fbeccb;font-family:'DM Mono',monospace}
.led{display:inline-block;width:16px;height:16px;border-radius:50%;margin-right:8px;vertical-align:middle}
.led-off{background:#4a4858;box-shadow:0 0 2px #333}
.led-blue{background:#3498db;box-shadow:0 0 8px #3498db,0 0 16px #3498db55}
.led-green{background:#34D399;box-shadow:0 0 8px #34D399,0 0 16px #34D39955}
.led-red{background:#e74c3c;box-shadow:0 0 8px #e74c3c,0 0 16px #e74c3c55}
.led-orange{background:#e67e22;box-shadow:0 0 8px #e67e22,0 0 16px #e67e2255}
.vb{padding:16px;border-radius:12px;margin:12px 0;font-size:1.05em}
.vb-p{background:linear-gradient(135deg,#2b4a3f,#33564a);border:2px solid #34D399;color:#c7f0e0}
.vb-f{background:linear-gradient(135deg,#4a2c3c,#563048);border:2px solid #F472B6;color:#f7d3e4}
.st{width:100%;border-collapse:collapse;font-family:'DM Mono',monospace;font-size:.9em}
.st th{background:#413F4A;color:#F3F1F8;padding:8px 12px;text-align:left;border-bottom:2px solid #8B6CFF}
.st td{padding:6px 12px;border-bottom:1px solid #524F5E}
.st tr.rp td{color:#34D399} .st tr.rf td{color:#F472B6;font-weight:bold} .st tr.rw td{color:#FBBF24} .st tr.rs td{color:#9A94A8} .st tr.rm td{color:#e67e22}
.dd{background:#38363F;border:1px solid #524F5E;border-radius:10px;padding:14px;margin:8px 0;color:#d8d3e4}
.dd ol{margin:6px 0;padding-left:20px} .dd li{margin:4px 0;line-height:1.5}
.phase-bar{display:flex;gap:4px;margin:10px 0 16px;flex-wrap:wrap}
.phase-pill{flex:1;min-width:90px;text-align:center;padding:8px 4px;border-radius:10px;font-size:.75em;font-weight:600;font-family:'DM Mono',monospace;border:2px solid #524F5E;transition:all .3s}
.pp-gray{background:#38363F;color:#9A94A8;border-color:#524F5E}
.pp-blue{background:#413F4A;color:#A78BFA;border-color:#8B6CFF}
.pp-green{background:#2b4a3f;color:#34D399;border-color:#34D399}
.pp-red{background:#4a2c3c;color:#F472B6;border-color:#F472B6}
.pp-orange{background:#4a4127;color:#e67e22;border-color:#e67e22}
.vi-box{background:linear-gradient(135deg,#38363F,#31303C);border:2px solid #524F5E;border-radius:12px;padding:16px;margin:10px 0}
</style>"""


def evaluate(value, tp):
    if value is None or value == "":
        return "skip", "Not measured"
    try:
        v = float(value)
    except (ValueError, TypeError):
        return "skip", "Invalid"
    is_monitor = tp.get("monitor", False)
    if v < tp["lsl"]:
        if v == 0:
            label = "MONITOR: DEAD (0" + tp["unit"] + ")" if is_monitor else "DEAD (0" + tp["unit"] + ")"
            return ("monitor" if is_monitor else "fail"), label
        pct = ((tp["lsl"] - v) / tp["lsl"]) * 100 if tp["lsl"] != 0 else 0
        label = f"MONITOR: LOW by {pct:.1f}% below LSL" if is_monitor else f"LOW by {pct:.1f}% below LSL"
        return ("monitor" if is_monitor else "fail"), label
    if v > tp["usl"]:
        pct = ((v - tp["usl"]) / tp["usl"]) * 100 if tp["usl"] != 0 else 0
        label = f"MONITOR: HIGH by {pct:.1f}% above USL" if is_monitor else f"HIGH by {pct:.1f}% above USL"
        return ("monitor" if is_monitor else "fail"), label
    rng = tp["usl"] - tp["lsl"]
    if rng > 0:
        if (v - tp["lsl"]) / rng < 0.1 or (tp["usl"] - v) / rng < 0.1:
            return "warn", "MARGINAL (near limit)"
    return "pass", "PASS"


def _tp_row(tp, val, status, msg):
    c = "tp-" + status
    n = str(tp["nom"]) if tp["nom"] is not None else "N/A"
    try:
        d = f"{float(val):.4f}" if val else "---"
    except (ValueError, TypeError):
        d = "---"
    ic = {"pass":"✅","fail":"❌","warn":"⚠️","skip":"⬜","monitor":"🟠"}.get(status,"⬜")
    step = tp.get("step", "")
    loc = tp.get("loc", "")
    step_tag = f'<span style="background:#0f3460;color:#fff;padding:1px 6px;border-radius:10px;font-size:.8em;margin-right:4px;">#{step}</span>' if step else ""
    loc_tag = f'<br><span style="font-size:.75em;color:#888;">📍 {loc}</span>' if loc else ""
    return (f'<div class="{c}">{step_tag}{ic} <b>{tp["tp"]}</b> {tp["name"]}'
            f' | KGU: {n} {tp["unit"]} | DUT: <b>{d}</b> {tp["unit"]}'
            f' | [{tp["lsl"]} - {tp["usl"]}] &rarr; <b>{msg}</b>{loc_tag}</div>')


def _render_board_map():
    """Render an SVG board map showing numbered test point locations."""
    # TP positions mapped from the PCB image (approximate x,y on 1000x750 grid)
    tp_positions = [
        (1,  "TP1207", "POE_VDD",        95, 590, "PoE Input"),
        (2,  "PSU",    "PoE Power",       95, 620, "PoE Input"),
        (3,  "TP1205", "POE_5V",          95, 175, "PoE Input"),
        (4,  "TP579",  "VDD_CX",          640, 45,  "Miami SoC Core"),
        (5,  "TP27",   "VDD_SOC_CX",      870, 400, "Miami SoC Core"),
        (6,  "TP29",   "VDD_SOC_MX",      830, 45,  "Miami SoC Core"),
        (7,  "TP578",  "VDD1V95_PMU",     460, 45,  "Miami SoC Core"),
        (8,  "TP574",  "VDD_DDR",         370, 680, "DDR4 Memory"),
        (9,  "TP576",  "VDD_LDO_2P5_VPP", 330, 45,  "DDR4 Memory"),
        (10, "TP503",  "VDD1.8_NAPA",     200, 680, "Shared / Analog"),
        (11, "TP28",   "VAA_0P8",         870, 310, "Shared / Analog"),
        (12, "TP36",   "VAA_1P2",         870, 490, "Shared / Analog"),
        (13, "TP504",  "VDD1.05_NAPA",    80,  430, "Ethernet PHY"),
        (14, "TP573",  "DVDD3.3",         250, 45,  "WiFi (Waikiki)"),
        (15, "TP535",  "DVDD5",           80,  340, "WiFi (Waikiki)"),
        (16, "TP589",  "DVDD3.3_BZT",     130, 45,  "WiFi (Waikiki)"),
        (17, "TP34",   "VDD_PCIE_0P925",  870, 440, "WiFi (Waikiki)"),
        (18, "TP30",   "VDD_PCIE_1P8",    870, 540, "WiFi (Waikiki)"),
        (19, "TP31",   "VDD_1V8_PX3",     870, 350, "WiFi (Waikiki)"),
        (20, "TP569",  "VDD_XPA",         920, 130, "RF Power Amps"),
        (21, "TP577",  "AVDD3.3_2G",      50,  80,  "RF Power Amps"),
        (22, "TP55",   "STBY_VDD3.3",     490, 680, "Standby / Misc"),
        (23, "TP590",  "LED_5V_3V3",      870, 600, "Standby / Misc"),
        (24, "TP56",   "USBC_ORIENT",     440, 730, "Standby / Misc"),
        (26, "PSU",    "PoE Power QSDK",  95, 650, "Standby / Misc"),
    ]
    colors = {
        "PoE Input": "#e74c3c",
        "Miami SoC Core": "#3498db",
        "DDR4 Memory": "#2ecc71",
        "Shared / Analog": "#f39c12",
        "Ethernet PHY": "#1abc9c",
        "WiFi (Waikiki)": "#9b59b6",
        "RF Power Amps": "#e67e22",
        "Standby / Misc": "#95a5a6",
    }
    # Build SVG
    circles = ""
    labels = ""
    for step, tp_name, signal, x, y, group in tp_positions:
        col = colors.get(group, "#888")
        circles += f'<circle cx="{x}" cy="{y}" r="14" fill="{col}" stroke="#fff" stroke-width="1.5" opacity="0.9"/>'
        circles += f'<text x="{x}" y="{y+5}" text-anchor="middle" fill="#fff" font-size="11" font-weight="bold" font-family="monospace">{step}</text>'
        # Label offset
        lx = x + 20 if x < 500 else x - 20
        anchor = "start" if x < 500 else "end"
        labels += f'<text x="{lx}" y="{y+4}" text-anchor="{anchor}" fill="#ccc" font-size="9" font-family="monospace">{tp_name}</text>'

    svg = f'''<svg viewBox="0 0 1000 760" style="width:100%;max-width:960px;background:#1a1a2e;border-radius:10px;border:1px solid #0f3460;">
    <rect x="30" y="30" width="940" height="700" rx="12" fill="#222" stroke="#444" stroke-width="1"/>
    <text x="500" y="22" text-anchor="middle" fill="#666" font-size="11" font-family="monospace">PCB — TOP VIEW (RJ45 at bottom-left)</text>
    <!-- Board outline regions -->
    <rect x="40" y="40" width="200" height="300" rx="4" fill="none" stroke="#444" stroke-width="0.5" stroke-dasharray="4"/>
    <text x="140" y="55" text-anchor="middle" fill="#555" font-size="8" font-family="monospace">PoE / Power</text>
    <rect x="350" y="150" width="300" height="350" rx="4" fill="none" stroke="#444" stroke-width="0.5" stroke-dasharray="4"/>
    <text x="500" y="165" text-anchor="middle" fill="#555" font-size="8" font-family="monospace">Miami SoC + DDR4</text>
    <rect x="700" y="100" width="260" height="400" rx="4" fill="none" stroke="#444" stroke-width="0.5" stroke-dasharray="4"/>
    <text x="830" y="115" text-anchor="middle" fill="#555" font-size="8" font-family="monospace">Waikiki / RF / Analog</text>
    {circles}
    {labels}
    </svg>'''

    st.markdown(svg, unsafe_allow_html=True)

    # Legend
    legend_items = " ".join(
        f'<span style="display:inline-block;margin:2px 8px;"><span style="display:inline-block;width:12px;height:12px;background:{c};border-radius:50%;margin-right:4px;vertical-align:middle;"></span><span style="color:#ccc;font-size:.8em;">{g}</span></span>'
        for g, c in colors.items()
    )
    st.markdown(f'<div style="text-align:center;margin:6px 0;">{legend_items}</div>', unsafe_allow_html=True)

    # Numbered reference table
    st.markdown("##### Probe Order Reference")
    rows = ""
    for step, tp_name, signal, x, y, group in tp_positions:
        tp_match = [v for v in TEST_POINTS.values() if v.get("step") == step]
        loc = tp_match[0]["loc"] if tp_match else ""
        rows += f"| {step} | {tp_name} | {signal} | {group} | {loc} |\n"
    st.markdown(
        "| # | Test Point | Signal | Group | Board Location |\n"
        "|---|-----------|--------|-------|----------------|\n"
        + rows
    )


def _render_component_diagnostics(diagnostics):
    """Render the ranked component-suspect diagnostic checklist."""
    if not diagnostics:
        return
    st.markdown("##### 🎯 Suspect Components (probe in order)")
    st.caption("Ranked by likelihood. Stop at the first failing check — that's your faulty component.")
    for i, d in enumerate(diagnostics, 1):
        prio = d.get("priority", "Medium")
        prio_color = {"High": "#e74c3c", "Medium": "#f39c12", "Low": "#3498db"}.get(prio, "#888")
        ref = d.get("ref", "")
        comp = d.get("component", "")
        loc = d.get("location", "")
        check = d.get("check", "")
        expected = d.get("expected", "")
        if_fail = d.get("if_fail", "")
        tools = d.get("tools", "")

        header = f'<div style="background:#1a1a2e;border-left:4px solid {prio_color};border-radius:6px;padding:10px 14px;margin:8px 0;">'
        header += f'<div style="font-weight:700;color:#e0e0e0;font-size:1.05em;">#{i} &nbsp; {ref} — {comp} '
        header += f'<span style="float:right;font-size:.8em;color:{prio_color};font-weight:600;">{prio.upper()} PRIORITY</span></div>'
        if loc:
            header += f'<div style="color:#aaa;font-size:.85em;margin:4px 0 8px 0;">📍 {loc}</div>'
        st.markdown(header, unsafe_allow_html=True)

        cols = st.columns([2, 2, 1])
        with cols[0]:
            st.markdown(f"**Probe / Check**")
            st.markdown(f"<span style='color:#bbb;font-size:.9em'>{check}</span>", unsafe_allow_html=True)
        with cols[1]:
            st.markdown(f"**Expected (KGU)**")
            st.markdown(f"<span style='color:#27ae60;font-size:.9em;font-family:monospace'>{expected}</span>", unsafe_allow_html=True)
        with cols[2]:
            if tools:
                st.markdown(f"**Tool**")
                st.markdown(f"<span style='color:#888;font-size:.85em'>{tools}</span>", unsafe_allow_html=True)
        if if_fail:
            st.markdown(f'<div style="background:#2a1a1a;border-left:3px solid #c0392b;padding:6px 10px;margin:6px 0;border-radius:4px;font-size:.85em;color:#e0c4c4;"><b>❌ If this fails:</b> {if_fail}</div>', unsafe_allow_html=True)
        st.markdown("</div>", unsafe_allow_html=True)


def _render_schematic_lookup(tp_name):
    """Render schematic circuit details for a given test point."""
    info = SCHEMATIC_DB.get(tp_name)
    if not info:
        # Try matching by group name
        for key, val in SCHEMATIC_DB.items():
            if tp_name in str(val.get("related_tps", [])):
                info = val
                break
    if not info:
        return
    with st.expander(f"🔍 Schematic: {info['circuit_name']}", expanded=True):
        st.markdown(f"**Circuit:** {info['circuit_name']}")
        st.markdown(f"**IC:** `{info['ic']}`")
        st.markdown(f"**Signal Path:**\n```\n{info['schematic_path']}\n```")
        st.markdown(f"**Description:** {info['description']}")
        if info.get("key_components"):
            comps = " → ".join(info["key_components"])
            st.markdown(f"**Key Components:** {comps}")
        if info.get("failure_modes"):
            st.markdown("**Failure Mode Analysis:**")
            for mode, action in info["failure_modes"].items():
                st.markdown(f"- **{mode}**: {action}")

        # NEW: Component-level diagnostic checklist
        if info.get("component_diagnostics"):
            st.markdown("---")
            _render_component_diagnostics(info["component_diagnostics"])

        if info.get("related_tps"):
            st.markdown(f"**Related Test Points:** {', '.join(info['related_tps'])}")


def _phase_results(phase_tps, readings, pnum):
    fails, warns, passes, monitors = [], [], [], []
    st.markdown("##### KGU Spec vs DUT Comparison")
    for k, tp in phase_tps.items():
        val = readings.get(k)
        s, m = evaluate(val, tp)
        st.markdown(_tp_row(tp, val, s, m), unsafe_allow_html=True)
        if s == "fail": fails.append((k, tp, m))
        elif s == "monitor": monitors.append((k, tp, m))
        elif s == "warn": warns.append((k, tp, m))
        elif s == "pass": passes.append((k, tp, m))
    st.markdown("---")

    # LED status indicator
    if fails:
        led = "led-red"
    elif monitors or warns:
        led = "led-orange"
    elif passes and not fails:
        led = "led-green"
    else:
        led = "led-blue"

    if fails:
        grp = list(phase_tps.values())[0]["group"]
        st.markdown(f'<div class="vb vb-f"><span class="led {led}"></span>❌ Phase {pnum} VERDICT: <b>FAIL</b> — {len(fails)} rail(s) out of spec</div>', unsafe_allow_html=True)
        st.markdown("##### Recommended Actions")
        for _, tp, m in fails:
            st.error(f"**{tp['tp']} ({tp['name']})** - {m}\n\n**Subsystem:** {tp['subsystem']}\n\n**Action:** {tp['fail_action']}")
            _render_schematic_lookup(tp["tp"])
        for tk, td in FAULT_TREES.items():
            if tk in grp or grp.startswith(tk.split(" ")[0]):
                st.markdown(f'<div class="vb vb-f" style="border-color:#e67e22;">🔍 Errors detected. Deep dive in <b>"{td["title"]}"</b> to isolate the fault.</div>', unsafe_allow_html=True)
                sh = "".join(f"<li>{s[3:]}</li>" for s in td["steps"])
                st.markdown(f'<div class="dd"><ol>{sh}</ol></div>', unsafe_allow_html=True)
                break
    elif monitors:
        st.markdown(f'<div class="vb vb-p" style="border-color:#e67e22;"><span class="led {led}"></span>🟠 Phase {pnum}: <b>MONITOR</b> — {len(monitors)} monitor-only rail(s) out of spec, {len(passes)} OK. These do not indicate board failure.</div>', unsafe_allow_html=True)
        for _, tp, m in monitors:
            st.info(f"**{tp['tp']} ({tp['name']})** — {m}\n\n📋 {tp['fail_action']}")
    elif warns:
        st.markdown(f'<div class="vb vb-p" style="border-color:#f39c12;"><span class="led {led}"></span>⚠️ Phase {pnum}: <b>MARGINAL</b> — {len(warns)} near limit, {len(passes)} OK</div>', unsafe_allow_html=True)
        st.info("Within spec but marginal. Proceed but flag for monitoring.")
    else:
        st.markdown(f'<div class="vb vb-p"><span class="led {led}"></span>✅ Phase {pnum}: <b>PASS</b> — {len(passes)}/{len(phase_tps)} within spec. Proceed to Phase {min(pnum+1,8)}.</div>', unsafe_allow_html=True)


def _full_summary(readings):
    results = []
    tf = tw = tp_ = ts = tm = 0
    fg = set()
    for k, tp in TEST_POINTS.items():
        val = readings.get(k)
        s, m = evaluate(val, tp)
        n = str(tp["nom"]) if tp["nom"] is not None else "N/A"
        try:
            d = f"{float(val):.4f}" if val else "---"
        except (ValueError, TypeError):
            d = "---"
        results.append({"Phase": tp["phase"], "TP": tp["tp"], "Rail": tp["name"],
                        "LSL": tp["lsl"], "Nom": n, "USL": tp["usl"],
                        "DUT": d, "Unit": tp["unit"], "Status": s.upper(),
                        "Detail": m, "Group": tp["group"],
                        "Subsystem": tp["subsystem"],
                        "Action": tp["fail_action"] if s == "fail" else ""})
        if s == "fail": tf += 1; fg.add(tp["group"])
        elif s == "monitor": tm += 1
        elif s == "warn": tw += 1
        elif s == "pass": tp_ += 1
        else: ts += 1

    st.markdown("##### Overall DUT Health")
    c1, c2, c3, c4, c5 = st.columns(5)
    c1.metric("PASS", tp_); c2.metric("FAIL", tf); c3.metric("MONITOR", tm); c4.metric("MARGINAL", tw); c5.metric("NOT TESTED", ts)

    # LED indicator
    if tf > 0:
        led = "led-red"
    elif tm > 0 or tw > 0:
        led = "led-orange"
    elif tp_ > 0:
        led = "led-green"
    else:
        led = "led-blue"

    if tf > 0:
        st.markdown(f'<div class="vb vb-f"><span class="led {led}"></span>❌ DUT: <b>FAIL</b> — {tf} rail(s) out of spec in: {", ".join(sorted(fg))}</div>', unsafe_allow_html=True)
    elif tm > 0:
        st.markdown(f'<div class="vb vb-p" style="border-color:#e67e22;"><span class="led {led}"></span>🟠 DUT: <b>PASS (with monitors)</b> — all decision rails OK, {tm} monitor-only out of spec</div>', unsafe_allow_html=True)
    elif tw > 0:
        st.markdown(f'<div class="vb vb-p" style="border-color:#f39c12;"><span class="led {led}"></span>⚠️ DUT: <b>MARGINAL</b> — all in spec but {tw} marginal</div>', unsafe_allow_html=True)
    elif tp_ > 0:
        st.markdown(f'<div class="vb vb-p"><span class="led {led}"></span>✅ DUT: <b>PASS</b> — all {tp_} rails within spec</div>', unsafe_allow_html=True)

    st.markdown("##### Full KGU vs DUT Comparison")
    rh = ""
    cp = 0
    for r in results:
        if r["Phase"] != cp:
            cp = r["Phase"]
            pi = PHASES[cp]
            rh += f'<tr><td colspan="8" style="background:#0f3460;color:#e0e0e0;font-weight:bold;padding:8px;">{pi["icon"]} Phase {cp}: {pi["name"]}</td></tr>'
        rc = "r" + r["Status"][0].lower()
        ic = {"PASS":"✅","FAIL":"❌","WARN":"⚠️","SKIP":"⬜","MONITOR":"🟠"}.get(r["Status"],"⬜")
        rh += f'<tr class="{rc}"><td>{r["TP"]}</td><td>{r["Rail"]}</td><td>{r["LSL"]}</td><td>{r["Nom"]}</td><td>{r["USL"]}</td><td><b>{r["DUT"]}</b></td><td>{r["Unit"]}</td><td>{ic} {r["Detail"]}</td></tr>'
    st.markdown(f'<table class="st"><thead><tr><th>Test Point</th><th>Rail</th><th>LSL</th><th>KGU Nom</th><th>USL</th><th>DUT</th><th>Unit</th><th>Verdict</th></tr></thead><tbody>{rh}</tbody></table>', unsafe_allow_html=True)

    if tf > 0:
        st.markdown("---")
        st.markdown("##### Failed Rail Actions")
        for r in results:
            if r["Status"] == "FAIL":
                st.error(f"**{r['TP']} ({r['Rail']})** - {r['Detail']}\n\n**Subsystem:** {r['Subsystem']}\n\n**Action:** {r['Action']}")
                _render_schematic_lookup(r["TP"])
        st.markdown("##### Deep Dive for Failed Subsystems")
        for g in sorted(fg):
            for tk, td in FAULT_TREES.items():
                if tk in g or g.startswith(tk.split(" ")[0]):
                    st.markdown(f"**{td['title']}**")
                    sh = "".join(f"<li>{s[3:]}</li>" for s in td["steps"])
                    st.markdown(f'<div class="dd"><ol>{sh}</ol></div>', unsafe_allow_html=True)
                    break

    st.markdown("---")
    df = pd.DataFrame(results)
    did = st.session_state.get("debugger_dut_id", "unknown")
    prog_slug = (get_selected_program() or "debug").lower().replace(" ", "_")
    st.download_button("Download Debug Report (CSV)", data=df.to_csv(index=False),
                       file_name=f"{prog_slug}_debug_{did}.csv", mime="text/csv", use_container_width=True)
    if st.button("Clear All Readings", use_container_width=True):
        st.session_state.debugger_readings = {}
        st.rerun()


def _get_reports_dir():
    prog = get_selected_program()
    if prog:
        return get_reports_dir(prog)
    return os.path.join(os.path.dirname(os.path.abspath(__file__)), "debug_reports")


def _get_ml_model_path():
    prog = get_selected_program()
    if prog:
        return get_ml_model_path(prog)
    return os.path.join(os.path.dirname(os.path.abspath(__file__)), "debugger_ml_model.json")


def _get_phase_status(phase_num, readings):
    """Evaluate all TPs in a phase and return status: gray/blue/green/red/orange."""
    ptps = {k: v for k, v in TEST_POINTS.items() if v["phase"] == phase_num}
    if not ptps:
        return "gray"
    has_data = False
    has_fail = False
    has_monitor = False
    has_warn = False
    all_pass = True
    for k, tp in ptps.items():
        val = readings.get(k)
        if val is not None and val != "":
            has_data = True
            s, _ = evaluate(val, tp)
            if s == "fail":
                has_fail = True
                all_pass = False
            elif s == "monitor":
                has_monitor = True
            elif s == "warn":
                has_warn = True
            elif s != "pass":
                all_pass = False
        else:
            all_pass = False
    if has_fail:
        return "red"
    if has_data and all_pass:
        return "green" if not has_monitor and not has_warn else "orange" if has_monitor else "orange"
    if has_data:
        return "blue"
    return "gray"


def _render_phase_status_bar(readings):
    """Render horizontal phase status indicator bar."""
    pills = ""
    for pn in sorted(PHASES):
        ph = PHASES[pn]
        status = _get_phase_status(pn, readings)
        cls = f"pp-{status}"
        icon_map = {"gray": "⬜", "blue": "🔵", "green": "🟢", "red": "🔴", "orange": "🟠"}
        ic = icon_map.get(status, "⬜")
        pills += f'<div class="phase-pill {cls}">{ic}<br>P{pn}: {ph["name"][:12]}</div>'
    st.markdown(f'<div class="phase-bar">{pills}</div>', unsafe_allow_html=True)


VI_OPTIONS = ["No Damage", "Crack / Physical Damage", "Liquid Ingress", "Burn Marks / Discoloration",
              "Bent Pins / Connector Damage", "Corrosion", "Missing Components", "Other"]


def _render_visual_inspection():
    """Render visual inspection step before Phase 1. Returns True only for info, never blocks."""
    st.markdown('<div class="vi-box">', unsafe_allow_html=True)
    st.markdown("##### 👁️ Step 0: Visual Inspection (Required)")
    st.markdown('<span style="color:#aaa;font-size:.9em;">Inspect the PCB before powering on. Select all that apply.</span>', unsafe_allow_html=True)
    if "vi_findings" not in st.session_state:
        st.session_state.vi_findings = []
    if "vi_notes" not in st.session_state:
        st.session_state.vi_notes = ""
    findings = st.multiselect("Visual Inspection Findings", VI_OPTIONS, default=st.session_state.vi_findings, key="vi_select")
    st.session_state.vi_findings = findings
    notes = st.text_area("Additional VI Notes", value=st.session_state.vi_notes, key="vi_notes_input",
                         placeholder="Describe location/severity of any damage found...", height=68)
    st.session_state.vi_notes = notes
    st.markdown('</div>', unsafe_allow_html=True)

    if "Liquid Ingress" in findings:
        st.markdown(
            '<div class="vb vb-f" style="border-color:#e67e22;">'
            '<span class="led led-orange"></span>⚠️ <b>PROCEED WITH CAUTION — Liquid Ingress Detected</b><br>'
            'Failure Symptom: <b>Potential dead board due to Liquid Ingress</b>. '
            'Follow the precautionary steps below before powering on.</div>', unsafe_allow_html=True)
        with st.expander("🧪 Liquid Ingress — Precautionary Steps Before Testing", expanded=True):
            st.markdown("""
**Pre-Power-On Cleaning & Drying Protocol:**

1. **Remove all visible liquid** — Tilt the board and blot with lint-free wipes. Do NOT shake vigorously (can spread liquid under BGA/QFN packages).
2. **Clean with 90%+ Isopropyl Alcohol (IPA)** — Use high-purity IPA (≥90%, ideally 99%) to displace water and dissolved minerals. Apply with a soft brush or lint-free swab around connectors, under shields, and near fine-pitch components. ([source](https://www.wonderfulpcb.com/blog/cleaning-printed-circuit-boards-without-causing-damage/))
3. **Pay special attention to BGA areas** — DDR4, Miami SoC, and Waikiki are BGA packages where liquid can become trapped. Use compressed air at low pressure to help displace moisture from under these components.
4. **Dry in a controlled environment** — Allow minimum 24-48 hours drying time in a warm, ventilated area (40-50°C). Use desiccant packs or a low-temperature oven if available. Do NOT use a heat gun directly on components. ([source](https://www.elektroda.com/qa,water-damage-electronics-solutions.html))
5. **Inspect for corrosion** — Look for white/green residue on copper traces, connector pins, and solder joints. Corrosion on fine-pitch pads (0.4mm BGA) can cause intermittent failures days after exposure. ([source](https://remedics.com/water-damaged-electronics-drying))
6. **Check resistance to ground on critical rails before powering** — Use a multimeter to measure resistance from each major rail to GND:
   - VDD_CX (TP579) to GND: should be >5Ω (if <1Ω, short circuit from corrosion)
   - VDD_DDR (TP574) to GND: should be >5Ω
   - 5V rail (TP1205) to GND: should be >10Ω
7. **Use a current-limited power supply** — Set current limit to 500mA initially. If the board draws excessive current immediately, power off and re-inspect for shorts.
8. **Document corrosion locations** — Photograph any corrosion areas for the FA report. Note which subsystems are affected.
9. **Monitor temperature during first power-on** — Use a thermal camera or touch-test for hot spots that indicate shorted components.

*Content was rephrased for compliance with licensing restrictions.*
""")
    if "Burn Marks / Discoloration" in findings:
        st.markdown('<div class="vb vb-f" style="border-color:#e67e22;"><span class="led led-orange"></span>⚠️ <b>Burn Marks Detected</b><br>'
                    'Inspect for shorted components near burn area. Identify affected subsystem before powering on. '
                    'Risk of further damage if powered with existing short.</div>', unsafe_allow_html=True)
    if "Crack / Physical Damage" in findings:
        st.info("📋 Physical damage noted. Proceed with caution — check affected area TPs carefully.")
    return False


def _generate_dfmea_report(readings, dut_id, test_date, test_stage, vi_findings, vi_notes):
    """Generate failure analysis report and store for ML training."""
    report = {
        "report_id": f"FA-{dut_id}-{datetime.now().strftime('%Y%m%d%H%M%S')}",
        "dut_id": dut_id,
        "test_date": str(test_date),
        "test_stage": test_stage,
        "generated_at": datetime.now().isoformat(),
        "visual_inspection": {"findings": vi_findings, "notes": vi_notes},
        "phases": {},
        "overall_verdict": "PASS",
        "failed_subsystems": [],
        "root_causes": [],
        "dfmea_entries": [],
    }

    all_fail = False
    for pn in sorted(PHASES):
        ph = PHASES[pn]
        ptps = {k: v for k, v in TEST_POINTS.items() if v["phase"] == pn}
        phase_data = {"name": ph["name"], "verdict": "PASS", "test_points": [], "failures": []}
        for k, tp in ptps.items():
            val = readings.get(k)
            s, m = evaluate(val, tp)
            n = str(tp["nom"]) if tp["nom"] is not None else "N/A"
            try:
                d = f"{float(val):.4f}" if val else "N/T"
            except (ValueError, TypeError):
                d = "N/T"
            tp_entry = {"tp": tp["tp"], "rail": tp["name"], "lsl": tp["lsl"], "nom": n,
                        "usl": tp["usl"], "dut_value": d, "unit": tp["unit"],
                        "status": s, "detail": m, "subsystem": tp["subsystem"],
                        "is_monitor": tp.get("monitor", False)}
            phase_data["test_points"].append(tp_entry)
            if s == "fail":
                phase_data["verdict"] = "FAIL"
                all_fail = True
                phase_data["failures"].append(tp_entry)
                # DFMEA entry
                report["dfmea_entries"].append({
                    "item": tp["tp"],
                    "function": tp["name"],
                    "potential_failure_mode": m,
                    "potential_effect": tp["fail_action"],
                    "severity": 8 if ph["critical"] else 5,
                    "potential_cause": f"{tp['subsystem']} failure",
                    "occurrence": 4,
                    "detection_method": f"Measurement at {tp['tp']}",
                    "detection": 3,
                    "rpn": (8 if ph["critical"] else 5) * 4 * 3,
                    "recommended_action": tp["fail_action"],
                    "subsystem": tp["subsystem"],
                    "phase": pn,
                })
                if tp["subsystem"] not in report["failed_subsystems"]:
                    report["failed_subsystems"].append(tp["subsystem"])
                    report["root_causes"].append(f"{tp['subsystem']}: {m}")
        report["phases"][str(pn)] = phase_data

    if "Liquid Ingress" in vi_findings:
        report["overall_verdict"] = "FAIL — Liquid Ingress"
        report["root_causes"].insert(0, "Liquid Ingress detected during Visual Inspection")
    elif all_fail:
        report["overall_verdict"] = "FAIL"
    else:
        report["overall_verdict"] = "PASS"

    # Store report for ML training
    os.makedirs(_get_reports_dir(), exist_ok=True)
    report_path = os.path.join(_get_reports_dir(), f"{report['report_id']}.json")
    with open(report_path, "w") as f:
        json.dump(report, f, indent=2)

    # Update ML training data
    _update_ml_model(report)

    return report


def _update_ml_model(report):
    """Incrementally update ML pattern database from new report."""
    model = {"patterns": {}, "failure_counts": {}, "subsystem_correlations": {}, "total_reports": 0}
    ml_path = _get_ml_model_path()
    if os.path.exists(ml_path):
        try:
            with open(ml_path) as f:
                model = json.load(f)
        except (json.JSONDecodeError, KeyError):
            pass

    model["total_reports"] = model.get("total_reports", 0) + 1

    # Track failure patterns: which TPs fail together
    failed_tps = []
    for pdata in report["phases"].values():
        for tp in pdata.get("failures", []):
            tp_name = tp["tp"]
            failed_tps.append(tp_name)
            model["failure_counts"][tp_name] = model["failure_counts"].get(tp_name, 0) + 1

    # Track co-failure patterns (which TPs fail together)
    if len(failed_tps) > 1:
        pattern_key = "+".join(sorted(failed_tps))
        if "patterns" not in model:
            model["patterns"] = {}
        model["patterns"][pattern_key] = model["patterns"].get(pattern_key, 0) + 1

    # Track subsystem correlations
    for sub in report.get("failed_subsystems", []):
        model["subsystem_correlations"][sub] = model["subsystem_correlations"].get(sub, 0) + 1

    # Track VI findings
    for vi in report.get("visual_inspection", {}).get("findings", []):
        if vi != "No Damage":
            vi_key = f"VI:{vi}"
            model["failure_counts"][vi_key] = model["failure_counts"].get(vi_key, 0) + 1

    with open(_get_ml_model_path(), "w") as f:
        json.dump(model, f, indent=2)


def _get_ml_insights():
    """Get ML-derived insights from accumulated reports."""
    ml_path = _get_ml_model_path()
    if not os.path.exists(ml_path):
        return None
    try:
        with open(ml_path) as f:
            model = json.load(f)
    except (json.JSONDecodeError, KeyError):
        return None
    if model.get("total_reports", 0) < 2:
        return None
    return model


def _render_report_ui(report):
    """Render the Failure Analysis report in the UI."""
    st.markdown("---")
    st.markdown(f'<div style="text-align:center;font-size:1.3em;font-weight:700;color:#e0e0e0;margin:10px 0;">📋 Failure Analysis Report</div>', unsafe_allow_html=True)
    st.markdown(f'<div style="text-align:center;color:#888;margin-bottom:12px;">Report ID: {report["report_id"]}</div>', unsafe_allow_html=True)

    # Header info
    c1, c2, c3, c4 = st.columns(4)
    c1.metric("DUT S/N", report["dut_id"] or "N/A")
    c2.metric("Date", report["test_date"])
    c3.metric("Stage", report["test_stage"])
    c4.metric("Verdict", report["overall_verdict"])

    # Visual Inspection
    vi = report["visual_inspection"]
    vi_text = ", ".join(vi["findings"]) if vi["findings"] else "No Damage"
    st.markdown(f"**Visual Inspection:** {vi_text}")
    if vi["notes"]:
        st.markdown(f"**VI Notes:** {vi['notes']}")

    # Phase-by-phase summary
    st.markdown("##### Phase Summary")
    for pn_str, pdata in report["phases"].items():
        pn = int(pn_str)
        ph = PHASES[pn]
        v = pdata["verdict"]
        ic = "✅" if v == "PASS" else "❌"
        fail_info = ""
        if pdata["failures"]:
            circuits = [f["subsystem"] for f in pdata["failures"]]
            fail_info = f' — Investigate: **{", ".join(circuits)}**'
        st.markdown(f"{ic} **Phase {pn}: {ph['name']}** → {v}{fail_info}")

    # Risk Analysis Table
    if report["dfmea_entries"]:
        st.markdown("##### Risk Analysis")
        dfmea_rows = ""
        for e in report["dfmea_entries"]:
            dfmea_rows += (f'<tr><td>{e["item"]}</td><td>{e["function"]}</td>'
                           f'<td>{e["potential_failure_mode"]}</td><td>{e["potential_cause"]}</td>'
                           f'<td style="text-align:center">{e["severity"]}</td>'
                           f'<td style="text-align:center">{e["occurrence"]}</td>'
                           f'<td style="text-align:center">{e["detection"]}</td>'
                           f'<td style="text-align:center;font-weight:bold;color:#e74c3c">{e["rpn"]}</td>'
                           f'<td>{e["recommended_action"][:60]}...</td></tr>')
        st.markdown(f'<table class="st"><thead><tr><th>TP</th><th>Function</th><th>Failure Mode</th>'
                    f'<th>Potential Cause</th><th>S</th><th>O</th><th>D</th><th>RPN</th>'
                    f'<th>Action</th></tr></thead><tbody>{dfmea_rows}</tbody></table>', unsafe_allow_html=True)

    # Root causes
    if report["root_causes"]:
        st.markdown("##### Root Cause Summary")
        for rc in report["root_causes"]:
            st.error(f"🔍 {rc}")

    # ML Insights
    ml = _get_ml_insights()
    if ml:
        st.markdown("##### 🤖 ML Pattern Insights")
        st.markdown(f'<span style="color:#888;">Based on {ml["total_reports"]} historical reports</span>', unsafe_allow_html=True)
        # Top failing TPs
        if ml.get("failure_counts"):
            sorted_fails = sorted(ml["failure_counts"].items(), key=lambda x: x[1], reverse=True)[:5]
            for tp_name, count in sorted_fails:
                pct = (count / ml["total_reports"]) * 100
                st.markdown(f"- **{tp_name}**: failed in {count}/{ml['total_reports']} reports ({pct:.0f}%)")
        # Co-failure patterns
        if ml.get("patterns"):
            sorted_patterns = sorted(ml["patterns"].items(), key=lambda x: x[1], reverse=True)[:3]
            if sorted_patterns:
                st.markdown("**Common co-failure patterns:**")
                for pattern, count in sorted_patterns:
                    st.markdown(f"- {pattern.replace('+', ' + ')} → {count} occurrences")

    # Download
    report_json = json.dumps(report, indent=2)
    st.download_button("📥 Download FA Report (JSON)", data=report_json,
                       file_name=f"{report['report_id']}.json", mime="application/json", use_container_width=True)
    # CSV version
    if report["dfmea_entries"]:
        df = pd.DataFrame(report["dfmea_entries"])
        st.download_button("📥 Download FA Table (CSV)", data=df.to_csv(index=False),
                           file_name=f"{report['report_id']}_dfmea.csv", mime="text/csv", use_container_width=True)


def render_debugger_ui():
    st.markdown(CSS, unsafe_allow_html=True)
    prog = get_selected_program() or "PCB"
    st.markdown(
        f'<div style="text-align:center;font-size:1.7em;font-weight:700;margin-bottom:4px;'
        f'background:linear-gradient(100deg,#A78BFA 0%,#E879F9 55%,#34D399 100%);'
        f'-webkit-background-clip:text;background-clip:text;-webkit-text-fill-color:transparent;">'
        f'{prog} PCB Interactive Debugger</div>',
        unsafe_allow_html=True,
    )
    st.markdown('<div style="text-align:center;color:#888;margin-bottom:16px;">Step-by-step fault isolation — KGU spec vs DUT measurement</div>', unsafe_allow_html=True)

    if "debugger_dut_id" not in st.session_state:
        st.session_state.debugger_dut_id = ""
    if "debugger_readings" not in st.session_state:
        st.session_state.debugger_readings = {}
    if "debugger_test_date" not in st.session_state:
        st.session_state.debugger_test_date = date.today()
    if "debugger_test_stage" not in st.session_state:
        st.session_state.debugger_test_stage = "U-Boot (Power-On)"

    c1, c2, c3 = st.columns([2, 2, 2])
    with c1:
        did = st.text_input("DUT Serial / ID", value=st.session_state.debugger_dut_id, placeholder="e.g. SNB-2026-00142")
        st.session_state.debugger_dut_id = did
    with c2:
        td = st.date_input("Test Date", value=st.session_state.debugger_test_date)
        st.session_state.debugger_test_date = td
    with c3:
        ts = st.selectbox("Test Stage", ["U-Boot (Power-On)", "QSDK (Full OS)", "Custom"])
        st.session_state.debugger_test_stage = ts

    # Phase status bar — always visible at top
    _render_phase_status_bar(st.session_state.debugger_readings)

    # Board reference map toggle
    with st.expander("📍 PCB Test Point Reference Map (click to expand)", expanded=False):
        _render_board_map()

    st.markdown("---")

    # Visual Inspection — always shown before phases
    _render_visual_inspection()

    st.markdown("---")
    mode = st.radio("Debug Mode", ["Guided (Phase-by-Phase)", "Quick Scan (All Rails)", "Deep Dive (Single Group)"], horizontal=True)

    if mode == "Guided (Phase-by-Phase)":
        opts = [f"{PHASES[k]['icon']} Phase {k}: {PHASES[k]['name']}" for k in sorted(PHASES)]
        si = st.selectbox("Select Phase (work top to bottom)", range(len(opts)), format_func=lambda i: opts[i])
        pn = si + 1
        ph = PHASES[pn]
        cc = " ph-c" if ph["critical"] else ""
        ct = " ⚠️ CRITICAL" if ph["critical"] else ""
        # LED: blue while entering data (pre-analysis)
        st.markdown(f'<div class="ph{cc}"><span class="led led-blue"></span>{ph["icon"]} Phase {pn}: {ph["name"]}{ct}<br><span style="font-size:.85em;font-weight:400;color:#aaa;">{ph["desc"]}</span></div>', unsafe_allow_html=True)
        ptps = {k: v for k, v in TEST_POINTS.items() if v["phase"] == pn}
        if not ptps:
            st.info("No test points for this phase.")
            return
        rd = {}
        st.markdown("##### Enter DUT Measurements")
        for k, tp in ptps.items():
            n = str(tp["nom"]) if tp["nom"] is not None else "N/A"
            lb = f'Step {tp["step"]}  ➜  {tp["tp"]} — {tp["name"]}  |  LSL: {tp["lsl"]}  |  Nom: {n}  |  USL: {tp["usl"]} {tp["unit"]}'
            sv = st.session_state.debugger_readings.get(k, "")
            val = st.text_input(lb, value=sv, key=f"g_{k}", placeholder=f'📍 {tp["loc"]}', help=f'Board location: {tp["loc"]}')
            if val:
                rd[k] = val
                st.session_state.debugger_readings[k] = val
        if st.button("Analyze Phase", type="primary", use_container_width=True):
            _phase_results(ptps, rd, pn)

        # Report generation button (available after any data entry)
        st.markdown("---")
        if st.button("📋 Generate Full FA Report", use_container_width=True):
            report = _generate_dfmea_report(
                st.session_state.debugger_readings, did, td, ts,
                st.session_state.get("vi_findings", []),
                st.session_state.get("vi_notes", ""))
            _render_report_ui(report)

    elif mode == "Quick Scan (All Rails)":
        st.markdown("##### Enter all DUT measurements (leave blank to skip)")
        rd = {}
        for pn in sorted(PHASES):
            ph = PHASES[pn]
            ptps = {k: v for k, v in TEST_POINTS.items() if v["phase"] == pn}
            if not ptps: continue
            cc = " ph-c" if ph["critical"] else ""
            st.markdown(f'<div class="ph{cc}">{ph["icon"]} Phase {pn}: {ph["name"]}</div>', unsafe_allow_html=True)
            cols = st.columns(min(len(ptps), 3))
            for i, (k, tp) in enumerate(ptps.items()):
                with cols[i % len(cols)]:
                    n = str(tp["nom"]) if tp["nom"] is not None else "N/A"
                    sv = st.session_state.debugger_readings.get(k, "")
                    val = st.text_input(f'#{tp["step"]} {tp["tp"]}: {tp["name"]}', value=sv, key=f"q_{k}",
                                        placeholder=f'{tp["lsl"]}-{tp["usl"]} {tp["unit"]} (nom {n})',
                                        help=f'📍 {tp["loc"]} | LSL={tp["lsl"]} | Nom={n} | USL={tp["usl"]} {tp["unit"]}')
                    if val:
                        rd[k] = val
                        st.session_state.debugger_readings[k] = val
        col1, col2 = st.columns(2)
        with col1:
            if st.button("Analyze All Rails", type="primary", use_container_width=True):
                _full_summary(rd)
        with col2:
            if st.button("📋 Generate Full FA Report", use_container_width=True):
                report = _generate_dfmea_report(
                    st.session_state.debugger_readings, did, td, ts,
                    st.session_state.get("vi_findings", []),
                    st.session_state.get("vi_notes", ""))
                _render_report_ui(report)

    else:  # Deep Dive
        groups = list(FAULT_TREES.keys())
        sg = st.selectbox("Select Subsystem to Deep Dive", groups)
        tree = FAULT_TREES[sg]
        st.markdown(f'<div class="ph">{tree["title"]}</div>', unsafe_allow_html=True)
        gtps = {k: v for k, v in TEST_POINTS.items() if v["group"] == sg or v["group"].startswith(sg.split(" ")[0])}
        if gtps:
            st.markdown("##### Relevant Test Points")
            rd = {}
            cols = st.columns(min(len(gtps), 3))
            for i, (k, tp) in enumerate(gtps.items()):
                with cols[i % len(cols)]:
                    sv = st.session_state.debugger_readings.get(k, "")
                    val = st.text_input(f'#{tp["step"]} {tp["tp"]}: {tp["name"]}', value=sv, key=f"d_{k}",
                                        placeholder=f'{tp["lsl"]}-{tp["usl"]} {tp["unit"]}',
                                        help=f'📍 {tp["loc"]}')
                    if val:
                        rd[k] = val
                        st.session_state.debugger_readings[k] = val
            if st.button("Analyze", type="primary", use_container_width=True):
                for k, tp in gtps.items():
                    val = rd.get(k)
                    s, m = evaluate(val, tp)
                    st.markdown(_tp_row(tp, val, s, m), unsafe_allow_html=True)
                    if s == "fail":
                        st.error(f"**{tp['tp']} FAIL:** {tp['fail_action']}")
                        _render_schematic_lookup(tp["tp"])
        st.markdown("##### Fault Isolation Steps")
        sh = "".join(f"<li>{s[3:]}</li>" for s in tree["steps"])
        st.markdown(f'<div class="dd"><ol>{sh}</ol></div>', unsafe_allow_html=True)
