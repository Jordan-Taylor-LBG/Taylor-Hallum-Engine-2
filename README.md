**Description**

The synthetic data generation engine provides an action-driven framework that deterministically ensures that generated data is referential integral, while enforcing defined table relationship rules. Users can supply table schemas, relationship definitions, generation dependencies, attribute generation functions, and a set of permitted actions. The engine traverses dependency-directed acyclic graphs (DAGs) using a depth-first approach, ensuring that entity selection and creation conform to specified relationship constraints throughout the generation process.

**Software requirements**
- Python

Install dependencies:
```powershell
pip install -r requirements.txt
```

## Directory overview

Legend:
- 🔒 **Core engine** — do not edit; change behaviour via config/pluggable modules instead.
- ⚙️ **Config** — you are expected to edit these to define/configure your dataset.
- 🧩 **Required module** — you are expected to edit these to define/configure your dataset, however you are free to rename these files as long as they are consistent with your config.
- 👤 **Example of optional file** - you are free to delete or modify as you see fit. These are either completely de-coupled scripts (e.g. post-processing) or files referenced by required modules 🧩.
- 📤 **Generated output** — created automatically by `main.py`; don't edit by hand.

| Path | Type | Description |
|---|:---:|---|
| `main.py` | 🔒 | Core `Engine`/`Table` classes that drive data generation. Run this to generate data. |
| `helper_functions.py` | 🔒 | Shared DAG/graph utility functions (topological sort, DAG building/inversion, etc.) used by `main.py`. |
| `config/master_config.yaml` | ⚙️ | Top-level configuration read by `main.py`; selects which schema/actions/attribute-generator/selection-functions config to use, plus run-time parameters. |
| `config/acbsuk/schema_entity_relationships.yaml`, `config/acbsny/schema_entity_relationships.yaml`, `config/mock/schema_entity_relationships.yaml` | ⚙️ | Table schema + relationship DAG definitions for each dataset. |
| `config/acbsuk/actions.yaml`, `config/mock/actions.yaml` | ⚙️ | Action definitions (which tables to create/select together) for each dataset. |
| `selection_functions/selection_function_uniform.py`, `selection_functions/selection_function_least_chosen.py` | 🧩 | Example "which candidate gets picked" logic (`select_action`, `select_entity`), named via `master_config.yaml`'s `selection_functions_module` (e.g. `selection_functions.selection_function_uniform`). Edit, or replace with your own module. Although it must contain 1 function named `select_action` and another named `select_entity`.
| `acbsuk_attr_gen_functions.py` | 🧩 | Example attribute-generation functions library (Faker-based) for the ACBS UK dataset, named via `master_config.yaml`'s `attr_gen_functions_module`. |
| `mock_attr_gen_functions.py` | 🧩 | Alternative/simplified attribute-generation functions library, for mock data. |
| `add_audit_cols.py` | � | Adds audit columns (any field marked `is_audit_column: true` per-table in the dataset's `schema_entity_relationships.yaml`, e.g. `delta_flag`, `bts_ingestion_ts`, `bts_ingest_map`, `bts_batch_dt`, `bts_flag`) to every generated delta/snapshot CSV, writing the result into that checkpoint's `gcp_staging_csv/` subfolder (source files are never modified). Called automatically by the engine after every checkpoint save; can also be run standalone (`python add_audit_cols.py`) to re-stage an existing `generated_data_files/` folder. |
| `ref_data/` | 👤 | Static reference data (e.g. `fx.csv`) available to attribute-generation functions. Add, edit, or remove files here as your generation functions need. |
| `generated_data_files/<simulated_datetime>/deltas/` | 📤 | Output per checkpoint: `csv/{positive,negative}/<table>.csv` and `parquet/{positive,negative}/<table>.parquet`, plus `gcp_staging_csv/{positive,negative}/<table>.csv` (audit columns added, see `add_audit_cols.py`). |
| `generated_data_files/<simulated_datetime>/snapshots/` | 📤 | Output per checkpoint: `csv/<table>.csv` and `parquet/<table>.parquet`, plus `gcp_staging_csv/<table>.csv` (audit columns added). |

## Configuration

### `config/master_config.yaml`

This is the single entry point `main.py` reads at start-up. All file paths are resolved relative to the repo root.

Mandatory keys:
- `schema_entity_relationships_filepath` — path to the table/relationship schema yaml to use, e.g. `config/acbsuk/schema_entity_relationships.yaml`.
- `actions_config` — path to the actions yaml to use, e.g. `config/acbsuk/actions.yaml`.
- `attr_gen_functions_module` — importable Python module name (no `.py` suffix) providing attribute-generation functions, e.g. `acbsuk_attr_gen_functions` or `mock_attr_gen_functions`.
- `selection_functions_module` — importable Python module name (no `.py` suffix, dotted for submodules) providing action/entity selection functions, e.g. `selection_functions.selection_function_uniform` or `selection_functions.selection_function_least_chosen`.

Optional keys (leave as `null` to fall back to the engine's own default):
- `initial_partition_date` — starting partition date/time (`YYYY-MM-DD` or `YYYY-MM-DD HH:MM:SS`). Default: current datetime.
- `seconds_per_time_step` — number of seconds each time step represents. Default: 3600 (1 hour).
- `period_between_snapshots` — number of time steps between full snapshot saves. Default: 24.
- `period_between_deltas` — number of time steps between delta saves. Default: 2.
- `max_time_steps` — total number of time steps to run before stopping. Default: 200.

To switch datasets (e.g. from ACBS UK to the mock dataset), point `schema_entity_relationships_filepath`, `actions_config` and `attr_gen_functions_module` at the corresponding config files/modules for the *same* source system configuration (i.e. the same `config/<dataset>/` subfolder) and re-run `main.py`. These three keys must all belong to the same dataset — e.g. mixing `config/acbsuk/schema_entity_relationships.yaml` with `config/mock/actions.yaml` will raise a `KeyError` at start-up because the actions reference tables that don't exist in that schema.

### Schema & table relationships config (e.g. `config/acbsuk/schema_entity_relationships.yaml`)

Defines, per table under `tables`:
- `fields` — list of `{name, datatype, nullable, default_function, is_audit_column}`. Supported `datatype`s: `INTEGER`, `STRING`, `DATE`, `DATETIME`, `FLOAT`. `default_function` (optional) names a function in the configured `attr_gen_functions_module` used to generate that field's value; fields without one get a random value of the right type.
- `primary_keys` — list of field names making up the table's primary key.
- `independent_qualifiers` (optional) — subset of the primary key that acts as a discriminator/conjugate key (e.g. a facility "type code") when a child needs to select a specific kind of parent entity.

Top-level `relationships` list defines the table-relationship DAG. Each entry has:
- `from` / `to` — child / parent table names.
- `on_field` / `foreign_key_in_to` — child column(s) and the parent column(s) they map to.
- `type` — `many-to-one` or `one-to-one` (do not use `one-to-many`; model it as `many-to-one` from the other side instead).
- `fields_added_to_foreign_key_in_to` (optional) — extra fixed key/value pairs required to disambiguate the parent entity (used together with `independent_qualifiers`).

### Actions config (e.g. `config/acbsuk/actions.yaml`)

Defines named actions, each with a `base_actions` map of `table_name -> {CRUD, hardcoded_values, attr_gen_functions, ...}` (so **a table may only be acted upon once per action**). Note that any `table_name`s in `base_actions`, which have relations to one another, will be created such that one newly created table will reference the other newly created table. At each time step, `main.py` picks an action using the configured select_action function from the currently possible actions, then creates/selects entities for every table involved, respecting the relationship DAG.

Supported `CRUD` values:
- `create` - generates a brand-new entity (as described above).
- `update` - regenerates a subset of an *existing* entity's attributes, named via `attributes_to_update: [attr1, ...]` (required); `hardcoded_values`/`attr_gen_functions` apply the same way as for `create`, but only to attributes in that list. The action isn't possible until a matching entity already exists.
- `read` - asserts "an entity must already exist here", without otherwise touching it. Equivalent to what happens automatically when a table is a dependency of an acted-on table but isn't itself listed under `base_actions` - `read` just lets you require/select from a table explicitly, even when nothing else in the action depends on it as a foreign key parent. The action isn't possible until a matching entity already exists.
- `macro` - hands off entirely to a named function in `attr_gen_functions_module`, given via `macro_function: function_name`. Nothing about a macro's feasibility or effects is enforced by the engine (beyond any `read`/`create`/`update` prerequisites elsewhere in the same action) - it's an escape hatch for scenarios the standard per-attribute generation can't express. The function is called as `function_name(table_name, tables_by_ref, tables_by_value, initial_partition_date, time_step, seconds_per_time_step, attr_values)`, where `tables_by_ref`/`tables_by_value` are `{table_name: DataFrame}` - `tables_by_ref` dataframes are the engine's live, mutable state (edits persist immediately), `tables_by_value` are independent copies safe to inspect without side effects. Also available directly on a running `Engine`: `get_table_dataframe(name)`/`get_all_table_dataframes()` (by-ref) and `get_table_dataframe_copy(name)`/`get_all_table_dataframes_copy()` (by-value).

Any table that is a dependency of an action's tables but not itself listed under `base_actions` is implicitly *selected* (read) from its existing entities, same as an explicit `read`.

### Attribute generation functions module (e.g. `acbsuk_attr_gen_functions.py` / `mock_attr_gen_functions.py`)

A plain Python module (named via `attr_gen_functions_module` in `master_config.yaml`) exposing one function per field-generation strategy referenced by `default_function` in the schema config. Each function is called with `(attr, table_name, entity, dataframe, primary_keys, initial_partition_date, time_step, seconds_per_time_step)` and returns the generated value. Swap this module out (or add new functions to it) to change how field values are generated, without touching `main.py`.

### Selection functions module (e.g. `selection_functions/selection_function_uniform.py`)

A plain Python module (named via `selection_functions_module` in `master_config.yaml`, e.g. `selection_functions.selection_function_uniform`) exposing `select_action(possible_actions)` and `select_entity(possible_entities)`. Two are shipped in the `selection_functions/` package:
- `selection_function_uniform.py` — both functions choose uniformly at random.
- `selection_function_least_chosen.py` — `select_action` tracks how many times each action has been chosen so far this run and always picks from whichever action(s) have been chosen the fewest times (ties broken at random); `select_entity` is still uniform at random.

Swap this module out (or add a new one to the `selection_functions/` package) to change selection strategy (e.g. weighted selection, user input or AI integration) globally, without needing to modify `main.py`.
- `select_action` is used to determine which action is called at each `time_step`
- `select_entity` is used to select entities from tables throughout the DAG traversal process, when executing an action

## User instructions

1. Edit `config/master_config.yaml` to point at the desired schema/actions/attribute-generator config (or add new config files following the same structure and point to those instead).
2. Generate data:
   ```powershell
   python main.py
   ```
   This clears out `generated_data_files/` (every simulated-datetime checkpoint folder), then runs for `max_time_steps` time steps, saving deltas every `period_between_deltas` steps and snapshots every `period_between_snapshots` steps.
3. (Optional) Any post-processing, e.g. adding audit columns to every generated file:
   ```powershell
   python add_audit_cols.py
   ```

## Packaging as a standalone executable

`build_standalone.py` uses [PyInstaller](https://pyinstaller.org/) to compile everything except the
editable/plugin files into a single `.exe`, so you can share the app with colleagues who have neither Python
nor access to this source code.

1. `pip install pyinstaller`
2. `python build_standalone.py`
3. Share the resulting `dist/release/` folder (zip it up). It contains:
   - `TaylorHallumEngine.exe` (+ supporting files) - the compiled app (`core/`, `ui/`, `parsers/` packages) -
     not viewable/editable by colleagues.
   - `config/`, `ref_data/`, `selection_functions/`, `assets/`, `mock_attr_gen_functions.py`,
     `acbsuk_attr_gen_functions.py` - left as plain files/folders next to the exe, so colleagues can still add
     datasets, tweak ref data, or write their own selection/attribute-generation logic without touching the
     compiled app. `generated_data_files/` is created next to the exe the first time it's run.

`add_audit_cols.py` is a fully standalone, decoupled script (not part of the packaged app) - colleagues would
need their own Python environment to run it.
