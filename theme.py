"""Central theme for the Failure Analyzer app.

Provides a single source of truth for:
  - The app name and version (printed in the UI).
  - The brand palette: a Kiro-inspired purple with green and magenta accents.
  - The application logo (inline SVG, replaces the old magnifying-glass emoji).
  - A global CSS injector that applies DM Sans everywhere and styles native
    Streamlit widgets to match the palette.
  - A reusable branded header renderer.

Import and call `inject_theme()` once at the top of every entry view, and use
`render_app_header()` / `LOGO_SVG` to render the brand mark.
"""

from __future__ import annotations

import streamlit as st

# --------------------------------------------------------------------------- #
# Identity
# --------------------------------------------------------------------------- #
APP_NAME = "Failure Analyzer"
APP_TAGLINE = "Field-return failure analysis, triage, PCB debug & statistical analytics"
APP_VERSION = "2.0.0"

# --------------------------------------------------------------------------- #
# Palette — Kiro purple with green + magenta accents
# --------------------------------------------------------------------------- #
PURPLE = "#7C3AED"         # primary brand violet (readable on white)
PURPLE_BRIGHT = "#9F67FF"  # lighter violet for fills / highlights
PURPLE_DEEP = "#5B21B6"    # deep violet for depth
GREEN = "#059669"          # emerald accent (success / positive)
MAGENTA = "#C026D3"        # magenta accent (highlight / alert)

BG = "#FFFFFF"             # white canvas
BG_ELEV = "#F7F5FC"        # slightly tinted elevated canvas
PANEL = "#F4F1FB"          # cards / panels (soft lavender white)
PANEL_2 = "#ECE8F8"        # nested panels / hovers
BORDER = "#E0DBF0"         # subtle borders
TEXT = "#211B33"           # primary text (near-black, purple tint)
TEXT_MUTED = "#5B5470"     # secondary text
TEXT_FAINT = "#8B84A0"     # tertiary text

# Semantic (kept readable on a light canvas)
SUCCESS = GREEN
WARNING = "#D97706"        # amber-600
DANGER = "#DB2777"         # pink-600

# Ordered categorical palette for Plotly charts
CHART_SEQUENCE = [PURPLE, GREEN, MAGENTA, PURPLE_BRIGHT, WARNING, "#0891B2", "#DB2777", "#65A30D"]

# Gradient used for headings and the logo (dark-purple, no pink)
BRAND_GRADIENT = f"linear-gradient(100deg, {PURPLE_DEEP} 0%, {PURPLE} 100%)"


# --------------------------------------------------------------------------- #
# Logo — an elegant "insight" emblem (rounded hex + analysis pulse + node)
# --------------------------------------------------------------------------- #
def logo_svg(size: int = 44) -> str:
    """Return the app logo as an inline SVG string, sized to `size` px."""
    return f'''<svg width="{size}" height="{size}" viewBox="0 0 48 48" fill="none"
        xmlns="http://www.w3.org/2000/svg" role="img" aria-label="Failure Analyzer logo">
      <defs>
        <linearGradient id="fa_hex" x1="6" y1="4" x2="42" y2="44" gradientUnits="userSpaceOnUse">
          <stop stop-color="{PURPLE_BRIGHT}"/>
          <stop offset="0.55" stop-color="{PURPLE}"/>
          <stop offset="1" stop-color="{PURPLE_DEEP}"/>
        </linearGradient>
        <linearGradient id="fa_pulse" x1="12" y1="30" x2="36" y2="18" gradientUnits="userSpaceOnUse">
          <stop stop-color="{GREEN}"/>
          <stop offset="1" stop-color="{MAGENTA}"/>
        </linearGradient>
      </defs>
      <!-- rounded hexagon shell (evokes a chip / component) -->
      <path d="M24 3.2 40.6 12.8 40.6 35.2 24 44.8 7.4 35.2 7.4 12.8Z"
            fill="url(#fa_hex)" opacity="0.16"/>
      <path d="M24 3.2 40.6 12.8 40.6 35.2 24 44.8 7.4 35.2 7.4 12.8Z"
            stroke="url(#fa_hex)" stroke-width="2.2" stroke-linejoin="round" fill="none"/>
      <!-- analysis pulse / waveform: the signal we read from the part -->
      <path d="M12 27 L19 27 L22.5 16.5 L27 33 L30 24 L36 24"
            stroke="url(#fa_pulse)" stroke-width="2.6" stroke-linecap="round"
            stroke-linejoin="round" fill="none"/>
      <!-- insight node -->
      <circle cx="36" cy="24" r="2.9" fill="{MAGENTA}"/>
      <circle cx="36" cy="24" r="5.4" stroke="{MAGENTA}" stroke-width="1.2" opacity="0.5" fill="none"/>
    </svg>'''


