"""
CSV -> parquet import for JDW's "Import CSV" feature (see ui/jdw_window.py). One CSV at a time only, since
datatype coercion needs reviewing per file. Reads every column as a raw string first (so leading zeros,
exact formatting, etc. are never lost by pandas' automatic type-guessing), then, only if the caller supplies
a column schema (YAML or JSON), explicitly casts columns to their declared datatype.
"""

import json
from pathlib import Path

import pandas as pd
import yaml

# Mirrors the datatype vocabulary already used in schema_entity_relationships.yaml (see parsers/schema_parser.py).
_DTYPE_CASTERS = {
    "STRING": lambda series: series,
    "INTEGER": lambda series: pd.to_numeric(series, errors="raise").astype("Int64"),
    "FLOAT": lambda series: pd.to_numeric(series, errors="raise").astype("float64"),
    "BOOLEAN": lambda series: series.str.strip().str.lower().map({"true": True, "1": True, "false": False, "0": False}),
    "DATE": lambda series: pd.to_datetime(series, errors="raise").dt.date,
    "DATETIME": lambda series: pd.to_datetime(series, errors="raise"),
}


def load_column_schema(schema_path: Path, table_name: str = None) -> dict:
    """
    Loads a column-datatype schema from either:
      - a simple {"columns": {name: TYPE}} mapping (YAML or JSON), or
      - a full schema_entity_relationships.yaml-style document (see e.g.
        config/acbsuk/schema_entity_relationships.yaml) - {"tables": {table_name: {"fields": [{"name":
        ..., "datatype": ...}, ...], ...}, ...}} - in which case table_name selects which table's fields
        describe this CSV (required if the document defines more than one table - see
        list_schema_table_names()).
    The schema may list more columns than any one CSV actually has (see import_csv_to_dataframe()).
    Returns: {column_name: datatype (upper-cased)}.
    """
    raw = _load_raw_schema_document(schema_path)

    if "columns" in raw:
        return {str(name): str(datatype).strip().upper() for name, datatype in (raw["columns"] or {}).items()}

    tables = raw.get("tables") or {}
    if tables:
        if table_name is None:
            if len(tables) != 1:
                raise ValueError(f"Schema defines multiple tables ({sorted(tables)}) - specify which one describes this CSV.")
            table_name = next(iter(tables))
        if table_name not in tables:
            raise ValueError(f"Table '{table_name}' not found in schema. Available: {sorted(tables)}.")
        fields = (tables[table_name] or {}).get("fields") or []
        return {str(field["name"]): str(field["datatype"]).strip().upper() for field in fields}

    raise ValueError("Schema file doesn't look like a recognised format (expected a top-level 'columns' or 'tables' key).")


def list_schema_table_names(schema_path: Path) -> list[str]:
    """Returns the table names defined in schema_path if it's a tables-style schema, else an empty list
    (e.g. for a simple {"columns": ...} schema, which only ever describes one, unnamed table)."""
    return sorted((_load_raw_schema_document(schema_path).get("tables") or {}))


def _load_raw_schema_document(schema_path: Path) -> dict:
    schema_path = Path(schema_path)
    with open(schema_path, "r") as f:
        raw = json.load(f) if schema_path.suffix.lower() == ".json" else yaml.safe_load(f)
    return raw or {}


def import_csv_to_dataframe(csv_path: Path, column_schema: dict = None) -> pd.DataFrame:
    """
    Reads csv_path with every column as dtype=str (never auto-guessed - preserves leading zeros, exact
    formatting, etc. exactly as written), then, if column_schema is given, explicitly casts each CSV column
    to its declared datatype (STRING/INTEGER/FLOAT/BOOLEAN/DATE/DATETIME). Without a schema, every column is
    left as plain strings - the safest possible default.

    Raises ValueError if:
      - column_schema is given but the CSV has a column not described in it (the schema may have MORE
        columns than the CSV, but the CSV may never have columns the schema doesn't know about).
      - a column's schema datatype is unrecognised, or a value can't actually be cast to it.
    """
    df = pd.read_csv(csv_path, dtype=str)

    if column_schema is None:
        return df

    unknown_columns = [column for column in df.columns if column not in column_schema]
    if unknown_columns:
        raise ValueError(f"CSV has column(s) not described in the schema: {unknown_columns}. Every CSV column must be listed in the schema.")

    for column in df.columns:
        datatype = column_schema[column]
        caster = _DTYPE_CASTERS.get(datatype)
        if caster is None:
            raise ValueError(f"Unknown datatype '{datatype}' for column '{column}' in schema. Supported: {sorted(_DTYPE_CASTERS)}.")
        try:
            df[column] = caster(df[column])
        except Exception as e:
            raise ValueError(f"Failed to cast column '{column}' to {datatype}: {e}") from e

    return df


def import_csv_to_parquet(csv_path: Path, destination_dir: Path, column_schema: dict = None) -> Path:
    """
    Converts csv_path to a parquet file (named after the CSV, written into destination_dir), applying
    column_schema (if given) via import_csv_to_dataframe(). Returns the new parquet file's path.
    """
    df = import_csv_to_dataframe(csv_path, column_schema)
    destination_dir = Path(destination_dir)
    destination_dir.mkdir(parents=True, exist_ok=True)
    parquet_path = destination_dir / f"{Path(csv_path).stem}.parquet"
    df.to_parquet(parquet_path, index=False)
    return parquet_path
