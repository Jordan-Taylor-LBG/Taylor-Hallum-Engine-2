WITH base AS (
    SELECT * FROM `{source_table}`  WHERE bts_batch_dt = CAST('2026-09-10' as DATE)
)
-- Deterministic shard assignment: every row hashes to exactly one shard, so
-- running this once per shard_id (0..num_shards-1) partitions the table with
-- no overlap/gaps and no expensive OFFSET re-scan.
SELECT *
FROM base
WHERE MOD(ABS(FARM_FINGERPRINT(TO_JSON_STRING(base))), {num_shards}) = {shard_id}