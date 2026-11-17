"""
Utilities for discovering per-dataset config folders (config/<dataset>/), reading their settings.yaml,
and writing the resulting selections out to config/master_config.yaml. Used by gui.py.
"""

from datetime import date, datetime, time, timedelta
from pathlib import Path

import yaml

from parsers import actions_parser
from parsers import schema_parser
from app_paths import get_base_path

BASE_PATH = get_base_path()
CONFIG_DIR = BASE_PATH / "config"
MASTER_CONFIG_PATH = CONFIG_DIR / "master_config.yaml"
SAVE_DATA_DIR = BASE_PATH / "save_data"


def ensure_save_data_dirs(dataset_name: str) -> dict:
    """
    Ensures save_data/<dataset_name>/sql_queries and save_data/<dataset_name>/saved_tables exist - creating
    save_data/ itself the first time any dataset is loaded - and returns their paths. Called whenever a
    dataset's config is loaded (see App._on_dataset_selected), and also used to create/validate standalone
    "JDW sessions" (see ui/session_picker.py) - a JDW session is just a save_data/<name>/ folder, whether or
    not <name> corresponds to an actual config/<dataset>/.
    """
    dataset_dir = SAVE_DATA_DIR / dataset_name
    dirs = {
        "sql_queries": dataset_dir / "sql_queries",
        "saved_tables": dataset_dir / "saved_tables",
    }
    for directory in dirs.values():
        directory.mkdir(parents=True, exist_ok=True)
    return dirs


def list_save_data_sessions() -> list[str]:
    """Returns sorted names of save_data/ subfolders that look like a valid JDW session (i.e. already have
    both sql_queries/ and saved_tables/ subfolders - see ensure_save_data_dirs())."""
    if not SAVE_DATA_DIR.exists():
        return []
    return sorted(
        folder.name
        for folder in SAVE_DATA_DIR.iterdir()
        if folder.is_dir() and (folder / "sql_queries").is_dir() and (folder / "saved_tables").is_dir()
    )


def list_dataset_names() -> list[str]:
    """
    Returns: sorted names of subfolders under config/ that contain a settings.yaml (e.g. ["acbsny", "acbsuk", "mock"]).
    """
    if not CONFIG_DIR.exists():
        return []

    return sorted(
        folder.name
        for folder in CONFIG_DIR.iterdir()
        if folder.is_dir() and (folder / "settings.yaml").exists()
    )


def list_selection_function_modules() -> list[str]:
    """
    Returns: sorted dotted module names (e.g. ["selection_functions.selection_function_least_chosen",
    "selection_functions.selection_function_uniform"]) for every .py file in the selection_functions/ package.
    """
    package_dir = BASE_PATH / "selection_functions"
    if not package_dir.exists():
        return []

    return sorted(
        f"selection_functions.{file.stem}"
        for file in package_dir.glob("*.py")
        if file.stem != "__init__"
    )


def create_dataset(dataset_name: str) -> None:
    """
    Scaffolds a brand-new config/<dataset_name>/ folder: settings.yaml (with placeholder module names the
    user must adjust), a template schema_entity_relationships.yaml (editable via schema_viewer.py), and an
    empty actions.yaml. Raises ValueError if dataset_name is invalid or already exists.
    """
    dataset_name = dataset_name.strip()
    if not dataset_name:
        raise ValueError("Dataset name cannot be empty.")
    if dataset_name != Path(dataset_name).name:
        raise ValueError(f"Dataset name '{dataset_name}' must not contain path separators.")
    if dataset_name in list_dataset_names():
        raise ValueError(f"Dataset '{dataset_name}' already exists.")

    dataset_dir = CONFIG_DIR / dataset_name
    dataset_dir.mkdir(parents=True, exist_ok=False)

    default_settings = {
        "attr_gen_functions_module": "mock_attr_gen_functions",
        "selection_functions_module": "selection_functions.selection_function_uniform",
        "seconds_per_time_step": 60,
        "daily_start_time": "09:00:00",
        "daily_end_time": "17:00:00",
        "checkpoint_times": ["00:00:00"],
        "start_date": None,
        "num_days": 2,
    }
    with open(dataset_dir / "settings.yaml", "w") as f:
        yaml.safe_dump(default_settings, f, sort_keys=False, default_flow_style=False)

    with open(dataset_dir / "schema_entity_relationships.yaml", "w") as f:
        f.write(schema_parser.new_schema_template_text())

    with open(dataset_dir / "actions.yaml", "w") as f:
        f.write(actions_parser.new_actions_template_text())


def load_dataset_settings(dataset_name: str) -> dict:
    """
    Reads config/<dataset_name>/settings.yaml and adds the (dataset-relative) schema/actions file paths.

    Returns: {
        "schema_entity_relationships_filepath": "config/<dataset_name>/schema_entity_relationships.yaml",
        "actions_config": "config/<dataset_name>/actions.yaml",
        "attr_gen_functions_module": ...,
        "selection_functions_module": ...,
        "seconds_per_time_step": ...,
        "daily_start_time": time(...),
        "daily_end_time": time(...),
        "checkpoint_times": [time(...), ...],
        "start_date": date(...),
        "num_days": int,
    }
    """
    settings_path = CONFIG_DIR / dataset_name / "settings.yaml"
    with open(settings_path, "r") as f:
        settings = yaml.safe_load(f) or {}

    settings["schema_entity_relationships_filepath"] = f"config/{dataset_name}/schema_entity_relationships.yaml"
    settings["actions_config"] = f"config/{dataset_name}/actions.yaml"
    settings["daily_start_time"] = time.fromisoformat(str(settings["daily_start_time"]))
    settings["daily_end_time"] = time.fromisoformat(str(settings["daily_end_time"]))
    settings["checkpoint_times"] = [time.fromisoformat(str(t)) for t in settings["checkpoint_times"]]
    settings["start_date"] = date.fromisoformat(str(settings["start_date"])) if settings.get("start_date") else date.today()
    settings["num_days"] = settings.get("num_days") or 1
    return settings


