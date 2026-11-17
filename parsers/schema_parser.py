"""
Parses/writes config/<dataset>/schema_entity_relationships.yaml files (see config/acbsuk/schema_entity_relationships.yaml
for the expected format) into a plain-data structure for display/editing by schema_viewer.py.
"""

from pathlib import Path

import yaml

NEW_SCHEMA_TEMPLATE = """\
tables:

  example_table:
    fields:
      - name: id
        datatype: STRING
        nullable: false
      - name: some_other_field
        datatype: STRING
        nullable: true
    primary_keys: [id]

relationships: []
"""


def load_schema(path: Path) -> dict:
    """
    Reads a schema_entity_relationships.yaml file into a normalised structure.

    Returns: {
        "tables": {
            table_name: {
                "primary_keys": [str, ...],
                "depends_on": [str, ...],           # normalised to a list, even if the yaml had null/a string
                "independent_qualifiers": [str, ...] or None,
                "fields": [dict, ...],               # raw field dicts, unmodified
            },
            ...
        },
        "relationships": [
            {"from": str, "to": str, "on_field": [...], "foreign_key_in_to": [...], "type": str, ...},
            ...
        ],
    }
    """
    with open(path, "r") as f:
        raw = yaml.safe_load(f) or {}

    tables = {}
    for table_name, table_config in (raw.get("tables") or {}).items():
        table_config = table_config or {}
        depends_on = table_config.get("depends_on")
        if depends_on is None:
            depends_on = []
        elif isinstance(depends_on, str):
            depends_on = [depends_on]

        tables[table_name] = {
            "primary_keys": table_config.get("primary_keys") or [],
            "depends_on": depends_on,
            "independent_qualifiers": table_config.get("independent_qualifiers"),
            "fields": table_config.get("fields") or [],
        }

    return {"tables": tables, "relationships": raw.get("relationships") or []}


def load_schema_raw_text(path: Path) -> str:
    with open(path, "r") as f:
        return f.read()


def save_schema_raw_text(path: Path, text: str) -> None:
    """Validates text as YAML before writing it to path - raises if it doesn't parse."""
    yaml.safe_load(text)
    with open(path, "w") as f:
        f.write(text)


def new_schema_template_text() -> str:
    return NEW_SCHEMA_TEMPLATE
