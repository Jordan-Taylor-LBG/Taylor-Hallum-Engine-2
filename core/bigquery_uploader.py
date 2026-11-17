"""
Uploads a CSV file's rows into an existing BigQuery table, validating the CSV's columns against the
target table's schema first (failing the job with a clear message rather than partially loading
mismatched data). Used by ui/bigquery_uploader_window.py.

Two insert methods are supported per job:
  - "sql": batched `INSERT INTO ... VALUES (...), (...)` statements - simplest, best for small datasets.
  - "stream": BigQuery's streaming insert API (tabledata.insertAll via insert_rows_json) - handles much
    higher throughput/volume; recommended (not mandatory) once a CSV gets past ~100MB.

get_client() is reused from core.bigquery_spooler - the authentication/client-construction story is
identical between spooling (download) and uploading.
"""

import csv
from pathlib import Path

from google.cloud import bigquery

from core.bigquery_schema_export import list_table_names
from core.bigquery_spooler import get_client

SQL_INSERT_BATCH_SIZE = 500
STREAM_INSERT_BATCH_SIZE = 500

# Past this CSV size, the streaming insert method is recommended (not mandatory) over plain SQL INSERTs.
ADVISORY_STREAM_THRESHOLD_BYTES = 100_000_000

_NUMERIC_FIELD_TYPES = {"INTEGER", "INT64", "FLOAT", "FLOAT64", "NUMERIC", "BIGNUMERIC"}
_BOOLEAN_FIELD_TYPES = {"BOOLEAN", "BOOL"}


def count_csv_rows(csv_path: Path) -> int:
    """Counts data rows (excluding the header) by scanning lines - cheap, local, no BigQuery call."""
    with open(csv_path, "r", encoding="utf-8", newline="") as f:
        return max(0, sum(1 for _ in f) - 1)


def get_table_schema(client: bigquery.Client, table_ref: str) -> list:
    """Returns the target table's list of bigquery.SchemaField."""
    return list(client.get_table(table_ref).schema)


def _read_csv_header(csv_path: Path) -> list:
    with open(csv_path, "r", encoding="utf-8", newline="") as f:
        return next(csv.reader(f))


def compare_csv_to_schema(csv_header: list, schema_fields: list) -> tuple:
    """Checks the CSV's columns against the target table's schema (case-insensitive column names). Fails
    if the CSV references a column that doesn't exist on the table, or if the table has a REQUIRED column
    the CSV doesn't provide - extra/missing NULLABLE columns are fine. Returns (is_ok, message)."""
    schema_names_lower = {field.name.lower() for field in schema_fields}
    csv_names_lower = {name.lower() for name in csv_header}

    unknown_columns = [name for name in csv_header if name.lower() not in schema_names_lower]
    missing_required = [
        field.name for field in schema_fields
        if field.mode == "REQUIRED" and field.name.lower() not in csv_names_lower
    ]

    if unknown_columns or missing_required:
        problems = []
        if unknown_columns:
            problems.append(f"CSV has column(s) not on the target table: {', '.join(unknown_columns)}")
        if missing_required:
            problems.append(f"Target table requires column(s) missing from the CSV: {', '.join(missing_required)}")
        return False, "; ".join(problems)
    return True, "CSV columns match the target table's schema."


def truncate_table(client: bigquery.Client, table_ref: str) -> None:
    """Deletes every existing row in table_ref via a TRUNCATE TABLE DML statement. Irreversible - callers
    must get explicit user confirmation before calling this (see ui/bigquery_uploader_window.py)."""
    client.query(f"TRUNCATE TABLE `{table_ref}`").result()


