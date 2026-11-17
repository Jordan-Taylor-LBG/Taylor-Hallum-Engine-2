import importlib
import pandas as pd
import pyarrow as pa
import pyarrow.parquet as pq
import yaml
from datetime import datetime, time, timedelta
from pathlib import Path
import shutil
from core.helper_functions import build_dag, invert_dag, invert_dict, is_dag, topological_sort, get_roots_of_dag, get_leaves_of_dag, get_sub_graph, get_subset_key_value_pairs, generate_random_value_of_given_type
from app_paths import get_base_path

BASE_PATH = get_base_path()

DATATYPE_MAPPINGS = {
    "INTEGER": pa.int64(),
    "STRING": pa.string(),
    "DATE": pa.date32(),
    "DATETIME": pa.timestamp("ms"),
    "BOOLEAN": pa.bool_(),
    "TIMESTAMP": pa.timestamp("ms")
}

KNOWN_CRUD_TYPES = {'create', 'update', 'read', 'macro'}


def _normalize_crud_types(crud_value) -> set:
    """Normalises a base_action's CRUD field - a single string (e.g. 'create') or a list of strings (e.g.
    ['read', 'macro']) - into a lowercase set, so callers can just check membership either way."""
    if isinstance(crud_value, (list, tuple, set)):
        return {str(c).strip().lower() for c in crud_value}
    return {str(crud_value).strip().lower()}


def _validate_crud_types(crud_types: set, table_name: str, action_name: str) -> None:
    unknown = crud_types - KNOWN_CRUD_TYPES
    if unknown:
        raise Exception(f"Unknown CRUD type(s) {sorted(unknown)} for table {table_name} in action {action_name}. Please amend in config.")
    if 'create' in crud_types and 'macro' in crud_types:
        raise Exception(f"Invalid CRUD combination {sorted(crud_types)} for table {table_name} in action {action_name}: 'create' cannot be combined with 'macro'. Please amend in config.")

