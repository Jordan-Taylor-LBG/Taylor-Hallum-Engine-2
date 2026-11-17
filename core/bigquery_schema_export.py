"""
Downloads BigQuery table schemas as JSON (via google-cloud-bigquery), then converts each JSON into a YAML
skeleton in the same {"tables": {name: {"fields": [...]}}} shape used by our own schema_entity_relationships
.yaml files (see parsers/schema_parser.py) - primary_keys/depends_on/relationships aren't derivable from a
BigQuery schema alone, so they're left as empty placeholders for the user to fill in afterwards.
Used by ui/bigquery_schema_window.py.
"""

import json
from pathlib import Path

import yaml
from google.cloud import bigquery

# BigQuery field types -> our schema vocabulary (see core/csv_import.py for the same set of tokens).
_BIGQUERY_TYPE_MAPPINGS = {
    "STRING": "STRING",
    "BYTES": "STRING",
    "GEOGRAPHY": "STRING",
    "JSON": "STRING",
    "TIME": "STRING",
    "INTEGER": "INTEGER",
    "INT64": "INTEGER",
    "FLOAT": "FLOAT",
    "FLOAT64": "FLOAT",
    "NUMERIC": "FLOAT",
    "BIGNUMERIC": "FLOAT",
    "BOOLEAN": "BOOLEAN",
    "BOOL": "BOOLEAN",
    "DATE": "DATE",
    "DATETIME": "DATETIME",
    "TIMESTAMP": "DATETIME",
    "RECORD": "STRING",
    "STRUCT": "STRING",
}


def get_client() -> bigquery.Client:
    """
    Constructs a bigquery.Client() using Application Default Credentials - raises a clear error (rather
    than the library's own less obvious one) if gcloud auth hasn't been set up yet (see
    ensure_gcloud_authenticated() in ui/bigquery_schema_window.py).
    """
    print("[bigquery_schema_export] Constructing BigQuery client (resolving ADC credentials)...", flush=True)
    try:
        client = bigquery.Client()
        print("[bigquery_schema_export] BigQuery client constructed.", flush=True)
        return client
    except Exception as e:
        raise Exception(f"Could not create a BigQuery client - have you authenticated with gcloud yet? ({e})") from e


def list_table_names(project: str, dataset: str, client: bigquery.Client = None) -> list[str]:
    """Returns every table name in project.dataset. Reuses client if given, else builds one via
    get_client() - reusing a client avoids repeating credential/ADC resolution (often the slow part,
    especially off-GCP where it has to time out probing the metadata server first) on every call."""
    client = client or get_client()
    print(f"[bigquery_schema_export] Calling list_tables({project}.{dataset})...", flush=True)
    table_names = sorted(table.table_id for table in client.list_tables(f"{project}.{dataset}"))
    print(f"[bigquery_schema_export] list_tables({project}.{dataset}) returned {len(table_names)} table(s).", flush=True)
    return table_names


def download_table_schema_json(project: str, dataset: str, table: str, destination_dir: Path) -> Path:
    """Fetches one table's schema and writes it as <table>.json (BigQuery's own to_api_repr() shape) into
    destination_dir. Returns the JSON file's path."""
    client = get_client()
    bq_table = client.get_table(f"{project}.{dataset}.{table}")
    schema = [field.to_api_repr() for field in bq_table.schema]

    destination_dir = Path(destination_dir)
    destination_dir.mkdir(parents=True, exist_ok=True)
    json_path = destination_dir / f"{table}.json"
    with open(json_path, "w") as f:
        json.dump(schema, f, indent=2)
    return json_path


def convert_json_schema_to_yaml(json_path: Path, table_name: str, destination_dir: Path) -> Path:
    """
    Converts a BigQuery schema JSON (as written by download_table_schema_json()) into a
    schema_entity_relationships.yaml-shaped YAML file (<table_name>.yaml) in destination_dir. Returns the
    YAML file's path.
    """
    with open(json_path, "r") as f:
        bq_fields = json.load(f)

    fields = [
        {
            "name": field["name"],
            "datatype": _BIGQUERY_TYPE_MAPPINGS.get(str(field.get("type", "")).upper(), "STRING"),
            "nullable": field.get("mode", "NULLABLE") != "REQUIRED",
        }
        for field in bq_fields
    ]

    document = {
        "tables": {
            table_name: {
                "fields": fields,
                "primary_keys": [],  # not derivable from a BigQuery schema alone - fill in manually
            }
        },
        "relationships": [],
    }

    destination_dir = Path(destination_dir)
    destination_dir.mkdir(parents=True, exist_ok=True)
    yaml_path = destination_dir / f"{table_name}.yaml"
    with open(yaml_path, "w") as f:
        yaml.safe_dump(document, f, sort_keys=False, default_flow_style=False)
    return yaml_path


def download_dataset_schemas(project: str, dataset: str, table: str, destination_dir: Path, on_progress=None) -> list[dict]:
    """
    Downloads schema JSON (+ a converted YAML copy) for table if given, else every table in project.dataset.
    on_progress, if given, is called as on_progress(completed_count, total_count, table_name) after each
    table finishes - e.g. to drive a progress bar (see ui/bigquery_schema_window.py).
    Returns [{"table": name, "json_path": Path, "yaml_path": Path}, ...] for reporting.
    """
    table_names = [table] if table else list_table_names(project, dataset)
    destination_dir = Path(destination_dir)
    total = len(table_names)

    results = []
    for index, table_name in enumerate(table_names, start=1):
        json_path = download_table_schema_json(project, dataset, table_name, destination_dir)
        yaml_path = convert_json_schema_to_yaml(json_path, table_name, destination_dir)
        results.append({"table": table_name, "json_path": json_path, "yaml_path": yaml_path})
        if on_progress:
            on_progress(index, total, table_name)
    return results
