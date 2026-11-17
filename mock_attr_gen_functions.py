from faker import Faker
import inspect
import pandas as pd
from typing import Any
import random
from datetime import datetime, timedelta
import uuid
import pandas as pd
from pathlib import Path
import numpy as np

from core.sql_macro_helpers import run_sql

BASE_PATH = Path(__file__).parent
fake = Faker()

COUNTRY_TO_LOCALE = {


    # Europe

    "FR": "fr_FR",
    "GB": "en_GB",
    "GR": "el_GR",


    # North America
    "CA": "en_CA",
    "US": "en_US",

}

SUPPORTED_COUNTRY_CODES = list(COUNTRY_TO_LOCALE.keys())

# FX rates for 04 Aug
FX_RATES = pd.read_csv(BASE_PATH/"ref_data/fx.csv")

# Cache of Faker instances per locale, avoids re-instantiating Faker (which reloads providers) on every call
_locale_faker_cache: dict[str, Faker] = {}

def _get_localised_faker(country_code: str) -> Faker:
    """
    Returns a Faker instance localised to the given country_code, falling back to the
    default (global) Faker instance if the country_code is unknown/unsupported.
    """
    locale = COUNTRY_TO_LOCALE.get(country_code)
    if locale is None:
        return fake

    if locale not in _locale_faker_cache:
        _locale_faker_cache[locale] = Faker(locale)

    return _locale_faker_cache[locale]

# Defines signature for attribute generation functions - used top ensure user implemented functions match this signature
def default_attr_gen_func(attr_name: str, table_name: str, entity_so_far: dict, table_data_frame_copy: pd.DataFrame, primary_keys: list[str], initial_partition_date: datetime, time_step: int, seconds_per_time_step: int) -> Any:
    """
    Parameters:
        - attr_name (str): Name of the attribute to be generated
        - table_name (str): Name of the table in which the attribute is to be generated
        - entity_so_far (dict): Maps attribute names to attribute values, for all attroibutes already generated / written
        - table_data_frame_copy (pd.DataFrame): Copy of the table df (does not include entity for which function generates attribute for)
        - primary_keys (list[str]): List of primary key attribute names (can be used to ensure uniqueness for conjugate keys)
        - time_step (int): Current time step at which this attribute is being generated
        - seconds_per_time_step (int): Number of seconds each time step represents
    Returns:
        Generated attribute (Any) to be added to the entity by the engine
    """
    pass

#------------------------------------------------------------------------------------------------------------------------------
# IMPLEMENT YOUR OWN FUNCTIONS - CANNOT BE CALLED "default_attr_gen_func"

# ---------------- Generic functions -----------------

# Returns table_name + time_step
def generate_unique_id(attr_name: str, table_name: str, entity_so_far: dict, table_data_frame_copy: pd.DataFrame, primary_keys: list[str], initial_partition_date: datetime, time_step: int, seconds_per_time_step: int):
    return table_name + str(time_step)

# ----------- Attribute specific functions -----------

# Customer

def generate_customer_id(attr_name: str, table_name: str, entity_so_far: dict, table_data_frame_copy: pd.DataFrame, primary_keys: list[str], initial_partition_date: datetime, time_step: int, seconds_per_time_step: int):
    return generate_unique_id(attr_name, table_name, entity_so_far, table_data_frame_copy, primary_keys, initial_partition_date, time_step, seconds_per_time_step)
    
def generate_sex(attr_name: str, table_name: str, entity_so_far: dict, table_data_frame_copy: pd.DataFrame, primary_keys: list[str], initial_partition_date: datetime, time_step: int, seconds_per_time_step: int):
    return random.choice(['M','F'])

def generate_name(attr_name: str, table_name: str, entity_so_far: dict, table_data_frame_copy: pd.DataFrame, primary_keys: list[str], initial_partition_date: datetime, time_step: int, seconds_per_time_step: int):
    if entity_so_far['sex'] == 'M':
        first_name = fake.first_name_male()
    else:
        first_name = fake.first_name_female()
    return first_name + ' ' + fake.last_name()

def generate_timestamp_created(attr_name: str, table_name: str, entity_so_far: dict, table_data_frame_copy: pd.DataFrame, primary_keys: list[str], initial_partition_date: datetime, time_step: int, seconds_per_time_step: int):
    start_of_day = datetime.now().replace(
        hour=0,
        minute=0,
        second=0,
        microsecond=0
    )
    return start_of_day + timedelta(
            seconds= time_step * seconds_per_time_step
        )