def resolve_bulk_upload_jobs(project: str, dataset: str, file_paths: list, method: str = "sql", truncate: bool = False, on_progress=None, client: bigquery.Client = None) -> tuple:
    """
    Used by the uploader window's bulk upload configurator wizard: for each file in file_paths, looks for a
    table in project.dataset named exactly after the file's stem (case-insensitive), or <stem>_view if no
    exact match exists. Returns (jobs, unmatched_stems) - jobs is a ready-to-queue job dict (same shape as
    ui/bigquery_uploader_window.py's self.jobs entries) for every file that matched a table; unmatched_stems
    lists the file stems that matched neither name, so the wizard can block bulk-configuring until the user
    fixes them (e.g. picks different files, or creates/renames a table). on_progress, if given, is called
    with {"stage", "message"} as each phase starts - this can be a slow network call (auth + listing every
    table in the dataset), so callers should run it off the UI thread and use on_progress to show the user
    it's still working rather than appearing to hang. client, if given (e.g. a client already constructed
    and cached by the caller), is reused instead of resolving credentials again - usually the slow part.
    """
    if on_progress:
        on_progress({"stage": "listing_tables", "message": f"Listing tables in {project}.{dataset}..."})
    print(f"[bigquery_uploader] resolve_bulk_upload_jobs: about to list tables in {project}.{dataset} for {len(file_paths)} file(s)...", flush=True)
    table_names = list_table_names(project, dataset, client=client)
    print(f"[bigquery_uploader] resolve_bulk_upload_jobs: got {len(table_names)} table(s) back from {project}.{dataset}.", flush=True)

    if on_progress:
        on_progress({"stage": "matching", "message": f"Matching {len(file_paths)} file(s) against {len(table_names)} table(s)..."})
    table_names_lower = {name.lower(): name for name in table_names}

    jobs = []
    unmatched_stems = []
    for file_path in file_paths:
        file_path = Path(file_path)
        stem = file_path.stem
        matched_table = table_names_lower.get(stem.lower()) or table_names_lower.get(f"{stem.lower()}_view")
        if matched_table is None:
            unmatched_stems.append(stem)
            continue
        jobs.append({
            "job_name": stem, "csv_path": str(file_path), "target_table": f"{project}.{dataset}.{matched_table}",
            "method": method, "truncate": truncate, "status": "Pending", "rows": "", "message": "",
        })

    if on_progress:
        on_progress({"stage": "done", "message": f"Matched {len(jobs)}/{len(file_paths)} file(s)."})
    print(f"[bigquery_uploader] resolve_bulk_upload_jobs: matched {len(jobs)}/{len(file_paths)} file(s), unmatched={unmatched_stems}", flush=True)
    return jobs, unmatched_stems


def _sql_literal(value, field_type: str) -> str:
    """Renders one CSV cell as a BigQuery Standard SQL literal. Numeric/boolean columns pass the raw
    value through; everything else is wrapped in triple-quotes (BigQuery's literal syntax that doesn't
    require escaping embedded single/double quotes) to keep arbitrary CSV text safe from SQL injection."""
    if value is None or value == "":
        return "NULL"
    if field_type in _NUMERIC_FIELD_TYPES:
        return value
    if field_type in _BOOLEAN_FIELD_TYPES:
        return "TRUE" if value.strip().lower() in ("true", "1", "yes") else "FALSE"
    escaped = value.replace("\\", "\\\\").replace("'''", "\\'''")
    return f"'''{escaped}'''"


def _coerce_for_streaming(value, field_type: str):
    """Converts one CSV cell to a JSON-friendly Python value matching field_type, for insert_rows_json()."""
    if value is None or value == "":
        return None
    if field_type in _NUMERIC_FIELD_TYPES:
        try:
            return int(value) if field_type in ("INTEGER", "INT64") else float(value)
        except ValueError:
            return value
    if field_type in _BOOLEAN_FIELD_TYPES:
        return value.strip().lower() in ("true", "1", "yes")
    return value


def _flush_sql_batch(client: bigquery.Client, table_ref: str, columns: list, value_tuples: list) -> None:
    column_list = ", ".join(f"`{col}`" for col in columns)
    sql = f"INSERT INTO `{table_ref}` ({column_list}) VALUES {', '.join(value_tuples)}"
    client.query(sql).result()


