# SNOWBIRD HARDWARE DEBUG BIBLE
## eero Outdoor 7 Complete Schematic Analysis and Failure Mode Handbook
Version 1.0 | March 9, 2026 | Schematic v.1 (2023-05-16)
SoC: Qualcomm Miami IPQ5332 | WiFi: Qualcomm Waikiki QCN9274

---

## 1. SYSTEM ARCHITECTURE

### Key Components

| Component | Part Number | Function |
|-----------|-------------|----------|
| Main SoC | Qualcomm IPQ5332 (Miami) | WiFi 7 SoC with 2.4G IPA |
| WiFi 7 Radio | Qualcomm QCN9274 (Waikiki) | 5GHz radio, 2x2 MIMO |
| Ethernet PHY | Qualcomm QCA8081 (Napa) | 2.5GBASE-T PHY |
| eMMC | JSC KLMBG1GELM-B04Q009 | 4GB flash storage |
| DDR4 | Nanya NT5AD512M16C4-JRI | 512MB x16 SDRAM |
| PoE PD | MPS MPM3690GQJ-Z | PoE controller 37-57V to 5V |
| BLE/Thread | Qorvo QPG7015M | BLE/Zigbee/Thread radio |
| 5G FEM x2 | Skyworks SKY85500-11 | 5GHz front end module |
| LED Driver | KTD2027B | RGB+White LED (I2C) |
| USB-CC | FUSB15201MX | USB-C CC controller |
| Crossbar | TS3USB3200RSVR | USB/UART mux |
| Temp Sensor | TI TMP709AIDBVR | Thermal switch 100C |
| SPBM | Dialog SLG4R44724TR | Power/boot manager |
| 2.4G SAW x2 | Murata SAFFB2G49MN0F0A | 2.4GHz band filter |
| 5G BPF x2 | ACX DF1508-R5R5NAB | 5GHz bandpass filter |
| Diplexer x2 | ACX DF1505-R3R5NAB | 2.4G/5G combiner |

Specs: IP66, -40F to 131F, PoE+ 802.3at, 2.5GbE, WiFi 7 2x2 MIMO, ~15000 sq ft coverage

### System Block Diagram

```
                    PoE+ Input (37-57V)
                         │
                    ┌────┴────┐
                    │ MPM3690 │ PoE PD Controller
                    │ GQJ-Z   │ 37-57V → 5V/6A
                    └────┬────┘
                         │ 5V Rail
              ┌──────────┼──────────────┐
              │          │              │
         ┌────┴───┐ ┌───┴────┐   ┌─────┴─────┐
         │ DC/DC  │ │ DC/DC  │   │  DC/DC    │
         │ 0.9V   │ │ 1.8V   │   │  3.3V     │
         └───┬────┘ └───┬────┘   └─────┬─────┘
             │          │              │
    ┌────────┴──┐   ┌───┴───┐    ┌────┴────┐
    │  Miami    │   │ DDR4  │    │ Waikiki │
    │ IPQ5332   │◄──┤ SDRAM │    │QCN9274  │
    │ (SoC)    │   └───────┘    │(WiFi 7) │
    └──┬──┬──┬─┘                └──┬───┬──┘
       │  │  │                     │   │
       │  │  └──► eMMC 4GB        │   └──► 5G FEM x2 (SKY85500)
       │  │                       │
       │  └──► Napa QCA8081       └──► 2.4G SAW + Diplexer
       │       (2.5GbE PHY)
       │
       ├──► QPG7015M (BLE/Thread)
       ├──► KTD2027B (LED Driver)
       └──► FUSB15201MX (USB-C CC)
```

### Signal Flow Summary

```
Internet ──► RJ45 ──► Napa PHY ──► SGMII ──► Miami SoC ──► PCIe ──► Waikiki
                                                │                      │
                                                ├── USB ──► BLE        ├── 5G FEM x2
                                                ├── I2C ──► LED        └── 5G BPF x2
                                                ├── SPI ──► eMMC
                                                └── DDR4 bus ──► SDRAM
```


---

## 2. POWER TREE AND SEQUENCING

### Complete Power Hierarchy

```
PoE+ Input (37-57V DC from Goldfinch PSU)
│
├── MPM3690GQJ-Z PoE PD Controller
│   └── 5V / 6A (30W max) ── Main System Rail
│       │
│       ├── Buck 1: 0.9V / 8A ── VCC_CX (Miami Core)
│       │   └── 700KHz switching, dynamic voltage scaling
│       │   └── MOST CRITICAL RAIL - SoC will not boot without it
│       │
│       ├── Buck 2: 1.8V / 2A ── SHARED RAIL
│       │   ├── Waikiki Analog (QCN9274 VDDA)
│       │   └── Napa PHY I/O (QCA8081)
│       │   └── WARNING: Single point of failure kills WiFi + Ethernet
│       │
│       ├── Buck 3: 1.2V / 2A ── VDD_DDR (DDR4 SDRAM)
│       │   └── Must be stable before Miami releases DDR reset
│       │
│       ├── Buck 4: 2.5V / 0.6A ── VPP (DDR4 Pump)
│       │   └── Required for DDR4 activation word line voltage
│       │
│       ├── Buck 5: 1.05V / 2A ── Napa Core (QCA8081)
│       │   └── Ethernet PHY digital core
│       │
│       ├── Buck 6: 3.3V / 3A ── Waikiki Main (QCN9274)
│       │   └── Digital I/O and PCIe interface
│       │
│       ├── Buck 7: 3.3V / 2A ── 2.4G IPA Supply
│       │   └── Miami internal 2.4GHz power amplifier
│       │
│       └── Buck 8: 4.2V / 2A ── 5G PA Supply
│           └── HIGHEST VOLTAGE RAIL - 8.4W in FEMs
│           └── Feeds SKY85500-11 front end modules
│
└── TMP709AIDBVR Thermal Switch
    └── Trips at 100°C, only 45°C headroom at max ambient (55°C)
```

### Boot Sequence (Power-On Timing)

| Step | Event | Rail/Signal | Timing | Notes |
|------|-------|-------------|--------|-------|
| 1 | PoE handshake | 37-57V input | T=0 | 802.3at classification |
| 2 | 5V rail stable | MPM3690 output | T+50ms | Main bus established |
| 3 | 0.9V VCC_CX | Miami core | T+55ms | SoC core power |
| 4 | 1.2V VDD_DDR | DDR4 supply | T+60ms | Memory power |
| 5 | 2.5V VPP | DDR4 pump | T+62ms | After VDD_DDR stable |
| 6 | 1.8V shared | Waikiki+Napa | T+65ms | Analog/IO power |
| 7 | SPBM release | SLG4R44724TR | T+100ms | Boot config loaded |
| 8 | Miami PBL | ROM bootloader | T+150ms | Primary boot loader |
| 9 | Miami SBL | eMMC read | T+300ms | Secondary boot loader |
| 10 | Linux kernel | DDR4 init | T+2s | OS boot begins |
| 11 | 3.3V Waikiki | QCN9274 power | T+3s | WiFi radio power |
| 12 | 4.2V 5G PA | FEM power | T+3.5s | RF amplifiers on |
| 13 | PCIe link | Miami↔Waikiki | T+4s | WiFi data path |
| 14 | Napa link | SGMII active | T+5s | Ethernet ready |
| 15 | LED solid white | KTD2027B | T+30s | Normal operation |

### Miami SoC Boot Configuration (SPBM)

The SLG4R44724TR (SPBM) controls Miami's boot mode via GPIO strapping:

| GPIO | Function | Default | Notes |
|------|----------|---------|-------|
| GPIO0 | BOOT_SELECT[0] | 0 | eMMC boot (00) |
| GPIO1 | BOOT_SELECT[1] | 0 | NAND=01, USB=10 |
| GPIO2 | JTAG_ENABLE | 0 | Debug access |
| GPIO3 | UART_ENABLE | 1 | Console output |
| GPIO20 | eMMC_RST_N | DNI | 0-ohm NOT installed |
| GPIO44 | FORCE_USB_BOOT | 0 | Emergency recovery |

**CRITICAL**: eMMC RST_N (GPIO20) has a 0-ohm resistor that is DNI (Do Not Install). This means there is NO active eMMC hardware reset capability. If eMMC enters a locked state, only power cycling can attempt recovery.

---

## 3. PoE INPUT STAGE

### Circuit Description

The MPM3690GQJ-Z is a fully integrated PoE PD (Powered Device) controller that converts the 37-57V DC from the Ethernet cable to the 5V system bus.

```
RJ45 ──► PoE Magnetics ──► Bridge Rectifier ──► MPM3690GQJ-Z ──► 5V/6A
                                                      │
                                                      ├── PGOOD signal → SPBM
                                                      ├── Classification resistor (802.3at Class 4)
                                                      └── Thermal pad → PCB ground plane
```

### Key Parameters

| Parameter | Value | Notes |
|-----------|-------|-------|
| Input range | 37-57V DC | PoE+ standard |
| Output | 5V / 6A | 30W max |
| Efficiency | ~90% | At full load |
| Switching freq | 300KHz | Fixed frequency |
| Classification | Class 4 | 25.5W guaranteed |
| Thermal shutdown | 150°C | Internal protection |

### PoE Failure Modes

| Failure | Symptom | Root Cause | Debug Step |
|---------|---------|------------|------------|
| No output | Unit dead | Input diode short, FET failure | Check Vin at bridge output |
| Low output | Brownouts, reboots | Cap degradation, load too high | Measure 5V under load |
| Oscillation | LED flicker | Feedback loop instability | Scope 5V rail for ripple |
| Overtemp | Intermittent shutdowns | Poor thermal pad solder | Thermal image MPM3690 |
| Classification fail | Won't power on | Wrong resistor value | Verify class resistor |

### TMP709 Thermal Protection

The TMP709AIDBVR is a thermal switch (not a sensor) with a fixed 100°C trip point:
- When PCB temperature reaches 100°C, TMP709 output goes LOW
- This signal connects to Miami's thermal interrupt GPIO
- Miami initiates graceful shutdown sequence
- **Design margin**: Max ambient 55°C + 45°C rise = 100°C trip. This is tight.
- At sustained full power (28-33W) in direct sunlight, thermal throttling is expected

---

## 4. SYSTEM POWER RAILS (DC/DC Converters)

### Complete Rail Reference

| Rail | Voltage | Current | Frequency | IC | Load | Purpose |
|------|---------|---------|-----------|-----|------|---------|
| VCC_CX | 0.9V | 8A | 700KHz | Buck 1 | Miami core | SoC digital logic, ARM cores |
| VDD_SHARED | 1.8V | 2A | 1MHz | Buck 2 | Waikiki+Napa | Analog + PHY I/O |
| VDD_DDR | 1.2V | 2A | 1MHz | Buck 3 | DDR4 SDRAM | Memory interface |
| VPP | 2.5V | 0.6A | 1MHz | Buck 4 | DDR4 pump | Word line activation |
| VDD_NAPA | 1.05V | 2A | 1MHz | Buck 5 | Napa core | Ethernet PHY digital |
| VDD_WK | 3.3V | 3A | 700KHz | Buck 6 | Waikiki | WiFi radio digital |
| VDD_2G | 3.3V | 2A | 700KHz | Buck 7 | Miami IPA | 2.4GHz power amp |
| VDD_5G | 4.2V | 2A | 500KHz | Buck 8 | FEMs x2 | 5GHz power amps |

### Power Budget Analysis

| Subsystem | Typical (W) | Max (W) | Notes |
|-----------|-------------|---------|-------|
| Miami SoC | 5.0 | 7.2 | 0.9V × 8A max |
| Waikiki | 4.0 | 5.5 | Core + analog |
| DDR4 | 1.5 | 2.4 | Active + refresh |
| Napa PHY | 1.5 | 2.1 | 2.5GBASE-T |
| 5G FEMs | 6.0 | 8.4 | 4.2V × 2A max |
| 2.4G IPA | 3.0 | 6.6 | 3.3V × 2A max |
| BLE/Thread | 0.3 | 0.5 | Low power |
| LED + misc | 0.2 | 0.3 | I2C peripherals |
| **Total** | **21.5** | **33.0** | PoE budget: 30W |

**WARNING**: Maximum theoretical draw (33W) exceeds PoE+ budget (30W). Thermal throttling and power management are essential. The system relies on Miami's power management to prevent all radios from transmitting at full power simultaneously.

### Rail Failure Impact Matrix

| Failed Rail | Impact | Symptoms |
|-------------|--------|----------|
| 0.9V VCC_CX | Total system failure | Completely dead, no LED |
| 1.8V shared | WiFi + Ethernet dead | LED on but no connectivity |
| 1.2V VDD_DDR | Boot failure | Stuck at bootloader, no Linux |
| 2.5V VPP | DDR4 init failure | Same as VDD_DDR failure |
| 1.05V Napa | No Ethernet | WiFi works, wired dead |
| 3.3V Waikiki | No WiFi | Ethernet works, no wireless |
| 3.3V 2.4G | No 2.4GHz band | 5GHz works, 2.4G dead |
| 4.2V 5G PA | No 5GHz band | 2.4GHz works, 5G dead |


---

## 5. RF POWER RAILS (Waikiki Subsystem)

### Waikiki QCN9274 Power Architecture

The Waikiki WiFi 7 radio requires 7 separate power rails:

| Rail | Voltage | Current | Purpose |
|------|---------|---------|---------|
| WK_VDDCX | 0.92V | 5A | Waikiki digital core (4.6W) |
| WK_VDD18 | 1.8V | shared | Analog (shared with Napa) |
| WK_VDD33 | 3.3V | 3A | Digital I/O, PCIe |
| WK_VDDPA5G | 4.2V | 2A | 5GHz PA supply via FEMs |
| WK_VDDA12 | 1.2V | 0.5A | PLL analog |
| WK_VDDA09 | 0.9V | 0.5A | ADC/DAC analog |
| WK_VDDIO | 1.8V | 0.3A | GPIO level shifters |

