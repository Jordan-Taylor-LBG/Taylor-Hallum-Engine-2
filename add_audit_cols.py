"""
Adds audit columns (fields marked `is_audit_column: true` per-table in schema_entity_relationships.yaml) to
already-generated snapshot/delta CSV files, writing the result into that same checkpoint's
gcp_staging_csv/ subfolder (mirroring the deltas/snapshots layout under each simulated-datetime folder) -
source files are never modified. Audit columns are excluded from the tables' own generated data (see
core/engine.py's Table.__init__, which filters them out before building each table's dataframe), so this is
purely a post-processing step over CSVs that already exist: there's no dependency between the underlying
data and the audit columns added here.

This script has no generation logic of its own - it's a generic dispatcher. Each audit column's value is
computed by a function in the dataset's own attr_gen_functions module (e.g. acbsuk_attr_gen_functions.py -
the same module used for every other generated attribute), resolved exactly like a regular field: the
schema's `default_function` for that field if set, else the convention `generate_<field_name>` (e.g.
"bts_batch_dt" -> generate_bts_batch_dt). An audit column with neither is left blank (None) - see
acbsuk_attr_gen_functions.py's template_audit_col_gen_func for the function signature these must implement.

Folder layout (per dataset, per simulated-datetime checkpoint):
    generated_data_files/<dataset_name>/<simulated_datetime>/deltas/{csv,parquet}/{positive,negative}/<table>.{csv,parquet}
    generated_data_files/<dataset_name>/<simulated_datetime>/deltas/gcp_staging_csv/{positive,negative}/<table>.csv
    generated_data_files/<dataset_name>/<simulated_datetime>/snapshots/{csv,parquet}/<table>.{csv,parquet}
    generated_data_files/<dataset_name>/<simulated_datetime>/snapshots/gcp_staging_csv/<table>.csv

Called automatically by the engine after every checkpoint save (see core/engine.py's
Engine.__save_checkpoint__(), which passes its own attr_gen_functions module through). Can also be run
standalone (python add_audit_cols.py) to (re)stage the whole current generated_data_files/<dataset>/ tree,
using whichever schema + attr_gen_functions_module config/master_config.yaml currently points at.
"""

from datetime import datetime
from pathlib import Path

import pandas as pd

from core import config_manager
from core import engine as engine_module
from parsers import schema_parser

BASE_PATH = Path(__file__).parent

# Matches the simulated-datetime folder name written by the engine, e.g. "20260922_113612"
DATETIME_FOLDER_FORMAT = "%Y%m%d_%H%M%S"


def get_table_audit_columns(schema_tables: dict, table_name: str) -> list[tuple[str, str]]:
    """Returns [(field_name, default_function_name_or_None), ...] for table_name's fields marked
    is_audit_column: true - [] if the table isn't in the schema, or has none declared."""
    fields = (schema_tables.get(table_name) or {}).get("fields") or []
    return [(field["name"], field.get("default_function")) for field in fields if field.get("is_audit_column")]


def _resolve_audit_column_function(attr_gen_functions, field_name: str, default_function_name: str):
    """Resolves the function to call for one audit column - the schema's default_function if given and
    present on the module, else the generate_<field_name> convention, else None (left blank)."""
    for function_name in (default_function_name, f"generate_{field_name}"):
        if function_name and hasattr(attr_gen_functions, function_name):
            return getattr(attr_gen_functions, function_name)
    return None


def get_simulated_datetime_from_folder_name(folder_name: str) -> datetime:
    try:
        return datetime.strptime(folder_name, DATETIME_FOLDER_FORMAT)
    except ValueError:
        raise Exception(f"Could not parse simulated datetime from folder name: {folder_name}")


def add_audit_cols_to_dataframe(df: pd.DataFrame, table_name: str, simulated_datetime: datetime, audit_columns: list, file_type: str, attr_gen_functions) -> pd.DataFrame:
    """Returns a copy of df with each audit column in audit_columns (see get_table_audit_columns())
    appended. Each column's resolved function (see _resolve_audit_column_function()) is called once for
    the whole file (not once per row) - it returns either a single value (broadcast to every row) or a
    list/array of one value per row. An audit column with no resolvable function is left blank (None)."""
    audit_col_values = {}
    for field_name, default_function_name in audit_columns:
        generator = _resolve_audit_column_function(attr_gen_functions, field_name, default_function_name)
        audit_col_values[field_name] = generator(field_name, table_name, df, simulated_datetime, file_type) if generator else None

    return pd.concat([df, pd.DataFrame(audit_col_values, index=df.index)], axis=1)


