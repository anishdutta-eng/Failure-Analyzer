"""One-time migration: move existing Snowbird data into programs/snowbird/."""
import os
import shutil
from program_config import register_program, get_program_dir

BASE = os.path.dirname(os.path.abspath(__file__))


def migrate():
    prog_dir = register_program(
        "Snowbird",
        display_name="Snowbird",
        product="eero Outdoor 7 (Snowbird)",
        description="WiFi 7 Outdoor Access Point — IP66, PoE, tri-band"
    )

    # Move debug_reports/
    src_reports = os.path.join(BASE, "debug_reports")
    dst_reports = os.path.join(prog_dir, "debug_reports")
    if os.path.isdir(src_reports):
        for f in os.listdir(src_reports):
            if f.endswith(".json"):
                shutil.move(os.path.join(src_reports, f), os.path.join(dst_reports, f))
        # Remove old dir if empty (ignore .DS_Store)
        remaining = [x for x in os.listdir(src_reports) if x != ".DS_Store"]
        if not remaining:
            shutil.rmtree(src_reports, ignore_errors=True)

    # Move ML model
    src_ml = os.path.join(BASE, "debugger_ml_model.json")
    dst_ml = os.path.join(prog_dir, "debugger_ml_model.json")
    if os.path.isfile(src_ml):
        shutil.move(src_ml, dst_ml)

    # Copy CSV data
    src_csv = os.path.join(BASE, "snowbird_field_returns.csv")
    dst_csv = os.path.join(prog_dir, "data", "snowbird_field_returns.csv")
    if os.path.isfile(src_csv):
        shutil.copy2(src_csv, dst_csv)

    # Copy debug bible
    src_bible = os.path.join(BASE, "snowbird_debug_bible.md")
    dst_bible = os.path.join(prog_dir, "snowbird_debug_bible.md")
    if os.path.isfile(src_bible):
        shutil.copy2(src_bible, dst_bible)

    print(f"Migration complete. Snowbird data moved to: {prog_dir}")


if __name__ == "__main__":
    migrate()