# Convenience constant for a default-sized logo.
LOGO_SVG = logo_svg()


# --------------------------------------------------------------------------- #
# Global CSS
# --------------------------------------------------------------------------- #
def _global_css() -> str:
    return f"""
    <style>
      @import url('https://fonts.googleapis.com/css2?family=DM+Sans:opsz,wght@9..40,400;9..40,500;9..40,600;9..40,700&family=DM+Mono:wght@400;500&display=swap');

      :root {{
        --fa-purple: {PURPLE};
        --fa-purple-bright: {PURPLE_BRIGHT};
        --fa-green: {GREEN};
        --fa-magenta: {MAGENTA};
        --fa-bg: {BG};
        --fa-panel: {PANEL};
        --fa-border: {BORDER};
        --fa-text: {TEXT};
        --fa-text-muted: {TEXT_MUTED};
      }}

      /* DM Sans everywhere */
      html, body, [class*="css"], .stApp, button, input, textarea, select,
      .stMarkdown, .stMetric, [data-testid="stMetricValue"],
      [data-testid="stMetricLabel"], h1, h2, h3, h4, h5, h6, p, span, div, label {{
        font-family: 'DM Sans', -apple-system, BlinkMacSystemFont, sans-serif !important;
      }}
      /* Numeric / tabular readouts stay aligned but keep the DM family */
      code, kbd, pre, .stCode, [data-testid="stDataFrame"] {{
        font-family: 'DM Mono', ui-monospace, monospace !important;
      }}
      /* IMPORTANT: never override Material icon fonts. Forcing DM Sans on these
         makes icons render as literal ligature text ("info", "keyboard_arrow_right")
         that overlaps adjacent labels. Restore their icon fonts explicitly. */
      span[data-testid="stIconMaterial"], [data-testid="stIconMaterial"],
      [class*="material-symbols"], [class*="material-icons"],
      .material-icons, .material-icons-outlined,
      .material-symbols-rounded, .material-symbols-outlined,
      [data-testid="stExpanderToggleIcon"] {{
        font-family: 'Material Symbols Rounded', 'Material Symbols Outlined',
                     'Material Icons Round', 'Material Icons' !important;
        font-feature-settings: 'liga' !important;
      }}

      .stApp {{
        background:
          radial-gradient(1200px 600px at 15% -10%, {PURPLE}12 0%, transparent 55%),
          radial-gradient(900px 500px at 110% 0%, {MAGENTA}0d 0%, transparent 50%),
          {BG};
        color: {TEXT};
      }}

      /* Headings */
      h1, h2, h3 {{ color: {TEXT}; letter-spacing: -0.01em; font-weight: 700; }}
      h4, h5, h6 {{ color: {TEXT}; font-weight: 600; }}

      /* Sidebar */
      [data-testid="stSidebar"] {{
        background: linear-gradient(180deg, {BG_ELEV} 0%, {BG} 100%);
        border-right: 1px solid {BORDER};
      }}
      [data-testid="stSidebar"] * {{ color: {TEXT}; }}

      /* Regular (secondary) buttons — light chip, dark text */
      .stButton > button {{
        border-radius: 10px;
        border: 1px solid {BORDER};
        background: {PANEL_2};
        color: {TEXT};
        font-weight: 600;
        transition: all .18s ease;
      }}
      .stButton > button:hover {{
        border-color: {PURPLE};
        color: {PURPLE};
        box-shadow: 0 4px 16px {PURPLE}26;
        transform: translateY(-1px);
      }}
      .stButton > button p {{ color: inherit !important; }}
      /* Primary + form-submit buttons — purple gradient, white text */
      .stButton > button[kind="primary"],
      .stFormSubmitButton > button {{
        border-radius: 10px;
        border: none;
        background: linear-gradient(100deg, {PURPLE} 0%, {PURPLE_DEEP} 100%);
        color: #fff;
        font-weight: 600;
        transition: all .18s ease;
      }}
      .stButton > button[kind="primary"] p, .stFormSubmitButton > button p {{ color: #fff !important; }}
      .stButton > button[kind="primary"]:hover,
      .stFormSubmitButton > button:hover {{
        box-shadow: 0 6px 22px {PURPLE}55;
        color: #fff;
        transform: translateY(-1px);
      }}
      .stDownloadButton > button {{
        border-radius: 10px;
        border: 1px solid {GREEN}66;
        background: {PANEL};
        color: {GREEN};
        font-weight: 600;
      }}
      .stDownloadButton > button:hover {{
        border-color: {GREEN};
        box-shadow: 0 4px 18px {GREEN}2e;
      }}

      /* Metric cards */
      [data-testid="stMetric"] {{
        background: linear-gradient(160deg, {PANEL} 0%, {BG_ELEV} 100%);
        border: 1px solid {BORDER};
        border-left: 3px solid {PURPLE};
        border-radius: 12px;
        padding: 14px 16px;
        box-shadow: 0 2px 12px {PURPLE}12;
      }}
      [data-testid="stMetricValue"] {{ color: {TEXT}; font-weight: 700; }}
      [data-testid="stMetricLabel"] {{ color: {TEXT_MUTED}; }}

      /* Tabs, expanders, inputs */
      .stTabs [data-baseweb="tab-list"] {{ gap: 4px; }}
      .stTabs [data-baseweb="tab"] {{ border-radius: 8px 8px 0 0; }}
      .streamlit-expanderHeader, [data-testid="stExpander"] summary {{
        border-radius: 10px; font-weight: 600;
      }}
      [data-testid="stExpander"] {{
        border: 1px solid {BORDER}; border-radius: 12px; background: {PANEL}66;
      }}
      /* Text / number inputs & textareas — dark field, light text, readable placeholder */
      .stTextInput input, .stNumberInput input, .stTextArea textarea,
      [data-baseweb="input"] input, [data-baseweb="textarea"] textarea,
      [data-baseweb="select"] > div {{
        border-radius: 9px !important;
        background-color: {PANEL_2} !important;
        color: {TEXT} !important;
        border: 1px solid {BORDER} !important;
      }}
      .stTextInput input:focus, .stNumberInput input:focus, .stTextArea textarea:focus,
      [data-baseweb="input"]:focus-within, [data-baseweb="input"] input:focus {{
        border-color: {PURPLE} !important;
        box-shadow: 0 0 0 2px {PURPLE}40 !important;
      }}
      /* Placeholder text — muted but clearly legible */
      .stTextInput input::placeholder, .stTextArea textarea::placeholder,
      [data-baseweb="input"] input::placeholder {{
        color: {TEXT_MUTED} !important;
        opacity: 1 !important;
      }}
      /* Widget labels above inputs */
      [data-testid="stWidgetLabel"], .stTextInput label, .stTextArea label,
      .stNumberInput label, .stSelectbox label, .stRadio label, .stCheckbox label {{
        color: {TEXT} !important;
      }}

      /* File uploader — dark drop zone with legible text */
      [data-testid="stFileUploader"] section,
      [data-testid="stFileUploaderDropzone"] {{
        background-color: {PANEL_2} !important;
        border: 1.5px dashed {BORDER} !important;
        border-radius: 12px !important;
      }}
      [data-testid="stFileUploader"] section:hover,
      [data-testid="stFileUploaderDropzone"]:hover {{
        border-color: {PURPLE} !important;
      }}
      [data-testid="stFileUploader"] label,
      [data-testid="stFileUploaderDropzoneInstructions"],
      [data-testid="stFileUploaderDropzoneInstructions"] * {{
        color: {TEXT} !important;
      }}
      [data-testid="stFileUploaderDropzoneInstructions"] small,
      [data-testid="stFileUploader"] small {{ color: {TEXT_MUTED} !important; }}
      /* "Browse files" button inside the uploader */
      [data-testid="stFileUploader"] button {{
        background: {PANEL} !important;
        color: {TEXT} !important;
        border: 1px solid {BORDER} !important;
        font-weight: 600 !important;
      }}
      [data-testid="stFileUploader"] button:hover {{
        border-color: {PURPLE} !important;
        color: {PURPLE} !important;
      }}

      /* Alerts (st.info / warning / success / error) — legible text on light canvas */
      [data-testid="stAlert"], [data-testid="stAlert"] p,
      [data-testid="stAlertContainer"], [data-testid="stAlertContainer"] p,
      [data-testid="stNotification"] p {{
        color: {TEXT} !important;
      }}

      /* Links & horizontal rules */
      a {{ color: {PURPLE}; }}
      hr {{ border-color: {BORDER}; }}

      /* --- Brand header --- */
      .fa-header {{
        display: flex; align-items: center; gap: 16px;
        padding: 18px 22px; margin: 2px 0 10px;
        background: linear-gradient(120deg, {PANEL} 0%, {BG_ELEV} 100%);
        border: 1px solid {BORDER};
        border-radius: 16px;
        box-shadow: 0 6px 24px {PURPLE}14;
      }}
      .fa-header .fa-mark {{
        display: flex; align-items: center; justify-content: center;
        width: 60px; height: 60px; border-radius: 14px;
        background: {BG};
        border: 1px solid {BORDER};
        box-shadow: inset 0 0 22px {PURPLE}1f;
      }}
      .fa-title {{
        font-size: 2.0rem; font-weight: 700; line-height: 1.05; letter-spacing: -0.02em;
        background: {BRAND_GRADIENT};
        -webkit-background-clip: text; background-clip: text;
        -webkit-text-fill-color: transparent;
      }}
      .fa-tagline {{ color: {TEXT_MUTED}; font-size: .92rem; margin-top: 3px; }}
      .fa-ver {{
        margin-left: auto; align-self: flex-start;
        font-family: 'DM Mono', monospace !important;
        font-size: .72rem; font-weight: 600; color: {PURPLE_DEEP};
        background: {PURPLE}14; border: 1px solid {PURPLE}3d;
        padding: 4px 10px; border-radius: 999px; white-space: nowrap;
      }}
    </style>
    """