class Engine():
    def __init__(self, config_schema_entity_relationships_filepath: str, config_actions_filepath: str, attr_gen_functions, selection_functions, daily_windows: list[tuple[datetime, datetime]], seconds_per_time_step: int = 60*60, checkpoint_times: list[time] = None):
        if seconds_per_time_step <= 0:
            raise Exception(f"seconds_per_time_step must be positive, got {seconds_per_time_step}.")
        if not daily_windows:
            raise Exception("daily_windows must contain at least one (start, end) window.")

        self.time_steps = 0
        # Chronological list of (window_start, window_end) datetime pairs the simulation runs within; simulated
        # time jumps straight from one window's end to the next window's start, skipping the gap between them.
        self.daily_windows = sorted(daily_windows, key=lambda window: window[0])
        self.current_window_index = 0
        self.current_simulated_datetime = self.daily_windows[0][0]
        # Kept as a fixed anchor (the very first window's start) for attribute-generation functions that need a
        # stable "run start" reference date, independent of how far the simulated clock has since progressed.
        self.initial_partition_date = self.daily_windows[0][0]
        self.end_partition_date = self.daily_windows[-1][1]
        self.seconds_per_time_step = seconds_per_time_step
        # Times of day (applied to every day of daily_windows) at which both deltas and a full snapshot are
        # exported, e.g. [time(0, 0), time(12, 0)] = once at midnight and once at noon each day.
        self.checkpoint_times = sorted(set(checkpoint_times)) if checkpoint_times else [time(0, 0)]
        # Flattened, sorted list of concrete checkpoint datetimes (one per checkpoint_time x day), and a pointer
        # to the next one still to be crossed - saves are triggered the first time simulated time passes one.
        self._checkpoint_datetimes = sorted(
            datetime.combine(window_start.date(), checkpoint_time)
            for window_start, _ in self.daily_windows
            for checkpoint_time in self.checkpoint_times
        )
        self._next_checkpoint_index = 0
        # Step-through state (see run_step_display/run_step_select/run_step_orchestrate): the possible actions
        # most recently computed, and the action most recently selected, awaiting orchestration.
        self._step_possible_actions = None
        self._step_selected_action = None
        # Modules providing attribute-generation functions (e.g. acbsuk_attr_gen_functions) and action/entity
        # selection functions (e.g. selection_functions), supplied by the caller (see main.py).
        self.attr_gen_functions = attr_gen_functions
        self.selection_functions = selection_functions
        self.tables = {}

        with open(config_schema_entity_relationships_filepath, "r") as f:
            config_schema_entity_relationships = yaml.safe_load(f) or {}

        # Kept so a checkpoint save can re-read the raw schema later (e.g. for is_audit_column fields - see
        # __save_checkpoint__()) without relying on self.tables, whose own field lists have audit columns
        # filtered out (see Table.__init__).
        self.schema_entity_relationships_filepath = config_schema_entity_relationships_filepath
        # Generated output (deltas/snapshots/gcp_staging_csv) is written under its own
        # generated_data_files/<dataset_name>/ subfolder, keyed off the schema file's parent folder name
        # (e.g. config/acbsuk/schema_entity_relationships.yaml -> "acbsuk") - so multiple datasets' output
        # never mixes, and "wipe output" can be scoped to just the currently selected dataset.
        self.dataset_name = Path(config_schema_entity_relationships_filepath).parent.name

        # Store full table relationship details (includes foreign keys etc.)
        self.table_relationship_details = config_schema_entity_relationships['relationships']

        # Build DAG

        # table_1 -> table_2 => table_1 depends on table_2
        self.inverse_table_relationship_dag = build_dag(config_schema_entity_relationships['tables'])
        
        # Check if it's a DAG (no cycles)
        if not is_dag(self.inverse_table_relationship_dag):
            raise Exception("Config file does not define table relationship DAG, cycles were found.")
        
        # table_1 -> table_2 => table_2 depends on table_1
        self.table_relationship_dag = invert_dag(self.inverse_table_relationship_dag)

        # CURRENTLY NOT USED
        # Get list of all tables in order of dependenices, x preceeds y => y depends on x (tables not in DAG are added after as they have no dependencies)
        table_list = config_schema_entity_relationships['tables'].keys()
        table_relationship_dag_dfs_list = topological_sort(self.table_relationship_dag)
        self.table_relationship_dag_dfs_list = table_relationship_dag_dfs_list + list(set(table_list).difference(set(table_relationship_dag_dfs_list)))

        # Create table objects
        tables = config_schema_entity_relationships['tables']
        for table_name in tables.keys():
            print(f"Creating table object: {table_name}")
            self.tables[table_name] = Table(table_name, tables[table_name], attr_gen_functions=self.attr_gen_functions, selection_functions=self.selection_functions)

        # Create all actions
        with open(config_actions_filepath, "r") as f:
            actions = yaml.safe_load(f) or {}

        # Add action_leaf_tables and action_table_relationship_dag to each action
        for action_name in actions:
            action_tables = [action_table for action_table in actions[action_name]['base_actions']]
            actions[action_name]['action_table_relationship_dag'] = get_sub_graph(self.table_relationship_dag, action_tables)
            actions[action_name]['action_leaf_tables'] = get_leaves_of_dag(actions[action_name]['action_table_relationship_dag'])
            actions[action_name]['action_root_tables'] = get_roots_of_dag(actions[action_name]['action_table_relationship_dag'])
        self.actions = actions


    @staticmethod
    def clear_deltas_and_snapshots(dataset_name: str, base_dir: str = BASE_PATH/"generated_data_files") -> None:
        """
        Deletes every simulated-datetime folder under generated_data_files/<dataset_name>/ (each holding
        that checkpoint's deltas/ and snapshots/ - see Table.save_deltas()/save_snapshot_csv()/
        save_snapshot_parquet()), preserving generated_data_files/<dataset_name>/ itself - only this
        dataset's output is affected, other datasets' subfolders under generated_data_files/ are untouched.
        Static so callers (e.g. the GUI) can wipe output without having to construct an Engine first.
        """
        dataset_dir = Path(base_dir) / dataset_name
        if not dataset_dir.exists():
            return

        for item in dataset_dir.iterdir():
            if item.is_dir():
                shutil.rmtree(item)
            else:
                item.unlink()

    # Function to get list of all actions that are currently possible to carry out
    def __get_possible_actions__(self) -> list:
        """
        Returns:
            - possible_action_names (list): names of all actions that are currently possible to carry out.
        """
        action_names = list(self.actions.keys())
        possible_action_names = []

        # Filter actions to only those where all tables to be created are s.t. all parents are either created in action or not empty (as otherwise we cannot select from their parents - still need to select for update & delete). Empty & cardinality checks are adapted slightly for independent qualifer cases (e.g. needs entity for specific independent qualifer value).
        for action_name in action_names:
            action_possible = True
            for table_name in self.actions[action_name]['base_actions']:
                crud_types = _normalize_crud_types(self.actions[action_name]['base_actions'][table_name]['CRUD'])
                _validate_crud_types(crud_types, table_name, action_name)
                table_to_be_created = 'create' in crud_types

                # An update acts on an existing entity, so the action isn't possible until one exists to update.
                # A read simply asserts "an entity must already exist here" (e.g. for standalone reference
                # tables not otherwise depended on within this action) - same existence requirement as update.
                # Both also require every table this one transitively depends_on (per schema, not just this
                # action) to already have an entity too - e.g. requiring a balance to exist also requires its
                # account to exist, without needing account to be separately listed in this action.
                if ('update' in crud_types or 'read' in crud_types) and not self.__is_table_and_ancestors_populated__(table_name):
                    action_possible = False

                # A macro hands off to a named attr_gen_functions_module function with unrestricted, by-reference
                # access to every table's dataframe - intentionally unconstrained, no possibility checks here.
                # (combine with 'read' on the same table if that table's existence should still be required)

                if table_to_be_created:
                    for parent_table_name in self.inverse_table_relationship_dag[table_name]:
                        parent_to_be_created = False

                        if parent_table_name in self.actions[action_name]['base_actions']:
                            if 'create' in _normalize_crud_types(self.actions[action_name]['base_actions'][parent_table_name]['CRUD']):
                                parent_to_be_created = True

                        ind_quals_vals=self.get_all_possible_added_key_values_from_child(child_name=table_name,
                                                                                        parent_name=parent_table_name)
                        
                        if (not parent_to_be_created) and not self.tables[parent_table_name].is_able_to_select_from(ind_quals_vals): 
                            action_possible = False

                        # special case for one-to-one relationships (where child is being created but not parent), need cardinality checks. 
                        if not parent_to_be_created:
                            # Returns true if not one-to-one (statement is vacuously False)
                            if not self.is_possible_to_create_child_in_one_to_one_realtionship(child_name=table_name, parent_name=parent_table_name):
                                action_possible = False

            if action_possible:
                possible_action_names.append(action_name)

        return possible_action_names

    # Returns True if table_name has an entity, and so does every table it (transitively) depends_on per the
    # schema's relationship DAG - used to gate CRUD=update/read, since selecting one only actually works if
    # its whole ancestor chain is populated too (e.g. a balance can't be meaningfully read/updated if the
    # account it references doesn't exist, even though only "balance" is listed in this particular action).
    def __is_table_and_ancestors_populated__(self, table_name: str, visited: set = None) -> bool:
        if visited is None:
            visited = set()
        if table_name in visited:
            return True
        visited.add(table_name)

        if self.tables[table_name].is_empty():
            return False

        return all(self.__is_table_and_ancestors_populated__(parent, visited) for parent in self.inverse_table_relationship_dag[table_name])

    # Function to select which action is called
    def __select_action__(self):
        possible_action_names = self.__get_possible_actions__()

        print("\n------------------------------------------------------")
        print(f"possible actions: {possible_action_names} ")

        if possible_action_names == []:
            raise Exception('No possible actions can be executed - ammend actions so that there exist actions that act on the root notes of the table relaionship DAG (initially no outstanding dependencies)')

        selected_action = self.selection_functions.select_action(possible_action_names)
        print("selected_action:", selected_action)
        return selected_action

    # Function to get all the added key values that a child could pass to parent (used to determine possible parents that have the independent qualifier pattern)
    def get_all_possible_added_key_values_from_child(self, child_name: str, parent_name):
        """
        Returns: list[dict] or None. Note: size of this list is the number of different possible independent qualifier combinations.
        """
        possible_added_key_values = [] # list of dictionaries

        for relationship in self.table_relationship_details:
            if relationship['from'] == child_name and relationship['to'] == parent_name:

                added_key_values = relationship.get('fields_added_to_foreign_key_in_to')
                if added_key_values != None:
                    possible_added_key_values.append(added_key_values)

        if possible_added_key_values == []:
            possible_added_key_values = None
        return possible_added_key_values

    # Function that returns True if all one-to-one relationships between child and parent are s.t. |child table| < |{entity in parent table : entity has correct independent qualifer for child, if applicable}|
    def is_possible_to_create_child_in_one_to_one_realtionship(self, child_name: str, parent_name: str):
        is_possible = True
        for relationship in self.table_relationship_details:
            if relationship['from'] == child_name and relationship['to'] == parent_name and relationship['type'].lower() == 'one-to-one':
                added_key_value_pairs_from_child = relationship.get('fields_added_to_foreign_key_in_to')
                if added_key_value_pairs_from_child == None:
                    added_key_value_pairs_from_child ={}
                is_possible = (self.tables[child_name].get_entity_count_satisfying_key_value_pairs() < self.tables[parent_name].get_entity_count_satisfying_key_value_pairs(added_key_value_pairs_from_child))
        return is_possible

    # Function to iteratively call backwards traversal through table relationship DAG to carry out action, on each leaf_table_node in action DAG. Ensures already selected entities are consistent throguhout iterations.
    def __orchestrate_action__(self, action_name: str):
        """
        Parameters:
            - action_name (str): key for self.actions
        """
        # Create mapping of table to selected entity if already visited (gets updated recursively)
        entities_already_selected = tuple()

        # Traverse back to root for each leaf node in subgraph of tables to be acted on, note: don't need to store entity selected for leaf nodes as they have no dependencies
        for table_leaf_node in self.actions[action_name]['action_leaf_tables']:
            leaf_table_primary_keys = tuple(self.tables[table_leaf_node].primary_keys)
            _, entities_already_selected = self.__recursively_crud_entity__(
                table_name=table_leaf_node,
                action_name=action_name,
                entities_already_selected=entities_already_selected,
                required_fields=leaf_table_primary_keys,
                selecting_first_table_from_table=True,
            )
        print("\nrecords already selected after whole action:")
        for table, entity in entities_already_selected:
            print("\n",table)
            print("\n",entity)

        # Post-actions: plain macro functions (named in actions.yaml's post_actions list, alongside the
        # list of tables each one touches - see get_action_post_action_tables()) run once, after every
        # base_action above has been fully orchestrated - a deliberate escape hatch from the
        # table-dependency DAG for cross-table logic that shouldn't need a depends_on/relationships edge
        # (and the ordering/FK-mapping machinery that comes with one) just to guarantee it runs last. Like
        # any other macro, they get unrestricted by-reference access to every table's dataframe, plus
        # entities_already_selected so they can see exactly what this action just created/selected without
        # having to re-derive it.
        for post_action in self.actions[action_name].get('post_actions') or []:
            post_action_function = getattr(self.attr_gen_functions, post_action['function'])
            post_action_function(
                action_name=action_name,
                entities_already_selected=entities_already_selected,
                tables_by_ref=self.get_all_table_dataframes(),
                tables_by_value=self.get_all_table_dataframes_copy(),
                initial_partition_date=self.initial_partition_date,
                time_step=self.time_steps,
                seconds_per_time_step=self.seconds_per_time_step,
            )


    # Function to recursively select (read) or act on entity
    def __recursively_crud_entity__(self, table_name: str, action_name: str, entities_already_selected: tuple, required_fields: tuple, selecting_first_table_from_table: bool, attr_values_from_child: tuple = (), candidate_primary_key_values = True, ineligible_primary_key_values: tuple = tuple()):
        """
        Parameters:
            - table_name (str): name of table to carry out crud operation on
            - action_name (str): key for self.actions
            - entities_already_selected (tuple): maps table name to entity already selected (whole entity)
            - required_fields (tuple): tuple of fields to return values for
            - candidate_primary_key_values (tuple(tuple(tuple)) or True): tuple of eligible combinations of (key, value) pairs (of tables primary_keys) for rud operation, e.g. ((('pk', '1'),), (('pk', '2'),)), default = True (represents ALL are eligible)
                Note: only keys from required_fields, we do need to add independent qualifer as filtering on just required fields is insufficient for ELIGIBLE list. 
            - ineligible_primary_key_values (tuple(tuple(tuple))): tuple of ineligible combinations of (key, value) pairs (of tables primary_keys) for rud operation, default = tuple() (represents NONE are ineligible).
                Note: used to exclude from candidate_primary_key_values at beginning of function.
            - selecting_first_table_from_table (bool): Flag for if doing CRUD operation for the first time, if this is flipped to false: this flag will be false for all tables further down the same path.
        Returns:
            - required_values (tuple): maps required field to value
            - entities_already_selected (tuple of tuples): maps table to selected entity
        """
        # DEBUGGING
        print("\nFunction call:")
        print(f"table_name: {table_name}")
        #print(f"entities_already_selected: {entities_already_selected}")
        print(f"required_fields: {required_fields}")
        print(f"candidate_primary_key_values_primary_key_values: {candidate_primary_key_values}")
        print(f"attr_values_from_child: {attr_values_from_child}")
        print(f"ineligible_primary_key_values: {ineligible_primary_key_values}")
        print(f"selecting_first_table_from_table: {selecting_first_table_from_table}\n")

        # Step 1: Check if entity has already been selected for current table (only if selecting_first_table_from_table)

        if selecting_first_table_from_table: 
            visit_count_current_table = 0
            selected_entity = None
            for pair in  entities_already_selected:
                table_name_already_selected, entity = pair
                if table_name_already_selected == table_name:
                    if attr_values_from_child == tuple():
                        # no independent qualifer case, just select entity already found
                        selected_entity = entity
                        visit_count_current_table += 1
                    elif attr_values_from_child in entity:
                        # independent qualifer case, needs to check that entity matches independent qualifer (attributes from child) as well
                        selected_entity = entity
                        visit_count_current_table += 1
            
            if visit_count_current_table == 1:
                print("returning already selected entity:", selected_entity)
                return get_subset_key_value_pairs(selected_entity, required_fields), entities_already_selected
            elif visit_count_current_table >= 2:
                raise Exception(f"Multiple entities already selected from {table_name}, no way of selecting correct entity for children. To resolve, either remove transitive dependency from table relationship DAG (if one exists) or break {action_name} up into smaller actions to be called separately.")

        attr_values_from_all_dependencies = tuple()
        primary_keys = self.tables[table_name].primary_keys

        # Get eligible_primary_key_values given candidate_primary_key_values (tuple or True - if True start with exhaustive list of pks), ineligible_primary_key_values and attr_values_from_child
        # Needed for selection even if root table
        # Note: eligible_primary_key_values (when not True) is shaped over required_fields, which may only be a SUBSET of this table's full
        # primary_keys (e.g. conjugate/independent_qualifier keys where only part of the compound key participates in the foreign key mapping) - so we
        # always re-derive a full primary_keys-shaped eligible_primary_key_values from this table's own dataframe, honouring both the
        # required_fields constraint (if any) and any fixed attr_values_from_child (e.g. a independent_qualifier value).
        if candidate_primary_key_values == True:
            eligible_primary_key_values = self.tables[table_name].get_eligible_primary_key_values(primary_keys, ineligible_primary_key_values=ineligible_primary_key_values, candidate_key_values_from_childs_fk=candidate_primary_key_values, fixed_attr_values=attr_values_from_child)
        else:
            eligible_primary_key_values = self.tables[table_name].get_eligible_primary_key_values(primary_keys,ineligible_primary_key_values=ineligible_primary_key_values, candidate_key_values_from_childs_fk=candidate_primary_key_values, fixed_attr_values=attr_values_from_child)

        # Check if not root node in table relationship DAG (<=> not leaf in inverse DAG)
        if self.inverse_table_relationship_dag[table_name] != []:
            # Recursive step
            # Step 2: Get dependency details from parents
            dependency_details = self.__get_dependency_details__(table_name)

            # Step 3: Check if we need to C or RUD (this includes R - table not to be acted on) on table (need to differentiate between finding eligibile_primary_key_values and ineligible_primary_key_values)
            table_to_be_created = False
            if table_name in self.actions[action_name]['action_table_relationship_dag'].keys():
                # table to be acted on
                if 'create' in _normalize_crud_types(self.actions[action_name]['base_actions'][table_name]['CRUD']):
                    table_to_be_created = True
            print(f"{table_name} TABLE TO BE CREATED: {table_to_be_created}")

            
            # Step 4: Go through each dependency, working out eligible and ineligible keys, and calling recursively_crud_entity

            tables_visited = []
            for dependency in dependency_details:
                parent_table_name = dependency['parent_table_name']
                dependency_type = dependency['type']
                dependency_foreign_key_maps_into = dependency['key_mappings'] # e.g. {attr1_in_dependent: attr1_in_parent, attr2_in_dependent, attr2_in_parent, ...}
                dependency_foreign_key_maps_from = invert_dict(dependency_foreign_key_maps_into) # e.g. {attr1_in_parent: attr1_in_dependent, attr2_in_parent, attr2_in_dependent, ...}


                # Set selecting_first_table_from_parent_table
                if parent_table_name in tables_visited or not selecting_first_table_from_table:
                    selecting_first_table_from_parent_table = False
                else:
                    selecting_first_table_from_parent_table = True

                # Add parent table name to tables_visited (after check if already visited)
                tables_visited.append(parent_table_name)

                # Add attr_values to pass to parent
                attr_values_to_give_parent = tuple(dependency.get('fields_added_to_foreign_key_in_to').items())


                if not table_to_be_created:
                    # RUD case: need to keep track of eligible primary key values and eligible foreign key values, in order to ensuure we select parent entites taht have children in common
                    eligible_foreign_key_values = self.tables[table_name].get_foreign_key_values_that_match_eligible_primary_key_values(eligible_primary_key_values, tuple(dependency_foreign_key_maps_into.keys()))

                    # Remap keys from current table's foreign key column names to parent's matching primary key column names, since the parent's get_eligible_primary_key_values filters its own dataframe using these as column names.
                    eligible_foreign_key_values = tuple(
                        tuple((dependency_foreign_key_maps_into[key], value) for key, value in combo)
                        for combo in eligible_foreign_key_values
                    )

                    attr_values_from_dependency, entities_already_selected = self.__recursively_crud_entity__(
                        table_name=parent_table_name,
                        action_name=action_name,
                        entities_already_selected=entities_already_selected,
                        required_fields=tuple(dependency_foreign_key_maps_into.values()),
                        selecting_first_table_from_table=selecting_first_table_from_parent_table,
                        attr_values_from_child=attr_values_to_give_parent,
                        candidate_primary_key_values=eligible_foreign_key_values,
                    ) # ineligible_primary_key_values not parameterised (default = tuple())

                    # Map attr_values_from_dependency keys from primary keys of parent to foreign keys of current table, before using them to filter current table's dataframe
                    attr_values_from_dependency_mapped_to_current_tables_keys = tuple((dependency_foreign_key_maps_from[key], value,) for key, value in attr_values_from_dependency)

                    eligible_primary_key_values = self.tables[table_name].update_eligible_primary_key_values_from_key_value_pairs(eligible_primary_key_values, attr_values_from_dependency_mapped_to_current_tables_keys)

                else:
                    # Create case
                    if dependency['type'] == "many-to-one":
                        # No restriction on parent selection (they can already be a parent or not)
                        attr_values_from_dependency, entities_already_selected = self.__recursively_crud_entity__(
                            table_name=parent_table_name,
                            action_name=action_name,
                            entities_already_selected=entities_already_selected,
                            required_fields=tuple(dependency_foreign_key_maps_into.values()),
                            selecting_first_table_from_table=selecting_first_table_from_parent_table,
                            attr_values_from_child=attr_values_to_give_parent,
                        ) # eligible_foreign_key_values & ineligible_primary_key_values not parameterised

                    elif dependency['type'] == "one-to-one":
                        # Need to work out ineligible foreign keys - based on ALL existing entities of table_name (not just eligible_primary_key_values,
                        # which may have been narrowed down by an unrelated exclusion, e.g. rows of table_name already claimed by a DIFFERENT one-to-one
                        # child). Any existing row of table_name, whether or not it is still available for that unrelated purpose, already occupies a
                        # parent entity here, so it must still count as ineligible for a newly created entity's parent selection.
                        all_existing_primary_key_values = self.tables[table_name].get_eligible_primary_key_values(primary_keys, candidate_key_values_from_childs_fk=True)
                        ineligible_foreign_key_values = self.tables[table_name].get_foreign_key_values_that_match_eligible_primary_key_values(all_existing_primary_key_values, tuple(dependency_foreign_key_maps_into.keys()))

                        # Remap keys from current table's foreign key column names to parent's matching primary key column names, since the parent's get_eligible_primary_key_values filters its own dataframe using these as column names.
                        ineligible_foreign_key_values = tuple(
                            tuple((dependency_foreign_key_maps_into[key], value) for key, value in combo)
                            for combo in ineligible_foreign_key_values
                        )

                        attr_values_from_dependency, entities_already_selected = self.__recursively_crud_entity__(
                            table_name=parent_table_name,
                            action_name=action_name,
                            entities_already_selected=entities_already_selected,
                            required_fields=tuple(dependency_foreign_key_maps_into.values()),
                            selecting_first_table_from_table=selecting_first_table_from_parent_table,
                            attr_values_from_child=attr_values_to_give_parent,
                            ineligible_primary_key_values=ineligible_foreign_key_values,
                        ) # eligible_foreign_key_values not parameterised
                # Map attr_values_from_dependency keys from primary keys of parent to foreign keys of parent table
                attr_values_from_dependency_mapped_to_current_tables_keys = tuple((dependency_foreign_key_maps_from[key], value,) for key, value in attr_values_from_dependency)

                # Add new attrs from dependency
                attr_values_from_all_dependencies = attr_values_from_all_dependencies + attr_values_from_dependency_mapped_to_current_tables_keys
            
        # Step 5: CRUD entity for current table, taking dependency info into account if available
        base_action = self.actions[action_name].get('base_actions', {}).get(table_name)

        if base_action is None:
            # Select
            print(f"{table_name}: BASE ACTION IS NONE - SELECT")
            entity = self.tables[table_name].select_entity(eligible_primary_key_values)
        else:
            # CRUD may be a single value (e.g. 'create') or a list (e.g. ['read', 'macro']) - 'read'/'update' only
            # ever contribute an existence requirement (already enforced in __get_possible_actions__), so the
            # actual dispatch below just picks whichever single operation actually acts on the table, in
            # priority order macro > create > update > read.
            crud_types = _normalize_crud_types(base_action['CRUD'])
            _validate_crud_types(crud_types, table_name, action_name)

            if 'macro' in crud_types:
                # Escape hatch for scenarios the standard create/update generation can't express: hands off to a
                # named function in attr_gen_functions_module with unrestricted, by-reference access to every
                # table's live dataframe (as well as a by-value copy), so it can perform arbitrary mutations
                # (across one or many tables) itself. Intentionally unenforced/unvalidated - see get_possible_actions.
                print(f"{table_name}: BASE ACTION IS MACRO")
                macro_function_name = base_action.get('macro_function')
                if not macro_function_name:
                    macro_function_name = "null_macro"
                macro_function = getattr(self.attr_gen_functions, macro_function_name)
                macro_result = macro_function(
                    table_name=table_name,
                    tables_by_ref=self.get_all_table_dataframes(),
                    tables_by_value=self.get_all_table_dataframes_copy(),
                    initial_partition_date=self.initial_partition_date,
                    time_step=self.time_steps,
                    seconds_per_time_step=self.seconds_per_time_step,
                    attr_values=attr_values_from_all_dependencies + attr_values_from_child,
                )
                entity = tuple(macro_result.items()) if isinstance(macro_result, dict) else tuple(macro_result or ())
            elif 'create' in crud_types:
                print(f"{table_name}: BASE ACTION IS CREATE")
                hardcoded_values = tuple((base_action.get('hardcoded_values') or {}).items())
                attr_gen_function_overrides = tuple((base_action.get('attr_gen_functions') or {}).items())
                entity = self.tables[table_name].create_entity(
                    self.initial_partition_date, self.time_steps, self.seconds_per_time_step,
                    attr_values_from_all_dependencies + attr_values_from_child + hardcoded_values,
                    attr_gen_function_overrides,
                )
            elif 'update' in crud_types:
                print(f"{table_name}: BASE ACTION IS UPDATE")
                attributes_to_update = tuple(base_action.get('attributes_to_update') or ())
                if not attributes_to_update:
                    raise Exception(f"CRUD update for table {table_name} in action {action_name} requires a non-empty attributes_to_update list. Please amend in config.")
                hardcoded_values = tuple((base_action.get('hardcoded_values') or {}).items())
                attr_gen_function_overrides = tuple((base_action.get('attr_gen_functions') or {}).items())
                selected_entity = self.tables[table_name].select_entity(eligible_primary_key_values)
                entity = self.tables[table_name].update_entity(
                    selected_entity, attributes_to_update, self.initial_partition_date, self.time_steps, self.seconds_per_time_step,
                    attr_values_from_all_dependencies + attr_values_from_child + hardcoded_values,
                    attr_gen_function_overrides,
                )
            elif 'read' in crud_types:
                # Same as the implicit (base_action is None) select case - exists so a table can be explicitly
                # declared as a required-to-already-exist dependency of an action, even if no other table in the
                # action structurally depends on it as a foreign key parent.
                print(f"{table_name}: BASE ACTION IS READ - SELECT")
                entity = self.tables[table_name].select_entity(eligible_primary_key_values)
            else:
                raise Exception(f'Unknown base operation CRUD in config, action_name = {action_name}, table_name = {table_name}')

        required_values = get_subset_key_value_pairs(entity, required_fields)
        entity_with_table_name = (table_name, entity)

        # Step 6: Add to entities_already_selected (append as single element)
        entities_already_selected = (*entities_already_selected, entity_with_table_name)

        # Step 7: Return required_values, entities_already_selected from current entity
        return required_values, entities_already_selected


    # Gets general dependency details of table, including parent table names, relationship types and key mappings (from child to each parent)
    def __get_dependency_details__(self, table_name:str):
        """
        Parameters:
            - action_name (str): key for self.actions
            - table_name (str): name of dependent table
        Returns:
            - dependency_details (list): [{'parent_table_name':..., 'type':... (e.g. one-to-one), 'key_mappings': {attr1_in_dependent: attr1_in_parent, attr2_in_dependent, attr2_in_parent, ...}, 'fields_added_to_foreign_key_in_to': {...}, ...], note this cannot be a dict as parent_table_name may not be unique.
        """
        dependency_details = []
        parent_tables = self.inverse_table_relationship_dag[table_name]
        for relationship in self.table_relationship_details:
            try:
                if relationship['type'] == 'one-to-many':
                    raise Exception(f'Relationship type in config ({relationship['from']} to {relationship['to']}) cannot be "one-to-many", reconfigure relationship so that it is many-to-one.')
                elif relationship['from'] == table_name and relationship['to'] in parent_tables:
                    # child-to-parent case
                    dependency_details.append({'parent_table_name':relationship['to'], 'type':relationship['type'], 'key_mappings': dict(zip(relationship['on_field'], relationship['foreign_key_in_to'])), 'fields_added_to_foreign_key_in_to': relationship.get('fields_added_to_foreign_key_in_to') or {}})
                elif relationship['from'] in parent_tables and relationship['to'] == table_name:
                    # parent-to-child case
                    raise Exception(f'Relationship type in config cannot be from parent ({relationship['from']}) to child ({relationship['to']}), reconfigure dependencies.')
                    """
                    # Old logic (allows relationships to be configured this way)
                    map_to_child_to_parent_case = {'one-to-one':'one-to-one', 'many-to-one':'one-to-many'}
                    relationship_type = map_to_child_to_parent_case[relationship['type']]
                    dependency_details.append({'parent_table_name':relationship['from'], 'type':relationship_type, 'key_mappings': dict(zip(relationship['on_field'], relationship['foreign_key_in_to']))})
                    """
            except:
                raise Exception(f'Error with relationship from config: {relationship}. Please ammend in config.')

        return dependency_details

    # Returns the current simulated datetime
    def get_simulated_datetime(self) -> datetime:
        return self.current_simulated_datetime

    # Advances simulated time by one time step, jumping straight to the next window's start if doing so would
    # overshoot the current window's end (this is how gaps between daily run windows are realised).
    def __advance_simulated_datetime__(self):
        self.current_simulated_datetime += timedelta(seconds=self.seconds_per_time_step)
        _, window_end = self.daily_windows[self.current_window_index]
        if self.current_simulated_datetime > window_end:
            self.current_window_index += 1
            if self.current_window_index < len(self.daily_windows):
                self.current_simulated_datetime = self.daily_windows[self.current_window_index][0]

    # Saves a full checkpoint (deltas + snapshot), then stages an audit-column copy of just the csv files
    # this checkpoint wrote (see add_audit_cols.stage_checkpoint_with_audit_cols()) into that same
    # simulated-datetime folder's deltas/snapshots gcp_staging_csv/ subfolders - purely a post-processing
    # step over already-written CSVs, with no bearing on the generated data itself (audit columns never
    # feed back into table generation).
    def __save_checkpoint__(self) -> None:
        simulated_datetime_str = self.get_simulated_datetime().strftime("%Y%m%d_%H%M%S")
        for table in self.tables.values():
            table.save_deltas(self.time_steps, self.dataset_name, simulated_datetime_str)
        for table in self.tables.values():
            table.save_snapshot_parquet(self.time_steps, self.dataset_name, simulated_datetime_str)
            table.save_snapshot_csv(self.time_steps, self.dataset_name, simulated_datetime_str)

        try:
            import add_audit_cols
            add_audit_cols.stage_checkpoint_with_audit_cols(self.schema_entity_relationships_filepath, self.dataset_name, simulated_datetime_str, self.attr_gen_functions, BASE_PATH)
        except Exception as e:
            print(f"Warning: failed to stage gcp_staging audit-column files for checkpoint {simulated_datetime_str}: {e}")

    # Manually saves deltas + a full snapshot at the current simulated_datetime, reusing the exact same save
    # logic that otherwise only runs automatically at a checkpoint/run completion (see run_step_orchestrate).
    def take_snapshot(self) -> None:
        self.__save_checkpoint__()

    def run_fuzzing(self):
        self.clear_deltas_and_snapshots(self.dataset_name)

        while not self.is_run_complete():
            self.run_step_display()
            self.run_step_select()
            self.run_step_orchestrate()

    # --- Step-through API -------------------------------------------------------------------------------
    # A decoupled, stateful alternative to run_fuzzing() used by the GUI's step-through window: the UI only
    # ever calls these three methods (in order) and reads their return values - it has no knowledge of, or
    # access to, the engine's internals (DAGs, tables, dependency resolution, etc).

    # True once simulated time has advanced past the last daily_windows entry (no more steps can be taken)
    def is_run_complete(self) -> bool:
        return self.current_window_index >= len(self.daily_windows)

    # Step 1/3: computes (and returns, for display) the actions currently possible to carry out
    def run_step_display(self) -> list:
        if self.is_run_complete():
            raise Exception("Run is already complete - there are no more time steps left in daily_windows.")

        self.time_steps += 1
        self._step_possible_actions = self.__get_possible_actions__()
        self._step_selected_action = None
        return self._step_possible_actions

    # Step 2/3: selects (and returns, for highlighting) one action from those computed by run_step_display()
    def run_step_select(self) -> str:
        if self._step_possible_actions is None:
            raise Exception("Call run_step_display() before run_step_select().")

        self._step_selected_action = self.__select_action__()
        return self._step_selected_action

    # Step 3/3: orchestrates the action selected by run_step_select(), advances simulated time, and saves
    # deltas/snapshots for any checkpoint just passed (or for the final state, if the run has now completed).
    # Returns: {"action": str, "simulated_datetime": datetime, "saved": bool, "run_complete": bool}
    def run_step_orchestrate(self) -> dict:
        if self._step_selected_action is None:
            raise Exception("Call run_step_select() before run_step_orchestrate().")

        action = self._step_selected_action
        self.__orchestrate_action__(action)
        self.__advance_simulated_datetime__()

        saved = False
        while self._next_checkpoint_index < len(self._checkpoint_datetimes) and self._checkpoint_datetimes[self._next_checkpoint_index] <= self.current_simulated_datetime:
            self.__save_checkpoint__()
            self._next_checkpoint_index += 1
            saved = True

        run_complete = self.is_run_complete()
        if run_complete:
            self.__save_checkpoint__()
            saved = True

        self._step_possible_actions = None
        self._step_selected_action = None

        return {"action": action, "simulated_datetime": self.current_simulated_datetime, "saved": saved, "run_complete": run_complete}

    # --- Read-only accessors for GUI visualisation (e.g. the DAG viewer window) -------------------------

    # Returns {table_name: [tables it depends on]} - a plain-dict copy, safe for external callers to read.
    def get_table_dependency_dag(self) -> dict:
        return {table: list(dependencies) for table, dependencies in self.inverse_table_relationship_dag.items()}

    # Returns the table names acted on by action_name, e.g. to highlight them in the DAG viewer window.
    def get_action_tables(self, action_name: str) -> list:
        return list(self.actions[action_name]['base_actions'].keys())

    # Returns {table_name: {crud_types}} (normalised sets, e.g. {'read', 'macro'}) for tables explicitly acted
    # on by action_name, e.g. so the DAG viewer window can badge tables being updated/macro'd differently
    # from tables being created.
    def get_action_table_cruds(self, action_name: str) -> dict:
        return {table: _normalize_crud_types(details['CRUD']) for table, details in self.actions[action_name]['base_actions'].items()}

    # Returns every table named in action_name's post_actions' affected_tables (deduplicated) - post_actions
    # are always macros (see __orchestrate_action__), so the DAG viewer window badges these the same as any
    # other CRUD=macro table.
    def get_action_post_action_tables(self, action_name: str) -> set:
        return {
            table
            for post_action in self.actions[action_name].get('post_actions') or []
            for table in post_action.get('affected_tables') or []
        }

    # --- Table dataframe access (primarily for CRUD=macro attr_gen_functions_module functions) -------------
    # By-reference: mutating the returned dataframe(s) directly changes engine state (inserts/updates/deletes
    # persist). By-value: independent copies, safe to inspect without side effects.

    def get_table_dataframe(self, table_name: str) -> pd.DataFrame:
        return self.tables[table_name].df

    def get_table_dataframe_copy(self, table_name: str) -> pd.DataFrame:
        return self.tables[table_name].df.copy()

    def get_all_table_dataframes(self) -> dict:
        return {name: table.df for name, table in self.tables.items()}

    def get_all_table_dataframes_copy(self) -> dict:
        return {name: table.df.copy() for name, table in self.tables.items()}


