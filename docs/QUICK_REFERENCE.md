# Quick Reference Guide - Triage Assistant

## Start the Application
```bash
python3 -m streamlit run failure_analysis_app.py
```

## Important Terminology

### DAA vs DOA
- **DAA (Dead After Arrival)**: Unit failed AFTER initial operation/use
  - Field failures, wear-out, environmental damage
  - Focus: eMMC, capacitors, solder joints, thermal cycling

- **DOA (Dead On Arrival)**: Unit NEVER worked from factory
  - Manufacturing defects, QC escapes, shipping damage
  - Focus: Factory testing, QC records, RMA process

## Top Hardware Failure Modes (by RPN)

| Rank | Failure Mode | RPN | Risk | Key Indicators |
|------|-------------|-----|------|----------------|
| 1 | Solder Joint Failure | 216 | 🔴 High | Intermittent, thermal cycling |
| 2 | eMMC Corruption | 128 | 🟡 Medium | Boot failure, firmware issues |
| 3 | Thermal Management | 120 | 🟡 Medium | Overheating, shutdowns |
| 4 | Connector Corrosion | 120 | 🟡 Medium | Intermittent, oxidation |
| 5 | Capacitor Failure | 105 | 🟡 Medium | Bulging, leaking, ESR high |

## New Features

### 1. DFMEA Analysis
- Risk Priority Number (RPN) = Severity × Occurrence × Detection
- Color-coded risk levels: 🔴 High (≥150) | 🟡 Medium (100-149) | 🟢 Low (<100)
- Interactive failure mode database with 15 modes

### 2. "Won't Do" Filtering
- Dashboard automatically excludes "Won't do" cases
- Cleaner statistics and visualizations
- Better ML model training
- Focus on actionable failures

### 3. Observed Failure Modes
- Real-time analysis of historical data
- Top 10 failure modes chart
- SW vs HW breakdown
- Trend visualization

## Hardware-Specific Diagnostics

### Capacitor Failure
```
Symptoms: Bulging, leaking, burst, power instability
Tests:
- Visual inspection for physical damage
- ESR measurement (should be <1Ω)
- Capacitance test (±20% tolerance)
- Ripple voltage check
- Thermal imaging
Cause: Temperature >85°C, electrolyte dry-out
```

### Solder Joint Failure
```
Symptoms: Intermittent connection, cold boot issues
Tests:
- X-ray inspection
- Thermal cycling test (-40°F to 131°F)
- Visual inspection under magnification
- CTE mismatch analysis
Cause: Thermal cycling fatigue, outdoor temperature extremes
```

### eMMC Corruption
```
Symptoms: Boot failure, firmware corruption, DAA
Tests:
- UART console boot logs
- Bad block scan
- ECC error count
- Wear leveling metrics
Cause: Power loss during write, temperature extremes
```

### Connector Corrosion
```
Symptoms: Intermittent connection, high resistance
Tests:
- Visual inspection
- Contact resistance measurement
- Corrosion analysis
Cause: Moisture, galvanic corrosion, poor sealing
```

## Known JIRA Issues

| JIRA | Issue | Resolution |
|------|-------|------------|
| CONN-45729 | Cloud key mismatch | Re-provision keys |
| INCIDENT-754 | Related to CONN-45729 | Same as above |
| CONN-47911 | Poor throughput | Firmware update |
| LUX-10203 | Mounting bracket force | New fixture |
| LUX-10289 | eMMC corruption | Firmware reload |
| LUX-10613 | EIPD/EOS | Unit replacement |
| SAFETY-125 | Exothermic event | Lab analysis |

## Product Specs (Snowbird)
- **WiFi:** WiFi 7, 2x2 MIMO, up to 2.1 Gbps
- **Power:** PoE+ (802.3at), 30W
- **Rating:** IP66, -40°F to 131°F
- **Coverage:** ~15,000 sq ft outdoor
- **Storage:** eMMC flash memory

## Triage Priority Levels

### Critical 🔴
- Fire, smoke, exothermic events
- Safety hazards
- File SAFETY ticket immediately

### High 🟠
- Widespread impact
- Known critical bugs
- Multiple unit failures

### Medium 🟡
- DAA, not working
- Standard failures
- Single unit issues

### Low 🟢
- Performance issues
- Cosmetic problems
- User error

## Quick Diagnostic Steps

### 1. Power Issues
```
1. Verify PoE+ (30W, 802.3at)
2. Measure voltage: 48-57V DC
3. Test with Goldfinch adapter
4. Check cable: Cat5e/Cat6, <100m
```

### 2. Cloud Registration
```
1. Check LED: Flashing blue?
2. Search JIRA: CONN-45729
3. Verify cloud keys
4. Re-provision if needed
```

### 3. Performance
```
1. Run iperf3 test
2. Compare to KGU
3. Check spectrum (2.4/5 GHz)
4. Measure RSSI/SNR
```

### 4. Physical Damage
```
1. Inspect M22 gland seal
2. Check for corrosion
3. Verify orientation
4. FTIR if liquid suspected
```

## Search Examples

### Find eMMC Issues
```
Keywords: eMMC, memory, corruption
Results: All memory-related cases with JIRA tickets
```

### Find Liquid Ingress
```
Keywords: liquid, ingress, water
Results: All water damage cases with resolutions
```

### Find Power Issues
```
Keywords: PoE, power, voltage, DAA
Results: All power-related failures
```

### Find Specific JIRA
```
Keywords: CONN-45729
Results: All cases related to this bug
```

## Technical Terminology

- **DAA:** Dead After Arrival
- **EIPD:** Electrically Induced Physical Damage
- **EOS:** Electrical Overstress
- **eMMC:** Embedded flash storage
- **PoE+:** Power over Ethernet Plus (30W)
- **FTIR:** Infrared spectroscopy for contamination
- **KGU:** Known Good Unit (baseline)
- **M22:** Waterproof cable gland

## Tips for Best Results

1. **Be specific:** "Flashing blue LED" not "LED issue"
2. **Include details:** Power source, temperature, environment
3. **Search first:** Use keyword search before manual analysis
4. **Check JIRA:** Known bugs may have quick fixes
5. **Document:** Photos, measurements, test results
6. **Compare:** Always compare to KGU baseline

## Contact & Escalation

- **EFFA tickets:** Field failure analysis
- **SAFETY tickets:** Critical safety issues
- **LUX tickets:** Manufacturing/CM issues
- **Lab analysis:** For complex hardware failures
