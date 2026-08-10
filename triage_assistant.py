import streamlit as st
import pandas as pd
import numpy as np
from sklearn.feature_extraction.text import TfidfVectorizer
from sklearn.metrics.pairwise import cosine_similarity
from program_config import get_selected_program
from sklearn.ensemble import RandomForestClassifier
from sklearn.linear_model import LogisticRegression
from sklearn.model_selection import cross_val_score, StratifiedKFold
from sklearn.preprocessing import LabelEncoder
import pickle
import re
from collections import Counter
import plotly.graph_objects as go
import plotly.express as px


# Domain normalization: expand abbreviations and collapse key multi-word
# phrases into single tokens so the vectorizer treats them as one strong
# signal (e.g. "flashing blue" -> the cloud-registration failure). Applied to
# both the training corpus and the query so they share the same vocabulary.
NORMALIZATION_PHRASES = [
    ("dead after arrival", " daa dead_after_arrival "),
    ("dead on arrival", " doa dead_on_arrival "),
    ("flashing blue", " flashing_blue cloud_registration "),
    ("blinking blue", " flashing_blue cloud_registration "),
    ("solid blue", " solid_blue setup_mode "),
    ("flashing white", " flashing_white boot_connection "),
    ("blinking white", " flashing_white boot_connection "),
    ("liquid ingress", " liquid_ingress moisture "),
    ("water ingress", " liquid_ingress moisture "),
    ("water damage", " liquid_ingress moisture "),
    ("cold boot", " cold_boot solder_joint intermittent "),
    ("thermal cycling", " thermal_cycling solder_joint "),
    ("cloud registration", " cloud_registration "),
    ("no power", " no_power dead "),
    ("won't boot", " no_boot "),
    ("wont boot", " no_boot "),
    ("no boot", " no_boot "),
    ("boot loop", " boot_loop "),
    ("power cycle", " power_cycle reboot "),
]

# Whole-word abbreviation expansions (word-boundary matched so we don't touch
# substrings inside other words).
NORMALIZATION_WORDS = {
    "daa": "daa dead_after_arrival",
    "doa": "doa dead_on_arrival",
    "emmc": "emmc flash_memory",
    "poe": "poe power_over_ethernet",
    "eos": "eos electrical_overstress",
    "eipd": "eipd electrical_overstress physical_damage",
    "esd": "esd electrical_overstress",
    "vswr": "vswr antenna rf",
    "esr": "esr capacitor",
    "bulging": "bulging capacitor",
    "burst": "burst capacitor",
    "ripple": "ripple capacitor",
}


# Values that appear in the Root_Cause_Reason column but are not real root
# causes (placeholders / SW-HW flags leaking in). Excluded from training and
# from the kNN vote so they can't be predicted.
JUNK_LABELS = {
    '', 'nan', 'none', 'no', 'yes', 'na', 'n/a', 'unknown', 'tbd', 'todo',
    'to do', "won't do", 'wont do', '-', '?', 'pending', 'n/a',
}


def canonical_label_key(s: str) -> str:
    """Normalized key used to merge label variants that differ only by
    whitespace/case (e.g. 'Liquid ingress' and 'Liquid Ingress')."""
    return re.sub(r"\s+", " ", str(s).strip()).lower()


def normalize_text(text: str) -> str:
    """Lowercase and expand domain synonyms/abbreviations. Shared by the
    training corpus and the query so both map into the same vocabulary."""
    if text is None:
        return ""
    t = " " + str(text).lower() + " "
    for phrase, repl in NORMALIZATION_PHRASES:
        t = t.replace(phrase, repl)
    def _sub_word(m):
        return NORMALIZATION_WORDS[m.group(0)]
    if NORMALIZATION_WORDS:
        pattern = r"\b(" + "|".join(re.escape(w) for w in NORMALIZATION_WORDS) + r")\b"
        t = re.sub(pattern, _sub_word, t)
    return re.sub(r"\s+", " ", t).strip()

