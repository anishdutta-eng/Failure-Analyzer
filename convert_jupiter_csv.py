"""Convert a Jupiter EFFA/WRR tracker CSV into the Snowbird field-returns schema
so it can be visualized in the Dashboard, Fault Wheel, and reports.

Jupiter columns:
    Unit Serial Number, Source, Reason Code, Time in Field (Looker, days),
    WOM, Device/PSU, Result/Status, Root Cause, Failure Category, Notes

Snowbird schema (target):
    ID, User_Reported_Date, Return_Reason_Code, Unit_SN, Power_Adapter,
    PSU_MFG_WW, Jira_Ticket, Jira_Ticket_Reported, FA_Status, Shipment_Status,
    CM_Ticket, Root_Cause, Root_Cause_Reason, SW_Related_Issue, SW_JIRA,
    HW_Related_Issue, NTF, Comments

The key idea: the Fault Wheel groups by `Root_Cause_Reason` (keyword-categorized),
so we set that field to Jupiter's `Failure Category` for identified defects, and
leave it blank for NTF / Won't-do / pending rows (so the wheel shows only real
failure modes). The specific component (e.g. "C448 short to GND") is preserved in
Comments.

Usage:
    python convert_jupiter_csv.py <input_jupiter.csv> <output_snowbird_format.csv>
"""

from __future__ import annotations

import csv
import sys

SNOWBIRD_COLUMNS = [
    "ID", "User_Reported_Date", "Return_Reason_Code", "Unit_SN", "Power_Adapter",
    "PSU_MFG_WW", "Jira_Ticket", "Jira_Ticket_Reported", "FA_Status",
    "Shipment_Status", "CM_Ticket", "Root_Cause", "Root_Cause_Reason",
    "SW_Related_Issue", "SW_JIRA", "HW_Related_Issue", "NTF", "Comments",
]

# Failure Category -> (issue_kind, Root_Cause_Reason used in the fault wheel)
DEFECT_CATEGORIES = {
    "capacitor short / damage": ("HW", "Capacitor Short / Damage"),
    "soc / ic failure": ("HW", "SoC / IC Failure"),
    "surge damage (multi-component)": ("HW", "Surge Damage"),
    "surge damage": ("HW", "Surge Damage"),
    "material / chemical": ("HW", "Material / Chemical"),
    "software / configuration": ("SW", "Software / Configuration"),
}

# Failure Category -> derived Root_Cause status (no real defect)
NODEFECT_CATEGORIES = {
    "no defect / customer / fraud": "No Failure Found",
    "no defect / ntf": "No Failure Found",
    "no defect / not analyzed": "Won't do",
    "pending analysis": "To Do",
}


def _norm_reason(reason: str) -> str:
    r = (reason or "").strip()
    rl = r.lower()
    if "dead after arrival" in rl or "will not turn on" in rl:
        return "DAA"
    if "dead on arrival" in rl:
        return "DOA"
    return r


def _clean(v) -> str:
    v = ("" if v is None else str(v)).strip()
    return "" if v.lower() in {"n/a", "na", "none", "null", "-", "nan"} else v


def convert_row(row: dict, idx: int) -> dict:
    fc = (row.get("Failure Category") or "").strip()
    fc_key = fc.lower()
    result_status = _clean(row.get("Result/Status"))
    specific_cause = _clean(row.get("Root Cause"))
    notes = (row.get("Notes") or "").strip().replace("\n", " ").replace("\r", " ")
    source = _clean(row.get("Source"))
    tif = _clean(row.get("Time in Field (Looker, days)"))
    wom = _clean(row.get("WOM"))

    sw = hw = ntf = ""
    if fc_key in DEFECT_CATEGORIES:
        status = "Root Cause Identified"
        kind, reason = DEFECT_CATEGORIES[fc_key]
        sw = "YES" if kind == "SW" else "NO"
        hw = "YES" if kind == "HW" else "NO"
        ntf = "NO"
        root_cause_reason = reason
    elif fc_key in NODEFECT_CATEGORIES:
        status = NODEFECT_CATEGORIES[fc_key]
        root_cause_reason = ""
        ntf = "YES" if status == "No Failure Found" else "NO"
    else:
        # Unknown/blank category: identified if a specific cause exists, else pending
        status = "Root Cause Identified" if specific_cause else "To Do"
        root_cause_reason = fc if (fc and specific_cause) else ""

    # Preserve the specific component / detail in Comments
    parts = []
    if source:
        parts.append(f"[{source}]")
    if specific_cause:
        parts.append(f"Root cause: {specific_cause}.")
    if tif:
        parts.append(f"Time in field: {tif} days.")
    if notes:
        parts.append(notes)
    comments = " ".join(parts).strip()

    return {
        "ID": idx,
        "User_Reported_Date": "",  # Jupiter tracker has no report date
        "Return_Reason_Code": _norm_reason(row.get("Reason Code")),
        "Unit_SN": _clean(row.get("Unit Serial Number")),
        "Power_Adapter": "",
        "PSU_MFG_WW": wom,
        "Jira_Ticket": "",
        "Jira_Ticket_Reported": "",
        "FA_Status": result_status,
        "Shipment_Status": "",
        "CM_Ticket": "",
        "Root_Cause": status,
        "Root_Cause_Reason": root_cause_reason,
        "SW_Related_Issue": sw,
        "SW_JIRA": "",
        "HW_Related_Issue": hw,
        "NTF": ntf,
        "Comments": comments,
    }


# Columns that identify a Jupiter tracker export (used for auto-detection).
JUPITER_SIGNATURE_COLUMNS = {"Reason Code", "Failure Category", "Root Cause"}


def looks_like_jupiter(columns) -> bool:
    """True if the given column set looks like a Jupiter tracker export."""
    return JUPITER_SIGNATURE_COLUMNS.issubset(set(columns))


def convert_dataframe(df):
    """Convert a Jupiter tracker DataFrame to a Snowbird-schema DataFrame.
    Values are stringified so numeric-looking columns (WOM, Time in Field)
    don't leak float artifacts like '2333.0'."""
    import pandas as pd
    rows = [convert_row({k: _clean(v) for k, v in r.items()}, i)
            for i, (_, r) in enumerate(df.iterrows(), start=1)]
    return pd.DataFrame(rows, columns=SNOWBIRD_COLUMNS)


def convert_bytes(file_bytes: bytes) -> bytes:
    """Convert Jupiter CSV bytes to Snowbird-schema CSV bytes (in memory)."""
    import io
    import pandas as pd
    # Read everything as strings (like csv.DictReader) so integer codes such as
    # WOM stay '2333' rather than becoming '2333.0'.
    df = pd.read_csv(io.BytesIO(file_bytes), dtype=str, keep_default_na=False)
    out = convert_dataframe(df)
    return out.to_csv(index=False).encode("utf-8")


def convert(input_path: str, output_path: str) -> int:
    with open(input_path, newline="", encoding="utf-8-sig") as f:
        reader = csv.DictReader(f)
        rows = [convert_row(r, i) for i, r in enumerate(reader, start=1)]
    with open(output_path, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=SNOWBIRD_COLUMNS)
        writer.writeheader()
        writer.writerows(rows)
    return len(rows)


if __name__ == "__main__":
    if len(sys.argv) != 3:
        print("Usage: python convert_jupiter_csv.py <input_jupiter.csv> <output.csv>")
        sys.exit(1)
    n = convert(sys.argv[1], sys.argv[2])
    print(f"Converted {n} rows -> {sys.argv[2]}")
