"""Snowbird PCB Interactive Debugger - KGU vs DUT comparison."""
import streamlit as st
import pandas as pd

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