class Table():
    def __init__(self, name: str, config: dict, attr_gen_functions, selection_functions):
        self.name = name
        # Modules providing attribute-generation and action/entity selection functions, supplied by Engine.
        self.attr_gen_functions = attr_gen_functions
        self.selection_functions = selection_functions
        print(config['fields'])
        # Filter out all audit columns
        config['fields'] = [field for field in config['fields'] if not field.get('is_audit_column')]

        attr_list = [field['name'] for field in config['fields']]

        self.df = pd.DataFrame(columns=attr_list)
        self.df_after_last_delta_save = pd.DataFrame(columns=attr_list)

        # Build DAG: attr_1 -> attr_2 => attr_1 depends on attr_2
        self.inverse_attr_relationship_dag = build_dag(config['fields'])
        # Check if it's a DAG (no cycles)
        if not is_dag(self.inverse_attr_relationship_dag):
            raise Exception(f"Config file does not define attribute relationship DAG for {name}, cycles were found.")
        # attr_1 -> attr_2 => attr_2 depends on attr_1
        self.attr_relationship_dag = invert_dag(self.inverse_attr_relationship_dag)

        # Get list of all attrbiutes in order of dependenices, x preceeds y => y depends on x (attrs not in DAG are added after as they have no dependencies)
        self.attr_relationship_dag_dfs_list = topological_sort(self.attr_relationship_dag)

        # Get list of primary keys
        self.primary_keys = config['primary_keys']

        # Get list of independent qualifiers if any:
        self.ind_quals = config.get('independent_qualifiers')

        # Get default attribute generation functions  each attribute, {attribute name: {'attr_gen_func': ...}
        self.default_attr_gen_funcs = {}
        for field in config['fields']:
            self.default_attr_gen_funcs[field['name']] = field.get('default_function')

        # Get attribute data types for each attribute, {attribute name: datatype}
        self.attr_datatypes = {}
        for field in config['fields']:
            if field.get('datatype') == None:
                raise Exception(f'Table {name} has attribute {field} with no datatype, please ammend in config.')
            self.attr_datatypes[field['name']] = field.get('datatype')

    # helper function, called by recursively_crud_entity. Parameter table_name is a key for the base action in action config
    def create_entity(self, initial_partition_date: datetime, time_step: int, seconds_per_time_step: int, attr_values: tuple = tuple(), attr_gen_function_overrides: tuple = tuple()):
        print("attr_values in create_entity:",attr_values)
        """
        Parameters:
            - attr_values (tuple): maps attribute name to value, e.g. (('country', 'UK'),)
            - attr_gen_function_overrides (tuple): maps attribute to function name, default is tuple() => uses default functions from config
        Returns:
           - entity (tuple): entire entity, maps field name to field value for all field names
        """
        data_frame_copy = self.df.copy()
        entity = {}

        # Process each attr in this order to ensure dependencies populated first
        for attr in self.attr_relationship_dag_dfs_list:
            hardcoded_value =  next((value for attr_to_write, value in attr_values if attr_to_write == attr), None)
            if hardcoded_value:
                entity[attr] = hardcoded_value
            else:
                attr_gen_function = next((details for attr_to_gen, details in attr_gen_function_overrides if attr_to_gen == attr), None)
                if attr_gen_function == None:
                    # Select defaults
                    attr_gen_function = self.default_attr_gen_funcs[attr]

                # Further check: if no default function just generate random variable of desired type
                if attr_gen_function == None:
                    entity[attr] = generate_random_value_of_given_type(datatype=self.attr_datatypes[attr])

                else:
                    # Generate attribute with function (self.attr_gen_functions here refers to the imported module, not a parameter)
                    entity[attr] = getattr(self.attr_gen_functions, attr_gen_function)(attr, self.name, entity, data_frame_copy, self.primary_keys, initial_partition_date, time_step, seconds_per_time_step)

        # check new primary key is eligible (unique)
        mask = True
        for attr in self.primary_keys:
            mask &= self.df[attr] == entity[attr]

        if mask.any():
            # New pk is not unique
            raise Exception(f"Primary key ({self.primary_keys}) generated for {self.name} is not unique. Entity used determined values: {attr_values} and functions: {attr_gen_function}.") 

        # Add entity to df
        self.df.loc[len(self.df)] = entity

        return tuple(entity.items())

    # Updates a subset of attributes on an existing entity (identified by primary key), leaving every other attribute untouched.
    def update_entity(self, existing_entity: tuple, attributes_to_update: tuple, initial_partition_date: datetime, time_step: int, seconds_per_time_step: int, attr_values: tuple = tuple(), attr_gen_function_overrides: tuple = tuple()):
        """
        Parameters:
            - existing_entity (tuple): full (attr, value) pairs of the entity to update, as returned by select_entity().
            - attributes_to_update (tuple[str, ...]): names of attributes to regenerate; every other attribute is left as-is.
            - attr_values (tuple): maps attribute name to a hardcoded value (takes priority over attr_gen_function_overrides/defaults).
            - attr_gen_function_overrides (tuple): maps attribute to function name, default is tuple() => uses default functions from config.
        Returns:
            - entity (tuple): the full, updated entity (all attributes, same shape as create_entity's return value).
        """
        entity = dict(existing_entity)

        unknown_attrs = [attr for attr in attributes_to_update if attr not in self.attr_datatypes]
        if unknown_attrs:
            raise Exception(f"attributes_to_update for {self.name} contains unknown attribute(s): {unknown_attrs}. Please amend in config.")

        primary_key_attrs = [attr for attr in attributes_to_update if attr in self.primary_keys]
        if primary_key_attrs:
            print(f"WARNING: attributes_to_update for {self.name} includes primary key attribute(s) {primary_key_attrs} - proceeding, but this may break entity identity/lookups elsewhere.")

        mask = pd.Series(True, index=self.df.index)
        for attr in self.primary_keys:
            mask &= (self.df[attr].astype(str) == str(entity[attr]))

        if not mask.any():
            raise Exception(f"update_entity could not find an existing entity in {self.name} with primary key values: {tuple((attr, entity[attr]) for attr in self.primary_keys)}.")

        # Excludes the entity being updated, consistent with create_entity's data_frame_copy contract (doesn't include
        # the entity a function generates an attribute for).
        data_frame_copy = self.df.loc[~mask].copy()
        attributes_to_update_set = set(attributes_to_update)

        # Process in the same dependency order as create_entity, but only touch attributes_to_update - entity already
        # has every other (untouched) attribute's current value seeded in from existing_entity.
        for attr in self.attr_relationship_dag_dfs_list:
            if attr not in attributes_to_update_set:
                continue

            hardcoded_value = next((value for attr_to_write, value in attr_values if attr_to_write == attr), None)
            if hardcoded_value:
                entity[attr] = hardcoded_value
            else:
                attr_gen_function = next((details for attr_to_gen, details in attr_gen_function_overrides if attr_to_gen == attr), None)
                if attr_gen_function == None:
                    # Select defaults
                    attr_gen_function = self.default_attr_gen_funcs[attr]

                if attr_gen_function == None:
                    entity[attr] = generate_random_value_of_given_type(datatype=self.attr_datatypes[attr])
                else:
                    entity[attr] = getattr(self.attr_gen_functions, attr_gen_function)(attr, self.name, entity, data_frame_copy, self.primary_keys, initial_partition_date, time_step, seconds_per_time_step)

        for attr in attributes_to_update:
            self.df.loc[mask, attr] = entity[attr]

        return tuple(entity.items())

    # Returns the list of primary key value combinations that are possible to select from
    def get_possible_entities(self, eligible_primary_key_values: tuple) -> list:
        """
        Parameters:
            - eligible_primary_key_values (tuple(tuple(tuple))): tuple of eligible primary key combinations to select from, each combination is a tuple of (key, value) pairs, e.g. ((('pk', '1'),), (('pk', '2'),))
        Returns:
            - possible_entities (list): eligible_primary_key_values as a list. Raises if empty.
        """
        possible_entities = list(eligible_primary_key_values)
        print(f"possible_entities in get_possible_entities(): {possible_entities}")
        if possible_entities == []:
            raise Exception(f"No avaialable entities in {self.name} to select from, with eligible_primary_key_values = {eligible_primary_key_values}")
        return possible_entities

    # Selects entity with primary keys that are in eligible_primary_key_values but not in ineligible_primary_key_values (note: eligible_primary_key_values should always contain values when passed as param here)
    def select_entity(self, eligible_primary_key_values: tuple):
        """
        Parameters:
            - eligible_primary_key_values (tuple(tuple(tuple))): tuple of eligible primary key combinations to select from, each combination is a tuple of (key, value) pairs, e.g. ((('pk', '1'),), (('pk', '2'),))
            Returns:
            - entity (tuple): entire entity, maps field name to field value for all field names
        """
        possible_entities = self.get_possible_entities(eligible_primary_key_values)

        chosen_primary_key_value_pairs = self.selection_functions.select_entity(possible_entities)

        # get whole entity
        mask = pd.Series(True, index=self.df.index)

        for col, value in chosen_primary_key_value_pairs:
            mask &= self.df[col] == value

        try:
            entity = self.df.loc[mask].iloc[0]
        except IndexError:
            raise Exception(
                f'select_entity could not select entity from {self.name} '
                f'with primary key value pairs: {chosen_primary_key_value_pairs}'
            )
        
        return tuple(entity.astype(str).items())


    # Returns tuple of every unique combination of values present for the given attributes.
    def get_existing_attr_values(self, attrs: tuple[str, ...]) -> tuple[tuple[str, ...], ...]:
        """
        Parameters:
            - attrs: fields to consider, e.g.
                ("country", "department")

        Returns:
            (
                ("UK", "Finance"),
                ("UK", "Risk"),
                ("US", "Finance")
            )
        """
        if not attrs:
            return tuple()

        return tuple(
            self.df[list(attrs)]
            .drop_duplicates()
            .astype(str)
            .itertuples(index=False, name=None)
        )

    # Returns tuple of full primary_keys value-combinations (as (key, value) pairs) that satisfy an (optional) constraint on a subset
    # of columns (candidate_key_values_from_childs_fk, itself already shaped as (key, value) pairs so its columns are self-describing)
    # and/or fixed attribute value constraints (fixed_attr_values). Used so that tables with compound/conjugate primary keys
    # (e.g. a independent_qualifier + id) can be filtered correctly even when only part of the key is known via a foreign key
    # mapping - the rest (e.g. independent_qualifier) being supplied via fixed_attr_values.
    def get_eligible_primary_key_values(self, primary_keys: tuple[str, ...], ineligible_primary_key_values: tuple = tuple(), candidate_key_values_from_childs_fk = True, fixed_attr_values: tuple = tuple()) -> tuple[tuple[tuple[str, str], ...], ...]:
        """
        Parameters:
            - primary_keys: full primary key column names of this table, e.g. ('independent_qualifier', 'pk')
            - ineligible_primary_key_values: tuple of ineligible combinations of (key, value) pairs
            - candidate_key_values_from_childs_fk: tuple of potentially eligible combinations of (key, value) pairs restricting a subset of columns,
                e.g. ((('pk', '1'),), (('pk', '2'),)), or True for no restriction. Columns are inferred from the pairs themselves.
            - fixed_attr_values: tuple of (attr_name, value) pairs that must match exactly, e.g. (('independent_qualifier', 'A'),)
        Returns:
            - tuple of unique primary_keys value-combinations satisfying both constraints, each as a tuple of (key, value) pairs
        """
        # Control for primary keys not in column names
        missing = [col for col in primary_keys if col not in self.df.columns]
        if missing:
            raise Exception(f"Error with config for table {self.name}: primary_key contains {missing}, which are not defined as field names. Please ammend in config.")

        filtered_df = self.df.copy()

        # filter by candidate_key_values_from_childs_fk
        if candidate_key_values_from_childs_fk != True:
            if not candidate_key_values_from_childs_fk:
                # No candidate foreign-key values at all (e.g. the child table this was derived from has no
                # rows yet) - nothing can be eligible, and there are no columns to infer from an empty tuple.
                return tuple()
            fk_columns = [key for key, _ in candidate_key_values_from_childs_fk[0]]
            candidate_key_values_from_childs_fk_set = {tuple(str(value) for _, value in combo) for combo in candidate_key_values_from_childs_fk}
            mask = filtered_df[fk_columns].astype(str).apply(lambda row: tuple(row) in candidate_key_values_from_childs_fk_set, axis=1)
            filtered_df = filtered_df[mask]

        # Filter to remove ineligible_primary_key_values
        if ineligible_primary_key_values:
            ineligible_columns = [key for key, _ in ineligible_primary_key_values[0]]
            ineligible_key_values_set = {tuple(str(value) for _, value in combo) for combo in ineligible_primary_key_values}
            mask = filtered_df[ineligible_columns].astype(str).apply(lambda row: tuple(row) not in ineligible_key_values_set, axis=1)
            filtered_df = filtered_df[mask]

        for attr, value in fixed_attr_values:
            if attr not in filtered_df.columns:
                raise Exception(f'Independent qualifer {attr} passed to parent where no such attribute exists.')
            filtered_df = filtered_df[filtered_df[attr].astype(str) == str(value)]

        return tuple(
            tuple(zip(primary_keys, row))
            for row in filtered_df[list(primary_keys)]
                .drop_duplicates()
                .astype(str)
                .itertuples(index=False, name=None)
        )

    # Used to get eligible_foreign_key_values from eligible_primary_key_values
    def get_foreign_key_values_that_match_eligible_primary_key_values(self, eligible_primary_key_values: tuple[tuple[tuple[str, str], ...], ...], foreign_keys: tuple[str, ...]
                                                                      ) -> tuple[tuple[tuple[str, str], ...], ...]:
        """
        Parameters
        ----------
        eligible_primary_key_values
            Tuple of eligible primary key combinations, each a tuple of (key, value) pairs (columns are self-describing). Example:
                (
                    (("customer_id", "100"), ("account_id", "A1")),
                    (("customer_id", "200"), ("account_id", "A2"))
                )

        foreign_keys
            Example:
                ("country_id", "branch_id")

        Returns
        -------
            (
                (("country_id", "1"), ("branch_id", "10")),
                (("country_id", "2"), ("branch_id", "20"))
            )
        """

        if not eligible_primary_key_values:
            return tuple()

        primary_keys = [key for key, _ in eligible_primary_key_values[0]]

        valid_keys = {
            tuple(str(value) for _, value in combo)
            for combo in eligible_primary_key_values
        }

        mask = self.df[primary_keys].astype(str).apply(
            lambda row: tuple(row) in valid_keys,
            axis=1
        )

        return tuple(
            tuple(zip(foreign_keys, row))
            for row in self.df.loc[mask, list(foreign_keys)]
                .drop_duplicates()
                .astype(str)
                .itertuples(index=False, name=None)
        )

    # Used to update eligible_primary_keys from either returned foreign_keys (attribute values from parent) or attribute values from child
    def update_eligible_primary_key_values_from_key_value_pairs(self, eligible_primary_key_values: tuple, foreign_key_values: tuple):
        """
        Parameters:
            - eligible_primary_key_values:
                (
                    (('facility_code', 'A'),),
                    (('facility_code', 'B'),),
                    (('facility_code', 'D'),)
                )

            - foreign_key_values (single entity's (key, value) pairs to filter self.df by):
                (
                    ('repayment_schedule_id', '2'),
                )

        Returns:
            (
                (('facility_code', 'B'),),
            )
        """

        if not eligible_primary_key_values:
            # Cannot filter further, already empty
            return tuple()

        # Filter dataframe by foreign key values
        filtered_df = self.df.copy()

        for foreign_key, expected_value in foreign_key_values:
            if foreign_key not in filtered_df.columns:
                return tuple()

            filtered_df = filtered_df[
                filtered_df[foreign_key].astype(str) == str(expected_value)
            ]

            if filtered_df.empty:
                return tuple()

        primary_keys = [key for key, _ in eligible_primary_key_values[0]]

        # Build set of valid PK tuples from the filtered dataframe
        valid_pk_values = set(
            filtered_df[primary_keys]
            .astype(str)
            .itertuples(index=False, name=None)
        )

        # Keep only eligible PKs that exist in the filtered set
        return tuple(
            combo
            for combo in eligible_primary_key_values
            if tuple(str(value) for _, value in combo) in valid_pk_values
        )

    def is_empty(self) -> bool:
        return self.df.empty

    # Checks whether a entity exists for each independent qualifiers possible from a specific child
    def has_entity_for_all_ind_quals(self, ind_quals_key_vals_combinations: list[dict]) -> bool:
        """
        Parameters:
            - ind_quals_key_vals_combinations (list[dict]): Each dict is combination of possible independent qualifiers from child (can deal with multiple) e.g. [['A'], ['B']]
        Returns: (bool) whether the table contains a entity for each combination of independent qualifiers
        """
        print(f"\nhas_entity_for_all_ind_quals: self.ind_quals = {self.ind_quals}, ind_quals_key_vals_combinations = {ind_quals_key_vals_combinations}")
        if self.ind_quals == None:
            raise Exception(f"Child exists with expectation that parent ({self.name}) has independent qualifiers, but none exist. Adjust config accordingly to resolve.")

        if set(self.ind_quals) != set(ind_quals_key_vals_combinations[0].keys()):
            raise Exception(f"Mismatch between child's keys to pass to parent and parent's ({self.name}) independent qualifiers. Adjust config accordingly to resolve.")

        has_entity_for_all_ind_quals = True
        for ind_quals_key_vals in ind_quals_key_vals_combinations:
            # ind_quals_val is specific combination of values for given independent qualifiers, e.g. {'independent_qualifier': 'A'}
            mask = pd.Series(True, index=self.df.index)
            for key, value in ind_quals_key_vals.items():
                mask &= (self.df[key] == value)
            if self.df[mask].empty:
                print(f'has_entity_for_all_ind_quals returned FALSE')
                return False

        print(f'has_entity_for_all_ind_quals returned TRUE')
        return has_entity_for_all_ind_quals

    # Returns True if table has a entity that could be selected from (given ind_quals_vals constraints, if any)
    def is_able_to_select_from(self, ind_quals_vals):
        print(f'is_able_to_select_from(): ind_quals_vals = {ind_quals_vals}')
        if ind_quals_vals:
            return self.has_entity_for_all_ind_quals(ind_quals_vals)
        else:
            return not self.is_empty()

    def get_entity_count_satisfying_key_value_pairs(self, key_value_pairs: dict = {}):
            "Returns: number of entities that satisfy the key value pairs, e.g. independent_qualifer = 'A'."
            print(f"get_entity_count_satisfying_key_value_pairs: key_value_pairs = {key_value_pairs}")
            if key_value_pairs:
                return (
                    self.df[list(key_value_pairs)]
                    .eq(pd.Series(key_value_pairs))
                    .all(axis=1)
                    .sum()
                )
            else:
                return len(self.df)

    # Saves positive & negative deltas (both csv and parquet) in:
    # "generated_data_files/<dataset_name>/<simulated_datetime_str>/deltas/{csv,parquet}/{positive,negative}/table_name.{csv,parquet}"
    # Sets self.df_after_last_delta_save = self.df
    def save_deltas(self, current_time_step: int, dataset_name: str, simulated_datetime_str: str):
        deltas_dir = BASE_PATH / "generated_data_files" / dataset_name / simulated_datetime_str / "deltas"
        csv_positive_dir = deltas_dir / "csv" / "positive"
        csv_negative_dir = deltas_dir / "csv" / "negative"
        parquet_positive_dir = deltas_dir / "parquet" / "positive"
        parquet_negative_dir = deltas_dir / "parquet" / "negative"
        for directory in (csv_positive_dir, csv_negative_dir, parquet_positive_dir, parquet_negative_dir):
            directory.mkdir(parents=True, exist_ok=True)

        try:
            added = self.df.merge(self.df_after_last_delta_save, how="outer", indicator=True)
            pos_delta = added[added["_merge"] == "left_only"].drop(columns="_merge")
            pos_delta.to_csv(csv_positive_dir / f"{self.name}.csv", index=False)
            pos_delta.to_parquet(parquet_positive_dir / f"{self.name}.parquet", index=False)
        except Exception as e:
            raise Exception(f"Failed to save positive delta for {self.name} at timestep {current_time_step}: {e}")

        try:
            # Keyed on primary_keys only (not full-row equality) so that updates - which change non-key
            # attributes but keep the same primary key - don't show up here as a false removal; a record only
            # belongs in the negative delta once its primary key no longer exists in self.df at all.
            primary_keys = list(self.primary_keys)
            current_keys = self.df[primary_keys].drop_duplicates()
            removed = self.df_after_last_delta_save.merge(current_keys, on=primary_keys, how="left", indicator=True)
            neg_delta = removed[removed["_merge"] == "left_only"].drop(columns="_merge")
            neg_delta.to_csv(csv_negative_dir / f"{self.name}.csv", index=False)
            neg_delta.to_parquet(parquet_negative_dir / f"{self.name}.parquet", index=False)
        except Exception as e:
            raise Exception(f"Failed to save negative delta for {self.name} at timestep {current_time_step}: {e}")

        # Update last-saved snapshot state
        self.df_after_last_delta_save = self.df.copy()

    # Saves snapshot as parquet in "generated_data_files/<dataset_name>/<simulated_datetime_str>/snapshots/parquet/table_name.parquet"
    def save_snapshot_parquet(self, current_time_step: int, dataset_name: str, simulated_datetime_str: str):
        snapshots_dir = BASE_PATH / "generated_data_files" / dataset_name / simulated_datetime_str / "snapshots" / "parquet"
        snapshots_dir.mkdir(parents=True, exist_ok=True)

        snapshot_path = snapshots_dir / f"{self.name}.parquet"
        try:
            # prefer pandas to_parquet
            self.df.to_parquet(snapshot_path, engine='pyarrow', index=False)
        except Exception as e:
            # fallback to pyarrow table write
            try:
                table = pa.Table.from_pandas(self.df.reset_index(drop=True))
                pq.write_table(table, snapshot_path)
            except Exception as e2:
                raise Exception(f"Failed to save snapshot for {self.name} at timestep {current_time_step}: {e} / {e2}")

    # Saves snapshot as csv in "generated_data_files/<dataset_name>/<simulated_datetime_str>/snapshots/csv/table_name.csv"
    def save_snapshot_csv(self, current_time_step: int, dataset_name: str, simulated_datetime_str: str):
        snapshots_dir = BASE_PATH / "generated_data_files" / dataset_name / simulated_datetime_str / "snapshots" / "csv"
        snapshots_dir.mkdir(parents=True, exist_ok=True)

        snapshot_path = snapshots_dir / f"{self.name}.csv"

        try:
            self.df.to_csv(snapshot_path, index=False)
        except Exception as e:
            raise Exception(f"Failed to save snapshot for {self.name} at timestep {current_time_step}: {e}")