class TriageAssistant:
    def __init__(self):
        # Richer vocabulary + bigrams capture multi-word failure signatures
        # ("flashing blue", "liquid ingress"). sublinear_tf dampens repeated
        # terms so long comments don't dominate.
        self.vectorizer = TfidfVectorizer(
            max_features=4000,
            ngram_range=(1, 2),
            stop_words='english',
            sublinear_tf=True,
            min_df=1,
        )
        self.model = None                 # active classifier (kept for API compat)
        self.label_encoder = LabelEncoder()
        self.df = None
        self.symptom_patterns = {}
        self.historical_vectors = None    # cached TF-IDF matrix of the leakage-free corpus
        self.corpus_root_causes = None    # root cause aligned to each corpus row (for kNN vote)
        self.cv_accuracy = None           # cross-validated accuracy estimate
        self.model_type = None
        self.n_training_cases = 0
        
        # Technical knowledge base for eero Outdoor (Snowbird)
        self.technical_specs = {
            'product': 'eero Outdoor 7 (Snowbird)',
            'type': 'Outdoor WiFi 7 Access Point',
            'rating': 'IP66 (dust-tight, water-resistant)',
            'temp_range': '-40°F to 131°F (-40°C to 55°C)',
            'wifi': 'Dual-band WiFi 7 (2.4GHz/5GHz), 2x2 MIMO',
            'speed': 'Up to 2.1 Gbps aggregate',
            'coverage': '~15,000 sq ft outdoor',
            'power': 'PoE+ (802.3at), 30W outdoor injector',
            'ethernet': '2.5 GbE port',
            'devices': '100+ concurrent connections',
            'storage': 'eMMC flash memory',
            'security': 'WPA3, TrueMesh, automatic updates'
        }
        
        # Technical failure mode database with DFMEA analysis
        self.failure_modes = {
            'daa': {  # Dead After Arrival
                'name': 'DAA (Dead After Arrival)',
                'symptoms': ['DAA', 'dead after arrival', 'no power', 'no boot', 'completely dead'],
                'causes': ['Power supply failure', 'eMMC corruption', 'Component damage', 'Liquid ingress', 'Manufacturing defect'],
                'severity': 9,  # DFMEA: Critical - no function
                'occurrence': 3,  # Medium occurrence
                'detection': 2,  # Easy to detect
                'rpn': 54,  # Risk Priority Number
                'tests': ['PoE power verification', 'Boot sequence analysis', 'Component inspection', 'Liquid ingress check'],
                'resolution': 'Systematic power-on diagnostics, component-level analysis'
            },
            'doa': {  # Dead On Arrival
                'name': 'DOA (Dead On Arrival)',
                'symptoms': ['DOA', 'dead on arrival', 'never worked', 'factory defect'],
                'causes': ['Manufacturing defect', 'Shipping damage', 'QC escape', 'Component failure'],
                'severity': 10,  # DFMEA: Critical - customer impact
                'occurrence': 2,  # Low occurrence (QC should catch)
                'detection': 1,  # Very easy to detect
                'rpn': 20,
                'tests': ['Factory test verification', 'Visual inspection', 'Power-on test'],
                'resolution': 'RMA replacement, root cause analysis at factory'
            },
            'emmc_corruption': {
                'name': 'eMMC Flash Memory Failure',
                'symptoms': ['eMMC', 'memory', 'flash', 'corruption', 'boot failure', 'firmware'],
                'causes': ['Power loss during write', 'Flash wear-out', 'Bad blocks', 'ECC errors', 'Temperature extremes', 'Voltage instability'],
                'severity': 8,  # DFMEA: High - data loss, no boot
                'occurrence': 4,  # Medium-high (known issue)
                'detection': 4,  # Requires diagnostic tools
                'rpn': 128,
                'tests': ['Boot sequence analysis', 'UART console logs', 'eMMC health check', 'Bad block scan', 'ECC error count'],
                'resolution': 'Firmware reload, eMMC replacement if persistent'
            },
            'capacitor_failure': {
                'name': 'Capacitor Failure (Electrolytic)',
                'symptoms': ['capacitor', 'bulging', 'burst', 'leaking', 'power instability', 'ripple'],
                'causes': ['Electrolyte dry-out', 'Temperature >85°C', 'Overvoltage', 'Reverse polarity', 'End of life', 'Ripple current'],
                'severity': 7,  # DFMEA: High - power supply failure
                'occurrence': 5,  # Medium-high (outdoor temp extremes)
                'detection': 3,  # Visual inspection or ESR test
                'rpn': 105,
                'tests': ['Visual inspection for bulging/leakage', 'ESR measurement', 'Capacitance test', 'Ripple voltage check', 'Thermal imaging'],
                'resolution': 'Replace failed capacitors, review thermal design'
            },
            'solder_joint_failure': {
                'name': 'Solder Joint Failure',
                'symptoms': ['intermittent', 'cold boot', 'connection loss', 'thermal cycling'],
                'causes': ['Thermal cycling fatigue', 'CTE mismatch', 'Mechanical stress', 'Vibration', 'Poor solder quality', 'Moisture'],
                'severity': 6,  # DFMEA: Medium-high - intermittent failure
                'occurrence': 6,  # High (outdoor thermal cycling)
                'detection': 6,  # Difficult - intermittent
                'rpn': 216,
                'tests': ['X-ray inspection', 'Thermal cycling test', 'Vibration test', 'Visual inspection under magnification'],
                'resolution': 'Rework solder joints, improve thermal design'
            },
            'liquid_ingress': {
                'name': 'Liquid Ingress / Moisture Damage',
                'symptoms': ['liquid', 'water', 'ingress', 'corrosion', 'moisture', 'condensation'],
                'causes': ['Improper M22 gland sealing', 'Incorrect orientation', 'Physical damage to enclosure', 'Condensation', 'IP66 seal failure'],
                'severity': 8,  # DFMEA: High - corrosion, shorts
                'occurrence': 4,  # Medium (installation dependent)
                'detection': 3,  # Visual inspection
                'rpn': 96,
                'tests': ['Visual inspection', 'FTIR analysis', 'Moisture detection', 'Seal integrity check', 'Corrosion analysis'],
                'resolution': 'Verify IP66 seal, check orientation, replace if damaged'
            },
            'eipd_eos': {
                'name': 'EIPD/EOS (Electrical Overstress)',
                'symptoms': ['EIPD', 'EOS', 'burn', 'component damage', 'overvoltage', 'surge'],
                'causes': ['Electrical overstress', 'Lightning strike', 'PoE surge', 'Incorrect voltage', 'ESD event', 'Power transient'],
                'severity': 9,  # DFMEA: Critical - component destruction
                'occurrence': 3,  # Medium (outdoor exposure)
                'detection': 2,  # Visual damage
                'rpn': 54,
                'tests': ['Component leakage test', 'Visual inspection', 'Power supply verification', 'TI chip analysis', 'Surge protection check'],
                'resolution': 'Replace unit, investigate power source, improve surge protection'
            },
            'cloud_registration': {
                'name': 'Cloud Registration Failure',
                'symptoms': ['cloud', 'registration', 'stuck flashing blue', 'setup failure', 'cannot connect', 'provisioning'],
                'causes': ['QC bug (CONN-45729)', 'Cloud key mismatch', 'Certificate error', 'Network blocking', 'Firmware bug'],
                'severity': 5,  # DFMEA: Medium - functionality limited
                'occurrence': 4,  # Medium (known bug)
                'detection': 2,  # LED indicator
                'rpn': 40,
                'tests': ['Cloud key verification', 'Certificate check', 'Network connectivity', 'Firewall rules', 'Firmware version check'],
                'resolution': 'Re-provision keys, firmware update, network configuration'
            },
            'poor_performance': {
                'name': 'RF/Wireless Performance Degradation',
                'symptoms': ['performance', 'throughput', 'slow', 'poor coverage', 'dropouts', 'interference'],
                'causes': ['Environmental factors', 'Interference', 'Antenna issues', 'Firmware bugs', 'RF path damage', 'Component drift'],
                'severity': 4,  # DFMEA: Low-medium - degraded function
                'occurrence': 5,  # Medium-high
                'detection': 5,  # Requires testing
                'rpn': 100,
                'tests': ['Wireless performance test', 'Spectrum analysis', 'Compare to KGU baseline', 'SNR measurement', 'Antenna inspection'],
                'resolution': 'Environment assessment, firmware update, antenna check'
            },
            'poe_power': {
                'name': 'PoE Power Delivery Failure',
                'symptoms': ['PoE', 'power', 'no power', 'intermittent power', 'LED off', 'reboots', 'brownout'],
                'causes': ['PoE injector failure', 'Cable issues', 'Voltage drop', 'Power budget exceeded', 'Connector corrosion', 'Cable length >100m'],
                'severity': 8,  # DFMEA: High - no power
                'occurrence': 4,  # Medium
                'detection': 3,  # Voltage measurement
                'rpn': 96,
                'tests': ['PoE voltage test', 'Cable continuity', 'Injector output', 'Power consumption measurement', 'Connector inspection'],
                'resolution': 'Replace injector, check cable, verify PoE+ compatibility'
            },
            'thermal': {
                'name': 'Thermal Management Failure',
                'symptoms': ['overheating', 'thermal shutdown', 'performance degradation', 'hot', 'temperature'],
                'causes': ['Extreme ambient temp', 'Direct sunlight', 'Poor ventilation', 'Component failure', 'Thermal paste degradation'],
                'severity': 6,  # DFMEA: Medium-high - reliability impact
                'occurrence': 5,  # Medium-high (outdoor)
                'detection': 4,  # Temperature monitoring
                'rpn': 120,
                'tests': ['Temperature logging', 'Thermal imaging', 'Ambient measurement', 'Stress test', 'Thermal resistance check'],
                'resolution': 'Relocate unit, add shading, verify within spec range'
            },
            'mounting_mechanical': {
                'name': 'Mechanical/Mounting Failure',
                'symptoms': ['setup issue', 'physical damage', 'connector problems', 'mounting', 'bracket'],
                'causes': ['Excessive insertion force', 'Bracket design', 'Installation error', 'Vibration', 'Physical impact'],
                'severity': 5,  # DFMEA: Medium - installation issue
                'occurrence': 3,  # Low-medium
                'detection': 2,  # Visual
                'rpn': 30,
                'tests': ['Force analysis', 'Fixture inspection', 'Connector integrity', 'Alignment check', 'Vibration test'],
                'resolution': 'Review installation procedure, use proper tools, check bracket'
            },
            'connector_corrosion': {
                'name': 'Connector Corrosion/Oxidation',
                'symptoms': ['connector', 'corrosion', 'oxidation', 'intermittent', 'contact resistance'],
                'causes': ['Moisture exposure', 'Galvanic corrosion', 'Poor sealing', 'Dissimilar metals', 'Salt spray'],
                'severity': 6,  # DFMEA: Medium-high - connection loss
                'occurrence': 5,  # Medium-high (outdoor)
                'detection': 4,  # Requires inspection
                'rpn': 120,
                'tests': ['Visual inspection', 'Contact resistance measurement', 'Corrosion analysis', 'Seal inspection'],
                'resolution': 'Clean/replace connectors, improve sealing, use corrosion-resistant materials'
            },
            'pcb_delamination': {
                'name': 'PCB Delamination/Cracking',
                'symptoms': ['delamination', 'crack', 'PCB damage', 'layer separation', 'warping'],
                'causes': ['Thermal stress', 'Moisture absorption', 'CTE mismatch', 'Mechanical stress', 'Poor reflow profile'],
                'severity': 8,  # DFMEA: High - structural failure
                'occurrence': 2,  # Low (quality issue)
                'detection': 4,  # Visual/acoustic inspection
                'rpn': 64,
                'tests': ['Visual inspection', 'Acoustic microscopy', 'Cross-section analysis', 'Thermal cycling test'],
                'resolution': 'Replace board, review manufacturing process'
            },
            'antenna_failure': {
                'name': 'Antenna/RF Path Failure',
                'symptoms': ['antenna', 'RF', 'no signal', 'poor range', 'RF path'],
                'causes': ['Physical damage', 'Connector failure', 'Impedance mismatch', 'Water ingress', 'Cable damage'],
                'severity': 7,  # DFMEA: High - no wireless
                'occurrence': 3,  # Low-medium
                'detection': 5,  # RF testing required
                'rpn': 105,
                'tests': ['VSWR measurement', 'Antenna inspection', 'Cable continuity', 'RF power output', 'Spectrum analysis'],
                'resolution': 'Replace antenna, check RF path, verify connections'
            }
        }
        
        # LED status codes (eero specific)
        self.led_codes = {
            'solid_white': 'Normal operation, connected to internet',
            'blinking_white': 'Booting up or attempting connection',
            'solid_blue': 'Setup mode, waiting for configuration',
            'blinking_blue': 'Bluetooth pairing mode, ready for app',
            'solid_green': 'Optimal operation, all systems normal',
            'blinking_yellow': 'Soft reset in progress or weak connection',
            'solid_yellow': 'No internet connection detected',
            'blinking_red': 'No internet, check upstream connection',
            'solid_red': 'Critical error, hardware or connection failure',
            'no_light': 'No power or hardware failure'
        }
        
        # Technical search keywords (based on actual data)
        self.technical_keywords = {
            'memory': ['emmc', 'flash', 'memory', 'storage', 'corruption', 'firmware'],
            'power': ['poe', 'power', 'voltage', 'injector', 'adapter', 'goldfinch', 'psu', 'exothermic', 'outlet'],
            'connectivity': ['cloud', 'registration', 'connect', 'network', 'wifi', 'ethernet', 'flashing blue', 'flashing white'],
            'environmental': ['liquid', 'water', 'ingress', 'temperature', 'thermal', 'weather', 'm22', 'seal'],
            'hardware': ['component', 'eipd', 'eos', 'damage', 'physical', 'burn', 'capacitor', 'solder'],
            'performance': ['throughput', 'speed', 'slow', 'performance', 'coverage', 'interference', 'poor'],
            'installation': ['mount', 'bracket', 'setup', 'installation', 'qr code']
        }
        
    def load_historical_data(self, df):
        """Load and prepare historical data, filtering out 'Won't do' cases"""
        self.df = df.copy()
        
        # Filter out "Won't do" cases - check both Root_Cause and Jira_Ticket columns
        # These cases have no useful analysis data
        self.df = self.df[
            (self.df['Root_Cause'] != "Won't do") & 
            (~self.df['Jira_Ticket'].isin(["Won't do", "To Do", "NA"]))
        ].copy()
        
        # symptom_corpus is the LEAKAGE-FREE model input: only fields that are
        # actually observable at triage time (return reason + comments +
        # SW/HW hints). It deliberately EXCLUDES Root_Cause_Reason, which is
        # the label — including it (as the old combined_text did) leaked the
        # answer into the features and inflated apparent accuracy.
        sw = self.df['SW_Related_Issue'].fillna('').apply(
            lambda v: 'software_related' if str(v).upper() == 'YES' else '')
        hw = self.df['HW_Related_Issue'].fillna('').apply(
            lambda v: 'hardware_related' if str(v).upper() == 'YES' else '')
        raw_corpus = (
            self.df['Return_Reason_Code'].fillna('') + ' ' +
            self.df['Comments'].fillna('') + ' ' + sw + ' ' + hw
        )
        self.df['symptom_corpus'] = raw_corpus.apply(normalize_text)

        # Kept only for backward-compatible display/reference; NOT used for
        # training or similarity anymore.
        self.df['combined_text'] = (
            self.df['Return_Reason_Code'].fillna('') + ' ' +
            self.df['Comments'].fillna('') + ' ' +
            self.df['Root_Cause_Reason'].fillna('')
        )

        self._canonicalize_labels()
        return self.df

    def _canonicalize_labels(self):
        """Merge root-cause label variants that differ only by case/whitespace
        and drop placeholder/junk labels. Produces 'root_cause_clean' used for
        training and the kNN vote; the original column is untouched for display."""
        raw = self.df['Root_Cause_Reason'].astype(str)
        forms = {}
        for s in raw:
            k = canonical_label_key(s)
            if k in JUNK_LABELS:
                continue
            display = re.sub(r"\s+", " ", s.strip())
            forms.setdefault(k, Counter())[display] += 1
        # Canonical display form = the most common original spelling per key
        canonical = {k: c.most_common(1)[0][0] for k, c in forms.items()}

        def clean(s):
            k = canonical_label_key(s)
            if k in JUNK_LABELS:
                return None
            return canonical.get(k)

        self.df['root_cause_clean'] = raw.apply(clean)
    
    def search_technical_keywords(self, keywords):
        """Search CSV for technical keywords and return related cases with JIRA tickets (excluding Won't do)"""
        if self.df is None:
            return []
        
        results = []
        keywords_lower = [k.lower() for k in keywords]
        
        # Search across multiple columns
        search_columns = ['Return_Reason_Code', 'Root_Cause_Reason', 'Comments', 
                         'SW_Related_Issue', 'HW_Related_Issue']
        
        for idx, row in self.df.iterrows():
            # Skip "Won't do" cases - check both Root_Cause and Jira_Ticket columns
            if row['Root_Cause'] == "Won't do" or row['Jira_Ticket'] in ["Won't do", "To Do", "NA"]:
                continue
            
            match_score = 0
            matched_fields = []
            
            for col in search_columns:
                if pd.notna(row[col]):
                    text = str(row[col]).lower()
                    for keyword in keywords_lower:
                        if keyword in text:
                            match_score += 1
                            matched_fields.append(f"{col}: {keyword}")
            
            if match_score > 0:
                results.append({
                    'id': row['ID'],
                    'match_score': match_score,
                    'matched_fields': matched_fields,
                    'return_reason': row['Return_Reason_Code'],
                    'root_cause': row['Root_Cause_Reason'],
                    'root_cause_status': row['Root_Cause'],
                    'jira': row['Jira_Ticket'],
                    'sw_jira': row.get('SW_JIRA', ''),
                    'comments': row['Comments'],
                    'sw_related': row['SW_Related_Issue'],
                    'hw_related': row['HW_Related_Issue'],
                    'unit_sn': row['Unit_SN'],
                    'date': row['User_Reported_Date']
                })
        
        # Sort by match score
        results.sort(key=lambda x: x['match_score'], reverse=True)
        return results
    
    def identify_failure_mode(self, symptom_text):
        """Identify most likely failure mode based on symptoms"""
        symptom_lower = symptom_text.lower()
        matches = []
        
        # Normalize terminology
        # DAA = Dead After Arrival (failed after some use)
        # DOA = Dead On Arrival (never worked from factory)
        if 'doa' in symptom_lower or 'dead on arrival' in symptom_lower:
            symptom_lower = symptom_lower + ' doa factory'
        elif 'daa' in symptom_lower or 'dead after arrival' in symptom_lower:
            symptom_lower = symptom_lower + ' daa field'
        
        for mode, details in self.failure_modes.items():
            score = 0
            for symptom in details['symptoms']:
                if symptom.lower() in symptom_lower:
                    score += 2
            
            # Check causes too
            for cause in details['causes']:
                if cause.lower() in symptom_lower:
                    score += 1
            
            if score > 0:
                matches.append({
                    'mode': mode,
                    'score': score,
                    'details': details
                })
        
        matches.sort(key=lambda x: x['score'], reverse=True)
        return matches
    
    def get_led_diagnosis(self, led_description):
        """Diagnose based on LED status"""
        led_lower = led_description.lower()
        
        for status, meaning in self.led_codes.items():
            status_words = status.replace('_', ' ')
            if status_words in led_lower:
                return status, meaning
        
        return None, None
    
    def build_symptom_patterns(self):
        """Build symptom to root cause mapping"""
        patterns = {}
        
        for _, row in self.df.iterrows():
            symptom = str(row['Return_Reason_Code']).lower()
            root_cause = str(row['Root_Cause_Reason'])
            
            if symptom not in patterns:
                patterns[symptom] = {
                    'root_causes': [],
                    'sw_related': [],
                    'hw_related': [],
                    'comments': [],
                    'jira_tickets': []
                }
            
            if pd.notna(root_cause) and root_cause != 'nan':
                patterns[symptom]['root_causes'].append(root_cause)
            
            if pd.notna(row['SW_Related_Issue']):
                patterns[symptom]['sw_related'].append(row['SW_Related_Issue'])
            
            if pd.notna(row['HW_Related_Issue']):
                patterns[symptom]['hw_related'].append(row['HW_Related_Issue'])
                
            if pd.notna(row['Comments']):
                patterns[symptom]['comments'].append(row['Comments'])
                
            if pd.notna(row['Jira_Ticket']):
                patterns[symptom]['jira_tickets'].append(row['Jira_Ticket'])
        
        self.symptom_patterns = patterns
        return patterns
    
    def _make_classifier(self):
        """Linear model tuned for sparse TF-IDF text with class imbalance.
        Outperforms RandomForest here and gives better-behaved probabilities."""
        return LogisticRegression(
            C=8.0,
            class_weight='balanced',
            max_iter=2000,
            solver='liblinear',   # robust for small, high-dimensional sparse data
        )

    def _evaluate_cv(self, X, y_encoded):
        """Stratified cross-validated accuracy on classes that have enough
        samples to validate. Returns a float estimate or None.

        We only report a number when there is enough labeled data to make the
        estimate meaningful — reporting "100%" off a handful of samples would
        be misleading, so in that case we return None ('needs more data')."""
        counts = Counter(y_encoded)
        keep = [c for c, n in counts.items() if n >= 2]
        # Need a few classes and a reasonable number of validatable samples,
        # otherwise the estimate is noise.
        eligible = int(np.isin(y_encoded, keep).sum())
        if len(keep) < 3 or eligible < 12:
            return None
        mask = np.isin(y_encoded, keep)
        Xk, yk = X[mask], y_encoded[mask]
        min_count = min(Counter(yk).values())
        k = int(max(2, min(5, min_count)))
        try:
            scores = cross_val_score(
                self._make_classifier(), Xk, yk,
                cv=StratifiedKFold(n_splits=k, shuffle=True, random_state=42),
                scoring='accuracy',
            )
            return float(scores.mean())
        except Exception:
            return None

    def train_model(self):
        """Train the triage classifier on historical data (leakage-free corpus)."""
        # Filter to rows that have a real (canonicalized) root cause label
        train_df = self.df[self.df['root_cause_clean'].notna()].copy()

        # Always fit the vectorizer on the full leakage-free corpus so
        # similarity search works even when there isn't enough labeled data.
        if len(self.df) > 0:
            X_all = self.df['symptom_corpus'].values
            self.vectorizer.fit(X_all)
            self.historical_vectors = self.vectorizer.transform(X_all)
            self.corpus_root_causes = self.df['root_cause_clean'].values

        self.n_training_cases = len(train_df)
        if len(train_df) < 5 or train_df['root_cause_clean'].nunique() < 2:
            self.model = None
            return False, "Not enough labeled data to train (need >=5 cases across >=2 root causes)"

        X_vectorized = self.vectorizer.transform(train_df['symptom_corpus'].values)
        y = train_df['root_cause_clean'].values
        y_encoded = self.label_encoder.fit_transform(y)

        # Measure accuracy before fitting the final model on all data
        self.cv_accuracy = self._evaluate_cv(X_vectorized, y_encoded)

        self.model = self._make_classifier()
        self.model.fit(X_vectorized, y_encoded)
        self.model_type = "Logistic Regression + kNN ensemble"

        msg = f"Model trained on {len(train_df)} cases across {len(self.label_encoder.classes_)} root causes"
        if self.cv_accuracy is not None:
            msg += f" · cross-validated accuracy ~{self.cv_accuracy*100:.0f}%"
        return True, msg

    def _knn_distribution(self, input_vector, k=10, threshold=0.12):
        """Similarity-weighted vote over the nearest historical cases,
        returning a normalized {root_cause: probability} distribution."""
        if self.historical_vectors is None or self.corpus_root_causes is None:
            return {}
        sims = cosine_similarity(input_vector, self.historical_vectors)[0]
        order = sims.argsort()[::-1]
        weights = {}
        used = 0
        for idx in order:
            s = sims[idx]
            if s < threshold or used >= k:
                break
            cause = self.corpus_root_causes[idx]
            if cause is None:
                continue
            cause_s = str(cause).strip()
            if not cause_s or cause_s.lower() == 'nan':
                continue
            weights[cause_s] = weights.get(cause_s, 0.0) + float(s)
            used += 1
        total = sum(weights.values())
        if total <= 0:
            return {}
        return {c: w / total for c, w in weights.items()}
    
    def find_similar_cases(self, symptom_text, top_n=5):
        """Find similar historical cases (excluding Won't do)"""
        if self.df is None or len(self.df) == 0:
            return []
        
        # Vectorize input through the same normalization the corpus used
        input_vector = self.vectorizer.transform([normalize_text(symptom_text)])
        
        # Reuse precomputed corpus vectors; fall back to computing once if needed
        if self.historical_vectors is None:
            self.historical_vectors = self.vectorizer.transform(self.df['symptom_corpus'])
        historical_vectors = self.historical_vectors
        
        # Calculate similarity
        similarities = cosine_similarity(input_vector, historical_vectors)[0]
        
        # Get top N similar cases
        top_indices = similarities.argsort()[-top_n*3:][::-1]  # Get more to filter
        
        similar_cases = []
        for idx in top_indices:
            if similarities[idx] > 0.1:  # Minimum similarity threshold
                case = self.df.iloc[idx]
                
                # Skip "Won't do" cases - check both Root_Cause and Jira_Ticket
                if case['Root_Cause'] == "Won't do" or case['Jira_Ticket'] in ["Won't do", "To Do", "NA"]:
                    continue
                
                similar_cases.append({
                    'similarity': similarities[idx],
                    'return_reason': case['Return_Reason_Code'],
                    'root_cause': case['Root_Cause_Reason'],
                    'root_cause_status': case['Root_Cause'],
                    'sw_related': case['SW_Related_Issue'],
                    'hw_related': case['HW_Related_Issue'],
                    'comments': case['Comments'],
                    'jira': case['Jira_Ticket']
                })
                
                # Stop when we have enough
                if len(similar_cases) >= top_n:
                    break
        
        return similar_cases
    
    def predict_top(self, symptom_text, top_k=3, w_clf=0.6, w_knn=0.4):
        """Return the top-k (root_cause, score) predictions by blending the
        classifier's probabilities with a similarity-weighted kNN vote.

        The blend is more robust than either signal alone: the classifier
        generalizes across vocabulary, while the kNN vote anchors the answer
        to real precedent and prevents confident-but-wrong single guesses."""
        input_vector = self.vectorizer.transform([normalize_text(symptom_text)])

        scores = {}

        # Classifier contribution
        if self.model is not None:
            probs = self.model.predict_proba(input_vector)[0]
            classes = self.label_encoder.inverse_transform(self.model.classes_)
            for cause, p in zip(classes, probs):
                scores[cause] = scores.get(cause, 0.0) + w_clf * float(p)

        # kNN vote contribution
        knn = self._knn_distribution(input_vector)
        for cause, p in knn.items():
            scores[cause] = scores.get(cause, 0.0) + w_knn * p

        if not scores:
            return []

        # Renormalize over the actually-scored causes so confidence is
        # comparable regardless of which signals fired.
        total = sum(scores.values())
        if total > 0:
            scores = {c: v / total for c, v in scores.items()}

        ranked = sorted(scores.items(), key=lambda kv: kv[1], reverse=True)
        return ranked[:top_k]

    def predict_root_cause(self, symptom_text):
        """Predict the single most likely root cause and a blended confidence."""
        ranked = self.predict_top(symptom_text, top_k=1)
        if not ranked:
            return None, 0.0
        return ranked[0][0], ranked[0][1]
    
    def generate_triage_recommendation(self, symptom_text, return_reason=None):
        """Generate comprehensive triage recommendation"""
        recommendation = {
            'predicted_root_cause': None,
            'confidence': 0.0,
            'top_predictions': [],
            'similar_cases': [],
            'triage_steps': [],
            'priority': 'Medium',
            'estimated_category': 'Unknown',
            'related_jiras': []
        }
        
        # Blended prediction (classifier + similarity-weighted kNN vote). Works
        # even without a trained classifier, as long as we have history.
        top_predictions = self.predict_top(symptom_text, top_k=3)
        recommendation['top_predictions'] = top_predictions
        if top_predictions:
            recommendation['predicted_root_cause'] = top_predictions[0][0]
            recommendation['confidence'] = top_predictions[0][1]
        
        # Find similar cases
        similar_cases = self.find_similar_cases(symptom_text, top_n=5)
        recommendation['similar_cases'] = similar_cases
        
        # Extract patterns from similar cases
        if similar_cases:
            sw_issues = [c['sw_related'] for c in similar_cases if pd.notna(c['sw_related'])]
            hw_issues = [c['hw_related'] for c in similar_cases if pd.notna(c['hw_related'])]
            
            # Extract EFFA tickets only (filter out "Won't do", "To Do", etc.)
            jiras = []
            for c in similar_cases:
                if pd.notna(c['jira']):
                    jira = str(c['jira']).strip()
                    # Only include EFFA, CONN, LUX, SAFETY, INCIDENT tickets
                    if any(prefix in jira.upper() for prefix in ['EFFA-', 'CONN-', 'LUX-', 'SAFETY-', 'INCIDENT-']):
                        jiras.append(jira)
            
            sw_count = sum(1 for x in sw_issues if x == 'YES')
            hw_count = sum(1 for x in hw_issues if x == 'YES')
            
            if sw_count > hw_count:
                recommendation['estimated_category'] = 'Software'
            elif hw_count > sw_count:
                recommendation['estimated_category'] = 'Hardware'
            else:
                recommendation['estimated_category'] = 'Mixed/Unknown'
            
            recommendation['related_jiras'] = list(set(jiras))
        
        # Generate triage steps based on symptom
        recommendation['triage_steps'] = self._generate_triage_steps(
            symptom_text, 
            return_reason,
            recommendation['estimated_category']
        )
        
        # Determine priority
        recommendation['priority'] = self._determine_priority(symptom_text, similar_cases)
        
        return recommendation
    
    def _generate_triage_steps(self, symptom_text, return_reason, category):
        """Generate specific technical triage steps"""
        steps = []
        symptom_lower = symptom_text.lower()
        
        # Identify failure modes
        failure_modes = self.identify_failure_mode(symptom_text)
        
        # Common initial steps
        steps.append("1. **Initial Assessment**")
        steps.append("   - Verify unit serial number (GGC3530X format)")
        steps.append("   - Check warranty status and manufacturing week (PSU_MFG_WW)")
        steps.append("   - Document LED status and behavior pattern")
        steps.append("   - Record power adapter model (Goldfinch/PoE injector)")
        
        steps.append("\n2. **Environmental & Physical Inspection**")
        steps.append("   - Verify IP66 seal integrity (M22 gland properly tightened)")
        steps.append("   - Check unit orientation (correct mounting per spec)")
        steps.append("   - Inspect for physical damage, corrosion, or liquid ingress")
        steps.append("   - Verify operating temperature range (-40°F to 131°F)")
        steps.append("   - Document installation environment (direct sunlight, exposure)")
        
        # Failure mode specific steps
        if failure_modes:
            primary_mode = failure_modes[0]
            mode_name = primary_mode['mode'].replace('_', ' ').title()
            details = primary_mode['details']
            
            steps.append(f"\n3. **Primary Failure Mode: {mode_name}**")
            steps.append(f"   **Likely Causes:**")
            for cause in details['causes']:
                steps.append(f"   - {cause}")
            
            steps.append(f"\n   **Required Tests:**")
            for test in details['tests']:
                steps.append(f"   - {test}")
            
            steps.append(f"\n   **Resolution Path:** {details['resolution']}")
        
        # Symptom-specific technical procedures
        if 'daa' in symptom_lower or 'dead after arrival' in symptom_lower:
            steps.append("\n4. **DAA (Dead After Arrival) Protocol**")
            steps.append("   **Definition:** Unit failed after initial operation (not DOA)")
            steps.append("   - Verify PoE+ power delivery (802.3at, 30W minimum)")
            steps.append("   - Test with known-good PoE injector (Goldfinch or equivalent)")
            steps.append("   - Check Ethernet cable: Cat5e/Cat6, max 100m length")
            steps.append("   - Measure PoE voltage at device: 48-57V DC expected")
            steps.append("   - Connect UART console for boot sequence analysis")
            steps.append("   - Check for eMMC corruption indicators in boot logs")
            steps.append("   - Inspect for capacitor failure: bulging, leakage, ESR test")
            steps.append("   - Perform visual inspection for EIPD (Electrically Induced Physical Damage)")
            steps.append("   - Check solder joints for thermal cycling fatigue")
            steps.append("   - If liquid suspected: FTIR analysis for contamination")
        
        elif 'doa' in symptom_lower or 'dead on arrival' in symptom_lower:
            steps.append("\n4. **DOA (Dead On Arrival) Protocol**")
            steps.append("   **Definition:** Unit never worked from factory (manufacturing defect)")
            steps.append("   - Verify factory test records and QC data")
            steps.append("   - Check for shipping damage: packaging, physical inspection")
            steps.append("   - Verify PoE+ power delivery with known-good source")
            steps.append("   - Inspect for manufacturing defects: solder quality, component placement")
            steps.append("   - Check for PCB damage: cracks, delamination")
            steps.append("   - Review manufacturing date and batch information")
            steps.append("   - Initiate RMA process and root cause analysis at factory")
            steps.append("   - Document for quality feedback to manufacturing")
        
        elif 'capacitor' in symptom_lower or 'bulging' in symptom_lower or 'burst' in symptom_lower:
            steps.append("\n4. **DAA (Dead After Arrival) Protocol**")
            steps.append("   - Verify PoE+ power delivery (802.3at, 30W minimum)")
            steps.append("   - Test with known-good PoE injector (Goldfinch or equivalent)")
            steps.append("   - Check Ethernet cable: Cat5e/Cat6, max 100m length")
            steps.append("   - Measure PoE voltage at device: 48-57V DC expected")
            steps.append("   - Connect UART console for boot sequence analysis")
            steps.append("   - Check for eMMC corruption indicators in boot logs")
            steps.append("   - Perform visual inspection for EIPD (Electrically Induced Physical Damage)")
        elif 'capacitor' in symptom_lower or 'bulging' in symptom_lower or 'burst' in symptom_lower:
            steps.append("\n4. **Capacitor Failure Analysis**")
            steps.append("   **Common in outdoor electronics due to temperature extremes**")
            steps.append("   - Visual inspection for bulging, leaking, or burst capacitors")
            steps.append("   - Measure ESR (Equivalent Series Resistance) - should be <1Ω typically")
            steps.append("   - Check capacitance value vs. rated (±20% tolerance)")
            steps.append("   - Measure ripple voltage on power rails")
            steps.append("   - Thermal imaging to identify hot spots")
            steps.append("   - Review temperature history: >85°C accelerates failure")
            steps.append("   - Check for electrolyte dry-out (most common failure mode)")
            steps.append("   - Inspect for reverse polarity or overvoltage damage")
            steps.append("   - Replace failed capacitors with same or higher temp rating")
        
        elif 'emmc' in symptom_lower or 'memory' in symptom_lower or 'corruption' in symptom_lower:
            steps.append("\n4. **eMMC Flash Memory Analysis**")
            steps.append("   - Check for firmware corruption (LUX-10289)")
            steps.append("   - Review ambient temperature history (extreme temps suspected)")
            steps.append("   - Attempt firmware reload via recovery mode")
            steps.append("   - Check for bad blocks in eMMC")
            steps.append("   - Verify ECC (Error Correction Code) status")
            steps.append("   - Test read/write performance and errors")
            steps.append("   - Check wear leveling and endurance metrics")
            steps.append("   - Review power stability during write operations")
            steps.append("   - If persistent: eMMC replacement required")
        
        elif 'solder' in symptom_lower or 'cold joint' in symptom_lower or 'thermal cycling' in symptom_lower:
            steps.append("\n4. **Solder Joint Failure Analysis**")
            steps.append("   **High risk in outdoor applications due to thermal cycling**")
            steps.append("   - X-ray inspection of solder joints")
            steps.append("   - Visual inspection under magnification (10-20x)")
            steps.append("   - Check for CTE (Coefficient of Thermal Expansion) mismatch")
            steps.append("   - Thermal cycling test: -40°F to 131°F")
            steps.append("   - Vibration testing if mechanical stress suspected")
            steps.append("   - Look for crack propagation in high-stress areas")
            steps.append("   - Inspect large components (connectors, inductors)")
            steps.append("   - Rework affected joints with proper reflow profile")
        
        elif 'flash' in symptom_lower or 'led' in symptom_lower:
            # Determine LED status
            led_status, led_meaning = self.get_led_diagnosis(symptom_text)
            
            steps.append("\n4. **LED Status Analysis**")
            if led_status:
                steps.append(f"   **Detected Status:** {led_status.replace('_', ' ').title()}")
                steps.append(f"   **Meaning:** {led_meaning}")
            
            if 'blue' in symptom_lower:
                steps.append("\n   **Flashing Blue - Cloud Registration Failure:**")
                steps.append("   - Check for known bug: CONN-45729 (QC cloud key mismatch)")
                steps.append("   - Verify cloud keys match board keys (factory QC issue)")
                steps.append("   - Review INCIDENT-754 for similar cases")
                steps.append("   - Test network connectivity: DNS, firewall, proxy")
                steps.append("   - Verify eero cloud service status")
                steps.append("   - Check certificate validity and time sync")
                steps.append("   - Attempt re-provisioning via eero app")
                
            elif 'white' in symptom_lower:
                steps.append("\n   **Flashing White - Boot/Connection Issue:**")
                steps.append("   - Monitor boot sequence duration (normal: <2 minutes)")
                steps.append("   - Check upstream network connectivity")
                steps.append("   - Verify DHCP server response")
                steps.append("   - Test with static IP configuration")
                steps.append("   - Review system logs for boot errors")
                steps.append("   - Check eMMC health and firmware integrity")
        
        elif 'performance' in symptom_lower or 'throughput' in symptom_lower or 'slow' in symptom_lower:
            steps.append("\n4. **Performance Analysis Protocol**")
            steps.append("   - Run wireless performance test (iperf3 or similar)")
            steps.append("   - Compare against KGU baseline performance")
            steps.append("   - Expected: Up to 2.1 Gbps aggregate (2x2 MIMO)")
            steps.append("   - Measure RSSI and SNR at client devices")
            steps.append("   - Perform spectrum analysis (2.4GHz and 5GHz)")
            steps.append("   - Check for interference sources (radar, other APs)")
            steps.append("   - Verify channel selection and width (WiFi 7 features)")
            steps.append("   - Test in controlled environment vs. field conditions")
            steps.append("   - Review firmware version for known performance bugs")
            steps.append("   - Check CONN-47911 for throughput issues")
        
        elif 'setup' in symptom_lower or 'installation' in symptom_lower or 'mount' in symptom_lower:
            steps.append("\n4. **Setup & Installation Issues**")
            steps.append("   - Review mounting bracket installation (LUX-10203)")
            steps.append("   - Verify insertion force is within acceptable range")
            steps.append("   - Check for Luxshare fixture design issues")
            steps.append("   - Inspect connector alignment and integrity")
            steps.append("   - Verify M22 gland installation procedure")
            steps.append("   - Test QR code functionality (check for broken links)")
            steps.append("   - Review installation manual for Canadian SKUs")
            steps.append("   - Validate eero app pairing process")
        
        elif 'ethernet' in symptom_lower or 'connectivity' in symptom_lower or 'network' in symptom_lower:
            steps.append("\n4. **Network Connectivity Diagnostics**")
            steps.append("   - Test Ethernet link: 2.5 GbE negotiation")
            steps.append("   - Verify PoE+ power classification (Class 4)")
            steps.append("   - Check cable: Cat5e minimum, Cat6/6a recommended")
            steps.append("   - Test with different PoE switch/injector")
            steps.append("   - Verify VLAN configuration if applicable")
            steps.append("   - Check for network loop or broadcast storm")
            steps.append("   - Test DNS resolution and internet connectivity")
            steps.append("   - Review firewall rules for eero cloud access")
        
        elif 'liquid' in symptom_lower or 'water' in symptom_lower or 'ingress' in symptom_lower:
            steps.append("\n4. **Liquid Ingress Investigation**")
            steps.append("   - Verify unit orientation during installation")
            steps.append("   - Check M22 gland seal: proper tightening torque")
            steps.append("   - Inspect for IP66 seal compromise")
            steps.append("   - Perform FTIR analysis on residue")
            steps.append("   - Review installation photos/documentation")
            steps.append("   - Test seal integrity with controlled liquid exposure")
            steps.append("   - Verify gravity-assisted drainage in correct orientation")
            steps.append("   - Document findings for PD team review")
        
        elif 'burn' in symptom_lower or 'fire' in symptom_lower or 'exothermic' in symptom_lower:
            steps.append("\n4. **SAFETY CRITICAL - Exothermic Event Protocol**")
            steps.append("   - **IMMEDIATE:** Isolate unit and power source")
            steps.append("   - File SAFETY ticket (e.g., SAFETY-125)")
            steps.append("   - Document thermal damage pattern and location")
            steps.append("   - Test both Snowbird unit and PSU separately")
            steps.append("   - Measure electrical parameters: voltage, current, resistance")
            steps.append("   - Inspect for asymmetric damage (indicates external source)")
            steps.append("   - Check outlet/power source: Neutral connection integrity")
            steps.append("   - Send to lab for detailed failure analysis")
            steps.append("   - Review for external heat source vs. internal PSU failure")
        
        # Category-specific technical steps
        steps.append("\n5. **Category-Specific Analysis**")
        if category == 'Software':
            steps.append("   **Software-Related Diagnostics:**")
            steps.append("   - Collect full system logs via UART/SSH")
            steps.append("   - Document firmware version and build date")
            steps.append("   - Search JIRA for known bugs (CONN-*, INCIDENT-*)")
            steps.append("   - Check for available firmware updates")
            steps.append("   - Test with beta/stable firmware if applicable")
            steps.append("   - Review cloud service logs and API responses")
            steps.append("   - Attempt factory reset and re-provisioning")
            
        elif category == 'Hardware':
            steps.append("   **Hardware-Related Diagnostics:**")
            steps.append("   - Perform detailed component-level inspection")
            steps.append("   - Check for physical damage: cracks, burns, corrosion")
            steps.append("   - Test power delivery at component level")
            steps.append("   - Inspect solder joints and connections")
            steps.append("   - Check antenna connections and RF path")
            steps.append("   - Measure component temperatures under load")
            steps.append("   - Send to lab for failure analysis if needed")
        
        # Documentation and escalation
        steps.append("\n6. **Documentation & Escalation**")
        steps.append("   - File EFFA ticket with all collected data")
        steps.append("   - Include: Serial number, symptoms, test results, photos")
        steps.append("   - Reference related JIRA tickets if found")
        steps.append("   - Update CM ticket if applicable (LUX-*)")
        steps.append("   - Set FA_Status and Shipment_Status appropriately")
        steps.append("   - Determine: Root Cause Identified / No Failure Found / Won't Do")
        
        steps.append("\n7. **Customer Communication**")
        steps.append("   - Provide clear explanation of findings")
        steps.append("   - Offer resolution: replacement, refund, or troubleshooting")
        steps.append("   - Set expectations for timeline")
        steps.append("   - Document customer interaction in CX system")
        
        return steps
    
    def _determine_priority(self, symptom_text, similar_cases):
        """Determine priority based on symptom and history"""
        symptom_lower = symptom_text.lower()
        
        # High priority keywords
        high_priority_keywords = ['fire', 'smoke', 'burn', 'exothermic', 'safety', 'shock']
        if any(keyword in symptom_lower for keyword in high_priority_keywords):
            return 'Critical'
        
        # Check if similar cases had critical issues
        if similar_cases:
            critical_causes = ['exothermic event', 'safety', 'fire']
            for case in similar_cases:
                if any(critical in str(case.get('root_cause', '')).lower() for critical in critical_causes):
                    return 'High'
        
        # Medium priority for common issues
        medium_priority_keywords = ['daa', 'dead', 'not working', 'failed']
        if any(keyword in symptom_lower for keyword in medium_priority_keywords):
            return 'Medium'
        
        # Low priority for performance/cosmetic issues
        low_priority_keywords = ['performance', 'cosmetic', 'slow', 'aesthetic']
        if any(keyword in symptom_lower for keyword in low_priority_keywords):
            return 'Low'
        
        return 'Medium'
    
    def get_statistics(self):
        """Get model and data statistics"""
        stats = {
            'total_cases': len(self.df) if self.df is not None else 0,
            'unique_symptoms': len(self.symptom_patterns),
            'cases_with_root_cause': 0,
            'model_trained': self.model is not None,
            'model_type': self.model_type,
            'cv_accuracy': self.cv_accuracy,
            'training_cases': self.n_training_cases,
        }
        
        if self.df is not None:
            stats['cases_with_root_cause'] = len(
                self.df[self.df['Root_Cause_Reason'].notna()]
            )
        
        return stats


