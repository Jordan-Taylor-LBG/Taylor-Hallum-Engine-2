import subprocess
import os
import concurrent.futures


def clear_results_folder(output_folder):
    if not os.path.isdir(output_folder):
        return

    for existing_file in os.listdir(output_folder):
        if existing_file.endswith('.csv'):
            os.remove(os.path.join(output_folder, existing_file))

def _bq_base_command(project_id, location, max_rows):
    return [
        "C:\\Program Files\\GoogleSDK\\google-cloud-sdk\\bin\\bq.cmd",
        "query",
        "--use_legacy_sql=false",
        "--format=csv",
        f"--max_rows={max_rows}",  # large enough to fetch a whole shard in one go
        f"--project_id={project_id}",
        f"--location={location}",
    ]


def run_bigquery_shard(query, output_csv_path, project_id, location, max_rows_per_call=5000, shard_id=None):
    """Download one shard, paging in max_rows_per_call chunks (a hard per-request row cap).

    OFFSET here only ever re-scans within this shard's slice, not the whole
    table, so cost stays bounded by shard size rather than table size.
    """
    label = f"shard {shard_id}" if shard_id is not None else "shard"
    offset = 0
    total_rows = 0
    wrote_header = False

    with open(output_csv_path, 'w', encoding='utf-8', newline='') as output_file:
        while True:
            page_num = offset // max_rows_per_call + 1
            print(f"{label}: requesting page {page_num} (offset={offset})...", flush=True)
            paginated_query = f"{query} LIMIT {max_rows_per_call} OFFSET {offset}"
            result = subprocess.run(
                _bq_base_command(project_id, location, max_rows_per_call),
                input=paginated_query,
                text=True,
                capture_output=True,
                encoding='utf-8',
                errors='replace'
            )

            if result.returncode != 0:
                raise RuntimeError(result.stderr.strip() or "bq query failed with no stderr output")

            lines = result.stdout.splitlines(keepends=True)
            rows_returned = max(0, len(lines) - 1)

            if rows_returned > 0:
                if not wrote_header:
                    output_file.writelines(lines)
                    wrote_header = True
                else:
                    output_file.writelines(lines[1:])
                total_rows += rows_returned

            print(f"{label}: page {page_num} returned {rows_returned} rows (running total={total_rows})", flush=True)

            if rows_returned < max_rows_per_call:
                break
            offset += max_rows_per_call

    return total_rows


def run_bigquery_query(sql_file_path, output_folder, project_id, location, source_table,
                        num_shards=8, max_concurrent_shards=4, max_rows_per_call=5000):
    """Download a table by fanning out num_shards parallel queries.

    Each shard query filters rows with MOD(FARM_FINGERPRINT(...), num_shards) = shard_id
    (see sql_script.sql), so shards are disjoint and exhaustive. Shards run
    concurrently through a thread pool capped at max_concurrent_shards - excess
    shards queue behind it rather than all firing at once - and each shard
    itself pages in max_rows_per_call chunks.
    """
    # Ensure the output folder exists
    os.makedirs(output_folder, exist_ok=True)
    clear_results_folder(output_folder)

    # Read the SQL file content
    with open(sql_file_path, 'r', encoding='utf-8') as file:
        query_template = file.read().strip().rstrip(';')

    print(f"Launching {num_shards} shards ({max_concurrent_shards} running at a time)...", flush=True)

    def run_one(shard_id):
        print(f"shard {shard_id}: starting", flush=True)
        query = query_template.format(source_table=source_table, num_shards=num_shards, shard_id=shard_id)
        output_csv_path = os.path.join(output_folder, f"bigquery_results_shard_{shard_id}.csv")
        rows = run_bigquery_shard(query, output_csv_path, project_id, location, max_rows_per_call, shard_id=shard_id)
        print(f"shard {shard_id}: done, rows={rows}", flush=True)
        return rows

    total_rows_downloaded = 0
    completed_shards = 0
    # ThreadPoolExecutor is the queue: only max_concurrent_shards run at a time,
    # the rest wait until a worker frees up.
    with concurrent.futures.ThreadPoolExecutor(max_workers=max_concurrent_shards) as executor:
        futures = {executor.submit(run_one, shard_id): shard_id for shard_id in range(num_shards)}
        for future in concurrent.futures.as_completed(futures):
            shard_id = futures[future]
            completed_shards += 1
            try:
                total_rows_downloaded += future.result()
            except Exception as exc:
                print(f"shard {shard_id} failed: {exc}", flush=True)
            print(f"progress: {completed_shards}/{num_shards} shards finished", flush=True)

    print(f"Total rows downloaded: {total_rows_downloaded}", flush=True)

def collate_csvs(input_folder, output_csv_path):
    # List all CSV files in the input folder
    csv_files = sorted(
        [os.path.join(input_folder, f) for f in os.listdir(input_folder) if f.endswith('.csv')]
    )

    if not csv_files:
        print(f"No CSV files found in {input_folder}. Skipping collation.")
        return

    # Preserve the downloaded CSV text exactly by concatenating files directly.
    wrote_header = False
    with open(output_csv_path, 'w', encoding='utf-8', newline='') as output_file:
        for csv_file in csv_files:
            if os.path.getsize(csv_file) == 0:
                print(f"Skipping empty CSV: {csv_file}")
                continue

            with open(csv_file, 'r', encoding='utf-8', newline='') as input_file:
                lines = input_file.readlines()

            if not lines:
                print(f"Skipping empty CSV: {csv_file}")
                continue

            if not wrote_header:
                output_file.writelines(lines)
                wrote_header = True
            else:
                output_file.writelines(lines[1:])

    if not wrote_header:
        print(f"No objects to concatenate in {input_folder}. Skipping collation.")
        return

