# Intelligent Triage Assistant Guide

## Overview

The enhanced Triage Assistant is a technical failure analysis tool specifically designed for the eero Outdoor 7 (Snowbird) - an outdoor WiFi 7 access point. It uses machine learning, pattern recognition, and a comprehensive technical knowledge base to provide detailed triage recommendations.

## Product: eero Outdoor 7 (Snowbird)

### Technical Specifications
- **Type:** Outdoor WiFi 7 Access Point
- **Rating:** IP66 (dust-tight, water-resistant)
- **Operating Temperature:** -40°F to 131°F (-40°C to 55°C)
- **WiFi:** Dual-band WiFi 7 (2.4GHz/5GHz), 2x2 MIMO
- **Speed:** Up to 2.1 Gbps aggregate throughput
- **Coverage:** ~15,000 sq ft outdoor
- **Power:** PoE+ (802.3at), 30W outdoor injector
- **Ethernet:** 2.5 GbE port
- **Storage:** eMMC flash memory
- **Devices:** 100+ concurrent connections

### Common Failure Modes

1. **eMMC Corruption**
   - Causes: Power loss during write, flash wear-out, temperature extremes
   - Symptoms: DAA, boot failure, firmware corruption
   - Resolution: Firmware reload, eMMC replacement

2. **Liquid Ingress**
   - Causes: Improper M22 gland sealing, incorrect orientation
   - Symptoms: DAA, corrosion, intermittent operation
   - Resolution: Verify IP66 seal, check orientation

3. **EIPD/EOS (Electrical Overstress)**
   - Causes: Lightning strike, PoE surge, incorrect voltage
   - Symptoms: Component damage, burn marks, no power
   - Resolution: Replace unit, investigate power source

4. **Cloud Registration Failure**
   - Causes: QC bug (CONN-45729), cloud key mismatch
   - Symptoms: Stuck flashing blue LED
   - Resolution: Re-provision keys, firmware update

5. **Performance Issues**
   - Causes: Environmental factors, interference, firmware bugs
   - Symptoms: Slow speeds, poor coverage
   - Resolution: Environment assessment, firmware update

## New Features

### 1. Technical Keyword Search
Search historical data for specific technical terms:
- **Memory issues:** eMMC, flash, corruption, NAND
- **Power issues:** PoE, voltage, injector, electrical
- **Connectivity:** cloud, registration, network, WiFi
- **Environmental:** liquid, water, temperature, thermal
- **Hardware:** component, EIPD, EOS, damage
- **Performance:** throughput, speed, coverage

**Example searches:**
- "eMMC, corruption" - Find all memory-related failures
- "liquid ingress" - Find water damage cases
- "CONN-45729" - Find specific JIRA ticket cases

### 2. LED Status Code Reference
Built-in reference for all eero LED indicators:
- **Solid White:** Normal operation
- **Flashing White:** Booting/connecting
- **Solid Blue:** Setup mode
- **Flashing Blue:** Bluetooth pairing
- **Solid Green:** Optimal operation
- **Flashing Yellow:** Soft reset/weak connection
- **Solid Yellow:** No internet
- **Flashing Red:** No internet detected
- **Solid Red:** Critical error
- **No Light:** No power/hardware failure

### 3. Failure Mode Identification
Automatically identifies likely failure modes based on symptoms and provides:
- Typical symptoms for each mode
- Likely root causes
- Required diagnostic tests
- Resolution paths

### 4. Enhanced Technical Triage Procedures

#### DAA (Dead After Arrival) Protocol
- PoE+ power delivery verification (802.3at, 30W)
- Known-good PoE injector testing
- Ethernet cable testing (Cat5e/Cat6, max 100m)
- PoE voltage measurement (48-57V DC)
- UART console boot sequence analysis
- eMMC corruption detection
- EIPD visual inspection
- FTIR analysis for liquid contamination

