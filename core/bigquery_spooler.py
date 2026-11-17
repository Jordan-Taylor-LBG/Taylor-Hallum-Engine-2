"""
Downloads the result of an arbitrary user-supplied SQL query from BigQuery as a single CSV, of any size.
Used by ui/bigquery_spooler_window.py.

How it works: the user's query becomes the body of a `base` CTE (`WITH base AS (<user query>) SELECT *
FROM base`), run as a SINGLE query execution. A COUNT(*) canary (which can itself be just as slow as the
real query, since it has to scan the same `base` data) runs concurrently in a background thread rather
than blocking the download - the actual query's result set starts streaming immediately, written to local
part files, rolling a part over to a new file whenever it would exceed the 10MB-per-CSV cap. The progress
bar tracks rows downloaded against the canary's total once it arrives, and simply grows to fit rows
downloaded so far in the meantime - it's never left spinning in an indeterminate state. Once every row has
been written, the parts are collated into a single <run_name>.csv and the part files deleted.

A single linear pass can't skip or duplicate rows, so no sharding/OFFSET/determinism tricks are needed -
and since a BigQuery query job's results are always paged through for free (no permission or extra query
cost needed beyond the one execution), this is also cheaper than fanning out multiple filtered queries.
"""

import csv
import io
import shutil
import threading
from pathlib import Path

from google.cloud import bigquery

# No single downloaded CSV may exceed 10MB; a part file is rolled over to a new one well before that hard
# cap, to leave headroom for the last row written tipping it over.

ROLLOVER_THRESHOLD_BYTES = 9_000_000


def get_client(project: str = None) -> bigquery.Client:
    """Constructs a bigquery.Client() using Application Default Credentials - raises a clear error if
    gcloud auth hasn't been set up yet (see _on_authenticate() in ui/bigquery_spooler_window.py). If
    project is given, queries run/bill against that GCP project rather than whatever ADC defaults to."""
    try:
        return bigquery.Client(project=project) if project else bigquery.Client()
    except Exception as e:
        raise Exception(f"Could not create a BigQuery client - have you authenticated with gcloud yet? ({e})") from e


def _row_to_csv_line(values: list) -> str:
    """Renders one row (or header) as a single properly-escaped CSV line, used both to write output files
    and to measure exact per-row byte size for the 10MB rollover check."""
    buffer = io.StringIO()
    csv.writer(buffer, lineterminator="\r\n").writerow(values)
    return buffer.getvalue()


def _row_values(row: bigquery.table.Row) -> list:
    """Converts a BigQuery Row's values to CSV-safe scalars, stringifying any nested RECORD/REPEATED
    fields rather than crashing on them."""
    return [str(v) if isinstance(v, (dict, list)) else v for v in row.values()]


def _base_cte(user_query: str) -> str:
    return f"WITH base AS (\n{user_query}\n)"


def estimate_total_rows(client: bigquery.Client, user_query: str) -> int:
    """Canary query: a cheap COUNT(*) over the user's query, used purely to give the download progress
    bar a row-count denominator before the real download starts."""
    count_sql = f"{_base_cte(user_query)}\nSELECT COUNT(*) AS row_count FROM base"
    rows = list(client.query(count_sql).result())
    return int(rows[0].row_count) if rows else 0


def collate_parts(parts_dir: Path, result_csv_path: Path) -> None:
    """Concatenates every part CSV (sorted by filename, so part order is deterministic) into one final
    CSV, writing the header once (from the first file) and skipping it for the rest."""
    part_files = sorted(parts_dir.glob("*.csv"))
    wrote_header = False
    with open(result_csv_path, "wb") as out_file:
        for part_file in part_files:
            with open(part_file, "rb") as in_file:
                lines = in_file.readlines()
            if not lines:
                continue
            if not wrote_header:
                out_file.writelines(lines)
                wrote_header = True
            else:
                out_file.writelines(lines[1:])