def _upload_sql_insert(client, csv_path, table_ref, field_types, total_rows, on_progress=None) -> int:
    rows_uploaded = 0
    with open(csv_path, "r", encoding="utf-8", newline="") as f:
        reader = csv.DictReader(f)
        columns = reader.fieldnames
        batch = []
        for row in reader:
            values = [_sql_literal(row.get(col), field_types.get(col.lower(), "STRING")) for col in columns]
            batch.append(f"({', '.join(values)})")
            if len(batch) >= SQL_INSERT_BATCH_SIZE:
                _flush_sql_batch(client, table_ref, columns, batch)
                rows_uploaded += len(batch)
                batch = []
                if on_progress:
                    on_progress({
                        "stage": "uploading", "rows_uploaded": rows_uploaded, "total_rows": total_rows,
                        "message": f"{rows_uploaded}/{total_rows} rows inserted (SQL)...",
                    })
        if batch:
            _flush_sql_batch(client, table_ref, columns, batch)
            rows_uploaded += len(batch)
    return rows_uploaded


def _flush_streaming_batch(client: bigquery.Client, table, rows: list) -> None:
    errors = client.insert_rows_json(table, rows)
    if errors:
        raise Exception(f"Streaming insert reported errors for {len(errors)} row(s): {errors[:3]}")


def _upload_streaming(client, csv_path, table_ref, field_types, total_rows, on_progress=None) -> int:
    table = client.get_table(table_ref)
    rows_uploaded = 0
    with open(csv_path, "r", encoding="utf-8", newline="") as f:
        reader = csv.DictReader(f)
        batch = []
        for row in reader:
            batch.append({col: _coerce_for_streaming(value, field_types.get(col.lower(), "STRING")) for col, value in row.items()})
            if len(batch) >= STREAM_INSERT_BATCH_SIZE:
                _flush_streaming_batch(client, table, batch)
                rows_uploaded += len(batch)
                batch = []
                if on_progress:
                    on_progress({
                        "stage": "uploading", "rows_uploaded": rows_uploaded, "total_rows": total_rows,
                        "message": f"{rows_uploaded}/{total_rows} rows inserted (streaming)...",
                    })
        if batch:
            _flush_streaming_batch(client, table, batch)
            rows_uploaded += len(batch)
    return rows_uploaded


def upload_job(
    client: bigquery.Client,
    csv_path: Path,
    table_ref: str,
    method: str,
    truncate: bool = False,
    on_progress=None,
) -> dict:
    """
    Validates csv_path's header against table_ref's schema, optionally truncates the target table, then
    uploads every row via either "sql" (batched INSERT statements) or "stream" (BigQuery streaming insert
    API). Raises on schema-validation failure or upload failure - callers (see
    ui/bigquery_uploader_window.py's queue runner) catch this per-job so one bad job doesn't abort the
    whole queue. Returns {"rows_uploaded", "method", "table_ref"}.
    """
    csv_path = Path(csv_path)

    if on_progress:
        on_progress({"stage": "validating", "message": "Checking CSV columns against the target table's schema..."})
    schema_fields = get_table_schema(client, table_ref)
    csv_header = _read_csv_header(csv_path)
    is_ok, message = compare_csv_to_schema(csv_header, schema_fields)
    if not is_ok:
        raise Exception(message)

    if truncate:
        if on_progress:
            on_progress({"stage": "truncating", "message": f"Truncating {table_ref}..."})
        truncate_table(client, table_ref)

    total_rows = count_csv_rows(csv_path)
    field_types = {field.name.lower(): field.field_type for field in schema_fields}

    if on_progress:
        on_progress({
            "stage": "uploading", "rows_uploaded": 0, "total_rows": total_rows,
            "message": f"Uploading {total_rows} row(s) via {method}...",
        })

    if method == "stream":
        rows_uploaded = _upload_streaming(client, csv_path, table_ref, field_types, total_rows, on_progress)
    else:
        rows_uploaded = _upload_sql_insert(client, csv_path, table_ref, field_types, total_rows, on_progress)

    if on_progress:
        on_progress({
            "stage": "done", "rows_uploaded": rows_uploaded, "total_rows": total_rows,
            "message": f"Done - {rows_uploaded} row(s) uploaded to {table_ref}.",
        })

    return {"rows_uploaded": rows_uploaded, "method": method, "table_ref": table_ref}