### 5GHz RF Signal Path

```
Waikiki QCN9274
    │
    ├── TX Chain 0 ──► SKY85500-11 (FEM 0) ──► DF1508 (BPF) ──► DF1505 (Diplexer) ──► Ant 0
    │                   │                                              │
    │                   ├── PA: +20dBm max                             └── 2.4G path
    │                   ├── LNA: 2.5dB NF
    │                   └── T/R switch
    │
    └── TX Chain 1 ──► SKY85500-11 (FEM 1) ──► DF1508 (BPF) ──► DF1505 (Diplexer) ──► Ant 1
```

### 2.4GHz RF Signal Path

```
Miami IPQ5332 (Internal PA)
    │
    ├── TX/RX 0 ──► SAFFB2G49MN (SAW 0) ──► DF1505 (Diplexer) ──► Ant 0
    │                                              │
    │                                              └── shared with 5G
    │
    └── TX/RX 1 ──► SAFFB2G49MN (SAW 1) ──► DF1505 (Diplexer) ──► Ant 1
```

### RF Component Failure Modes

| Component | Failure Mode | Symptom | Debug |
|-----------|-------------|---------|-------|
| SKY85500 FEM | PA burnout | No 5G TX, RX OK | Measure 4.2V at FEM Vcc |
| SKY85500 FEM | LNA damage | Poor 5G RX sensitivity | Check NF with signal gen |
| SAW filter | Cracked | No 2.4G or shifted passband | Network analyzer sweep |
| Diplexer | Open/short | One band dead | Check insertion loss both bands |
| BPF | Detuned | Poor 5G selectivity | Sweep S21 response |
| RF trace | Impedance break | High VSWR, low power | TDR measurement |
| Antenna connector | Corrosion | Intermittent RF | Visual + contact resistance |

**SAW Filter Note**: The 2.4GHz SAW filters (SAFFB2G49MN0F0A) have a note "wait for mass confirmation" in the schematic. This means the exact part may change between production batches. When debugging 2.4GHz issues, verify the actual SAW filter part number matches the BOM.

---

## 6. MIAMI SoC (IPQ5332) DETAILED ANALYSIS

### Pin Groups and Functions

| Group | Pins | Function | Voltage |
|-------|------|----------|---------|
| ARM Core | VCC_CX | Dual Cortex-A53 @ 1.5GHz | 0.9V |
| DDR4 | DQ[15:0], DQS, DM | 16-bit DDR4 interface | 1.2V |
| eMMC | DAT[7:0], CMD, CLK | 8-bit eMMC 5.1 | 1.8V/3.3V |
| PCIe | TX±, RX± | Gen3 x2 to Waikiki | AC coupled |
| SGMII | TX±, RX± | To Napa PHY | 1.2V swing |
| USB 2.0 | DP, DM | To BLE + USB-C | 3.3V |
| I2C | SDA, SCL | LED driver, sensors | 1.8V |
| SPI | MOSI, MISO, CLK, CS | Boot flash (if used) | 1.8V |
| UART | TX, RX | Debug console | 1.8V |
| GPIO | Multiple | Boot config, interrupts | 1.8V |
| JTAG | TDI, TDO, TMS, TCK | Debug (normally disabled) | 1.8V |

### Miami Boot Sequence Detail

```
Power On
    │
    ▼
PBL (Primary Boot Loader) ── ROM, cannot be modified
    │ Reads boot config from SPBM GPIO strapping
    │ Default: eMMC boot (GPIO0=0, GPIO1=0)
    ▼
SBL (Secondary Boot Loader) ── First 512KB of eMMC
    │ Initializes DDR4 (training sequence)
    │ Loads ATF (ARM Trusted Firmware)
    ▼
ATF ── Secure world setup
    │ TrustZone configuration
    │ PSCI (Power State Coordination Interface)
    ▼
U-Boot ── Bootloader
    │ Hardware init, device tree
    │ Loads kernel from eMMC partition
    ▼
Linux Kernel ── OpenWrt based
    │ Driver initialization
    │ Network stack, WiFi drivers
    ▼
eero Application Layer
    │ Cloud registration
    │ Mesh networking
    └── Normal operation (LED solid white)
```

### Miami Failure Modes

| Failure | Symptom | Likely Cause | Debug Approach |
|---------|---------|-------------|----------------|
| PBL hang | No UART output at all | 0.9V rail failure, SPBM config | Check VCC_CX, SPBM output |
| SBL hang | UART shows "SBL" then stops | eMMC read failure | Check eMMC power, CMD/CLK signals |
| DDR4 init fail | "DDR training failed" on UART | 1.2V/2.5V rail, DDR4 IC | Check VDD_DDR, VPP, DDR4 signals |
| Kernel panic | Boot loop, LED flashing | eMMC corruption, bad FW | UART console, try USB boot recovery |
| PCIe link fail | No WiFi, Ethernet OK | Waikiki power, PCIe signals | Check 3.3V WK, PCIe TX/RX |
| SGMII fail | No Ethernet, WiFi OK | Napa power, SGMII signals | Check 1.05V Napa, SGMII AC coupling |
| Thermal throttle | Slow performance | High ambient, poor cooling | Read thermal sensors via UART |

---

## 7. DDR4 SDRAM SUBSYSTEM

### Circuit Description

The Nanya NT5AD512M16C4-JRI is a 512MB x16 DDR4-3200 SDRAM connected to Miami via a 16-bit bus.

### DDR4 Signal Connections

| Signal Group | Pins | Function | Impedance |
|-------------|------|----------|-----------|
| DQ[15:0] | 16 | Data bus | 40Ω ±10% |
| DQS[1:0]± | 4 | Data strobe (differential) | 40Ω diff |
| DM[1:0] | 2 | Data mask | 40Ω |
| A[15:0] | 16 | Address bus | 40Ω |
| BA[1:0] | 2 | Bank address | 40Ω |
| BG[0] | 1 | Bank group | 40Ω |
| CK± | 2 | Clock (differential) | 40Ω diff |
| CKE | 1 | Clock enable | 40Ω |
| CS_N | 1 | Chip select | 40Ω |
| RAS_N, CAS_N, WE_N | 3 | Command | 40Ω |
| ODT | 1 | On-die termination | 40Ω |
| RESET_N | 1 | DDR4 reset | - |

### DDR4 Power Requirements

| Rail | Voltage | Tolerance | Purpose |
|------|---------|-----------|---------|
| VDD_DDR | 1.2V | ±60mV (5%) | Core power |
| VPP | 2.5V | ±125mV (5%) | Word line pump |
| VREF_DQ | 0.6V | ±3% | Data reference (VDD/2) |
| VTT | 0.6V | ±40mV | Termination (VDD/2) |

### DDR4 Failure Modes

| Failure | Symptom | Root Cause | Debug |
|---------|---------|------------|-------|
| Training fail | No boot, UART shows DDR error | VDD_DDR noise, BGA solder | Scope VDD_DDR ripple, check BGA |
| Bit errors | Random crashes, data corruption | Signal integrity, crosstalk | Eye diagram on DQ lines |
| Refresh fail | Crashes after minutes of operation | VPP low, temperature | Check VPP, ambient temp |
| BGA crack | Intermittent boot failures | Thermal cycling, CTE mismatch | X-ray BGA, thermal cycle test |
| VREF drift | Marginal operation, random errors | Resistor divider drift | Measure VREF_DQ accuracy |

**RPN Note**: DDR4 BGA solder joint failure has RPN=162 (S=9, O=6, D=3) due to thermal cycling in outdoor environment. This is the 3rd highest risk component.

---

## 8. eMMC FLASH STORAGE

### Circuit Description

The JSC KLMBG1GELM-B04Q009 is a 4GB eMMC 5.1 device providing boot storage and firmware.

### eMMC Interface

| Signal | Function | Notes |
|--------|----------|-------|
| DAT[7:0] | 8-bit data bus | HS400 capable |
| CMD | Command/response | Bidirectional |
| CLK | Clock | Up to 200MHz |
| DS | Data strobe | HS400 mode |
| RST_N | Hardware reset | **DNI - NOT CONNECTED** |
| VCCQ | I/O voltage | 1.8V (HS200/HS400) |
| VCC | Core voltage | 3.3V |

### eMMC Partition Layout (Typical eero)

| Partition | Size | Content |
|-----------|------|---------|
| Boot0 | 4MB | SBL (Secondary Boot Loader) |
| Boot1 | 4MB | SBL backup |
| RPMB | 4MB | Replay Protected Memory Block (keys) |
| User Area | ~3.7GB | Kernel, rootfs, config, logs |

### eMMC Failure Modes

| Failure | Symptom | Root Cause | Debug |
|---------|---------|------------|-------|
| Boot0 corruption | No boot after PBL | Power loss during FW update | Try Boot1, USB recovery |
| Bad blocks | Random read errors | Flash wear, ECC exhaustion | eMMC health via UART |
| CMD timeout | Boot hangs at SBL | CMD line integrity, power | Scope CMD/CLK signals |
| Write protect | Can't update firmware | Unexpected WP bit set | Check WP status register |
| Locked state | eMMC unresponsive | Password lock, error state | Power cycle (no RST_N!) |
| Wear-out | Increasing errors over time | Write amplification | Check eMMC life estimate |

**CRITICAL DESIGN ISSUE**: The eMMC RST_N pin is connected through a 0-ohm resistor (R_xxx) that is DNI (Do Not Install). This means:
- There is NO hardware reset for the eMMC
- If eMMC enters an error state, only full power cycle can attempt recovery
- If eMMC firmware locks up, the device may become permanently unbootable
- This is a known design trade-off (GPIO20 was needed for other function)


---

## 9. USB AND PCIe INTERFACES

### USB 2.0 Subsystem

Miami provides one USB 2.0 port that is multiplexed between two functions:

```
Miami USB 2.0
    │
    ▼
TS3USB3200RSVR (Crossbar Switch)
    │
    ├── Path A: QPG7015M (BLE/Thread Radio)
    │   └── Normal operation path
    │
    └── Path B: USB-C Connector
        └── FUSB15201MX (CC Controller)
        └── Debug/recovery path
```

The TS3USB3200RSVR crossbar switch selects between BLE radio and USB-C based on a GPIO control signal from Miami. During normal operation, USB is routed to BLE. During debug/recovery, USB can be switched to the USB-C port.

### USB-C Debug Port

| Pin | Function | Notes |
|-----|----------|-------|
| CC1/CC2 | Configuration Channel | FUSB15201MX manages |
| D+/D- | USB 2.0 data | Via crossbar switch |
| VBUS | 5V power | Can power device for debug |
| SBU1/SBU2 | UART TX/RX | Debug console alternate |

**USB Boot Recovery**: If eMMC is corrupted, Miami can boot from USB by setting GPIO44 (FORCE_USB_BOOT) high. This requires physical access to the debug header or USB-C connection with proper firmware image.

### PCIe Gen3 x2 (Miami ↔ Waikiki)

```
Miami IPQ5332                    Waikiki QCN9274
    │                                │
    ├── PCIe TX0± ──── AC caps ────► PCIe RX0±
    ├── PCIe TX1± ──── AC caps ────► PCIe RX1±
    ├── PCIe RX0± ◄── AC caps ────── PCIe TX0±
    ├── PCIe RX1± ◄── AC caps ────── PCIe TX1±
    ├── PERST_N ──────────────────► RESET
    └── CLKREQ_N ◄────────────────── CLKREQ
```

| Parameter | Value | Notes |
|-----------|-------|-------|
| Generation | Gen3 | 8GT/s per lane |
| Lanes | x2 | 16GT/s aggregate |
| Bandwidth | ~2GB/s | Sufficient for WiFi 7 |
| AC coupling | 100nF | Series caps on each lane |
| Impedance | 85Ω diff | PCB controlled impedance |

### PCIe Failure Modes

| Failure | Symptom | Root Cause | Debug |
|---------|---------|------------|-------|
| Link down | No WiFi at all | Waikiki power, AC caps | Check 3.3V WK, PERST_N |
| Link degraded | x1 instead of x2 | One lane damaged | PCIe link status register |
| CRC errors | WiFi drops/stutters | Signal integrity | Eye diagram on PCIe lanes |
| PERST stuck | Waikiki won't init | GPIO driver, pull-up | Scope PERST_N timing |

---

## 10. ETHERNET PHY (Napa QCA8081)

### Circuit Description

The QCA8081 (Napa) is a 2.5GBASE-T Ethernet PHY connecting the RJ45 port to Miami via SGMII+.

```
RJ45 Connector
    │
    ▼
Magnetics (Bob Smith termination)
    │
    ├── MDI pair 0 (pins 1,2) ──► Napa TXP/TXN_A
    ├── MDI pair 1 (pins 3,6) ──► Napa TXP/TXN_B
    ├── MDI pair 2 (pins 4,5) ──► Napa TXP/TXN_C
    └── MDI pair 3 (pins 7,8) ──► Napa TXP/TXN_D
                                      │
                                      ▼
                                  QCA8081 (Napa)
                                      │
                                      ├── SGMII+ TX± ──► Miami
                                      ├── SGMII+ RX± ◄── Miami
                                      ├── MDIO ◄──────── Miami (management)
                                      └── MDC ◄───────── Miami (management clock)
```

### Napa Power Rails

| Rail | Voltage | Source | Purpose |
|------|---------|--------|---------|
| VDD_CORE | 1.05V | Buck 5 | Digital core |
| VDD_IO | 1.8V | Buck 2 (shared) | I/O interface |
| VDD_ANALOG | 1.8V | Buck 2 (shared) | Analog front end |
| VDD_MDI | 3.3V | LDO | MDI driver |