def run_queries_bulk(sql_file_path, output_folder_base, project_id, location, source_table, output_csv_path,
                      num_shards=8, max_concurrent_shards=4):
    output_folder = os.path.join(output_folder_base, 'results')

    run_bigquery_query(sql_file_path, output_folder, project_id, location, source_table,
                        num_shards=num_shards, max_concurrent_shards=max_concurrent_shards)

    # Collate results for each day into a separate CSV file
    collate_csvs(output_folder, output_csv_path)

def run_job_queue(job_list, output_folder_base, project_id, location, default_num_shards=8, default_max_concurrent_shards=4):
    output_folder = os.path.join(output_folder_base, 'results')

    for job in job_list:
        print(str(job))
        source_table = job['source_table']
        output_csv_path = job.get('output_csv_path')
        if not output_csv_path:
            output_csv_path = f"{source_table.split('.')[-1]}.csv"

        run_bigquery_query(
            job['sql_file_path'],
            output_folder,
            project_id,
            location,
            source_table,
            num_shards=job.get('num_shards', default_num_shards),
            max_concurrent_shards=job.get('max_concurrent_shards', default_max_concurrent_shards)
        )
        collate_csvs(output_folder, output_csv_path)
        clear_results_folder(output_folder)

# Enter details
output_folder_base = 'bigquery_results'
project_id = 'dmn01-finsoi-prd-01-8747'
location = 'europe-west2'

## Number of shards = number of parallel bq query processes launched per table.
## Each shard downloads MOD(FARM_FINGERPRINT(row), num_shards) = shard_id rows,
## 5000 at a time, so raise this for bigger tables / more parallelism.
default_num_shards = 256

## Caps how many shard queries run at once (the rest queue behind the thread
## pool); lower this if you hit BigQuery concurrent-query quota limits.
default_max_concurrent_shards = 16

## sql_file_path should be consistent
## change source table to whatever you need to download
## if you only need one download - only have one job. simple
## add 'num_shards': N / 'max_concurrent_shards': N to a job to override the defaults

jobs = [



    {
        'sql_file_path': 'sql_script.sql',
        'source_table': 'ap-btsstg-prd-01-36da.ap_btsstg_prd_01_bqd_euwe2_acbs_view_01.j_cams_view',
    },
    {
        'sql_file_path': 'sql_script.sql',
        'source_table': 'ap-btsstg-prd-01-36da.ap_btsstg_prd_01_bqd_euwe2_acbs_view_01.j_cldt_view',
    },

    {
        'sql_file_path': 'sql_script.sql',
        'source_table': 'ap-btsstg-prd-01-36da.ap_btsstg_prd_01_bqd_euwe2_acbs_view_01.j_clla_view',
    },

   {
        'sql_file_path': 'sql_script.sql',
        'source_table': 'ap-btsstg-prd-01-36da.ap_btsstg_prd_01_bqd_euwe2_acbs_view_01.j_clmi_view',
    },


       {
       'sql_file_path': 'sql_script.sql',
       'source_table': 'ap-btsstg-prd-01-36da.ap_btsstg_prd_01_bqd_euwe2_acbs_view_01.j_clms_view',
   },



        {
        'sql_file_path': 'sql_script.sql',
        'source_table': 'ap-btsstg-prd-01-36da.ap_btsstg_prd_01_bqd_euwe2_acbs_view_01.j_clte_view',
    },


        {
        'sql_file_path': 'sql_script.sql',
        'source_table': 'ap-btsstg-prd-01-36da.ap_btsstg_prd_01_bqd_euwe2_acbs_view_01.j_ctde_view',
    },


            {
        'sql_file_path': 'sql_script.sql',
        'source_table': 'ap-btsstg-prd-01-36da.ap_btsstg_prd_01_bqd_euwe2_acbs_view_01.j_ctun_view',
    },



            {
        'sql_file_path': 'sql_script.sql',
        'source_table': 'ap-btsstg-prd-01-36da.ap_btsstg_prd_01_bqd_euwe2_acbs_view_01.j_cuad_view',
    },


   {
       'sql_file_path': 'sql_script.sql',
      'source_table': 'ap-btsstg-prd-01-36da.ap_btsstg_prd_01_bqd_euwe2_acbs_view_01.j_cums_view',
   },




]

run_job_queue(jobs, output_folder_base, project_id, location,
              default_num_shards=default_num_shards, default_max_concurrent_shards=default_max_concurrent_shards)



#    {
#        'sql_file_path': 'sql_script.sql',
#        'source_table': 'ap-btsstg-prd-01-36da.ap_btsstg_prd_01_bqd_euwe2_acbs_view_01.j_clas_view',
#    },
#    {
#        'sql_file_path': 'sql_script.sql',
##        'source_table': 'ap-btsstg-prd-01-36da.ap_btsstg_prd_01_bqd_euwe2_acbs_view_01.dsclra_view',
 #   },
 #   {
 #       'sql_file_path': 'sql_script.sql',
 #       'source_table': 'ap-btsstg-prd-01-36da.ap_btsstg_prd_01_bqd_euwe2_acbs_view_01.j_cafe_view',
 #   },
 #   {
 #       'sql_file_path': 'sql_script.sql',
 #       'source_table': 'ap-btsstg-prd-01-36da.ap_btsstg_prd_01_bqd_euwe2_acbs_view_01.j_calm_view',
 #   },
 #   {
 #       'sql_file_path': 'sql_script.sql',#
 #       'source_table': 'ap-btsstg-prd-01-36da.ap_btsstg_prd_01_bqd_euwe2_acbs_view_01.j_cami_view',
 #   },