#### LED Status Analysis
- Flashing Blue: Cloud registration (CONN-45729 bug check)
- Flashing White: Boot/connection issues
- Includes specific JIRA ticket references

#### Performance Analysis
- Wireless performance testing (iperf3)
- KGU baseline comparison
- RSSI and SNR measurement
- Spectrum analysis (2.4GHz/5GHz)
- Interference detection
- Firmware bug checks (CONN-47911)

#### eMMC Flash Memory Analysis
- Firmware corruption detection (LUX-10289)
- Temperature history review
- Firmware reload via recovery mode
- Bad block detection
- ECC status verification
- Wear leveling metrics

#### Liquid Ingress Investigation
- Unit orientation verification
- M22 gland seal inspection
- IP66 seal integrity testing
- FTIR residue analysis
- Controlled liquid exposure testing

#### Safety Critical - Exothermic Events
- Immediate isolation protocol
- SAFETY ticket filing (e.g., SAFETY-125)
- Thermal damage documentation
- Separate PSU and unit testing
- Outlet/power source inspection
- Lab failure analysis

## Usage

### Step 1: Technical Keyword Search
1. Enter keywords: "eMMC, memory, corruption"
2. Click "Search"
3. Review matching cases with JIRA tickets
4. Note patterns and resolutions

### Step 2: Enter Symptom Details
Be specific and technical:
- LED status and behavior
- Environmental conditions
- Power source details
- Error messages or codes
- Physical observations

**Good example:**
"Unit DAA, stuck flashing blue LED during cloud registration. Using Goldfinch 30W PoE+ adapter. Ambient temp ~85°F. M22 gland properly sealed. No physical damage visible."

### Step 3: Analyze
Click "Analyze & Generate Technical Triage Plan" to get:
- Priority level (Critical/High/Medium/Low)
- Estimated category (SW/HW/Mixed)
- ML prediction with confidence score
- Identified failure modes with details
- Step-by-step technical procedure
- Similar historical cases
- Related JIRA tickets

### Step 4: Follow Technical Procedure
Execute the generated triage steps:
1. Initial assessment
2. Environmental & physical inspection
3. Failure mode-specific tests
4. Symptom-specific diagnostics
5. Category-specific analysis
6. Documentation & escalation
7. Customer communication

## Technical Terminology

### Acronyms
- **DAA:** Dead After Arrival
- **EIPD:** Electrically Induced Physical Damage
- **EOS:** Electrical Overstress
- **eMMC:** Embedded MultiMediaCard (flash storage)
- **PoE+:** Power over Ethernet Plus (802.3at, up to 30W)
- **FTIR:** Fourier Transform Infrared Spectroscopy
- **ECC:** Error Correction Code
- **UART:** Universal Asynchronous Receiver-Transmitter
- **RSSI:** Received Signal Strength Indicator
- **SNR:** Signal-to-Noise Ratio
- **KGU:** Known Good Unit (baseline reference)

### JIRA Ticket Patterns
- **EFFA-xxxx:** Field Failure Analysis tickets
- **CONN-xxxx:** Connectivity issues
- **INCIDENT-xxxx:** Incident reports
- **LUX-xxxx:** Luxshare (CM) tickets
- **SAFETY-xxxx:** Safety-critical issues

## Best Practices

### For Accurate Diagnosis
1. **Be specific:** Include exact LED patterns, not just "LED issue"
2. **Include environment:** Temperature, weather, installation location
3. **Document power:** PoE injector model, voltage measurements
4. **Note timing:** When did failure occur? After what event?
5. **Physical inspection:** Seal integrity, damage, corrosion

### Technical Investigation
1. **Start with power:** Verify PoE+ delivery before other tests
2. **Check seals:** M22 gland is common failure point
3. **Review JIRA:** Search for known bugs before deep dive
4. **Compare to KGU:** Baseline performance comparison
5. **Document everything:** Photos, measurements, logs