def _load_master_config(master_config_path: Path) -> dict:
    with open(master_config_path, "r") as f:
        return yaml.safe_load(f) or {}


def load_attr_gen_functions_module_from_master_config(master_config_path: Path = BASE_PATH/"config/master_config.yaml"):
    """
    Reads config/master_config.yaml and dynamically imports the module named by attr_gen_functions_module
    (e.g. acbsuk_attr_gen_functions), for the caller to pass into Engine.
    """
    master_config = _load_master_config(master_config_path)
    return importlib.import_module(master_config["attr_gen_functions_module"])


def load_selection_functions_module_from_master_config(master_config_path: Path = BASE_PATH/"config/master_config.yaml"):
    """
    Reads config/master_config.yaml and dynamically imports the module named by selection_functions_module
    (e.g. selection_functions), for the caller to pass into Engine.
    """
    master_config = _load_master_config(master_config_path)
    return importlib.import_module(master_config["selection_functions_module"])


def _parse_master_config_datetime(value) -> datetime:
    # yaml parses "YYYY-MM-DD" as a date and "YYYY-MM-DD HH:MM:SS" as a datetime; normalise both to a datetime.
    if isinstance(value, datetime):
        return value
    return datetime.fromisoformat(str(value))


def _parse_master_config_time(value) -> time:
    if isinstance(value, time):
        return value
    return time.fromisoformat(str(value))


