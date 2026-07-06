"""Program configuration and registry for multi-program support."""
import os
import json
import streamlit as st

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
PROGRAMS_DIR = os.path.join(BASE_DIR, "programs")
REGISTRY_PATH = os.path.join(PROGRAMS_DIR, "registry.json")


def _ensure_dirs():
    """Ensure programs directory exists."""
    os.makedirs(PROGRAMS_DIR, exist_ok=True)


def load_registry():
    """Load the program registry."""
    _ensure_dirs()
    if os.path.exists(REGISTRY_PATH):
        with open(REGISTRY_PATH) as f:
            return json.load(f)
    return {"programs": {}}


def save_registry(registry):
    """Save the program registry."""
    _ensure_dirs()
    with open(REGISTRY_PATH, "w") as f:
        json.dump(registry, f, indent=2)


def get_program_list():
    """Return list of registered program names."""
    return list(load_registry().get("programs", {}).keys())


def get_program_dir(program_name):
    """Return the directory path for a given program."""
    slug = program_name.lower().replace(" ", "_")
    return os.path.join(PROGRAMS_DIR, slug)


def get_ml_training_dir(program_name):
    """Return the ML training directory for a program (reports + trained model)."""
    return os.path.join(get_program_dir(program_name), "ml_training")


def get_reports_dir(program_name):
    """Return the debug_reports directory for a program (ML training data)."""
    return os.path.join(get_ml_training_dir(program_name), "debug_reports")


def get_ml_model_path(program_name):
    """Return the ML model JSON path for a program."""
    return os.path.join(get_ml_training_dir(program_name), "debugger_ml_model.json")


def get_csv_dir(program_name):
    """Return the CSV data directory for a program."""
    return os.path.join(get_program_dir(program_name), "data")


def register_program(name, display_name=None, product=None, description=""):
    """Register a new program in the registry and create its folder structure."""
    registry = load_registry()
    slug = name.lower().replace(" ", "_")
    prog_dir = get_program_dir(name)

    # Create folder structure
    os.makedirs(prog_dir, exist_ok=True)
    os.makedirs(os.path.join(prog_dir, "ml_training", "debug_reports"), exist_ok=True)
    os.makedirs(os.path.join(prog_dir, "data"), exist_ok=True)

    registry["programs"][name] = {
        "slug": slug,
        "display_name": display_name or name,
        "product": product or name,
        "description": description,
        "directory": prog_dir,
    }
    save_registry(registry)
    return prog_dir


def get_selected_program():
    """Get the currently selected program from session state."""
    return st.session_state.get("selected_program", None)


def set_selected_program(name):
    """Set the currently selected program in session state."""
    st.session_state["selected_program"] = name