### Ethernet Speed Negotiation

| Speed | Pairs Used | PoE Compatible | Notes |
|-------|-----------|----------------|-------|
| 2.5GBASE-T | 4 pairs | Yes (802.3at) | Full capability |
| 1000BASE-T | 4 pairs | Yes | Fallback |
| 100BASE-TX | 2 pairs | Yes (Alt-A) | Minimum |

### Ethernet Failure Modes

| Failure | Symptom | Root Cause | Debug |
|---------|---------|------------|-------|
| No link | LED off, no Ethernet | Napa power, magnetics | Check 1.05V, 1.8V, magnetics |
| 100M only | Slow speed | Pair damage, cable | Check all 4 pairs, cable quality |
| CRC errors | Packet loss | Magnetics, impedance | Check Bob Smith termination |
| PoE conflict | Intermittent power | PoE + data on same pairs | Verify PoE midspan vs endspan |
| PHY hang | Link up but no data | SGMII link, Napa firmware | MDIO register read, reset PHY |
| Connector corrosion | Intermittent link | Moisture in RJ45 | Visual inspection, contact resistance |

### Bob Smith Termination

The RJ45 magnetics include Bob Smith termination (75Ω to chassis ground via 1000pF cap) for common-mode noise rejection. If these components fail:
- Increased EMI emissions
- Susceptibility to external noise
- Potential PoE classification issues

---

## 11. WAIKIKI WiFi 7 RADIO (QCN9274)

### Architecture Overview

Waikiki is a dedicated 5GHz WiFi 7 radio connected to Miami via PCIe Gen3 x2. It handles all 5GHz transmission and reception.

### Waikiki Interfaces

| Interface | Connection | Purpose |
|-----------|-----------|---------|
| PCIe Gen3 x2 | Miami | Data + control |
| RF TX0/RX0 | FEM 0 (SKY85500) | 5G chain 0 |
| RF TX1/RX1 | FEM 1 (SKY85500) | 5G chain 1 |
| I2C | Temperature sensor | Thermal monitoring |
| GPIO | Miami | Interrupt, control |
| XTAL | 40MHz crystal | Reference clock |

### Waikiki Power Sequencing

| Step | Rail | Voltage | Timing |
|------|------|---------|--------|
| 1 | WK_VDD33 | 3.3V | T+0ms (after Miami boot) |
| 2 | WK_VDDCX | 0.92V | T+5ms |
| 3 | WK_VDD18 | 1.8V | T+10ms (shared rail) |
| 4 | WK_VDDA12 | 1.2V | T+12ms |
| 5 | WK_VDDA09 | 0.9V | T+15ms |
| 6 | PERST_N release | HIGH | T+20ms |
| 7 | PCIe link training | - | T+25ms |
| 8 | FEM power (4.2V) | 4.2V | T+50ms (after PCIe up) |

### Waikiki Failure Modes

| Failure | Symptom | Root Cause | Debug |
|---------|---------|------------|-------|
| No PCIe link | No WiFi | Power sequencing, PERST | Check all WK rails in order |
| TX power low | Poor 5G range | FEM failure, 4.2V low | Measure FEM Vcc, TX power |
| RX sensitivity poor | Weak 5G signal | LNA damage, NF degraded | Check FEM LNA bias |
| Channel failure | Some channels dead | SAW/BPF issue, regulatory | Sweep RF response |
| Thermal throttle | 5G speed drops | High temp, poor cooling | Read Waikiki temp sensor |
| Crystal drift | Connection drops | 40MHz XTAL aging | Measure XTAL frequency |

---

## 12. 5GHz FRONT END MODULES (SKY85500-11)

### Circuit Description

Two SKY85500-11 FEMs provide the 5GHz RF front end. Each FEM contains:
- Power Amplifier (PA): +20dBm max output
- Low Noise Amplifier (LNA): 2.5dB noise figure
- T/R Switch: TX/RX path selection
- Bypass mode: For low-power operation

### FEM Pin Functions

| Pin | Function | Notes |
|-----|----------|-------|
| VCC | 4.2V supply | From Buck 8 |
| RF_IN | TX input from Waikiki | 50Ω match |
| RF_OUT | To BPF/antenna | 50Ω match |
| ANT | Antenna port | Via diplexer |
| CTRL | PA/LNA/Bypass select | From Waikiki GPIO |
| GND | Ground | Thermal pad |

### FEM Power Dissipation

| Mode | Current | Power | Duty Cycle |
|------|---------|-------|------------|
| TX max | 450mA | 1.89W | <50% |
| TX typical | 300mA | 1.26W | ~30% |
| RX (LNA) | 30mA | 126mW | ~60% |
| Bypass | 5mA | 21mW | <10% |
| **Per FEM avg** | ~150mA | ~630mW | Mixed |
| **Both FEMs** | ~300mA | ~1.26W | Mixed |

**Note**: Peak power for both FEMs at max TX is 3.78W from the 4.2V rail alone. Combined with Waikiki core power, the 5GHz subsystem can draw up to 8.4W peak.

### FEM Failure Modes

| Failure | Symptom | Root Cause | Debug |
|---------|---------|------------|-------|
| PA burnout | No 5G TX, RX works | EOS, excessive VSWR | Check 4.2V, measure TX power |
| LNA damage | Poor 5G RX | ESD, lightning nearby | Check RX sensitivity |
| T/R switch stuck | TX or RX only | Control line failure | Check CTRL GPIO from Waikiki |
| Thermal runaway | FEM overheats | Poor thermal pad, high duty | Thermal image FEM area |
| Impedance shift | High VSWR | Solder joint, PCB damage | Network analyzer at FEM port |


---

## 13. BLE/THREAD RADIO (QPG7015M)

### Circuit Description

The Qorvo QPG7015M provides BLE 5.2 and IEEE 802.15.4 (Thread/Zigbee) connectivity for device setup and smart home integration.

### QPG7015M Connections

| Interface | Connection | Purpose |
|-----------|-----------|---------|
| USB 2.0 | Miami (via crossbar) | Data interface |
| RF | PCB antenna | 2.4GHz BLE/Thread |
| GPIO | Miami | Wake, interrupt |
| RESET | Miami GPIO | Hardware reset |

### BLE Failure Modes

| Failure | Symptom | Root Cause | Debug |
|---------|---------|------------|-------|
| No BLE | Can't find in app | USB crossbar, QPG power | Check crossbar select, 3.3V |
| Pairing fail | BLE visible but fails | Firmware, interference | Check BLE RSSI, retry |
| Thread fail | Smart home devices lost | QPG firmware, network | Check Thread network status |
| Range poor | BLE only works close | Antenna, interference | Check BLE TX power setting |

---

## 14. USB-C DEBUG PORT

### Circuit Description

The USB-C port serves dual purpose: debug console access and emergency firmware recovery.

```
USB-C Connector
    │
    ├── CC1/CC2 ──► FUSB15201MX (CC Controller)
    │                   └── Detects cable orientation
    │                   └── Manages power role
    │
    ├── D+/D- ──► TS3USB3200RSVR (Crossbar)
    │                   └── Switched from BLE to USB-C
    │                   └── Miami GPIO controls mux
    │
    └── SBU1/SBU2 ──► UART TX/RX
                        └── Debug console (115200 baud)
                        └── Always available regardless of USB mux
```

### FUSB15201MX Functions

| Function | Description |
|----------|-------------|
| CC detection | Cable plug orientation |
| VBUS control | 5V source/sink negotiation |
| Role detection | DFP/UFP/DRP |
| Power delivery | Basic USB PD (not full PD3.0) |

### Debug Access Procedure

1. Connect USB-C cable to Snowbird debug port
2. UART console available on SBU pins (always active)
3. Use terminal at 115200 baud, 8N1
4. For USB data access, Miami must switch crossbar to USB-C path
5. For USB boot recovery, set GPIO44 high before power-on

---

## 15. LED SUBSYSTEM (KTD2027B)

### Circuit Description

The KTD2027B is an I2C-controlled LED driver providing RGB + White LED indication.

### LED Driver Connections

| Pin | Function | LED Color | I2C Register |
|-----|----------|-----------|-------------|
| OUT1 | LED channel 1 | Red | 0x06 |
| OUT2 | LED channel 2 | Green | 0x07 |
| OUT3 | LED channel 3 | Blue | 0x08 |
| OUT4 | LED channel 4 | White | 0x09 |
| SDA | I2C data | - | Miami I2C bus |
| SCL | I2C clock | - | Miami I2C bus |

### LED Status Codes (eero Specific)

| LED State | Color | Meaning | System State |
|-----------|-------|---------|-------------|
| Solid white | White | Normal operation | Connected, internet OK |
| Blinking white | White | Booting/connecting | Startup or reconnecting |
| Solid blue | Blue | Setup mode | Waiting for app config |
| Blinking blue | Blue | BLE pairing | Ready for app setup |
| Solid green | Green | Optimal | All systems nominal |
| Blinking yellow | R+G | Soft reset / weak link | Reset in progress |
| Solid yellow | R+G | No internet | Upstream connection lost |
| Blinking red | Red | No internet | Check upstream |
| Solid red | Red | Critical error | Hardware/connection failure |
| No light | Off | No power | Power failure or dead unit |

### LED Failure Modes

| Failure | Symptom | Root Cause | Debug |
|---------|---------|------------|-------|
| No LED at all | Dark unit | I2C bus failure, driver dead | Check I2C SDA/SCL, 3.3V |
| Wrong color | Misleading status | I2C register corruption | Read KTD2027B registers |
| Stuck on one color | No status change | Miami I2C driver crash | Check Miami I2C bus activity |
| Dim LED | Hard to see outdoors | LED aging, current limit | Check LED current setting |
| Flickering | Unstable indication | I2C noise, power ripple | Scope I2C bus, check 3.3V |

---

## 16. RJ45 CONNECTOR AND MAGNETICS

### Circuit Description

The RJ45 connector provides both Ethernet data and PoE power input through integrated magnetics.

```
External Cable
    │
    ▼
RJ45 Jack (with integrated magnetics)
    │
    ├── Pairs 1,2 (TX) ──► Magnetics ──► Napa MDI_A
    ├── Pairs 3,6 (RX) ──► Magnetics ──► Napa MDI_B
    ├── Pairs 4,5 (PoE+) ──► Center tap ──► PoE PD (MPM3690)
    ├── Pairs 7,8 (PoE-) ──► Center tap ──► PoE PD (MPM3690)
    │
    └── Shield ──► Chassis GND (via ferrite + cap)
```

### PoE Power Extraction

In 802.3at (PoE+), power is delivered on all 4 pairs:
- Mode A: Power on data pairs (1,2 and 3,6) via center taps
- Mode B: Power on spare pairs (4,5 and 7,8)
- Snowbird supports both modes (auto-detect)

### Connector Failure Modes

| Failure | Symptom | Root Cause | Debug |
|---------|---------|------------|-------|
| Pin corrosion | Intermittent link/power | Moisture ingress at RJ45 | Visual inspection, contact resistance |
| Magnetics open | No Ethernet, PoE OK | Magnetics winding break | Continuity test on magnetics |
| Magnetics short | No Ethernet + PoE issues | Magnetics insulation fail | Isolation test |
| Shield ground break | EMI issues, noise | Ferrite/cap failure | Check shield to ground path |
| Cable strain | Intermittent everything | Physical cable damage | Inspect cable at connector |
| M22 gland leak | Water at connector | Improper installation | Check M22 gland torque |

### M22 Cable Gland

The Ethernet cable enters through an M22 cable gland that provides IP66 sealing:
- Proper torque: 2-3 Nm
- Cable diameter range: 6-12mm
- Must use outdoor-rated Ethernet cable (UV resistant jacket)
- Improper installation is the #1 cause of liquid ingress

---

## 17. CONNECTORS AND MECHANICAL

### Physical Interfaces

| Connector | Type | Purpose | Sealing |
|-----------|------|---------|---------|
| RJ45 | 8P8C with magnetics | Ethernet + PoE | M22 gland |
| USB-C | USB 2.0 + UART | Debug/recovery | Rubber plug |
| Reset button | Momentary switch | Factory reset | Membrane seal |
| Mounting bracket | Stainless steel | Wall/pole mount | N/A |

### Reset Button Circuit

```
3.3V ──► 10KΩ pull-up ──┬──► Miami GPIO (RESET_N)
                         │
                    Reset Button
                         │
                    Discharge Circuit ──► GND
```

**KNOWN ISSUE**: The reset button discharge circuit has a design issue where the discharge triggers at the wrong voltage threshold. This can cause:
- False reset detection during power transients
- Incomplete reset if button is released too quickly
- Recommendation: Hold reset button for >10 seconds for reliable factory reset

### Mechanical Failure Modes

| Failure | Symptom | Root Cause | Debug |
|---------|---------|------------|-------|
| M22 gland loose | Water ingress | Installation error | Check torque, reseal |
| USB-C plug missing | Moisture in port | Lost during debug | Replace rubber plug |
| Reset stuck | Can't factory reset | Corrosion, debris | Clean button mechanism |
| Bracket fatigue | Unit falls | Wind load, vibration | Check bracket + hardware |
| Enclosure crack | IP66 compromised | Impact, UV degradation | Visual inspection |


---

## 18. THERMAL MANAGEMENT

### Thermal Budget

| Source | Typical (W) | Max (W) | Location |
|--------|-------------|---------|----------|
| Miami SoC | 5.0 | 7.2 | Center of PCB |
| Waikiki | 4.0 | 5.5 | Adjacent to Miami |
| FEM 0 | 0.6 | 1.9 | Near antenna 0 |
| FEM 1 | 0.6 | 1.9 | Near antenna 1 |
| Napa PHY | 1.5 | 2.1 | Near RJ45 |
| DC/DC converters | 2.5 | 3.5 | Distributed |
| PoE PD (MPM3690) | 2.5 | 3.3 | Input stage |
| DDR4 | 1.5 | 2.4 | Near Miami |
| Other | 0.8 | 1.2 | Distributed |
| **Total** | **19.0** | **29.0** | - |