def load_engine_kwargs_from_master_config(master_config_path: Path = BASE_PATH/"config/master_config.yaml") -> dict:
    """
    Reads config/master_config.yaml and builds the kwargs dict used to construct Engine.
    - schema_entity_relationships_filepath and actions_config are mandatory, and are resolved relative to BASE_PATH.
    - daily_windows (mandatory) is a list of {start, end} mappings, converted here into a list of (start, end) datetime tuples.
    - Any other (optional) setting left as null in the yaml is omitted here, so Engine falls back to its own default.
    """
    master_config = _load_master_config(master_config_path)

    engine_kwargs = {
        "config_schema_entity_relationships_filepath": BASE_PATH/master_config["schema_entity_relationships_filepath"],
        "config_actions_filepath": BASE_PATH/master_config["actions_config"],
        "daily_windows": [
            (_parse_master_config_datetime(window["start"]), _parse_master_config_datetime(window["end"]))
            for window in master_config["daily_windows"]
        ],
    }

    checkpoint_times = master_config.get("checkpoint_times")
    if checkpoint_times is not None:
        engine_kwargs["checkpoint_times"] = [_parse_master_config_time(t) for t in checkpoint_times]

    seconds_per_time_step = master_config.get("seconds_per_time_step")
    if seconds_per_time_step is not None:
        engine_kwargs["seconds_per_time_step"] = seconds_per_time_step

    return engine_kwargs