# loan_facility

def generate_portfoilio_id(attr_name: str, table_name: str, entity_so_far: dict, table_data_frame_copy: pd.DataFrame, primary_keys: list[str], initial_partition_date: datetime, time_step: int, seconds_per_time_step: int):
    return str(uuid.uuid4())

def generate_facility_code(attr_name: str, table_name: str, entity_so_far: dict, table_data_frame_copy: pd.DataFrame, primary_keys: list[str], initial_partition_date: datetime, time_step: int, seconds_per_time_step: int):
    return generate_unique_id(attr_name, table_name, entity_so_far, table_data_frame_copy, primary_keys, initial_partition_date, time_step, seconds_per_time_step)

# repayment_schedule

def generate_repayment_schedule_id(attr_name: str, table_name: str, entity_so_far: dict, table_data_frame_copy: pd.DataFrame, primary_keys: list[str], initial_partition_date: datetime, time_step: int, seconds_per_time_step: int):
    return generate_unique_id(attr_name, table_name, entity_so_far, table_data_frame_copy, primary_keys, initial_partition_date, time_step, seconds_per_time_step)

def generate_repayment_schedule_info(attr_name: str, table_name: str, entity_so_far: dict, table_data_frame_copy: pd.DataFrame, primary_keys: list[str], initial_partition_date: datetime, time_step: int, seconds_per_time_step: int):
    num_years = random.choice([1,2,5,10])
    return str(num_years) + ' years'

# loan

def generate_loan_id(attr_name: str, table_name: str, entity_so_far: dict, table_data_frame_copy: pd.DataFrame, primary_keys: list[str], initial_partition_date: datetime, time_step: int, seconds_per_time_step: int):
    return generate_unique_id(attr_name, table_name, entity_so_far, table_data_frame_copy, primary_keys, initial_partition_date, time_step, seconds_per_time_step)

def generate_currency_code(attr_name: str, table_name: str, entity_so_far: dict, table_data_frame_copy: pd.DataFrame, primary_keys: list[str], initial_partition_date: datetime, time_step: int, seconds_per_time_step: int):
    return fake.currency_code()

def generate_amount(attr_name: str, table_name: str, entity_so_far: dict, table_data_frame_copy: pd.DataFrame, primary_keys: list[str], initial_partition_date: datetime, time_step: int, seconds_per_time_step: int):
    try:
        fx_rate = int(FX_RATES.loc[FX_RATES["to_currency_code"] == entity_so_far['currency_code'], "fx_rate"].iloc[0])
    except:
        # Fall back to GBP
        fx_rate = 1

    amount_gbp = np.random.randint(1000,100000)
    return amount_gbp * fx_rate

# address

def generate_address_id(attr_name: str, table_name: str, entity_so_far: dict, table_data_frame_copy: pd.DataFrame, primary_keys: list[str], initial_partition_date: datetime, time_step: int, seconds_per_time_step: int):
    return generate_unique_id(attr_name, table_name, entity_so_far, table_data_frame_copy, primary_keys, initial_partition_date, time_step, seconds_per_time_step)

def generate_country_code(attr_name: str, table_name: str, entity_so_far: dict, table_data_frame_copy: pd.DataFrame, primary_keys: list[str], initial_partition_date: datetime, time_step: int, seconds_per_time_step: int):
    return random.choice(SUPPORTED_COUNTRY_CODES)

# Generates a city name using a Faker instance localised to entity_so_far['country_code']
def generate_city(attr_name: str, table_name: str, entity_so_far: dict, table_data_frame_copy: pd.DataFrame, primary_keys: list[str], initial_partition_date: datetime, time_step: int, seconds_per_time_step: int):
    country_code = entity_so_far.get('country_code')
    localized_fake = _get_localised_faker(country_code)
    return localized_fake.city()

# Generates a postcode using a Faker instance localised to entity_so_far['country_code'] (generated after city, per depends_on config)
def generate_postcode(attr_name: str, table_name: str, entity_so_far: dict, table_data_frame_copy: pd.DataFrame, primary_keys: list[str], initial_partition_date: datetime, time_step: int, seconds_per_time_step: int):
    country_code = entity_so_far.get('country_code')
    localized_fake = _get_localised_faker(country_code)
    return localized_fake.postcode()