def inject_theme():
    """Inject the global stylesheet. Safe to call on every view/rerun."""
    st.markdown(_global_css(), unsafe_allow_html=True)


def render_app_header(subtitle: str | None = None):
    """Render the branded header with logo, name, tagline and version."""
    tagline = subtitle if subtitle is not None else APP_TAGLINE
    st.markdown(
        f'''<div class="fa-header">
              <div class="fa-mark">{logo_svg(38)}</div>
              <div>
                <div class="fa-title">{APP_NAME}</div>
                <div class="fa-tagline">{tagline}</div>
              </div>
              <div class="fa-ver">v{APP_VERSION}</div>
            </div>''',
        unsafe_allow_html=True,
    )


def version_caption() -> str:
    """Short version string for footers/sidebars."""
    return f"{APP_NAME} · v{APP_VERSION}"


# --------------------------------------------------------------------------- #
# Plotly helpers
# --------------------------------------------------------------------------- #
# Continuous scale (purple -> magenta) for heat/among-bars coloring.
CONTINUOUS_SCALE = [
    [0.0, PURPLE_DEEP],
    [0.5, PURPLE],
    [1.0, MAGENTA],
]


def style_fig(fig, height: int | None = None):
    """Apply the app's dark, DM Sans styling to a Plotly figure in place."""
    fig.update_layout(
        paper_bgcolor="rgba(0,0,0,0)",
        plot_bgcolor="rgba(0,0,0,0)",
        font=dict(family="DM Sans, sans-serif", color=TEXT, size=13),
        title=dict(font=dict(family="DM Sans, sans-serif", color=TEXT, size=17)),
        legend=dict(font=dict(color=TEXT_MUTED)),
        margin=dict(t=70, l=10, r=10, b=10),
        colorway=CHART_SEQUENCE,
    )
    fig.update_xaxes(gridcolor=BORDER, zerolinecolor=BORDER, linecolor=BORDER,
                     tickfont=dict(color=TEXT_MUTED), title_font=dict(color=TEXT_MUTED))
    fig.update_yaxes(gridcolor=BORDER, zerolinecolor=BORDER, linecolor=BORDER,
                     tickfont=dict(color=TEXT_MUTED), title_font=dict(color=TEXT_MUTED))
    if height:
        fig.update_layout(height=height)
    return fig