### Thermal Path

```
Component die ──► Thermal pad ──► PCB copper ──► Enclosure ──► Ambient air
                                      │
                                      └──► Internal air gap ──► Enclosure
```

The Snowbird uses a sealed enclosure (IP66) with NO active cooling (no fan, no vents). All heat must be conducted through the PCB to the aluminum enclosure and radiated/convected to ambient air.

### Thermal Protection

| Protection | Threshold | Action |
|-----------|-----------|--------|
| TMP709 trip | 100°C PCB | Miami thermal interrupt → graceful shutdown |
| Miami internal | 125°C junction | Hardware thermal throttle |
| Waikiki internal | 110°C junction | TX power reduction |
| PoE PD (MPM3690) | 150°C junction | Output shutdown |

### Thermal Design Margins

| Condition | Ambient | PCB Rise | PCB Temp | Margin to 100°C |
|-----------|---------|----------|----------|-----------------|
| Typical indoor | 25°C | +30°C | 55°C | 45°C |
| Typical outdoor | 35°C | +35°C | 70°C | 30°C |
| Hot outdoor shade | 45°C | +40°C | 85°C | 15°C |
| Hot outdoor sun | 55°C | +45°C | 100°C | **0°C** |
| Extreme | 60°C | +45°C | 105°C | **-5°C TRIP** |

**CRITICAL**: At maximum rated ambient (55°C / 131°F) with full load, the unit operates at the TMP709 trip threshold. Direct sunlight adds additional radiant heating. Thermal throttling is expected in hot climates.

### Thermal Failure Modes

| Failure | Symptom | Root Cause | Debug |
|---------|---------|------------|-------|
| Thermal shutdown | Unit powers off in heat | Ambient + load exceeds 100°C | Check ambient, add shade |
| Thermal throttle | Slow WiFi in afternoon | Temperature-based TX reduction | Read thermal sensors |
| Solder fatigue | Intermittent after years | Daily thermal cycling | X-ray BGA joints |
| Cap dry-out | Power instability | Electrolyte evaporation at temp | ESR test on caps |
| Enclosure warp | IP66 seal failure | Thermal expansion mismatch | Visual inspection |

---

## 19. POWER SEQUENCING MANAGER (SPBM)

### SLG4R44724TR (Dialog SPBM)

The SPBM (Smart Power and Boot Manager) controls the power-on sequence and Miami boot configuration.

### SPBM Functions

| Function | Description |
|----------|-------------|
| Power sequencing | Controls enable pins of all DC/DC converters |
| Boot strapping | Sets Miami GPIO configuration at reset |
| Voltage monitoring | Monitors PGOOD from each converter |
| Reset generation | Generates system reset after all rails stable |
| Watchdog | Optional watchdog timer for Miami |

### SPBM Power Sequence

```
PoE PGOOD ──► SPBM
                │
                ├── T+0ms: Enable 0.9V (VCC_CX)
                ├── T+5ms: Enable 1.2V (VDD_DDR)
                ├── T+7ms: Enable 2.5V (VPP)
                ├── T+10ms: Enable 1.8V (shared)
                ├── T+15ms: Enable 1.05V (Napa)
                ├── T+20ms: All PGOOD verified
                ├── T+25ms: Set boot strapping GPIOs
                └── T+30ms: Release Miami RESET_N
                                │
                                ▼
                          Miami PBL starts
```

### SPBM Failure Modes

| Failure | Symptom | Root Cause | Debug |
|---------|---------|------------|-------|
| No sequence start | All dead despite 5V OK | SPBM failure, no PoE PGOOD | Check SPBM Vcc, PGOOD input |
| Partial sequence | Some rails up, others not | SPBM output stuck | Measure each rail enable pin |
| Wrong boot config | Miami boots wrong mode | SPBM GPIO output error | Check boot strap GPIOs |
| Reset stuck low | Miami never starts | PGOOD not achieved | Check all converter PGOOD |
| Watchdog reset | Unexpected reboots | Miami hang, WDT timeout | Check WDT configuration |

---

## 20. FAILURE MODE AND EFFECTS ANALYSIS (DFMEA)

### Complete FMEA Table

Sorted by RPN (Risk Priority Number = Severity × Occurrence × Detection), highest risk first:

| # | Failure Mode | Component | Severity | Occurrence | Detection | RPN | Recommended Action |
|---|-------------|-----------|----------|------------|-----------|-----|-------------------|
| 1 | Solder joint fatigue | BGA/QFN packages | 7 | 6 | 6 | **252** | X-ray inspection, thermal cycling test |
| 2 | Capacitor cracking | MLCC ceramics | 7 | 6 | 5 | **210** | Flex testing, visual inspection |
| 3 | Solder joint failure (general) | All solder joints | 6 | 6 | 6 | **216** | Reflow profile optimization |
| 4 | DDR4 BGA crack | NT5AD512M16C4 | 9 | 6 | 3 | **162** | X-ray, thermal cycle qualification |
| 5 | eMMC corruption | KLMBG1GELM | 8 | 4 | 4 | **128** | Power loss protection, wear leveling |
| 6 | Connector corrosion | RJ45, USB-C | 6 | 5 | 4 | **120** | Seal inspection, corrosion-resistant plating |
| 7 | Thermal management | Enclosure/PCB | 6 | 5 | 4 | **120** | Thermal testing, shade recommendation |
| 8 | Capacitor failure (electrolytic) | Bulk caps | 7 | 5 | 3 | **105** | ESR testing, temperature derating |
| 9 | Antenna/RF path | RF traces, connectors | 7 | 3 | 5 | **105** | VSWR testing, visual inspection |
| 10 | Poor RF performance | Multiple RF components | 4 | 5 | 5 | **100** | Baseline comparison, spectrum analysis |
| 11 | Liquid ingress | Enclosure seals | 8 | 4 | 3 | **96** | IP66 verification, installation training |
| 12 | PoE power failure | MPM3690GQJ-Z | 8 | 4 | 3 | **96** | Input protection, voltage monitoring |
| 13 | PCB delamination | FR4 substrate | 8 | 2 | 4 | **64** | Cross-section analysis, moisture test |
| 14 | DAA (Dead After Arrival) | System level | 9 | 3 | 2 | **54** | Systematic power-on diagnostics |
| 15 | EIPD/EOS | TVS, input protection | 9 | 3 | 2 | **54** | Surge testing, TVS verification |
| 16 | Cloud registration | Firmware/cloud | 5 | 4 | 2 | **40** | Key provisioning, firmware update |
| 17 | Mechanical/mounting | Bracket, gland | 5 | 3 | 2 | **30** | Installation guide, torque spec |
| 18 | DOA (Dead On Arrival) | Manufacturing | 10 | 2 | 1 | **20** | Factory test coverage |

### RPN Risk Categories

| RPN Range | Risk Level | Action Required |
|-----------|-----------|-----------------|
| >200 | **CRITICAL** | Immediate design review, mandatory testing |
| 100-200 | **HIGH** | Enhanced testing, monitoring program |
| 50-99 | **MEDIUM** | Standard testing, periodic review |
| <50 | **LOW** | Monitor, no immediate action |

### Top 3 Risk Items Deep Dive

**1. Solder Joint Fatigue (RPN=252)**
- Root cause: Daily thermal cycling in outdoor environment (-40°F to 131°F range)
- Affected: All BGA packages (Miami, Waikiki, DDR4, eMMC)
- CTE mismatch between silicon die, solder balls, and FR4 PCB
- Mitigation: Underfill on critical BGAs, corner bonding, thermal cycling qualification to 1000 cycles

**2. Capacitor Cracking (RPN=210)**
- Root cause: Board flex during assembly, thermal shock, mechanical stress
- Affected: All MLCC ceramic capacitors, especially >0402 size
- Crack propagates under thermal cycling, eventually opens or shorts
- Mitigation: Flex testing, avoid placing large MLCCs near board edges or mounting holes

**3. DDR4 BGA Crack (RPN=162)**
- Root cause: Thermal cycling + CTE mismatch on fine-pitch BGA
- Affected: Nanya DDR4 SDRAM
- Symptom progression: Intermittent boot → frequent crashes → permanent failure
- Mitigation: X-ray inspection at incoming, thermal cycling qualification


---

## 21. STEP-BY-STEP DEBUG ISOLATION PROCEDURES

These procedures are designed to systematically isolate the root cause of a dead or malfunctioning Snowbird PCB. Each procedure follows a strict measure → compare → decide flow. Always start with Procedure A (Master Triage) to determine which sub-procedure to follow.

### Required Equipment

| Equipment | Purpose | Minimum Spec |
|-----------|---------|-------------|
| Digital Multimeter (DMM) | Voltage, resistance, continuity | 4.5 digit, True RMS |
| Oscilloscope | Ripple, signals, timing | 100MHz+, 2ch minimum |
| Current-limited bench PSU | Controlled power-on | 0-60V, 0-6A, current limit |
| PoE+ injector (known good) | Normal power source | 802.3at, 30W |
| Known-good Ethernet cable | Eliminate cable as variable | Cat5e+, tested |
| USB-C cable | Debug console access | USB 2.0 capable |
| Serial terminal | UART console | 115200 baud, 8N1 |
| Thermal camera (optional) | Hot spot identification | ±2°C accuracy |
| 10x loupe / microscope | Visual inspection | 10x minimum |

---

### PROCEDURE A: MASTER TRIAGE (Start Here for Every Dead/Faulty Unit)

This is the entry point. It classifies the unit into a failure category and directs you to the correct sub-procedure.

```
STEP A1: VISUAL INSPECTION (Power OFF)
├── Inspect RJ45 port for bent pins, corrosion, debris
├── Inspect USB-C port for damage, missing rubber plug
├── Inspect M22 cable gland for proper seating
├── Inspect enclosure for cracks, warping, discoloration
├── Look for any signs of liquid (white residue, staining)
├── Look for burn marks, discoloration on enclosure
│
├── FOUND liquid residue/staining? ──► Go to PROCEDURE H (Liquid Ingress)
├── FOUND burn marks/melting? ──► Go to PROCEDURE G (EIPD/EOS)
└── CLEAN? ──► Continue to STEP A2
```

```
STEP A2: CONNECT KNOWN-GOOD PoE+ INJECTOR
├── Use known-good Cat5e+ cable, <50m length
├── Connect to known-good PoE+ injector (802.3at, 30W)
├── Observe LED within 60 seconds
│
├── LED comes on (any color)? ──► Go to STEP A4 (Unit has power)
└── NO LED at all after 60s? ──► Go to STEP A3 (Dead unit)
```

```
STEP A3: DEAD UNIT - CURRENT DRAW CHECK
├── Replace PoE injector with bench PSU set to 48V, current limit 100mA
├── Connect via RJ45 center taps (pins 4,5 = V+; pins 7,8 = V-)
├── Observe current draw on bench PSU
│
├── Current = 0mA (zero draw)?
│   └── Open circuit: PoE magnetics, bridge rectifier, or input fuse
│   └── ──► Go to PROCEDURE B, Step B1
│
├── Current < 10mA (very low)?
│   └── PoE PD controller not classifying
│   └── ──► Go to PROCEDURE B, Step B3
│
├── Current 10-50mA (low, not booting)?
│   └── PoE PD running but downstream failure
│   └── ──► Go to PROCEDURE C (5V Rail Debug)
│
├── Current 50-200mA (partial boot)?
│   └── Some rails up, boot sequence stalled
│   └── ──► Go to PROCEDURE D (Boot Sequence Debug)
│
├── Current >500mA and rising rapidly?
│   └── SHORT CIRCUIT - remove power immediately
│   └── ──► Go to PROCEDURE F (Short Circuit Isolation)
│
└── Current 200-500mA (normal range)?
    └── Unit is drawing power but no LED
    └── ──► Go to PROCEDURE E (LED/I2C Debug)
```

```
STEP A4: UNIT HAS POWER (LED visible) - CLASSIFY SYMPTOM
│
├── LED solid white? ──► Unit is operational. Check Ethernet/WiFi.
│   └── No Ethernet? ──► Go to PROCEDURE I (Ethernet Debug)
│   └── No WiFi? ──► Go to PROCEDURE J (WiFi Debug)
│   └── Poor performance? ──► Go to PROCEDURE K (Performance Debug)
│
├── LED blinking white (>2 min)? ──► Boot loop or connection issue
│   └── ──► Go to PROCEDURE D (Boot Sequence Debug)
│
├── LED solid/blinking blue? ──► Setup/registration issue
│   └── ──► Go to PROCEDURE L (Cloud Registration Debug)
│
├── LED solid yellow? ──► No internet (upstream issue, not unit fault)
│   └── Verify upstream internet, DNS, firewall
│
├── LED solid/blinking red? ──► Critical error
│   └── ──► Go to PROCEDURE D (Boot Sequence Debug)
│
└── LED flickering/unstable? ──► Power instability
    └── ──► Go to PROCEDURE C (5V Rail Debug)
```

---

### PROCEDURE B: PoE INPUT STAGE ISOLATION

For units drawing zero or very low current from PoE source.