def download_query_to_csv(
    user_query: str,
    destination_dir: Path,
    run_name: str,
    project: str = None,
    client: bigquery.Client = None,
    on_progress=None,
) -> dict:
    """
    Top-level entry point used by ui/bigquery_spooler_window.py's background thread. Kicks off a COUNT(*)
    canary in the background (purely to give the progress bar a row-count total once it's known) and
    immediately starts streaming the user's query (single execution) into
    destination_dir/<run_name>/parts/part<NNN>.csv part files (rolled over under the 10MB cap), collates
    them into destination_dir/<run_name>/<run_name>.csv, and deletes the parts folder. Returns
    {"result_csv_path", "total_rows", "total_bytes"}. client, if given (e.g. when running a queue of
    several jobs back to back), is reused instead of constructing a new one via project.
    """
    client = client or get_client(project)

    # The canary can take just as long as the real download (same underlying scan), so it runs in the
    # background rather than being waited on - total_rows_expected stays None until it resolves, single
    # writer (this thread) / many readers, so no lock is needed for the plain attribute assignment.
    class _Canary:
        total_rows_expected = None

    canary = _Canary()

    def run_canary():
        try:
            count = estimate_total_rows(client, user_query)
        except Exception:
            return
        canary.total_rows_expected = count
        if on_progress:
            on_progress({"stage": "row_count_known", "total_rows_expected": count, "message": f"Canary query finished - {count} total row(s) expected."})

    threading.Thread(target=run_canary, daemon=True).start()

    run_dir = Path(destination_dir) / run_name
    parts_dir = run_dir / "parts"
    parts_dir.mkdir(parents=True, exist_ok=True)

    if on_progress:
        on_progress({
            "stage": "downloading",
            "rows_downloaded": 0,
            "total_rows_expected": None,
            "message": "Downloading (counting total rows in the background)...",
        })

    sql = f"{_base_cte(user_query)}\nSELECT * FROM base"
    rows_iter = client.query(sql).result()

    part_index = 0
    current_file = None
    current_bytes = 0
    total_rows = 0
    total_bytes = 0

    def open_new_part(header_values):
        nonlocal current_file, current_bytes
        part_path = parts_dir / f"part{part_index:03d}.csv"
        current_file = open(part_path, "w", encoding="utf-8", newline="")
        header_line = _row_to_csv_line(header_values)
        current_file.write(header_line)
        current_bytes = len(header_line.encode("utf-8"))

    try:
        for row in rows_iter:
            if current_file is None:
                open_new_part(list(row.keys()))

            line = _row_to_csv_line(_row_values(row))
            current_file.write(line)
            line_bytes = len(line.encode("utf-8"))
            current_bytes += line_bytes
            total_bytes += line_bytes
            total_rows += 1

            # Throttled - this is a single-threaded linear pass, so we don't want to marshal an
            # on_progress call (and the UI update it triggers) for every single row.
            if on_progress and total_rows % 500 == 0:
                total_rows_expected = canary.total_rows_expected
                suffix = f"/{total_rows_expected}" if total_rows_expected is not None else " (total still counting...)"
                on_progress({
                    "stage": "downloading",
                    "rows_downloaded": total_rows,
                    "total_rows_expected": total_rows_expected,
                    "message": f"{total_rows}{suffix} rows downloaded ({total_bytes / 1_000_000:.2f} MB so far)...",
                })

            if current_bytes >= ROLLOVER_THRESHOLD_BYTES:
                current_file.close()
                current_file = None
                part_index += 1
    finally:
        if current_file is not None:
            current_file.close()

    if on_progress:
        on_progress({
            "stage": "collating",
            "rows_downloaded": total_rows,
            "total_rows_expected": canary.total_rows_expected,
            "message": "Combining downloaded parts into a single CSV...",
        })
    result_csv_path = run_dir / f"{run_name}.csv"
    collate_parts(parts_dir, result_csv_path)
    shutil.rmtree(parts_dir)

    final_bytes = result_csv_path.stat().st_size if result_csv_path.exists() else 0
    if on_progress:
        on_progress({
            "stage": "done",
            "rows_downloaded": total_rows,
            "total_rows_expected": canary.total_rows_expected,
            "message": f"Done - {total_rows} rows, {final_bytes / 1_000_000:.2f} MB, saved to {result_csv_path}",
        })

    return {
        "result_csv_path": result_csv_path,
        "total_rows": total_rows,
        "total_bytes": final_bytes,
    }