def _file_type_for_path(filepath: Path) -> str:
    """'positive'/'negative' for a delta file (based on its containing folder), else 'snapshot'."""
    return filepath.parent.name if filepath.parent.name in ("positive", "negative") else "snapshot"


def stage_file_with_audit_cols(source_path: Path, destination_path: Path, schema_tables: dict, simulated_datetime: datetime, attr_gen_functions) -> None:
    """
    Reads source_path (a csv), adds its table's audit columns (looked up by source_path's stem as the table
    name), and writes the result to destination_path (creating parent folders as needed) - source_path is
    never modified. Does nothing for an empty csv (no delta rows) or a table with no audit columns declared.
    """
    if source_path.stat().st_size == 0:
        return  # No delta rows were generated for this table/checkpoint - nothing to add columns to.

    df = pd.read_csv(source_path)

    table_name = source_path.stem
    audit_columns = get_table_audit_columns(schema_tables, table_name)
    if not audit_columns:
        return

    df = add_audit_cols_to_dataframe(df, table_name, simulated_datetime, audit_columns, _file_type_for_path(source_path), attr_gen_functions)

    destination_path.parent.mkdir(parents=True, exist_ok=True)
    df.to_csv(destination_path, index=False)


def _stage_checkpoint_folder(checkpoint_dir: Path, schema_tables: dict, simulated_datetime: datetime, attr_gen_functions) -> None:
    """Stages checkpoint_dir's deltas/csv/ and snapshots/csv/ files into their sibling gcp_staging_csv/
    folders (see module docstring for the full layout)."""
    for section in ("deltas", "snapshots"):
        csv_source_dir = checkpoint_dir / section / "csv"
        if not csv_source_dir.exists():
            continue
        gcp_staging_dir = checkpoint_dir / section / "gcp_staging_csv"
        for source_path in csv_source_dir.rglob("*.csv"):
            destination_path = gcp_staging_dir / source_path.relative_to(csv_source_dir)
            stage_file_with_audit_cols(source_path, destination_path, schema_tables, simulated_datetime, attr_gen_functions)


def stage_checkpoint_with_audit_cols(schema_entity_relationships_filepath, dataset_name: str, simulated_datetime_str: str, attr_gen_functions, base_path: Path = BASE_PATH) -> None:
    """Stages just one checkpoint's worth of files
    (generated_data_files/<dataset_name>/<simulated_datetime_str>/...). Called automatically after every
    engine checkpoint save, passing that engine's own attr_gen_functions module through."""
    schema_tables = schema_parser.load_schema(schema_entity_relationships_filepath)["tables"]
    simulated_datetime = get_simulated_datetime_from_folder_name(simulated_datetime_str)
    checkpoint_dir = Path(base_path) / "generated_data_files" / dataset_name / simulated_datetime_str
    _stage_checkpoint_folder(checkpoint_dir, schema_tables, simulated_datetime, attr_gen_functions)


def stage_all_with_audit_cols(schema_entity_relationships_filepath, attr_gen_functions, base_path: Path = BASE_PATH) -> None:
    """Re-stages every simulated-datetime folder under generated_data_files/<dataset_name>/ (dataset_name
    derived from schema_entity_relationships_filepath's parent folder, e.g.
    config/acbsuk/schema_entity_relationships.yaml -> "acbsuk") - e.g. for a manual/standalone re-run
    (python add_audit_cols.py) against an existing output folder."""
    schema_tables = schema_parser.load_schema(schema_entity_relationships_filepath)["tables"]
    dataset_name = Path(schema_entity_relationships_filepath).parent.name
    dataset_dir = Path(base_path) / "generated_data_files" / dataset_name
    if not dataset_dir.exists():
        return

    for checkpoint_dir in dataset_dir.iterdir():
        if not checkpoint_dir.is_dir():
            continue
        try:
            simulated_datetime = get_simulated_datetime_from_folder_name(checkpoint_dir.name)
        except Exception:
            continue  # Not a simulated-datetime checkpoint folder - skip it.
        _stage_checkpoint_folder(checkpoint_dir, schema_tables, simulated_datetime, attr_gen_functions)


if __name__ == '__main__':
    master_config = config_manager.load_master_config_for_gui()
    attr_gen_functions = engine_module.load_attr_gen_functions_module_from_master_config()
    stage_all_with_audit_cols(config_manager.BASE_PATH / master_config["schema_entity_relationships_filepath"], attr_gen_functions)