### Known Issues to Check
- **CONN-45729:** Cloud key mismatch (QC bug)
- **INCIDENT-754:** Related to CONN-45729
- **CONN-47911:** Throughput/performance issues
- **LUX-10203:** Mounting bracket insertion force
- **LUX-10289:** eMMC firmware corruption
- **LUX-10613:** EIPD/EOS issues

## Advanced Features

### Failure Mode Confidence Scoring
The system scores each failure mode based on:
- Symptom keyword matches (2 points each)
- Cause keyword matches (1 point each)
- Historical pattern frequency

### Similar Case Matching
Uses TF-IDF vectorization and cosine similarity to find:
- Top 5 most similar historical cases
- Similarity scores (0-100%)
- Complete case details and resolutions

### ML Prediction
Random Forest classifier trained on:
- Return reason codes
- Comments and descriptions
- Root cause reasons
- Provides confidence scores

## Troubleshooting

### "Not enough training data"
- Need minimum 5 cases with documented root causes
- Ensure Root_Cause_Reason column is populated
- Add more resolved cases to CSV

### Low confidence predictions
- Symptom may be unique or poorly documented
- Try technical keyword search instead
- Review similar cases manually

### No JIRA tickets found
- Tickets may not be filed yet
- Check for "Won't do" status
- Search by symptom category instead

## Future Enhancements

1. **Real-time JIRA integration:** Auto-pull ticket details
2. **Automated test procedures:** Generate test scripts
3. **Thermal analysis:** Temperature logging integration
4. **Multi-program comparison:** Cross-program pattern analysis
5. **Predictive maintenance:** Failure prediction before occurrence
6. **Cost analysis:** Triage time and resource estimation

## How It Works

### 1. **Pattern Recognition**
- Analyzes historical failure data to identify patterns
- Maps symptoms to root causes using past cases
- Learns from resolved tickets and their outcomes

### 2. **Machine Learning Model**
- Uses Random Forest Classifier trained on your historical data
- Combines symptom descriptions, return reasons, and comments
- Provides confidence scores for predictions

### 3. **Similarity Matching**
- Finds similar past cases using TF-IDF vectorization
- Calculates cosine similarity between current and historical symptoms
- Shows top 5 most similar cases with their resolutions

### 4. **Rule-Based Logic**
- Applies expert rules for specific symptom patterns
- Generates step-by-step triage procedures
- Determines priority levels (Critical, High, Medium, Low)

## Features

### Symptom Analysis
Enter a description of the issue and the tool will:
- Predict the most likely root cause
- Estimate if it's SW or HW related
- Assign a priority level
- Generate specific triage steps

### Similar Case Lookup
- Shows historical cases with similar symptoms
- Displays their root causes and resolutions
- Links to related JIRA tickets
- Shows SW/HW categorization

### Triage Recommendations
Generates customized triage steps based on:
- **DAA (Dead on Arrival)**: Power, connections, physical damage checks
- **LED/Flashing Issues**: Cloud connectivity, firmware, registration
- **Performance Issues**: Wireless tests, interference, baseline comparison
- **Setup Issues**: Installation verification, mounting, activation
- **Connectivity Issues**: Ethernet, PoE, network configuration

### Priority Determination
- **Critical**: Safety issues (fire, smoke, exothermic events)
- **High**: Widespread impact or safety-adjacent issues
- **Medium**: Standard failures (DAA, not working)
- **Low**: Performance, cosmetic issues

## Usage

### Step 1: Load Data
Upload your CSV file in the main dashboard. The system will automatically:
- Load historical data
- Build symptom patterns
- Train the ML model

### Step 2: Switch to Triage View
In the sidebar, select "🔧 Triage Assistant"

### Step 3: Enter Symptom
- Describe the issue in detail
- Select a return reason category (optional)
- Add unit serial number (optional)

### Step 4: Analyze
Click "Analyze & Generate Triage Plan" to get:
- Priority level
- Estimated category (SW/HW)
- ML prediction with confidence
- Step-by-step triage procedure
- Similar historical cases
- Related JIRA tickets