# child_w_2_fks

def generate_pk(attr_name: str, table_name: str, entity_so_far: dict, table_data_frame_copy: pd.DataFrame, primary_keys: list[str], initial_partition_date: datetime, time_step: int, seconds_per_time_step: int):
    return generate_unique_id(attr_name, table_name, entity_so_far, table_data_frame_copy, primary_keys, initial_partition_date, time_step, seconds_per_time_step)

def generate_independent_qualifier(attr_name: str, table_name: str, entity_so_far: dict, table_data_frame_copy: pd.DataFrame, primary_keys: list[str], initial_partition_date: datetime, time_step: int, seconds_per_time_step: int):
    return random.choice(['A','B'])

# Increments pk counter for independent qualifer given: 1 more than prev (= max) pk
def generate_pk_not_guarenteed_unique(attr_name: str, table_name: str, entity_so_far: dict, table_data_frame_copy: pd.DataFrame, primary_keys: list[str], initial_partition_date: datetime, time_step: int, seconds_per_time_step: int):
    table_data_frame_copy_for_given_discr = table_data_frame_copy[
        table_data_frame_copy["independent_qualifier"] == entity_so_far["independent_qualifier"]
    ]

    if table_data_frame_copy_for_given_discr.empty:
        pk = 0
    else:
        pk = int(table_data_frame_copy_for_given_discr[attr_name].astype(int).max()) + 1

    # Primary key values are compared/stored as strings elsewhere (e.g. select_entity, get_eligible_primary_key_values),
    # so keep this consistent with other pk-generating functions (e.g. generate_unique_id, which also returns a str).
    return str(pk)

# ---------------- Macro example (config/testy) -----------------
def null_macro(table_name, tables_by_ref, tables_by_value, initial_partition_date, time_step, seconds_per_time_step, attr_values):
    pass


# CRUD=macro escape hatch: picks an arbitrary account directly from the live dataframe (tables_by_ref),
# zeroes its some_other_field, then zeroes the amount of whichever balance row references that account.
def macro_mock_set_balance_amt_and_account_some_other_value_to_zero(table_name, tables_by_ref, tables_by_value, initial_partition_date, time_step, seconds_per_time_step, attr_values):
    account_df = tables_by_ref['account']
    balance_df = tables_by_ref['balance']

    if account_df.empty:
        print("macro_mock_set_balance_amt_and_account_some_other_value_to_zero: no accounts exist, nothing to do.")
        return {}

    chosen_account_id = random.choice(account_df['id'].tolist())
    account_df.loc[account_df['id'] == chosen_account_id, 'some_other_field'] = "0"

    matching_balance_mask = balance_df['account_id'] == chosen_account_id
    if not matching_balance_mask.any():
        print(f"macro_mock_set_balance_amt_and_account_some_other_value_to_zero: no balance found for account {chosen_account_id}.")
        return {'id': chosen_account_id}

    balance_df.loc[matching_balance_mask, 'amount'] = 0

    return {'id': chosen_account_id}


# CRUD=macro escape hatch demonstrating DuckDB use via run_sql() (see core/sql_macro_helpers.py): a series of
# plain INSERT statements (DML) - one for the new account, one for its matching balance - referencing the
# real table names directly. run_sql() takes care of materialising/syncing tables_by_ref, so the macro itself
# only needs to know SQL.
def macro_mock_duckdb_insert_account_and_balance(table_name, tables_by_ref, tables_by_value, initial_partition_date, time_step, seconds_per_time_step, attr_values):
    new_account_id = str(uuid.uuid4()) + "_sql_defined"
    new_balance_id = str(uuid.uuid4())
    new_amount = round(random.uniform(10, 10000), 2)

    run_sql(tables_by_ref, [
        ("INSERT INTO account VALUES (?, ?)", [new_account_id, "duckdb_generated"]),
        ("INSERT INTO balance VALUES (?, ?, ?)", [new_balance_id, new_account_id, new_amount]),
    ])
    # balance.amount may have just been created (and so typed as VARCHAR) if balance was empty - see run_sql()'s
    # docstring caveat - so re-assert its numeric type here regardless.
    tables_by_ref['balance']['amount'] = tables_by_ref['balance']['amount'].astype(float)

    return {'id': new_account_id}