```
STEP B1: CHECK INPUT PATH CONTINUITY (Power OFF, DMM Ohms mode)
├── Measure resistance from RJ45 pin 4 to MPM3690 VIN+ pad
│   ├── Expected: <2Ω (through magnetics center tap + trace)
│   ├── >10Ω or OL? ──► Open magnetics center tap or broken trace
│   │   └── ACTION: Inspect magnetics, check for cracked solder joints
│   │   └── Measure across magnetics center tap winding individually
│   └── <2Ω? ──► Input path OK, continue to B2
│
├── Measure resistance from RJ45 pin 7 to MPM3690 VIN- pad
│   ├── Expected: <2Ω
│   ├── >10Ω or OL? ──► Open return path
│   └── <2Ω? ──► Return path OK, continue to B2
```

```
STEP B2: CHECK INPUT BRIDGE RECTIFIER
├── Measure diode mode across bridge rectifier (4 diodes)
│   ├── Forward: 0.4-0.7V each diode
│   ├── Reverse: OL (open)
│   ├── Any diode shorted (0V or <0.1V)? ──► Replace bridge rectifier
│   ├── Any diode open (OL both ways)? ──► Replace bridge rectifier
│   └── All diodes OK? ──► Continue to B3
```

```
STEP B3: CHECK MPM3690 PoE PD CONTROLLER
├── Apply 48V via bench PSU (current limit 100mA)
├── Measure voltage at MPM3690 VIN pin
│   ├── Expected: 46-48V (input minus diode drops)
│   ├── <40V? ──► Excessive drop in input path, recheck B1
│   ├── 0V? ──► Open circuit before MPM3690, recheck B1/B2
│   └── 46-48V present? ──► Continue to B4
```

```
STEP B4: CHECK MPM3690 OUTPUT (5V RAIL)
├── Measure voltage at MPM3690 VOUT pin (5V rail bulk capacitor)
│   ├── Expected: 4.9-5.1V
│   │
│   ├── 0V? ──► MPM3690 not switching
│   │   ├── Check ENABLE pin voltage (should be HIGH from classification)
│   │   ├── Check classification resistor value
│   │   ├── Check for thermal shutdown (touch MPM3690 - hot?)
│   │   └── ACTION: MPM3690 likely failed. Replace PoE PD controller.
│   │
│   ├── <4.5V? ──► Output low, possible overload
│   │   ├── Raise current limit to 500mA, re-measure
│   │   ├── If voltage recovers ──► downstream short pulling it down
│   │   └── ──► Go to PROCEDURE F (Short Circuit Isolation)
│   │
│   ├── >5.5V? ──► Feedback loop failure
│   │   └── ACTION: MPM3690 feedback resistors or controller failed
│   │
│   └── 4.9-5.1V? ──► 5V rail is good!
│       └── ──► Go to PROCEDURE D (Boot Sequence Debug)
```

```
STEP B5: CHECK PoE CLASSIFICATION
├── If PoE injector won't power unit but bench PSU works:
│   ├── Measure classification resistor (connected to MPM3690 CLASS pin)
│   │   ├── Expected: ~24.9KΩ (Class 4 = 25.5W)
│   │   ├── Wrong value? ──► Wrong class, injector may refuse power
│   │   └── Correct? ──► Try different PoE injector (compatibility issue)
│   └── Check if PoE injector supports 802.3at (not just 802.3af)
│       └── 802.3af only provides 15.4W, Snowbird needs 802.3at (30W)
```

---

### PROCEDURE C: 5V RAIL AND DC/DC CONVERTER DEBUG

For units where 5V is present but downstream rails are failing.

```
STEP C1: MEASURE ALL POWER RAILS (Power ON via bench PSU at 48V, 1A limit)
├── Use DMM to measure each rail at its bulk output capacitor:
│
│   RAIL          TEST POINT          EXPECTED    TOLERANCE
│   ─────────────────────────────────────────────────────────
│   5V system     MPM3690 VOUT cap    5.0V        ±0.1V
│   0.9V VCC_CX   Buck 1 output cap   0.90V       ±0.045V
│   1.2V VDD_DDR  Buck 3 output cap   1.20V       ±0.060V
│   2.5V VPP      Buck 4 output cap   2.50V       ±0.125V
│   1.8V shared   Buck 2 output cap   1.80V       ±0.090V
│   1.05V Napa    Buck 5 output cap   1.05V       ±0.053V
│   3.3V Waikiki  Buck 6 output cap   3.30V       ±0.165V
│   3.3V 2.4G     Buck 7 output cap   3.30V       ±0.165V
│   4.2V 5G PA    Buck 8 output cap   4.20V       ±0.210V
│
├── ALL rails within tolerance? ──► Power is good.
│   └── ──► Go to PROCEDURE D (Boot Sequence Debug)
│
├── ONE rail missing (0V)?
│   └── ──► Go to STEP C2 for that specific rail
│
├── ONE rail low (below tolerance)?
│   └── ──► Go to STEP C3 for that specific rail
│
├── MULTIPLE rails missing?
│   └── Check SPBM (SLG4R44724TR) output sequence
│   └── ──► Go to STEP C4 (SPBM Debug)
│
└── 5V rail sagging under load?
    └── ──► Go back to PROCEDURE B, Step B4
```

```
STEP C2: SINGLE RAIL MISSING (0V) - ISOLATION
├── Identify which DC/DC converter feeds the missing rail (see Section 4 table)
├── Check the converter's ENABLE pin:
│   ├── ENABLE = LOW? ──► SPBM not enabling this converter
│   │   └── ──► Go to STEP C4 (SPBM Debug)
│   └── ENABLE = HIGH? ──► Converter enabled but not switching. Continue.
│
├── Check converter VIN (should be 5V from system rail):
│   ├── VIN = 0V? ──► Open trace or fuse between 5V bus and converter
│   │   └── ACTION: Check continuity from 5V rail to converter VIN
│   └── VIN = 5V? ──► Converter has input power. Continue.
│
├── Check converter switching node with oscilloscope:
│   ├── Switching waveform present? ──► Output filter problem
│   │   └── Check output inductor continuity (should be <0.5Ω)
│   │   └── Check output capacitors (not shorted)
│   ├── No switching? ──► Converter IC failed
│   │   └── Check feedback pin voltage
│   │   └── Check for short on output (measure resistance to GND)
│   │   └── ACTION: Replace converter IC if confirmed failed
│   └── Erratic switching? ──► Feedback loop instability
│       └── Check feedback resistor divider values
│       └── Check compensation network components
```

```
STEP C3: SINGLE RAIL LOW (below tolerance) - ISOLATION
├── Measure rail voltage under load and no-load:
│   ├── Disconnect load (if possible) by removing downstream IC
│   │   └── Voltage recovers to nominal? ──► Downstream IC drawing excess current
│   │       └── Possible short in load IC (Miami, Waikiki, DDR4, etc.)
│   │       └── ACTION: Check load IC for shorts (resistance to GND)
│   └── Voltage still low with no load? ──► Converter problem
│       └── Check feedback resistor divider (sets output voltage)
│       └── Check reference voltage on converter
│       └── ACTION: Replace converter or feedback resistors
│
├── Use oscilloscope to check ripple on the low rail:
│   ├── Ripple >50mV pk-pk? ──► Output capacitor degradation
│   │   └── ESR test on output caps
│   │   └── ACTION: Replace output capacitors
│   └── Ripple normal (<20mV)? ──► Steady-state regulation issue
│       └── Feedback loop problem, check compensation
```

```
STEP C4: SPBM (SLG4R44724TR) DEBUG
├── Check SPBM VCC pin:
│   ├── Expected: 3.3V (derived from 5V via LDO)
│   ├── 0V? ──► SPBM has no power. Check LDO from 5V rail.
│   └── 3.3V present? ──► Continue.
│
├── Check SPBM input: PoE PGOOD signal
│   ├── Expected: HIGH when 5V rail is stable
│   ├── LOW? ──► MPM3690 PGOOD not asserted. 5V rail issue.
│   │   └── ──► Go back to PROCEDURE B
│   └── HIGH? ──► SPBM should be sequencing. Continue.
│
├── Check SPBM enable outputs (one per converter):
│   ├── Use oscilloscope, trigger on PoE PGOOD rising edge
│   ├── Verify each enable output goes HIGH in sequence:
│   │   T+0ms:  EN_0V9  (VCC_CX)     ──► should go HIGH
│   │   T+5ms:  EN_1V2  (VDD_DDR)    ──► should go HIGH
│   │   T+7ms:  EN_2V5  (VPP)        ──► should go HIGH
│   │   T+10ms: EN_1V8  (shared)     ──► should go HIGH
│   │   T+15ms: EN_1V05 (Napa)       ──► should go HIGH
│   │
│   ├── All enables go HIGH in sequence? ──► SPBM is working
│   │   └── Problem is in individual converter (go to C2)
│   ├── Sequence stops at a certain point?
│   │   └── SPBM is waiting for PGOOD from previous converter
│   │   └── The converter BEFORE the stop point has a PGOOD issue
│   │   └── Debug that converter (Step C2)
│   └── No enables go HIGH?
│       └── SPBM IC failed or configuration corrupted
│       └── ACTION: Replace SPBM (SLG4R44724TR)
```


---

### PROCEDURE D: BOOT SEQUENCE DEBUG

For units that have power (all rails OK) but fail to boot or get stuck in boot loop.

```
STEP D1: CONNECT UART CONSOLE
├── Connect USB-C cable to Snowbird debug port
├── Open serial terminal: 115200 baud, 8N1, no flow control
├── UART is on SBU1/SBU2 pins (always active, no mux needed)
├── Power on the unit
├── Observe UART output:
│
├── NO output at all?
│   └── ──► Go to STEP D2 (PBL not running)
│
├── Output starts then stops at "PBL..."?
│   └── ──► Go to STEP D3 (PBL to SBL transition failure)
│
├── Output shows "SBL" then "DDR training..." then stops?
│   └── ──► Go to STEP D4 (DDR4 initialization failure)
│
├── Output shows "U-Boot" then stops or loops?
│   └── ──► Go to STEP D5 (eMMC/kernel load failure)
│
├── Output shows kernel panic or crash dump?
│   └── ──► Go to STEP D6 (Kernel/firmware failure)
│
└── Output shows full boot but LED stuck blinking?
    └── ──► Go to STEP D7 (Application layer failure)
```

```
STEP D2: PBL NOT RUNNING (No UART output, rails OK)
├── This means Miami SoC is not executing code at all.
│
├── Verify 0.9V VCC_CX at Miami power pins:
│   ├── 0V? ──► Go to PROCEDURE C, debug 0.9V rail
│   └── 0.9V present? ──► Continue.
│
├── Verify Miami RESET_N pin:
│   ├── Measure with scope, should go HIGH ~30ms after all rails stable
│   ├── Stuck LOW? ──► SPBM not releasing reset
│   │   └── ──► Go to PROCEDURE C, Step C4 (SPBM Debug)
│   └── Goes HIGH? ──► Continue.
│
├── Verify Miami clock (XTAL):
│   ├── Scope the crystal oscillator pins
│   ├── Expected: Clean 25MHz (or specified frequency) sine/square wave
│   ├── No oscillation? ──► Crystal or load capacitor failure
│   │   └── ACTION: Replace crystal and load caps
│   └── Oscillating? ──► Continue.
│
├── Check boot strap GPIO pins (from SPBM):
│   ├── GPIO0 = LOW, GPIO1 = LOW (eMMC boot mode)
│   ├── Wrong values? ──► SPBM misconfigured or GPIO stuck
│   └── Correct? ──► Miami SoC may be dead
│       └── ACTION: Check for shorts on Miami power pins
│       └── Measure Miami VCC_CX current (should be 200-500mA at PBL)
│       └── 0mA? ──► Miami die failure. Replace SoC.
│       └── Normal current but no UART? ──► Check UART path
│           └── Verify UART TX from Miami to USB-C SBU pin continuity
```

```
STEP D3: PBL → SBL TRANSITION FAILURE
├── PBL runs (UART shows PBL messages) but SBL doesn't start
├── This means PBL cannot read SBL from eMMC Boot0 partition
│
├── Check eMMC power:
│   ├── VCC (3.3V) at eMMC pin ──► Expected: 3.3V ±5%
│   ├── VCCQ (1.8V) at eMMC pin ──► Expected: 1.8V ±5%
│   ├── Either missing? ──► Debug that power rail (Procedure C)
│   └── Both present? ──► Continue.
│
├── Scope eMMC CLK pin:
│   ├── Expected: Clock activity during boot attempt (26MHz initial)
│   ├── No clock? ──► Miami eMMC controller not initializing
│   │   └── Check Miami eMMC GPIO configuration
│   └── Clock present? ──► Continue.
│
├── Scope eMMC CMD pin:
│   ├── Expected: Command/response activity
│   ├── CMD stuck HIGH? ──► eMMC not responding to commands
│   │   └── eMMC may be in locked/error state
│   │   └── Power cycle (remember: no RST_N available!)
│   │   └── If persists after 5 power cycles ──► eMMC failed
│   │   └── ACTION: Replace eMMC IC
│   ├── CMD shows commands but no responses?
│   │   └── eMMC receiving but not responding
│   │   └── Check eMMC DAT0 for busy signal
│   │   └── ACTION: eMMC likely failed. Replace.
│   └── Normal CMD activity? ──► SBL image may be corrupted
│       └── Try USB boot recovery (GPIO44 = HIGH, USB-C with FW image)
│       └── If USB boot works ──► Re-flash eMMC Boot0 partition
│       └── If USB boot fails ──► Miami or board-level failure
```