### Step 5: Quick Lookup
Use the "Quick Symptom Lookup" to browse known symptoms and their historical patterns

## Best Practices

### For Accurate Predictions
1. **Provide detailed descriptions**: More context = better predictions
2. **Use consistent terminology**: Match language used in historical data
3. **Include specific symptoms**: "Stuck flashing blue" vs "LED issue"
4. **Add environmental context**: Installation conditions, power source, etc.

### Building Better Models
1. **Keep data updated**: Regularly upload new cases
2. **Document root causes**: More resolved cases = better predictions
3. **Standardize categories**: Use consistent return reason codes
4. **Add detailed comments**: Rich descriptions improve pattern matching

### Interpreting Results
- **High confidence (>70%)**: Strong pattern match, follow recommendation
- **Medium confidence (40-70%)**: Multiple possibilities, investigate similar cases
- **Low confidence (<40%)**: Unique case, rely more on similar case analysis

## Technical Details

### Machine Learning Approach
- **Algorithm**: Random Forest Classifier (100 trees)
- **Features**: TF-IDF vectors from combined text (return reason + comments + root cause)
- **Training**: Requires minimum 5 cases with known root causes
- **Validation**: Uses historical case similarity as validation

### Similarity Calculation
- **Method**: Cosine similarity on TF-IDF vectors
- **Threshold**: 0.1 minimum similarity score
- **Top N**: Shows 5 most similar cases

### Pattern Database
- Symptom → Root Cause mapping
- SW/HW categorization statistics
- JIRA ticket associations
- Historical comment analysis

## Extending the System

### Adding New Programs
The triage assistant automatically adapts to new programs:
1. Upload CSV with same format
2. System learns new patterns
3. Model retrains on new data

### Custom Triage Rules
Edit `triage_assistant.py` → `_generate_triage_steps()` to add:
- Program-specific procedures
- Custom symptom patterns
- Company-specific workflows

### Integration with JIRA
Future enhancement: Direct JIRA API integration for:
- Auto-filing tickets
- Pulling related bug information
- Updating ticket status

## Example Scenarios

### Scenario 1: DAA Issue
**Input**: "Unit dead on arrival, no LED lights, tried multiple power sources"

**Output**:
- Priority: Medium
- Category: Hardware
- Predicted: Liquid ingress or EIPD
- Steps: Power verification, physical inspection, liquid ingress check
- Similar: 3 cases with liquid ingress, 2 with EIPD

### Scenario 2: Connectivity Issue
**Input**: "Stuck flashing blue, cannot register to cloud"

**Output**:
- Priority: Medium
- Category: Software
- Predicted: Cloud registration (CONN-45729)
- Steps: Check cloud keys, verify QC process, firmware check
- Similar: 2 cases with CONN-45729 bug

### Scenario 3: Performance Issue
**Input**: "Poor WiFi performance, slow speeds in metal shed"

**Output**:
- Priority: Low
- Category: Hardware/Environmental
- Predicted: No Failure Found
- Steps: Wireless testing, interference check, environment assessment
- Similar: 4 cases with similar KGU performance

## Troubleshooting

### "Not enough training data"
- Need at least 5 cases with documented root causes
- Add more resolved cases to your CSV
- Ensure Root_Cause_Reason column is populated

### Low prediction confidence
- Add more similar historical cases
- Improve symptom descriptions
- Standardize terminology across cases

### No similar cases found
- Symptom might be unique/new
- Check spelling and terminology
- Try broader symptom descriptions

## Future Enhancements

1. **Deep Learning**: Neural networks for better pattern recognition
2. **Real-time Learning**: Update model as new cases are resolved
3. **Multi-program Comparison**: Cross-program pattern analysis
4. **Automated Testing**: Suggest specific test procedures
5. **Cost Estimation**: Predict triage time and resources needed
6. **Warranty Analysis**: Factor in warranty status and coverage