def save_dataset_settings(dataset_name: str, settings: dict) -> None:
    """
    Writes settings (attr_gen_functions_module, selection_functions_module, seconds_per_time_step,
    daily_start_time, daily_end_time, checkpoint_times, start_date, num_days) back to
    config/<dataset_name>/settings.yaml, so they're restored next time this dataset is selected.
    """
    dataset_settings = {
        "attr_gen_functions_module": settings["attr_gen_functions_module"],
        "selection_functions_module": settings["selection_functions_module"],
        "seconds_per_time_step": settings["seconds_per_time_step"],
        "daily_start_time": settings["daily_start_time"].strftime("%H:%M:%S"),
        "daily_end_time": settings["daily_end_time"].strftime("%H:%M:%S"),
        "checkpoint_times": [t.strftime("%H:%M:%S") for t in settings["checkpoint_times"]],
        "start_date": settings["start_date"].strftime("%Y-%m-%d"),
        "num_days": settings["num_days"],
    }

    settings_path = CONFIG_DIR / dataset_name / "settings.yaml"
    with open(settings_path, "w") as f:
        yaml.safe_dump(dataset_settings, f, sort_keys=False, default_flow_style=False)


def build_daily_windows(start_date: date, num_days: int, daily_start_time: time, daily_end_time: time) -> list[tuple[datetime, datetime]]:
    """
    Builds the list of (window_start, window_end) datetimes the engine should run within: one window per day,
    from start_date for num_days days, each spanning daily_start_time to daily_end_time on that day.
    """
    if num_days < 1:
        raise ValueError(f"num_days must be at least 1, got {num_days}.")
    if daily_end_time <= daily_start_time:
        raise ValueError(f"daily_end_time ({daily_end_time}) must be after daily_start_time ({daily_start_time}).")

    return [
        (
            datetime.combine(start_date + timedelta(days=day_offset), daily_start_time),
            datetime.combine(start_date + timedelta(days=day_offset), daily_end_time),
        )
        for day_offset in range(num_days)
    ]


def write_master_config(dataset_name: str, settings: dict, daily_windows: list[tuple[datetime, datetime]], master_config_path: Path = MASTER_CONFIG_PATH) -> None:
    """
    Writes config/master_config.yaml from a dataset's (possibly edited) settings dict and the computed daily_windows.
    """
    master_config = {
        "schema_entity_relationships_filepath": f"config/{dataset_name}/schema_entity_relationships.yaml",
        "actions_config": f"config/{dataset_name}/actions.yaml",
        "attr_gen_functions_module": settings["attr_gen_functions_module"],
        "selection_functions_module": settings["selection_functions_module"],
        "seconds_per_time_step": settings["seconds_per_time_step"],
        "checkpoint_times": [t.strftime("%H:%M:%S") for t in settings["checkpoint_times"]],
        "daily_windows": [
            {"start": window_start.strftime("%Y-%m-%d %H:%M:%S"), "end": window_end.strftime("%Y-%m-%d %H:%M:%S")}
            for window_start, window_end in daily_windows
        ],
    }

    master_config_path.parent.mkdir(parents=True, exist_ok=True)
    with open(master_config_path, "w") as f:
        yaml.safe_dump(master_config, f, sort_keys=False, default_flow_style=False)


def load_master_config_for_gui(master_config_path: Path = MASTER_CONFIG_PATH) -> dict:
    """
    Reads config/master_config.yaml back into a GUI-friendly shape, deriving start_date/num_days/
    daily_start_time/daily_end_time from its daily_windows (always uniform, since only this GUI generates them).
    """
    with open(master_config_path, "r") as f:
        master_config = yaml.safe_load(f) or {}

    windows = sorted(
        (
            datetime.strptime(str(window["start"]), "%Y-%m-%d %H:%M:%S"),
            datetime.strptime(str(window["end"]), "%Y-%m-%d %H:%M:%S"),
        )
        for window in master_config["daily_windows"]
    )
    first_window_start, first_window_end = windows[0]

    return {
        "schema_entity_relationships_filepath": master_config["schema_entity_relationships_filepath"],
        "actions_config": master_config["actions_config"],
        "attr_gen_functions_module": master_config["attr_gen_functions_module"],
        "selection_functions_module": master_config["selection_functions_module"],
        "seconds_per_time_step": master_config["seconds_per_time_step"],
        "checkpoint_times": [time.fromisoformat(str(t)) for t in master_config["checkpoint_times"]],
        "daily_start_time": first_window_start.time(),
        "daily_end_time": first_window_end.time(),
        "start_date": first_window_start.date(),
        "num_days": len(windows),
    }