```
STEP D4: DDR4 INITIALIZATION FAILURE
├── UART shows "DDR training failed" or hangs at DDR init
│
├── Check DDR4 power rails:
│   ├── VDD_DDR (1.2V) at DDR4 pin ──► Expected: 1.20V ±5%
│   ├── VPP (2.5V) at DDR4 pin ──► Expected: 2.50V ±5%
│   ├── VREF_DQ (0.6V) at resistor divider ──► Expected: 0.600V ±3%
│   ├── VTT (0.6V) at termination regulator ──► Expected: 0.600V ±40mV
│   │
│   ├── Any rail missing or out of spec?
│   │   └── Debug that specific rail (Procedure C)
│   └── All rails OK? ──► Continue.
│
├── Scope DDR4 CK± (clock):
│   ├── Expected: Differential clock, amplitude ~1.2V pk-pk
│   ├── No clock? ──► Miami DDR controller not starting
│   │   └── Check Miami VCC_CX stability (scope for dropouts)
│   └── Clock present? ──► Continue.
│
├── Scope DDR4 DQS (data strobe):
│   ├── Expected: Activity during training sequence
│   ├── No activity? ──► DDR4 IC not responding
│   │   └── Check DDR4 RESET_N pin (should go HIGH after VDD stable)
│   │   └── Check solder joints on DDR4 BGA (X-ray if available)
│   │   └── ACTION: Possible DDR4 BGA solder failure (RPN=162)
│   └── Activity present but training fails?
│       └── Signal integrity issue
│       └── Check for noise on VDD_DDR (scope, AC coupled, 20MHz BW)
│       └── Ripple >30mV? ──► Output cap degradation on 1.2V rail
│       └── Ripple OK? ──► DDR4 IC marginal or damaged
│       └── ACTION: Replace DDR4 SDRAM
```

```
STEP D5: eMMC / KERNEL LOAD FAILURE
├── UART shows U-Boot starts but kernel doesn't load, or CRC errors
│
├── U-Boot prompt accessible?
│   ├── YES ──► Run eMMC diagnostics from U-Boot:
│   │   ├── "mmc info" ──► Check eMMC detected, size, version
│   │   ├── "mmc read" ──► Try reading kernel partition
│   │   ├── Read errors? ──► eMMC has bad blocks in kernel area
│   │   │   └── Try alternate partition if dual-boot supported
│   │   │   └── Re-flash firmware via USB boot
│   │   │   └── Persistent errors? ──► eMMC wear-out. Replace.
│   │   └── Read OK but CRC fail? ──► Firmware image corrupted
│   │       └── Re-flash firmware via USB boot recovery
│   │
│   └── NO (U-Boot crashes) ──► U-Boot image corrupted
│       └── USB boot recovery (GPIO44 HIGH + USB-C firmware)
│       └── Re-flash Boot0 and Boot1 partitions
```

```
STEP D6: KERNEL PANIC / CRASH
├── Capture full crash dump from UART
├── Look for key indicators:
│   ├── "Unable to mount root filesystem" ──► eMMC rootfs partition corrupt
│   │   └── Re-flash rootfs via recovery
│   ├── "Kernel panic - not syncing" ──► Driver or hardware init failure
│   │   └── Note which driver/subsystem caused panic
│   │   └── If PCIe related ──► Waikiki power/connection issue
│   │   └── If USB related ──► BLE module or crossbar issue
│   │   └── If network related ──► Napa PHY issue
│   ├── "Out of memory" ──► DDR4 not fully accessible
│   │   └── Check DDR4 training results in boot log
│   │   └── Partial DDR4 failure (some banks bad)
│   └── Repeating crash at same point ──► Consistent hardware fault
│       └── Identify the subsystem from crash trace
│       └── Debug that specific subsystem
```

```
STEP D7: APPLICATION LAYER FAILURE (Full boot, LED stuck)
├── Unit boots Linux but eero application doesn't start properly
├── UART shows Linux prompt or application errors
│
├── LED stuck blinking white (>5 min)?
│   └── Application trying to connect to cloud
│   └── Check Ethernet link (Napa PHY):
│       ├── "ethtool eth0" ──► Link detected? Speed?
│       ├── No link? ──► Go to PROCEDURE I (Ethernet Debug)
│       └── Link OK? ──► Cloud/network issue, not hardware
│
├── LED stuck blinking blue?
│   └── BLE pairing mode, waiting for app setup
│   └── Check if unit was previously set up (factory reset?)
│   └── Not a hardware issue unless BLE is non-functional
│
└── LED solid red?
    └── Critical application error
    └── Check application logs via UART
    └── May need firmware re-flash
```


---

### PROCEDURE E: LED / I2C DEBUG

For units drawing normal current (200-500mA) but LED is completely off.

```
STEP E1: CHECK LED DRIVER POWER
├── Measure 3.3V at KTD2027B VCC pin
│   ├── 0V? ──► 3.3V rail not reaching LED driver
│   │   └── Check trace from 3.3V rail to KTD2027B
│   │   └── Check for series resistor or ferrite bead (open?)
│   └── 3.3V present? ──► Continue to E2.
```

```
STEP E2: CHECK I2C BUS
├── Scope I2C SDA and SCL lines at KTD2027B pins
│   ├── Both lines HIGH (~1.8V) with no activity?
│   │   └── Miami not sending I2C commands to LED driver
│   │   └── Check if Miami is booting (connect UART, Procedure D)
│   │   └── If Miami is booting ──► I2C driver not loaded or address wrong
│   │
│   ├── SCL toggling but SDA stuck LOW?
│   │   └── I2C bus hung (slave holding SDA low)
│   │   └── ACTION: Power cycle. If persists, KTD2027B failed.
│   │
│   ├── Both lines stuck LOW?
│   │   └── Short circuit on I2C bus
│   │   └── Check for solder bridges on SDA/SCL
│   │   └── Disconnect KTD2027B, check if bus recovers
│   │
│   └── Normal I2C traffic visible?
│       └── LED driver is being commanded. Continue to E3.
```

```
STEP E3: CHECK LED OUTPUTS
├── Measure voltage at KTD2027B output pins (OUT1-OUT4)
│   ├── Expected when LED should be ON: ~2.0-3.2V (depends on LED color)
│   │   Red (OUT1): ~2.0V forward
│   │   Green (OUT2): ~3.0V forward
│   │   Blue (OUT3): ~3.2V forward
│   │   White (OUT4): ~3.0V forward
│   │
│   ├── Output voltage present but LED dark?
│   │   └── LED itself is open (failed)
│   │   └── ACTION: Replace LED
│   │
│   ├── Output voltage = 0V despite I2C commands?
│   │   └── KTD2027B output driver failed
│   │   └── ACTION: Replace KTD2027B
│   │
│   └── Output voltage = VCC (3.3V)?
│       └── LED is shorted
│       └── ACTION: Replace LED
```

---

### PROCEDURE F: SHORT CIRCUIT ISOLATION

For units drawing excessive current (>500mA at power-on, rapidly rising). **CAUTION: Remove power immediately if current exceeds 2A.**

```
STEP F1: IDENTIFY SHORTED RAIL
├── Power OFF. Set bench PSU to 5V, current limit 50mA.
├── Connect bench PSU directly to 5V rail (bypass PoE stage)
├── Measure current:
│   ├── >50mA at 5V? ──► Short is on 5V bus or downstream
│   │   └── Continue to F2
│   └── <50mA at 5V? ──► Short is in PoE input stage
│       └── Check MPM3690 for internal short
│       └── Check input bridge rectifier
│       └── Check input capacitors
```

```
STEP F2: ISOLATE SHORTED DOWNSTREAM RAIL
├── Power OFF. Use DMM in resistance mode (lowest range).
├── Measure resistance from each rail to GND at the output capacitor:
│
│   RAIL          EXPECTED (to GND)    SHORTED IF
│   ──────────────────────────────────────────────
│   0.9V VCC_CX   >5Ω                  <1Ω
│   1.2V VDD_DDR  >10Ω                 <1Ω
│   2.5V VPP      >50Ω                 <2Ω
│   1.8V shared   >10Ω                 <1Ω
│   1.05V Napa    >10Ω                 <1Ω
│   3.3V Waikiki  >5Ω                  <1Ω
│   3.3V 2.4G     >10Ω                 <2Ω
│   4.2V 5G PA    >5Ω                  <1Ω
│
│   NOTE: Low resistance readings are normal for high-current rails
│   due to decoupling capacitors. A TRUE short reads <0.5Ω.
│
├── Found shorted rail? ──► Continue to F3 for that rail
└── No obvious short? ──► Use thermal method (F4)
```

```
STEP F3: PINPOINT SHORT ON IDENTIFIED RAIL
├── Apply low voltage (1V) at current limit (100mA) to the shorted rail
├── Use thermal camera or freeze spray method:
│   ├── Thermal camera: Look for hot spot (component drawing all current)
│   ├── Freeze spray: Spray components on the rail, shorted one warms fastest
│
├── Common short circuit culprits by rail:
│   ├── 0.9V VCC_CX: Miami SoC internal short (die failure)
│   ├── 1.2V VDD_DDR: DDR4 IC short, decoupling cap short
│   ├── 1.8V shared: Waikiki or Napa IC short, MLCC cap crack→short
│   ├── 3.3V Waikiki: Waikiki IC short, bypass cap failure
│   ├── 4.2V 5G PA: FEM internal short (PA burnout)
│   └── Any rail: MLCC capacitor crack leading to short
│
├── Identified shorted component?
│   └── ACTION: Remove component, verify short clears
│   └── Replace component, re-test
│
└── Cannot identify?
    └── Systematically remove components from the shorted rail
    └── Start with ICs (largest loads), then capacitors
    └── After each removal, re-check resistance to GND
    └── When resistance recovers ──► last removed component was shorted
```

```
STEP F4: THERMAL SHORT CIRCUIT DETECTION (No obvious rail short)
├── Apply 48V via bench PSU, current limit 200mA
├── Power on for exactly 10 seconds, then power off
├── Immediately use thermal camera to scan entire PCB
│   ├── Hot spot on a specific IC? ──► That IC has internal short
│   ├── Hot spot on a capacitor? ──► Cracked MLCC (short mode)
│   ├── Hot spot on a trace? ──► PCB internal short (delamination)
│   └── Uniform heating? ──► Distributed short, likely PCB issue
│       └── ACTION: Cross-section analysis needed
```

---

### PROCEDURE G: EIPD/EOS (Electrical Overstress) INVESTIGATION

For units with visible burn marks, component damage, or suspected surge/lightning damage.

```
STEP G1: VISUAL DAMAGE ASSESSMENT
├── Use 10x loupe or microscope to inspect:
│   ├── PoE input stage (MPM3690 area):
│   │   ├── Burn marks on bridge rectifier? ──► Input surge
│   │   ├── Cracked/exploded capacitors? ──► Overvoltage event
│   │   └── MPM3690 package cracked/discolored? ──► PoE surge
│   │
│   ├── TVS diodes (near RJ45):
│   │   ├── TVS visibly damaged? ──► Absorbed surge (did its job)
│   │   ├── TVS missing? ──► "Reserve for surge test" - NOT POPULATED
│   │   │   └── NOTE: TVS diodes may be DNI per schematic note
│   │   │   └── Unit had NO surge protection if TVS not populated
│   │   └── TVS intact? ──► Surge exceeded TVS rating
│   │
│   ├── Miami SoC area:
│   │   ├── Discoloration on package? ──► EOS on power pins
│   │   └── Burn marks on nearby passives? ──► Overcurrent event
│   │
│   └── FEM area (SKY85500):
│       ├── FEM package damaged? ──► RF overstress or antenna VSWR
│       └── Nearby components damaged? ──► Power surge through 4.2V rail
```

```
STEP G2: ELECTRICAL DAMAGE ASSESSMENT
├── Power OFF. DMM diode mode.
├── Check TVS diodes (if populated):
│   ├── Forward: 0.6-0.7V (normal silicon)
│   ├── Reverse: Should show breakdown voltage (varies by TVS)
│   ├── Shorted (0V both ways)? ──► TVS absorbed surge, now shorted
│   │   └── Remove shorted TVS, check if downstream survived
│   └── Open (OL both ways)? ──► TVS blown open, no protection remains
│
├── Check PoE input diodes:
│   ├── Same diode mode test as Procedure B, Step B2
│   └── Any shorted? ──► Surge came through PoE
│
├── Check each power rail resistance to GND (Procedure F, Step F2):
│   └── Any shorted rail indicates EOS damage to that subsystem
│
├── Damage limited to input stage only?
│   └── Replace PoE PD, bridge rectifier, TVS diodes
│   └── Test downstream - may have survived
│
├── Damage extends to Miami/Waikiki?
│   └── Board-level replacement needed
│   └── Document damage pattern for failure analysis report
```

```
STEP G3: DETERMINE EOS SOURCE
├── Based on damage pattern:
│   ├── Damage at PoE input only ──► PoE surge (injector or cable)
│   │   └── Check injector output with scope for transients
│   │   └── Check if outdoor cable run is near lightning risk
│   │
│   ├── Damage at RJ45 data pins ──► Ethernet surge (lightning on cable)
│   │   └── Recommend surge protector on Ethernet run
│   │
│   ├── Damage at USB-C ──► ESD event during debug
│   │   └── Check ESD protection on USB-C (FUSB15201MX)
│   │
│   └── Damage at FEMs ──► Antenna port overstress
│       └── Check antenna VSWR (disconnected/damaged antenna)
│       └── Check for nearby high-power transmitter
```

---

### PROCEDURE H: LIQUID INGRESS INVESTIGATION

For units with suspected water/moisture damage.

```
STEP H1: EXTERNAL INSPECTION
├── Check M22 cable gland:
│   ├── Loose? ──► Improper installation (torque spec: 2-3 Nm)
│   ├── Cable too thin for gland? ──► Seal not compressed properly
│   ├── Wrong cable type? ──► Must be round, 6-12mm diameter
│   └── Gland cracked? ──► Physical damage, replace gland
│
├── Check USB-C rubber plug:
│   ├── Missing? ──► Water entry point
│   ├── Cracked/degraded? ──► UV damage, replace
│   └── Present and sealed? ──► Not the entry point
│
├── Check enclosure:
│   ├── Cracks or gaps? ──► Impact damage
│   ├── Warped? ──► Thermal damage to enclosure
│   └── Intact? ──► Water entered through gland or connector
```

