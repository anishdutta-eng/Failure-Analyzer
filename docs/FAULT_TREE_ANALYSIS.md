# Fault Tree Analysis (FTA) Implementation

## Overview

The Fault Tree Analysis implementation follows industry-standard FTA methodology for electronics failure analysis. It provides a top-down, deductive analysis of system failures.

## FTA Methodology

### Structure
```
Level 0: Top Event (System Failure)
    ↓
Level 1: Intermediate Events (Failure Categories)
    ↓
Level 2: Basic Events (Root Causes)
```

### Principles

1. **Top-Down Deductive Analysis**
   - Starts with undesired top event (system failure)
   - Breaks down into intermediate events (categories)
   - Identifies basic events (root causes)

2. **Boolean Logic**
   - Uses AND/OR gates (implicit in categorization)
   - Shows failure paths and combinations
   - Visualizes cascading effects

3. **Hierarchical Categorization**
   - Hardware Failures
   - Software Failures
   - Environmental Failures
   - Power Failures
   - Installation Failures

## Implementation Details

### Automatic Categorization

The system automatically categorizes root causes based on keywords:

#### Hardware Failures
Keywords: eMMC, component, capacitor, solder, PCB, hardware, EIPD, EOS
- Component failures
- PCB issues
- Solder joint problems
- Electrical overstress

#### Software Failures
Keywords: firmware, software, cloud, registration, certificate
- Firmware corruption
- Cloud connectivity
- Software bugs
- Configuration issues

#### Environmental Failures
Keywords: liquid, ingress, temperature, thermal, moisture, corrosion
- Liquid ingress
- Temperature extremes
- Moisture damage
- Corrosion

#### Power Failures
Keywords: PoE, power, voltage, electrical
- PoE delivery issues
- Voltage problems
- Power supply failures

#### Installation Failures
Keywords: mount, bracket, installation, setup
- Mounting issues
- Installation errors
- Setup problems

### Visualization

Uses **Sunburst Diagram** (recommended for fault trees):
- Center: Top Event (System Failure)
- Inner Ring: Intermediate Events (Categories)
- Outer Ring: Basic Events (Root Causes)

**Color Coding:**
- 🔴 Red: Top Event (System Failure)
- 🔵 Teal: Intermediate Events (Categories)
- 🟢 Light Teal: Basic Events (Root Causes)

### Features

1. **Interactive Exploration**
   - Click to zoom into categories
   - Hover for detailed counts
   - Percentage of parent shown

2. **Proportional Sizing**
   - Size represents failure count
   - Easy identification of major contributors
   - Visual impact assessment

3. **Top 5 Limiting**
   - Shows top 5 root causes per category
   - Prevents overcrowding
   - Focuses on critical issues

## Usage

### In Dashboard
Navigate to "Fault Tree Analysis" section to see:
- Hierarchical failure breakdown
- Category-wise distribution
- Root cause identification

### Interpretation

1. **Top Event Size**: Total system failures
2. **Category Sizes**: Relative contribution of each failure type
3. **Root Cause Sizes**: Specific failure frequency

### Example Analysis

```
System Failure (62 cases)
├── Hardware Failures (35 cases)
│   ├── eMMC corruption (15)
│   ├── Capacitor failure (10)
│   ├── Solder joint (5)
│   ├── EIPD (3)
│   └── Component damage (2)
├── Environmental Failures (15 cases)
│   ├── Liquid ingress (10)
│   └── Thermal (5)
├── Software Failures (8 cases)
│   └── Cloud registration (8)
└── Power Failures (4 cases)
    └── PoE issues (4)
```

**Interpretation:**
- Hardware failures are the dominant category (56%)
- eMMC corruption is the #1 root cause
- Environmental failures are significant (24%)
- Focus improvement efforts on hardware reliability

## FTA Best Practices

### 1. Regular Updates
- Update as new failures are identified
- Refine categorization based on patterns
- Track trends over time

### 2. Root Cause Focus
- Drill down to true root causes
- Avoid symptom-level analysis
- Use "5 Whys" technique

### 3. Quantitative Analysis
- Track failure rates
- Calculate probabilities
- Prioritize by frequency

### 4. Corrective Actions
- Address high-frequency root causes first
- Implement preventive measures
- Verify effectiveness

## Integration with DFMEA

FTA complements DFMEA:
- **DFMEA**: Proactive (design phase)
- **FTA**: Reactive (field data)

Together they provide:
- Design risk assessment (DFMEA)
- Field failure validation (FTA)
- Continuous improvement loop

## Technical Details

### Data Requirements
- Root_Cause_Reason field populated
- Sufficient failure cases (>5 recommended)
- Excludes "Won't do" cases

### Categorization Algorithm
1. Extract root causes from data
2. Analyze keywords in each cause
3. Assign to appropriate category
4. Calculate totals per category
5. Build hierarchical structure
6. Generate visualization

### Limitations
- Requires meaningful root cause descriptions
- Keyword-based categorization may need tuning
- Limited to top 5 causes per category for clarity

## Future Enhancements

1. **Boolean Gates**: Add explicit AND/OR gate visualization
2. **Probability Calculation**: Compute failure probabilities
3. **Cut Sets**: Identify minimal cut sets
4. **Importance Measures**: Calculate component importance
5. **Time-Based Analysis**: Track failure rate trends
6. **Multi-Level Trees**: Support deeper hierarchies

## References

- FTA follows ISO 31010 risk assessment standard
- Based on aerospace/electronics industry practices
- Implements top-down deductive methodology
- Uses Boolean logic principles
- Provides visual failure path analysis

## Benefits

1. **Visual Clarity**: Easy to understand failure relationships
2. **Prioritization**: Identifies major contributors
3. **Root Cause Focus**: Drills down to basic events
4. **Quantitative**: Provides failure counts and percentages
5. **Actionable**: Guides improvement efforts
6. **Comprehensive**: Covers all failure categories

---

**Note**: The fault tree automatically updates when new data is loaded. Categories and root causes are dynamically generated from your field return data.
