"""
Parses/writes config/<dataset>/actions.yaml files (top-level: action_name -> {base_actions: {table_name:
{CRUD, hardcoded_values, attr_gen_functions, attributes_to_update, macro_function}, ...}, entity_selection_functions: ...}).
CRUD is one of create/update/read/macro - see README.md for details. Used by actions_viewer.py.
"""

from pathlib import Path

import yaml

NEW_ACTIONS_TEMPLATE = """\
create_example_table_record:
  base_actions:
    example_table:
      CRUD: create
      hardcoded_values: null # map attribute to value (takes priority over function if any function enetered for same attribute) if null default functions are used
      attr_gen_functions: null # map attribute to function if null default functions are used
  entity_selection_functions: null # map table to function, if null picks entity uniformly at random
"""


def load_actions(path: Path) -> dict:
    with open(path, "r") as f:
        return yaml.safe_load(f) or {}


def load_actions_raw_text(path: Path) -> str:
    with open(path, "r") as f:
        return f.read()


def save_actions_raw_text(path: Path, text: str) -> None:
    """Validates text as YAML before writing it to path - raises if it doesn't parse."""
    yaml.safe_load(text)
    with open(path, "w") as f:
        f.write(text)


def new_actions_template_text() -> str:
    return NEW_ACTIONS_TEMPLATE