```
STEP H2: INTERNAL INSPECTION (Open enclosure)
├── Look for:
│   ├── Standing water ──► Active leak, identify entry point
│   ├── Water stains (tide marks) ──► Previous water exposure
│   ├── White crystalline residue ──► Flux + moisture corrosion
│   ├── Green/blue deposits ──► Copper corrosion (galvanic)
│   ├── Black deposits ──► Silver sulfide corrosion
│   └── Condensation droplets ──► Thermal cycling condensation
│
├── Document location and extent of moisture evidence
├── Photograph all findings before cleaning
```

```
STEP H3: CORROSION DAMAGE ASSESSMENT
├── Inspect under microscope:
│   ├── Corrosion on component leads?
│   │   └── Measure resistance between adjacent pins
│   │   └── <100KΩ between pins that should be isolated? ──► Leakage path
│   │
│   ├── Corrosion on PCB traces?
│   │   └── Check continuity of affected traces
│   │   └── Open trace? ──► Corrosion ate through copper
│   │
│   ├── Corrosion under BGA packages?
│   │   └── Cannot inspect visually
│   │   └── X-ray if available
│   │   └── Check for intermittent failures (thermal cycling test)
│   │
│   └── Electrochemical migration (dendrites between traces)?
│       └── Visible metallic whiskers between pads
│       └── Can cause intermittent shorts
│       └── ACTION: Clean with IPA, verify isolation resistance
│
├── Corrosion limited to non-critical area?
│   └── Clean with IPA (isopropyl alcohol), dry thoroughly
│   └── Re-test unit functionality
│   └── If functional ──► Document and monitor
│
├── Corrosion on critical components (Miami, Waikiki, DDR4)?
│   └── Board-level replacement likely needed
│   └── Document for failure analysis
```


---

### PROCEDURE I: ETHERNET DEBUG

For units that boot (LED on) but have no Ethernet connectivity.

```
STEP I1: CHECK PHYSICAL LAYER
├── Inspect RJ45 connector:
│   ├── Bent pins? ──► Straighten or replace connector
│   ├── Corrosion? ──► Clean with contact cleaner
│   ├── Debris? ──► Clean out
│   └── Clean? ──► Continue.
│
├── Test with known-good cable:
│   ├── Link comes up? ──► Original cable was bad
│   └── Still no link? ──► Continue to I2.
```

```
STEP I2: CHECK NAPA PHY POWER
├── Measure Napa power rails:
│   ├── VDD_CORE (1.05V) at Napa pin ──► Expected: 1.05V ±5%
│   ├── VDD_IO (1.8V) at Napa pin ──► Expected: 1.8V ±5%
│   ├── VDD_MDI (3.3V) at Napa pin ──► Expected: 3.3V ±5%
│   │
│   ├── 1.05V missing? ──► Buck 5 failure. Go to Procedure C.
│   ├── 1.8V missing? ──► Shared rail failure. Go to Procedure C.
│   │   └── NOTE: 1.8V failure also kills Waikiki analog
│   │   └── If WiFi is also dead ──► confirms shared 1.8V rail failure
│   ├── 3.3V MDI missing? ──► LDO or trace failure for MDI supply
│   └── All present? ──► Continue to I3.
```

```
STEP I3: CHECK NAPA PHY OPERATION
├── Via UART console (if Linux booted):
│   ├── "ethtool eth0" ──► Check link status, speed, duplex
│   │   ├── "Link detected: no" ──► PHY not linking
│   │   │   └── Continue to I4
│   │   ├── "Link detected: yes" but "Speed: 100Mb/s" ──► Degraded
│   │   │   └── Only 2 pairs working (cable or magnetics issue)
│   │   │   └── Test all 4 pairs with cable tester
│   │   └── "Link detected: yes, Speed: 2500Mb/s" ──► Link is good
│   │       └── Problem is above PHY layer (IP config, routing)
│   │       └── Not a hardware issue
│   │
│   ├── "ethtool -d eth0" ──► Dump PHY registers
│   │   └── Check for error counters, link partner capability
│   │
│   └── "eth0: not found" ──► MDIO communication failure
│       └── Miami cannot talk to Napa
│       └── Check MDIO/MDC signals with scope
│       └── Check Napa RESET_N pin (should be HIGH)
```

```
STEP I4: CHECK MAGNETICS AND MDI SIGNALS
├── Scope MDI signals at Napa pins (with cable connected):
│   ├── Expected: Link pulses visible (~2V pk-pk, 16ms interval)
│   ├── No link pulses from Napa? ──► Napa TX not working
│   │   └── Check Napa MDI driver power (3.3V)
│   │   └── ACTION: Napa PHY may be failed. Replace QCA8081.
│   ├── Link pulses from Napa but none from partner?
│   │   └── Cable or far-end issue, not Snowbird
│   └── Both sides sending link pulses but no link?
│       └── Auto-negotiation failure
│       └── Try forcing speed: "ethtool -s eth0 speed 1000 duplex full"
│       └── If forced link works ──► Auto-neg issue (firmware or PHY config)
│
├── Check magnetics continuity:
│   ├── DMM resistance across each transformer winding
│   ├── Expected: <2Ω per winding
│   ├── Open (OL)? ──► Magnetics winding broken
│   │   └── ACTION: Replace magnetics module
│   └── All windings OK? ──► Magnetics are good
```

```
STEP I5: CHECK SGMII LINK (Miami ↔ Napa)
├── Via UART: Check for SGMII errors in dmesg
│   ├── "SGMII link down" ──► Internal link between Miami and Napa failed
│   │   └── Check SGMII AC coupling capacitors (100nF)
│   │   └── Scope SGMII TX/RX differential pairs
│   │   └── Expected: ~800mV pk-pk differential swing
│   └── SGMII link up but packet errors?
│       └── Signal integrity issue on SGMII traces
│       └── Check for solder bridges near SGMII AC caps
```

---

### PROCEDURE J: WiFi DEBUG

For units that boot and have Ethernet but no WiFi or degraded WiFi.

```
STEP J1: IDENTIFY WHICH BAND IS AFFECTED
├── Via UART console:
│   ├── "iw dev" ──► List wireless interfaces
│   │   ├── No interfaces at all? ──► Go to J2 (Waikiki not detected)
│   │   ├── Only 2.4GHz interface? ──► 5GHz (Waikiki) failed. Go to J2.
│   │   ├── Only 5GHz interface? ──► 2.4GHz (Miami IPA) failed. Go to J5.
│   │   └── Both interfaces present? ──► Go to J6 (RF performance issue)
```

```
STEP J2: WAIKIKI NOT DETECTED (No 5GHz)
├── Check PCIe link:
│   ├── "lspci" ──► Should show QCN9274
│   ├── Not listed? ──► PCIe link down. Continue.
│   └── Listed? ──► Driver issue, not hardware (usually)
│
├── Check Waikiki power rails (all must be present):
│   ├── WK_VDD33 (3.3V) ──► Expected: 3.3V ±5%
│   ├── WK_VDDCX (0.92V) ──► Expected: 0.92V ±5%
│   ├── WK_VDD18 (1.8V) ──► Expected: 1.8V ±5% (shared rail)
│   │
│   ├── Any rail missing? ──► Debug that rail (Procedure C)
│   └── All present? ──► Continue to J3.
```

```
STEP J3: CHECK PCIe LINK (Miami ↔ Waikiki)
├── Check PERST_N signal:
│   ├── Scope PERST_N at Waikiki pin
│   ├── Expected: Goes HIGH after Waikiki power stable (~20ms)
│   ├── Stuck LOW? ──► Miami not releasing Waikiki reset
│   │   └── Check Miami GPIO driving PERST_N
│   │   └── Check pull-up resistor on PERST_N
│   └── Goes HIGH? ──► Continue.
│
├── Scope PCIe reference clock:
│   ├── Expected: 100MHz differential clock
│   ├── No clock? ──► Clock generator or buffer failure
│   └── Clock present? ──► Continue.
│
├── Scope PCIe TX lanes (Miami → Waikiki):
│   ├── Expected: Electrical idle or training pattern
│   ├── No signal? ──► Miami PCIe TX driver failure
│   │   └── Check AC coupling caps (100nF) on PCIe lanes
│   └── Signal present? ──► Waikiki RX may be damaged
│       └── ACTION: Waikiki IC may need replacement
```

```
STEP J4: CHECK 5GHz FEMs
├── If Waikiki detected but 5GHz TX power is zero or very low:
│   ├── Check 4.2V at FEM VCC pins:
│   │   ├── 0V? ──► Buck 8 (4.2V) failure. Go to Procedure C.
│   │   ├── <3.8V? ──► Buck 8 sagging. Check load, output caps.
│   │   └── 4.2V present? ──► Continue.
│   │
│   ├── Check FEM CTRL pins (from Waikiki):
│   │   ├── Scope during TX: Should toggle for PA enable
│   │   ├── Stuck LOW? ──► Waikiki not enabling PA
│   │   └── Toggling? ──► FEM PA may be burned out
│   │       └── Measure FEM current draw (should be ~300mA during TX)
│   │       └── 0mA during TX? ──► PA open (burned out)
│   │       └── ACTION: Replace SKY85500-11 FEM
│   │
│   ├── Check 5GHz BPF (DF1508):
│   │   └── If TX power present at FEM output but not at antenna
│   │   └── BPF may be open or detuned
│   │   └── Measure insertion loss with network analyzer
│   │
│   └── Check diplexer (DF1505):
│       └── If signal present at BPF output but not at antenna port
│       └── Diplexer 5G path may be damaged
│       └── Measure S21 through 5G path of diplexer
```

```
STEP J5: 2.4GHz FAILURE (Miami Internal PA)
├── 2.4GHz uses Miami's internal power amplifier (IPA)
│
├── Check 3.3V 2.4G IPA supply:
│   ├── Measure at Buck 7 output ──► Expected: 3.3V ±5%
│   ├── 0V? ──► Buck 7 failure. Go to Procedure C.
│   └── 3.3V present? ──► Continue.
│
├── Check SAW filters (SAFFB2G49MN0F0A):
│   ├── If TX power present at Miami RF pins but not at antenna
│   ├── SAW filter may be cracked or detuned
│   ├── NOTE: SAW part may vary between batches ("wait for mass confirmation")
│   └── Measure insertion loss with network analyzer if available
│
├── Check diplexer 2.4G path:
│   └── Measure S21 through 2.4G path of diplexer (DF1505)
│
├── Miami IPA itself failed?
│   └── If 3.3V present, SAW OK, diplexer OK, but no 2.4G TX
│   └── Miami internal PA damaged (EOS or thermal)
│   └── ACTION: SoC replacement needed (board-level repair)
```

```
STEP J6: RF PERFORMANCE DEGRADATION (Both bands present but weak)
├── Compare to Known Good Unit (KGU) baseline:
│   ├── Measure TX power at antenna port:
│   │   ├── 5GHz expected: +15 to +20 dBm
│   │   ├── 2.4GHz expected: +18 to +23 dBm
│   │   ├── >3dB below KGU? ──► Component degradation
│   │   └── Within 1dB of KGU? ──► Environmental/installation issue
│   │
│   ├── Measure RX sensitivity:
│   │   ├── Use signal generator at known power level
│   │   ├── Compare packet error rate to KGU
│   │   ├── >3dB worse? ──► LNA or RF path degradation
│   │   └── Similar to KGU? ──► Not a hardware issue
│   │
│   └── Check antenna VSWR:
│       ├── Expected: <2:1 across operating band
│       ├── >3:1? ──► Antenna damage or impedance mismatch
│       └── OK? ──► RF path components (filters, diplexer) may be drifting
```

---

### PROCEDURE K: PERFORMANCE DEBUG

For units that work but have throughput, latency, or coverage issues.

```
STEP K1: BASELINE COMPARISON
├── Compare unit performance to KGU in same environment:
│   ├── Same location, same client device, same test
│   ├── Throughput within 80% of KGU? ──► Likely environmental
│   └── Throughput <50% of KGU? ──► Hardware degradation. Continue.
```

```
STEP K2: THERMAL CHECK
├── Read thermal sensors via UART:
│   ├── Miami junction temp >100°C? ──► Thermal throttling active
│   │   └── Check ambient temperature
│   │   └── Check for direct sunlight exposure
│   │   └── Check enclosure ventilation (not blocked)
│   │   └── ACTION: Relocate unit or add shade structure
│   └── Temps normal (<85°C)? ──► Not thermal. Continue.
```

```
STEP K3: CHECK INDIVIDUAL RADIO PERFORMANCE
├── Test 5GHz independently:
│   ├── Connect 5GHz client, run iperf3
│   ├── Expected: >800 Mbps (WiFi 7, 2x2, 80MHz)
│   ├── <400 Mbps? ──► 5GHz degradation
│   │   └── Check FEM TX power (Procedure J, Step J4)
│   │   └── Check for interference (spectrum analyzer)
│   └── OK? ──► 5GHz is fine.
│
├── Test 2.4GHz independently:
│   ├── Connect 2.4GHz client, run iperf3
│   ├── Expected: >200 Mbps (WiFi 7, 2x2, 40MHz)
│   ├── <100 Mbps? ──► 2.4GHz degradation
│   │   └── Check IPA supply, SAW filters (Procedure J, Step J5)
│   │   └── Check for 2.4GHz interference (very common outdoors)
│   └── OK? ──► 2.4GHz is fine.
│
├── Test Ethernet independently:
│   ├── Direct iperf3 over Ethernet
│   ├── Expected: >2.0 Gbps (2.5GBASE-T)
│   ├── <1.0 Gbps? ──► Ethernet degradation
│   │   └── Check negotiated speed (ethtool)
│   │   └── Check cable quality
│   │   └── Check Napa PHY (Procedure I)
│   └── OK? ──► Ethernet is fine.
```

