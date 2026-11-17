
import os

def _split_first_line_binary(data: bytes):
    """
    Split binary data into (first_line, remainder) handling CRLF or LF.
    Returns (first_line_bytes, remainder_bytes). If no newline is found,
    the first_line is the entire data and remainder is empty.
    """
    if not data:
        return b"", b""

    lf_idx = data.find(b'\n')
    if lf_idx == -1:
        # No newline at all
        return data, b""

    # Handle CRLF if the byte before LF is CR
    if lf_idx > 0 and data[lf_idx - 1] == 0x0D:  # '\r'
        first_line = data[:lf_idx + 1]  # include CRLF
        remainder = data[lf_idx + 1:]
    else:
        first_line = data[:lf_idx + 1]  # include LF
        remainder = data[lf_idx + 1:]

    return first_line, remainder


def collate_csvs(input_folder: str, output_csv_path: str) -> None:
    """
    Concatenate all CSV files in `input_folder` into a single CSV at `output_csv_path`,
    treating each record as a single entity and avoiding text decoding entirely.

    - First file: written as-is (including header).
    - Subsequent files: header line is detected and skipped; remainder is written as-is.
    - Works in binary mode to avoid UnicodeDecodeError and preserve original bytes.
    """
    # Validate output path looks like a file (not a directory)
    output_csv_path = os.path.normpath(output_csv_path)
    if output_csv_path.endswith(os.sep):
        raise ValueError(
            f"Output path '{output_csv_path}' looks like a directory. "
            "Provide a filename like 'results.csv'."
        )

    # Validate input folder
    if not os.path.isdir(input_folder):
        print(f"Input folder '{input_folder}' does not exist or is not a directory.")
        return

    # Find CSV files
    csv_files = [
        os.path.join(input_folder, f)
        for f in os.listdir(input_folder)
        if f.lower().endswith(".csv") and os.path.isfile(os.path.join(input_folder, f))
    ]
    if not csv_files:
        print(f"No CSV files found in {input_folder}. Skipping collation.")
        return

    # Deterministic order
    csv_files.sort()

    # Ensure output directory exists
    out_dir = os.path.dirname(os.path.abspath(output_csv_path))
    if out_dir and not os.path.exists(out_dir):
        os.makedirs(out_dir, exist_ok=True)

    total_bytes_written = 0
    files_processed = 0

    try:
        with open(output_csv_path, "wb") as out_f:
            for idx, csv_path in enumerate(csv_files, start=1):
                try:
                    with open(csv_path, "rb") as in_f:
                        data = in_f.read()
                except OSError as e:
                    print(f"Error: Unable to read '{csv_path}': {e}. Skipping.")
                    continue

                if not data:
                    print(f"Warning: {os.path.basename(csv_path)} is empty. Skipping.")
                    continue

                if files_processed == 0:
                    # First file: write as-is
                    out_f.write(data)
                    total_bytes_written += len(data)
                    files_processed += 1
                    print(f"[{idx}/{len(csv_files)}] {os.path.basename(csv_path)}: wrote {len(data)} bytes (first file, including header).")
                else:
                    # Subsequent files: skip the first line (header) and write the rest
                    _, remainder = _split_first_line_binary(data)
                    if not remainder:
                        # File contains only a header line
                        print(f"[{idx}/{len(csv_files)}] {os.path.basename(csv_path)}: only header detected, no data rows to append.")
                    else:
                        out_f.write(remainder)
                        total_bytes_written += len(remainder)
                        files_processed += 1
                        print(f"[{idx}/{len(csv_files)}] {os.path.basename(csv_path)}: appended {len(remainder)} bytes (header skipped).")

        if total_bytes_written > 0:
            print(f"Collation complete: wrote {total_bytes_written} bytes to '{output_csv_path}'.")
        else:
            print("No data written (all files empty or unreadable).")

    except OSError as e:
        print(f"File I/O error while writing to '{output_csv_path}': {e}")


# ----------------------------
# Final call / Invocation
# ----------------------------
if __name__ == "__main__":
    sql_file_path = 'sql_script.sql'  # (unused here, kept for context)
    output_folder_base = 'bigquery_results'
    project_id = 'dmn01-finsoi-prd-01-8747'
    location = 'europe-west2'

    # Input folder containing CSVs
    output_folder = os.path.join(output_folder_base, 'results')

    # Output file (ensure it's a file path, not a folder)
    collated_folder = os.path.join(output_folder_base, 'collated')
    os.makedirs(collated_folder, exist_ok=True)
    output_csv_path = os.path.join(collated_folder, 'results.csv')

    # Final call
    collate_csvs(output_folder, output_csv_path)