def render_triage_ui(df):
    """Render the triage assistant UI"""
    st.markdown(
        '<div style="font-size:1.7em;font-weight:700;margin-bottom:2px;'
        'background:linear-gradient(100deg,#5B21B6 0%,#7C3AED 100%);'
        '-webkit-background-clip:text;background-clip:text;-webkit-text-fill-color:transparent;">'
        '🔧 Intelligent Triage Assistant</div>',
        unsafe_allow_html=True,
    )
    prog = get_selected_program() or "Snowbird"
    st.caption(f"Technical failure analysis for {prog}")
    
    # Initialize assistant
    if 'triage_assistant' not in st.session_state:
        st.session_state.triage_assistant = TriageAssistant()
        st.session_state.triage_assistant.load_historical_data(df)
        st.session_state.triage_assistant.build_symptom_patterns()
        success, message = st.session_state.triage_assistant.train_model()
        if success:
            st.success(f"✅ {message}")
        else:
            st.warning(f"⚠️ {message}")
    
    assistant = st.session_state.triage_assistant
    
    # Technical specifications
    with st.expander("📋 Product Technical Specifications", expanded=False):
        specs = assistant.technical_specs
        col1, col2, col3 = st.columns(3)
        with col1:
            st.write(f"**Product:** {specs['product']}")
            st.write(f"**Type:** {specs['type']}")
            st.write(f"**Rating:** {specs['rating']}")
            st.write(f"**Temp Range:** {specs['temp_range']}")
        with col2:
            st.write(f"**WiFi:** {specs['wifi']}")
            st.write(f"**Speed:** {specs['speed']}")
            st.write(f"**Coverage:** {specs['coverage']}")
            st.write(f"**Devices:** {specs['devices']}")
        with col3:
            st.write(f"**Power:** {specs['power']}")
            st.write(f"**Ethernet:** {specs['ethernet']}")
            st.write(f"**Storage:** {specs['storage']}")
            st.write(f"**Security:** {specs['security']}")
    
    # LED Status Reference
    with st.expander("💡 LED Status Code Reference", expanded=False):
        led_df = pd.DataFrame([
            {'Status': k.replace('_', ' ').title(), 'Meaning': v} 
            for k, v in assistant.led_codes.items()
        ])
        st.dataframe(led_df, use_container_width=True, hide_index=True)
    
    # Failure Modes Analysis
    with st.expander("Failure Modes Analysis", expanded=False):
        st.markdown("### Design Failure Mode & Effects Analysis")
        st.caption("Comprehensive failure mode database with RPN (Risk Priority Number) analysis")
        
        # Create DFMEA dataframe
        dfmea_data = []
        for mode_key, mode in assistant.failure_modes.items():
            dfmea_data.append({
                'Failure Mode': mode['name'],
                'Severity': mode.get('severity', 'N/A'),
                'Occurrence': mode.get('occurrence', 'N/A'),
                'Detection': mode.get('detection', 'N/A'),
                'RPN': mode.get('rpn', 'N/A'),
                'Primary Causes': ', '.join(mode['causes'][:2])
            })
        
        dfmea_df = pd.DataFrame(dfmea_data)
        dfmea_df = dfmea_df.sort_values('RPN', ascending=False)
        
        # Color code by RPN
        def color_rpn(val):
            if isinstance(val, (int, float)):
                if val >= 150:
                    return 'background-color: #ffcccc'  # Red
                elif val >= 100:
                    return 'background-color: #ffffcc'  # Yellow
                else:
                    return 'background-color: #ccffcc'  # Green
            return ''
        
        styled_df = dfmea_df.style.applymap(color_rpn, subset=['RPN'])
        st.dataframe(styled_df, use_container_width=True, hide_index=True)
        
        st.caption("**RPN Scale:** 🔴 High Risk (≥150) | 🟡 Medium Risk (100-149) | 🟢 Low Risk (<100)")
        st.caption("**Ratings:** Severity (1-10), Occurrence (1-10), Detection (1-10)")
    
    # Top failure modes details (separate section, not nested)
    st.markdown("#### Top 5 Critical Failure Modes (by RPN)")
    dfmea_data = []
    for mode_key, mode in assistant.failure_modes.items():
        dfmea_data.append({
            'Failure Mode': mode['name'],
            'RPN': mode.get('rpn', 0),
            'mode_key': mode_key
        })
    
    dfmea_df = pd.DataFrame(dfmea_data)
    dfmea_df = dfmea_df.sort_values('RPN', ascending=False)
    
    for i, row in dfmea_df.head(5).iterrows():
        mode_details = assistant.failure_modes[row['mode_key']]
        
        with st.expander(f"{row['Failure Mode']} (RPN: {row['RPN']})", expanded=False):
            col1, col2 = st.columns(2)
            with col1:
                st.write(f"**Severity:** {mode_details.get('severity', 'N/A')}/10")
                st.write(f"**Occurrence:** {mode_details.get('occurrence', 'N/A')}/10")
                st.write(f"**Detection:** {mode_details.get('detection', 'N/A')}/10")
            with col2:
                st.write(f"**RPN:** {row['RPN']}")
                rpn_level = "🔴 High Risk" if row['RPN'] >= 150 else "🟡 Medium Risk" if row['RPN'] >= 100 else "🟢 Low Risk"
                st.write(f"**Risk Level:** {rpn_level}")
            
            st.write("**Root Causes:**")
            for cause in mode_details['causes']:
                st.write(f"- {cause}")
            
            st.write("**Recommended Tests:**")
            for test in mode_details['tests']:
                st.write(f"- {test}")
            
            st.write(f"**Resolution:** {mode_details['resolution']}")
    
    # Observed Failure Modes from Data
    with st.expander("📊 Observed Failure Modes (from Historical Data)", expanded=False):
        if len(assistant.df) > 0:
            # Analyze actual failure modes from data
            failure_summary = assistant.df.groupby('Root_Cause_Reason').agg({
                'ID': 'count',
                'SW_Related_Issue': lambda x: (x == 'YES').sum(),
                'HW_Related_Issue': lambda x: (x == 'YES').sum()
            }).reset_index()
            failure_summary.columns = ['Root Cause', 'Count', 'SW Cases', 'HW Cases']
            failure_summary = failure_summary[failure_summary['Root Cause'].notna()]
            failure_summary = failure_summary.sort_values('Count', ascending=False)
            
            # Create visualization
            fig = px.bar(failure_summary.head(10), 
                        x='Root Cause', 
                        y='Count',
                        title='Top 10 Observed Failure Modes',
                        color='Count',
                        color_continuous_scale=[[0.0, "#5B21B6"], [0.5, "#7C3AED"], [1.0, "#C026D3"]])
            fig.update_layout(xaxis_tickangle=-45, coloraxis_showscale=False,
                              paper_bgcolor="rgba(0,0,0,0)", plot_bgcolor="rgba(0,0,0,0)",
                              font=dict(family="DM Sans, sans-serif", color="#211B33"))
            st.plotly_chart(fig, use_container_width=True)
            
            # Show table
            st.dataframe(failure_summary, use_container_width=True, hide_index=True)
        else:
            st.info("No historical data loaded yet")
    
    # Statistics
    with st.expander("📊 System Statistics", expanded=False):
        stats = assistant.get_statistics()
        col1, col2, col3, col4 = st.columns(4)
        col1.metric("Total Cases", stats['total_cases'])
        col2.metric("Unique Symptoms", stats['unique_symptoms'])
        col3.metric("Cases with Root Cause", stats['cases_with_root_cause'])
        col4.metric("Model Status", "✅ Trained" if stats['model_trained'] else "❌ Not Trained")

        col5, col6, col7, col8 = st.columns(4)
        acc = stats.get('cv_accuracy')
        col5.metric("Cross-Validated Accuracy", f"{acc*100:.0f}%" if acc is not None else "N/A")
        col6.metric("Training Cases", stats.get('training_cases', 0))
        col7.metric("Model", stats.get('model_type') or "—")
        col8.metric("Prediction", "Classifier + kNN")
        if acc is not None:
            st.caption("Accuracy is a stratified cross-validation estimate on root causes with at least two examples. "
                       "It improves as more debugged cases are added.")
        else:
            st.caption("Not enough labeled history yet to estimate accuracy reliably. "
                       "Predictions still work (classifier + similarity vote); the estimate will appear "
                       "once more cases with confirmed root causes accumulate.")
    
    st.markdown("---")
    
    # Technical Keyword Search Section
    st.subheader("🔍 Technical Keyword Search")
    st.caption("Search historical data for specific technical terms (e.g., eMMC, memory, liquid ingress, EIPD)")
    
    col1, col2 = st.columns([3, 1])
    with col1:
        search_keywords = st.text_input(
            "Enter technical keywords (comma-separated)",
            placeholder="e.g., eMMC, memory corruption, liquid ingress",
            help="Search across all fields including comments and JIRA tickets"
        )
    with col2:
        st.write("")
        st.write("")
        search_button = st.button("🔎 Search", type="secondary", use_container_width=True)
    
    if search_button and search_keywords:
        keywords = [k.strip() for k in search_keywords.split(',')]
        search_results = assistant.search_technical_keywords(keywords)
        
        if search_results:
            st.success(f"Found {len(search_results)} cases matching your keywords")
            
            # Display results
            for i, result in enumerate(search_results[:10], 1):
                with st.expander(f"Case {i} - ID: {result['id']} | {result['return_reason']} | Match Score: {result['match_score']}", expanded=(i<=3)):
                    col1, col2 = st.columns(2)
                    
                    with col1:
                        st.write(f"**Unit SN:** {result['unit_sn']}")
                        st.write(f"**Date:** {result['date']}")
                        st.write(f"**Root Cause:** {result['root_cause']}")
                        st.write(f"**Status:** {result['root_cause_status']}")
                    
                    with col2:
                        st.write(f"**SW Related:** {result['sw_related']}")
                        st.write(f"**HW Related:** {result['hw_related']}")
                        if pd.notna(result['jira']):
                            st.write(f"**JIRA:** `{result['jira']}`")
                        if pd.notna(result['sw_jira']):
                            st.write(f"**SW JIRA:** `{result['sw_jira']}`")
                    
                    st.write(f"**Matched Fields:** {', '.join(result['matched_fields'])}")
                    
                    if pd.notna(result['comments']):
                        st.write(f"**Comments:** {result['comments']}")
            
            # Extract unique EFFA tickets only (filter out "Won't do", "To Do", etc.)
            jira_tickets = set()
            for result in search_results:
                if pd.notna(result['jira']):
                    jira = str(result['jira']).strip()
                    # Only include EFFA, CONN, LUX, SAFETY, INCIDENT tickets
                    if any(prefix in jira.upper() for prefix in ['EFFA-', 'CONN-', 'LUX-', 'SAFETY-', 'INCIDENT-']):
                        jira_tickets.add(jira)
                if pd.notna(result['sw_jira']):
                    sw_jira = str(result['sw_jira']).strip()
                    if any(prefix in sw_jira.upper() for prefix in ['EFFA-', 'CONN-', 'LUX-', 'SAFETY-', 'INCIDENT-']):
                        jira_tickets.add(sw_jira)
            
            if jira_tickets:
                st.info(f"**Related JIRA Tickets:** {', '.join(sorted(jira_tickets))}")
        else:
            st.warning("No cases found matching your keywords")
    
    st.markdown("---")
    
    # Input section
    st.subheader("Enter Symptom Information")
    
    col1, col2 = st.columns([2, 1])
    
    with col1:
        symptom_text = st.text_area(
            "Describe the symptom/issue (be specific and technical)",
            placeholder="e.g., Unit DAA, stuck flashing blue LED, eMMC corruption suspected, liquid ingress visible",
            height=120,
            help="Include technical details: LED status, error codes, environmental conditions, etc."
        )
    
    with col2:
        return_reason = st.selectbox(
            "Return Reason Category",
            options=[''] + list(df['Return_Reason_Code'].dropna().unique()),
            help="Select a predefined category or leave blank"
        )
        
        unit_sn = st.text_input("Unit Serial Number (optional)", placeholder="GGC3530B44031206")
        
        power_adapter = st.selectbox(
            "Power Adapter Type",
            options=['', 'Goldfinch', 'PoE switch', 'PoE injector', 'Other'],
            help="Select the power source being used"
        )
    
    # Analyze button
    if st.button("🔍 Analyze & Generate Technical Triage Plan", type="primary", use_container_width=True):
        if symptom_text.strip():
            with st.spinner("Analyzing patterns and generating technical recommendations..."):
                # Generate recommendation
                full_text = f"{return_reason} {symptom_text}" if return_reason else symptom_text
                recommendation = assistant.generate_triage_recommendation(full_text, return_reason)
                
                # Identify failure modes
                failure_modes = assistant.identify_failure_mode(symptom_text)
                
                # Display results
                st.markdown("---")
                st.subheader("📋 Technical Triage Recommendation")
                
                # Priority and Category
                col1, col2, col3, col4 = st.columns(4)
                
                priority_colors = {
                    'Critical': '🔴',
                    'High': '🟠',
                    'Medium': '🟡',
                    'Low': '🟢'
                }
                
                with col1:
                    st.metric(
                        "Priority",
                        f"{priority_colors.get(recommendation['priority'], '⚪')} {recommendation['priority']}"
                    )
                
                with col2:
                    st.metric("Estimated Category", recommendation['estimated_category'])
                
                with col3:
                    if recommendation['confidence'] > 0:
                        st.metric(
                            "ML Confidence",
                            f"{recommendation['confidence']*100:.1f}%"
                        )
                
                with col4:
                    if failure_modes:
                        st.metric("Failure Modes", len(failure_modes))
                
                # Predicted Root Cause (blended classifier + kNN)
                if recommendation['predicted_root_cause']:
                    conf = recommendation['confidence']
                    st.info(f"🎯 **Predicted Root Cause:** {recommendation['predicted_root_cause']}  ·  {conf*100:.0f}% confidence")
                    if conf < 0.4:
                        st.caption("⚠️ Low confidence — treat the ranked candidates below as leads and lean on the similar cases and failure-mode analysis.")

                    top_preds = recommendation.get('top_predictions', [])
                    if len(top_preds) > 1:
                        st.write("**Ranked candidate root causes:**")
                        for rank, (cause, score) in enumerate(top_preds, 1):
                            st.markdown(
                                f"{rank}. {cause} — `{score*100:.0f}%`"
                            )
                
                # Failure Mode Analysis
                if failure_modes:
                    st.markdown("### Identified Failure Modes")
                    for i, mode in enumerate(failure_modes[:3], 1):
                        mode_name = mode['mode'].replace('_', ' ').title()
                        with st.expander(f"{i}. {mode_name} (Confidence: {mode['score']})", expanded=(i==1)):
                            details = mode['details']
                            
                            col1, col2 = st.columns(2)
                            with col1:
                                st.write("**Typical Symptoms:**")
                                for symptom in details['symptoms']:
                                    st.write(f"- {symptom}")
                            
                            with col2:
                                st.write("**Likely Causes:**")
                                for cause in details['causes']:
                                    st.write(f"- {cause}")
                            
                            st.write("**Required Tests:**")
                            for test in details['tests']:
                                st.write(f"- {test}")
                            
                            st.write(f"**Resolution:** {details['resolution']}")
                
                # Triage Steps
                st.markdown("### 📝 Detailed Technical Triage Procedure")
                for step in recommendation['triage_steps']:
                    st.markdown(step)
                
                # Similar Cases
                if recommendation['similar_cases']:
                    st.markdown("### 🔎 Similar Historical Cases")
                    
                    # Filter to show only cases with root causes
                    actionable_cases = [c for c in recommendation['similar_cases'] 
                                       if c['root_cause_status'] in ['Root Cause Identified', 'No Failure Found']]
                    
                    if actionable_cases:
                        for i, case in enumerate(actionable_cases[:5], 1):
                            # Highlight if it has root cause
                            status_icon = "✅" if case['root_cause_status'] == 'Root Cause Identified' else "❌"
                            
                            with st.expander(f"{status_icon} Case {i} - {case['return_reason']} (Similarity: {case['similarity']*100:.1f}%)"):
                                col1, col2 = st.columns(2)
                                with col1:
                                    st.write(f"**Root Cause:** {case['root_cause']}")
                                    st.write(f"**Status:** {case['root_cause_status']}")
                                    st.write(f"**SW Related:** {case['sw_related']}")
                                with col2:
                                    st.write(f"**HW Related:** {case['hw_related']}")
                                    if pd.notna(case['jira']) and case['jira'] not in ["Won't do", "To Do", "NA"]:
                                        # Highlight EFFA tickets
                                        jira_str = str(case['jira'])
                                        if 'EFFA' in jira_str:
                                            st.write(f"**JIRA:** 🎫 `{case['jira']}`")
                                        else:
                                            st.write(f"**JIRA:** `{case['jira']}`")
                                
                                if pd.notna(case['comments']):
                                    st.write(f"**Comments:** {case['comments'][:300]}...")
                    else:
                        st.info("No similar cases with identified root causes found. All similar cases were 'Won't do' (not analyzed).")
                
                # Related JIRAs
                if recommendation['related_jiras']:
                    st.markdown("### 🎫 Related JIRA Tickets")
                    
                    # Separate by type
                    effa_tickets = [j for j in recommendation['related_jiras'] if 'EFFA' in j.upper()]
                    conn_tickets = [j for j in recommendation['related_jiras'] if 'CONN' in j.upper()]
                    lux_tickets = [j for j in recommendation['related_jiras'] if 'LUX' in j.upper()]
                    safety_tickets = [j for j in recommendation['related_jiras'] if 'SAFETY' in j.upper()]
                    other_tickets = [j for j in recommendation['related_jiras'] 
                                    if not any(x in j.upper() for x in ['EFFA', 'CONN', 'LUX', 'SAFETY'])]
                    
                    if effa_tickets:
                        st.write("**EFFA (Field Failure Analysis):**")
                        st.write(", ".join([f"`{j}`" for j in effa_tickets]))
                    
                    if conn_tickets:
                        st.write("**CONN (Connectivity Issues):**")
                        st.write(", ".join([f"`{j}`" for j in conn_tickets]))
                    
                    if lux_tickets:
                        st.write("**LUX (Manufacturing/CM):**")
                        st.write(", ".join([f"`{j}`" for j in lux_tickets]))
                    
                    if safety_tickets:
                        st.write("**SAFETY (Critical Safety Issues):**")
                        st.write(", ".join([f"`{j}`" for j in safety_tickets]))
                    
                    if other_tickets:
                        st.write("**Other:**")
                        st.write(", ".join([f"`{j}`" for j in other_tickets]))
                else:
                    st.info("No JIRA tickets found for similar cases")
                
        else:
            st.warning("⚠️ Please enter symptom information")
    
    # Quick lookup section
    st.markdown("---")
    st.subheader("🔍 Quick Symptom Lookup")
    
    col1, col2 = st.columns(2)
    
    with col1:
        known_symptoms = list(assistant.symptom_patterns.keys())
        selected_symptom = st.selectbox(
            "Browse known symptoms",
            options=[''] + known_symptoms,
            help="Select a symptom to see historical patterns"
        )
    
    with col2:
        # Technical keyword categories
        keyword_category = st.selectbox(
            "Or search by technical category",
            options=[''] + list(assistant.technical_keywords.keys()),
            help="Search by technical category"
        )
    
    if selected_symptom:
        pattern = assistant.symptom_patterns[selected_symptom]
        
        col1, col2, col3 = st.columns(3)
        
        with col1:
            st.write("**Root Causes:**")
            if pattern['root_causes']:
                cause_counts = Counter(pattern['root_causes'])
                for cause, count in cause_counts.most_common(5):
                    st.write(f"- {cause} ({count}x)")
            else:
                st.write("No root causes recorded")
        
        with col2:
            st.write("**Issue Type:**")
            sw_yes = sum(1 for x in pattern['sw_related'] if x == 'YES')
            hw_yes = sum(1 for x in pattern['hw_related'] if x == 'YES')
            st.write(f"- Software: {sw_yes} cases")
            st.write(f"- Hardware: {hw_yes} cases")
        
        with col3:
            st.write("**JIRA Tickets:**")
            if pattern['jira_tickets']:
                unique_jiras = list(set(pattern['jira_tickets']))[:5]
                for jira in unique_jiras:
                    st.write(f"- `{jira}`")
            else:
                st.write("No JIRA tickets")
    
    elif keyword_category:
        keywords = assistant.technical_keywords[keyword_category]
        st.info(f"Searching for: {', '.join(keywords)}")
        search_results = assistant.search_technical_keywords(keywords)
        
        if search_results:
            st.write(f"Found {len(search_results)} related cases")
            
            # Show summary
            jiras = set()
            root_causes = []
            for result in search_results[:10]:
                if pd.notna(result['jira']):
                    jiras.add(result['jira'])
                if pd.notna(result['root_cause']):
                    root_causes.append(result['root_cause'])
            
            col1, col2 = st.columns(2)
            with col1:
                st.write("**Top Root Causes:**")
                cause_counts = Counter(root_causes)
                for cause, count in cause_counts.most_common(5):
                    st.write(f"- {cause} ({count}x)")
            
            with col2:
                st.write("**Related JIRAs:**")
                for jira in list(jiras)[:10]:
                    st.write(f"- `{jira}`")