```
STEP K4: CHECK FOR INTERFERENCE
├── Use spectrum analyzer or WiFi scanner:
│   ├── 2.4GHz band: Check for competing APs, Bluetooth, microwave
│   ├── 5GHz band: Check for DFS radar events, competing APs
│   ├── High noise floor (>-80 dBm)? ──► Environmental interference
│   │   └── Change channel, reduce channel width
│   │   └── Not a hardware issue
│   └── Clean spectrum? ──► Hardware issue, go back to J6
```

---

### PROCEDURE L: CLOUD REGISTRATION DEBUG

For units stuck in setup mode (LED blinking blue) or failing cloud registration.

```
STEP L1: VERIFY NETWORK PATH
├── Via UART console:
│   ├── "ping 8.8.8.8" ──► Internet reachable?
│   │   ├── No? ──► Network/Ethernet issue. Go to Procedure I.
│   │   └── Yes? ──► Continue.
│   │
│   ├── "ping eero.com" ──► DNS working?
│   │   ├── No? ──► DNS issue (not hardware)
│   │   └── Yes? ──► Continue.
│   │
│   └── Check firewall: eero needs ports 443 (HTTPS) and 8443
│       └── If blocked ──► Network policy issue, not hardware
```

```
STEP L2: CHECK CLOUD REGISTRATION STATUS
├── Via UART console, check eero application logs:
│   ├── "Cloud key mismatch" ──► Provisioning error
│   │   └── Known issue: QC bug CONN-45729
│   │   └── ACTION: Re-provision cloud keys
│   │
│   ├── "Certificate error" ──► TLS certificate issue
│   │   └── Check system clock (wrong date causes cert failures)
│   │   └── ACTION: Sync NTP, re-attempt registration
│   │
│   ├── "Registration timeout" ──► Cloud server not responding
│   │   └── Check eero cloud service status
│   │   └── Not a hardware issue
│   │
│   └── No cloud-related errors? ──► BLE setup issue
│       └── Check BLE radio (Procedure J concepts, but for BLE)
│       └── Check USB crossbar is routing to QPG7015M
│       └── Check QPG7015M power (3.3V)
```

---

### PROCEDURE M: INTERMITTENT FAILURE DEBUG

For units that work sometimes but fail unpredictably. These are the hardest to debug.

```
STEP M1: CHARACTERIZE THE INTERMITTENT
├── When does it fail?
│   ├── After warming up (30+ min)? ──► Thermal-related
│   │   └── Monitor temperature during operation
│   │   └── Failure correlates with temp rise? ──► Solder joint or cap issue
│   │   └── Use thermal camera to find hot spots
│   │
│   ├── After cooling down (morning)? ──► Cold solder joint
│   │   └── Solder joint opens when cold, closes when warm
│   │   └── Flex test: gently flex board while monitoring function
│   │   └── X-ray BGA packages for cracks
│   │
│   ├── During rain/humidity? ──► Moisture-related
│   │   └── Go to Procedure H (Liquid Ingress)
│   │   └── Check for condensation inside enclosure
│   │
│   ├── Random, no pattern? ──► Continue to M2
│   └── After power events (outages, surges)? ──► Power quality
│       └── Monitor PoE input with scope for transients
│       └── Add surge protector on Ethernet run
```

```
STEP M2: STRESS TESTING
├── Thermal cycling test:
│   ├── Heat unit to 55°C (heat gun on enclosure, carefully)
│   ├── Cool to 0°C (freezer or cold spray)
│   ├── Cycle 10 times, monitoring function continuously
│   ├── Failure during heating? ──► Component opens at temp
│   ├── Failure during cooling? ──► Solder crack opens when cold
│   └── No failure? ──► Increase cycle count or range
│
├── Vibration test:
│   ├── Tap unit firmly while monitoring (UART + ping)
│   ├── Failure on tap? ──► Cracked solder joint or loose component
│   │   └── Tap different areas to localize
│   │   └── X-ray suspected area
│   └── No failure on tap? ──► Not mechanical
│
├── Power stress test:
│   ├── Vary PoE input voltage: 37V → 57V → 37V (slowly)
│   ├── Monitor all rails with scope during voltage sweep
│   ├── Any rail drops out at certain input voltage?
│   │   └── Converter marginal, check feedback loop
│   └── All rails stable across input range? ──► Power is robust
```

```
STEP M3: LONG-TERM MONITORING
├── If intermittent cannot be reproduced in lab:
│   ├── Enable all logging (UART capture, syslog)
│   ├── Monitor power rails with data logger
│   ├── Record ambient temperature continuously
│   ├── Wait for failure, then correlate logs with conditions
│   └── Common findings:
│       ├── Failure at peak temperature ──► Thermal design margin
│       ├── Failure during rain ──► Moisture ingress
│       ├── Failure at night (cold) ──► Solder joint fatigue
│       └── Failure during high traffic ──► Power budget exceeded
```


---

## 22. QUICK-REFERENCE: 9-STEP DEAD UNIT TRIAGE

For rapid triage without reading the full procedures. Follow steps 1-9 in order.

| Step | Action | Measure | Expected | If FAIL |
|------|--------|---------|----------|---------|
| 1 | Visual inspect | Eyes + loupe | No damage, no liquid | Procedure G (EOS) or H (Liquid) |
| 2 | Connect PoE | LED observation | LED on within 60s | Step 3 |
| 3 | Bench PSU 48V/100mA | Current draw | 200-500mA | 0mA→Proc B, >500mA→Proc F |
| 4 | Measure 5V rail | DMM at MPM3690 out | 4.9-5.1V | Procedure B (PoE debug) |
| 5 | Measure 0.9V | DMM at Buck 1 out | 0.85-0.95V | Procedure C (rail debug) |
| 6 | Measure 1.2V | DMM at Buck 3 out | 1.14-1.26V | Procedure C (rail debug) |
| 7 | Measure 1.8V | DMM at Buck 2 out | 1.71-1.89V | Procedure C (rail debug) |
| 8 | Connect UART | Serial terminal | Boot messages | Procedure D (boot debug) |
| 9 | Check LED state | Visual | Solid white | Procedure D/E/I/J/L |

---

## 23. VOLTAGE REFERENCE CARD

Print this and keep at your bench.

```
╔══════════════════════════════════════════════════════════════╗
║           SNOWBIRD VOLTAGE REFERENCE CARD                    ║
╠══════════════════════════════════════════════════════════════╣
║                                                              ║
║  RAIL         NOMINAL   MIN      MAX      MEASURE AT         ║
║  ──────────────────────────────────────────────────────────  ║
║  PoE Input    48.0V     37.0V    57.0V    RJ45 center tap   ║
║  5V System     5.0V      4.9V     5.1V    MPM3690 VOUT cap  ║
║  0.9V VCC_CX   0.90V     0.855V   0.945V  Buck 1 out cap   ║
║  1.2V VDD_DDR  1.20V     1.14V    1.26V   Buck 3 out cap   ║
║  2.5V VPP      2.50V     2.375V   2.625V  Buck 4 out cap   ║
║  1.8V Shared   1.80V     1.71V    1.89V   Buck 2 out cap   ║
║  1.05V Napa    1.05V     0.998V   1.103V  Buck 5 out cap   ║
║  3.3V Waikiki  3.30V     3.135V   3.465V  Buck 6 out cap   ║
║  3.3V 2.4G     3.30V     3.135V   3.465V  Buck 7 out cap   ║
║  4.2V 5G PA    4.20V     3.99V    4.41V   Buck 8 out cap   ║
║  DDR4 VREF     0.60V     0.582V   0.618V  Resistor divider ║
║  DDR4 VTT      0.60V     0.56V    0.64V   Term. regulator  ║
║                                                              ║
║  CURRENT DRAW (at 48V input):                                ║
║  Normal boot:     200-500mA                                  ║
║  Full operation:  400-650mA                                  ║
║  Max (all TX):    600-700mA                                  ║
║  Short circuit:   >1A (remove power!)                        ║
║                                                              ║
║  THERMAL LIMITS:                                             ║
║  TMP709 trip:     100°C PCB                                  ║
║  Miami max:       125°C junction                             ║
║  Waikiki max:     110°C junction                             ║
║  Max ambient:     55°C (131°F)                               ║
║                                                              ║
╚══════════════════════════════════════════════════════════════╝
```

---

## 24. KNOWN DESIGN ISSUES AND WORKAROUNDS

| # | Issue | Impact | Workaround |
|---|-------|--------|------------|
| 1 | eMMC RST_N is DNI (0-ohm not installed on GPIO20) | No hardware eMMC reset. Locked eMMC = dead unit. | Power cycle only recovery. USB boot if eMMC unresponsive. |
| 2 | TVS diodes marked "Reserve for surge test" | May NOT be populated. No surge protection on some units. | Verify TVS population on unit under test. Add external surge protector on long cable runs. |
| 3 | Reset button discharge circuit wrong threshold | False resets during power transients, incomplete resets | Hold reset >10 seconds. Verify reset behavior after power events. |
| 4 | SAW filters "wait for mass confirmation" | Part may change between batches. 2.4GHz performance may vary. | Verify SAW part number matches BOM for the specific batch. |
| 5 | Shared 1.8V rail (Waikiki analog + Napa PHY I/O) | Single point of failure kills both WiFi and Ethernet | If both WiFi and Ethernet dead simultaneously, check 1.8V rail first. |
| 6 | TMP709 threshold 100°C with 45°C headroom at max ambient | Thermal throttling expected in hot climates with direct sun | Install in shade. Thermal margin is zero at rated max ambient + full load. |
| 7 | Max power draw (33W) exceeds PoE+ budget (30W) | Relies on software power management to prevent simultaneous full TX | If power management fails, PoE injector may shut down. |

---

## 25. EFFA FIELD DATA CORRELATION

Based on actual Snowbird field return data (EFFA tickets):

| Failure Category | % of Real Failures | Top Root Cause | Procedure |
|-----------------|-------------------|----------------|-----------|
| Liquid Ingress | 40% | M22 gland improper install | Procedure H |
| EIPD/EOS | 20% | PoE surge, lightning | Procedure G |
| Cloud Registration | 20% | QC bug CONN-45729 | Procedure L |
| Exothermic/Thermal | 20% | Thermal runaway, cap failure | Procedure C + thermal |
| eMMC Failure | 10% | Flash corruption, wear-out | Procedure D, Step D3/D5 |

**Note**: Percentages exceed 100% because some units have multiple failure modes.

**Field Return Statistics** (from CSV data analysis):
- Real failures: 16.1% of returns
- NTF (No Trouble Found): 14.5% of returns
- Won't Do (never returned for analysis): 69.4% of returns

---

## APPENDIX A: ACRONYMS

| Acronym | Meaning |
|---------|---------|
| BGA | Ball Grid Array |
| BLE | Bluetooth Low Energy |
| BPF | Band Pass Filter |
| CTE | Coefficient of Thermal Expansion |
| DAA | Dead After Arrival (failed in field after working) |
| DFMEA | Design Failure Mode and Effects Analysis |
| DMM | Digital Multimeter |
| DNI | Do Not Install |
| DOA | Dead On Arrival (never worked from factory) |
| EFFA | eero Field Failure Analysis |
| EIPD | Electrically Induced Physical Damage |
| EOS | Electrical Overstress |
| ESD | Electrostatic Discharge |
| ESR | Equivalent Series Resistance |
| FEM | Front End Module |
| IPA | Internal Power Amplifier |
| KGU | Known Good Unit |
| LNA | Low Noise Amplifier |
| MDIO | Management Data Input/Output |
| MLCC | Multi-Layer Ceramic Capacitor |
| NTF | No Trouble Found |
| PA | Power Amplifier |
| PBL | Primary Boot Loader |
| PCIe | Peripheral Component Interconnect Express |
| PD | Powered Device (PoE) |
| PoE | Power over Ethernet |
| PSU | Power Supply Unit (Goldfinch) |
| RPN | Risk Priority Number (Severity × Occurrence × Detection) |
| SBL | Secondary Boot Loader |
| SGMII | Serial Gigabit Media Independent Interface |
| SPBM | Smart Power and Boot Manager |
| TDR | Time Domain Reflectometry |
| TVS | Transient Voltage Suppressor |
| UART | Universal Asynchronous Receiver/Transmitter |
| VSWR | Voltage Standing Wave Ratio |

## APPENDIX B: RECOMMENDED TEST EQUIPMENT

| Equipment | Recommended Model | Purpose |
|-----------|------------------|---------|
| DMM | Fluke 87V or Keysight U1282A | Voltage, resistance, diode test |
| Oscilloscope | Keysight DSOX1204G (4ch, 200MHz) | Signal analysis, ripple, timing |
| Bench PSU | Keysight E36312A (triple output) | Controlled power-on, current limit |
| Thermal Camera | FLIR C5 or E8 Pro | Hot spot detection |
| Microscope | AmScope SM-4TZ-144A | Visual inspection, solder joints |
| Network Analyzer | NanoVNA V2 (budget) or Keysight E5063A | RF path, VSWR, insertion loss |
| Logic Analyzer | Saleae Logic Pro 16 | I2C, SPI, UART decode |
| Cable Tester | Fluke DSX-5000 | Ethernet cable certification |
| X-ray | Nordson Dage (if available) | BGA inspection |
| Freeze Spray | MG Chemicals 403A | Cold-related intermittent isolation |

---

*End of Snowbird Hardware Debug Bible v1.0*
*Document covers all 20 schematic pages, 18 failure modes, 13 debug procedures, and 30+ FMEA items.*