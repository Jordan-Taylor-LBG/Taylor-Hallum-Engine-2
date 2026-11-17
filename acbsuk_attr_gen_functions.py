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

global initial_partition_date
initial_partition_date = 'PLACEHOLDER' # will remove this and feed in parameter to all functions

global global_src_extract_ts
global_src_extract_ts = 'PLACEHOLDER' # will remove this and feed in parameter to all functions - use timestamp to work out day, and pick timestamp during day

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

# FX rates for 04/08/2026
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
def template_attr_gen_func(attr_name: str, table_name: str, entity_so_far: dict, table_data_frame_copy: pd.DataFrame, primary_keys: list[str], initial_partition_date: datetime, time_step: int, seconds_per_time_step: int) -> Any:
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

# Defines signature for an action's post_actions (actions.yaml) - plain macro functions run once, after
# every base_action in the action has been fully orchestrated, with no dependency/ordering wiring needed:
# just a script that runs last, with unrestricted by-reference access to every table. Declared in
# actions.yaml as a list of {function, affected_tables} - affected_tables is purely metadata (the tables
# this function touches), used by the DAG viewer window to badge them like any other CRUD=macro table.
def template_post_action_func(action_name: str, entities_already_selected: tuple, tables_by_ref: dict, tables_by_value: dict, initial_partition_date: datetime, time_step: int, seconds_per_time_step: int) -> None:
    """
    Parameters:
        - action_name (str): Name of the action (key in actions.yaml) that just finished orchestrating
        - entities_already_selected (tuple): ((table_name, entity), ...) - entity is itself a tuple of
          (attr_name, value) pairs - every table CRUD'd/selected during this action, e.g.
          dict(entities_already_selected)["j_cldt"] gives the just-created j_cldt entity's full field values
        - tables_by_ref (dict): {table_name: pd.DataFrame} - every table's LIVE dataframe; mutating one
          directly (e.g. tables_by_ref["j_clla"].loc[mask, "balance_field"] += amount) persists
        - tables_by_value (dict): same shape as tables_by_ref, but independent copies - safe to inspect
          without side effects
        - time_step (int): Current time step at which this action is being orchestrated
        - seconds_per_time_step (int): Number of seconds each time step represents
    Returns:
        None - post-actions work purely by mutating tables_by_ref in place
    """
    pass

#------------------------------------------------------------------------------------------------------------------------------
# IMPLEMENT YOUR OWN FUNCTIONS - CANNOT BE CALLED "template_attr_gen_func"

def generate_int_as_string(attr_name: str, table_name: str, entity_so_far: dict, table_data_frame_copy: pd.DataFrame, primary_keys: list[str], initial_partition_date: datetime, time_step: int, seconds_per_time_step: int):
    return str(random.randint(1, 99999999999))  # Example: 11-digit random number

def generate_zero_as_string(attr_name: str, table_name: str, entity_so_far: dict, table_data_frame_copy: pd.DataFrame, primary_keys: list[str], initial_partition_date: datetime, time_step: int, seconds_per_time_step: int):
    return '0'

def generate_portfolio_id(attr_name: str, table_name: str, entity_so_far: dict, table_data_frame_copy: pd.DataFrame, primary_keys: list[str], initial_partition_date: datetime, time_step: int, seconds_per_time_step: int):  
    # Generate a random portfolio ID based on the current entity index
    # This is a placeholder function, you can modify it to generate IDs as per your requirements
    return "L3"

def generate_transaction_id_j_cxpn(attr_name: str, table_name: str, entity_so_far: dict, table_data_frame_copy: pd.DataFrame, primary_keys: list[str], initial_partition_date: datetime, time_step: int, seconds_per_time_step: int):
    # Generate a random transaction ID based on the current entity index
    # This is a placeholder function, you can modify it to generate IDs as per your requirements
    return str(random.randint(1, 99999999999))  # Example: 11-digit random number

def generate_delta_type(attr_name: str, table_name: str, entity_so_far: dict, table_data_frame_copy: pd.DataFrame, primary_keys: list[str], initial_partition_date: datetime, time_step: int, seconds_per_time_step: int):
    return 'F'

def generate_ca_number(attr_name: str, table_name: str, entity_so_far: dict, table_data_frame_copy: pd.DataFrame, primary_keys: list[str], initial_partition_date: datetime, time_step: int, seconds_per_time_step: int):
    return 'FC' + str(random.randint(10, 99999999))

def generate_j_rjxc(attr_name: str, table_name: str, entity_so_far: dict, table_data_frame_copy: pd.DataFrame, primary_keys: list[str], initial_partition_date: datetime, time_step: int, seconds_per_time_step: int):
    # choose a random value from a set. Only 'A' entities are to be ingested
    return random.choice(['A', 'B', 'C', 'D'])

def generate_j_cngc(attr_name: str, table_name: str, entity_so_far: dict, table_data_frame_copy: pd.DataFrame, primary_keys: list[str], initial_partition_date: datetime, time_step: int, seconds_per_time_step: int):
    return random.choice(['600'])

def generate_j_cnc(attr_name: str, table_name: str, entity_so_far: dict, table_data_frame_copy: pd.DataFrame, primary_keys: list[str], initial_partition_date: datetime, time_step: int, seconds_per_time_step: int):
    return random.choice(['600'])

def generate_j_cnfc(attr_name: str, table_name: str, entity_so_far: dict, table_data_frame_copy: pd.DataFrame, primary_keys: list[str], initial_partition_date: datetime, time_step: int, seconds_per_time_step: int):
    return random.choice(['5'])

def generate_j_nodn(attr_name: str, table_name: str, entity_so_far: dict, table_data_frame_copy: pd.DataFrame, primary_keys: list[str], initial_partition_date: datetime, time_step: int, seconds_per_time_step: int):
    return random.choice(['0', '1'])

def generate_j_noen(attr_name: str, table_name: str, entity_so_far: dict, table_data_frame_copy: pd.DataFrame, primary_keys: list[str], initial_partition_date: datetime, time_step: int, seconds_per_time_step: int):
    return random.choice(['0', '1'])

def generate_j_bcac(attr_name: str, table_name: str, entity_so_far: dict, table_data_frame_copy: pd.DataFrame, primary_keys: list[str], initial_partition_date: datetime, time_step: int, seconds_per_time_step: int):
    return random.choice(['A', 'B'])

def generate_j_baec(attr_name: str, table_name: str, entity_so_far: dict, table_data_frame_copy: pd.DataFrame, primary_keys: list[str], initial_partition_date: datetime, time_step: int, seconds_per_time_step: int):
    return random.choice(['FAT', 'FCT'])

def generate_j_mcgc(attr_name: str, table_name: str, entity_so_far: dict, table_data_frame_copy: pd.DataFrame, primary_keys: list[str], initial_partition_date: datetime, time_step: int, seconds_per_time_step: int):
    return random.choice(['UK', 'KY', 'US', 'TR', 'FR', 'DE'])

def generate_j_mccc(attr_name: str, table_name: str, entity_so_far: dict, table_data_frame_copy: pd.DataFrame, primary_keys: list[str], initial_partition_date: datetime, time_step: int, seconds_per_time_step: int):
    return random.choice(['140'])


def generate_j_mesc(attr_name: str, table_name: str, entity_so_far: dict, table_data_frame_copy: pd.DataFrame, primary_keys: list[str], initial_partition_date: datetime, time_step: int, seconds_per_time_step: int):
    return 'CCA'

def generate_j_mcqi(attr_name: str, table_name: str, entity_so_far: dict, table_data_frame_copy: pd.DataFrame, primary_keys: list[str], initial_partition_date: datetime, time_step: int, seconds_per_time_step: int):
    return random.choice([
        '47009000', '60000527', '44001115', '44001114', '32000056',
        '60000818', '60000558', '44000502', '60000510', '56000008',
        '60000019', '44010107', '56000010', '60000528', '44000503',
        '60000531', '44000144', '60000013', '44000922', '47001000',
        '44000745', '56400001', '56200013', '56700031', '60000835',
        '99999999', '44000527', '44000512', '44000904', '44001117',
        '32000023', '44000720', '44003006', '60000533', '60000011',
        '32000022', '44000529', '44003003', '44000730', '44000593',
        '44000594', '32000011', '44000927', '60000700', '44000701',
        '44000907', '57000005', '44000918', '44000903', '44007000'
    ])

def generate_j_nadi(attr_name: str, table_name: str, entity_so_far: dict, table_data_frame_copy: pd.DataFrame, primary_keys: list[str], initial_partition_date: datetime, time_step: int, seconds_per_time_step: int):
    return random.choice(['LT026',
    'T0335',
    'T0340',
    'T1075',
    'T1095',
    'T1105',
    'T1300',
    'T2005',
    'T2060',
    'T2110',
    'T2375'])


def generate_j_naft(attr_name: str, table_name: str, entity_so_far: dict, table_data_frame_copy: pd.DataFrame, primary_keys: list[str], initial_partition_date: datetime, time_step: int, seconds_per_time_step: int):
    return 'GBP'

# Increments pk counter for independent qualifer given: 1 more than prev (= max) pk
def generate_j_naei(attr_name: str, table_name: str, entity_so_far: dict, table_data_frame_copy: pd.DataFrame, primary_keys: list[str], initial_partition_date: datetime, time_step: int, seconds_per_time_step: int):
    table_data_frame_copy_for_given_ind_qual = table_data_frame_copy[
        table_data_frame_copy["j_nadi"] == entity_so_far.get("j_nadi")
    ]

    if table_data_frame_copy_for_given_ind_qual.empty:
        pk = 0
    else:
        pk = int(table_data_frame_copy_for_given_ind_qual[attr_name].astype(int).max()) + 1

    return str(pk)

def generate_j_nofc(attr_name: str, table_name: str, entity_so_far: dict, table_data_frame_copy: pd.DataFrame, primary_keys: list[str], initial_partition_date: datetime, time_step: int, seconds_per_time_step: int):
    return '08'

def generate_loan_id(attr_name: str, table_name: str, entity_so_far: dict, table_data_frame_copy: pd.DataFrame, primary_keys: list[str], initial_partition_date: datetime, time_step: int, seconds_per_time_step: int):
    return str(random.randint(1, 990000000))

def generate_j_rjxc(attr_name: str, table_name: str, entity_so_far: dict, table_data_frame_copy: pd.DataFrame, primary_keys: list[str], initial_partition_date: datetime, time_step: int, seconds_per_time_step: int):
    return 'A'

def generate_customer_id(attr_name: str, table_name: str, entity_so_far: dict, table_data_frame_copy: pd.DataFrame, primary_keys: list[str], initial_partition_date: datetime, time_step: int, seconds_per_time_step: int):
    return ("customer_" + str(random.randint(1, 990000000)))

def generate_j_cfgc(attr_name: str, table_name: str, entity_so_far: dict, table_data_frame_copy: pd.DataFrame, primary_keys: list[str], initial_partition_date: datetime, time_step: int, seconds_per_time_step: int):
    return random.choice(['100', '600'])

def generate_j_mrzt_company_short_name(attr_name: str, table_name: str, entity_so_far: dict, table_data_frame_copy: pd.DataFrame, primary_keys: list[str], initial_partition_date: datetime, time_step: int, seconds_per_time_step: int):
    return random.choice([
        'CRUMPET LTD', 'TEA TECH LTD', 'BISCUIT PLC', 'PUDDING SYS LTD', 'CHIPPY NET PLC', 'CUPPA CORP LTD',
        'BANGERS PLC', 'MASH WARE LTD', 'SPOTTED DOG LTD', 'YORKIE TECH PLC', 'JOLLY GOOD LTD', 'PROPER LTD',
        'CHEEKY INC LTD', 'PINT SYS PLC', 'PUB NET LTD', 'SCONE SOFT PLC', 'UNION JACK LTD', 'FISHY TECH LTD',
        'CHIMNEY AI PLC', 'PORRIDGE CO LTD', 'BROLLY NET LTD', 'GUVNOR SYS PLC', 'PIP PIP LTD', 'BLIMEY TECH LTD',
        'DODGY INC PLC', 'KNACKERED LTD', 'BRILL WARE PLC', 'LOO ROLL LTD', 'BARMY NET PLC', 'GINGER NUT LTD',
        'PLONKER AI PLC', 'WELLY CORP LTD', 'RUDDY LTD', 'TOFFEE SYS PLC', 'JAMMY NET LTD', 'CRISP CO PLC',
        'TROLLEY AI LTD', 'BREW SOFT PLC', 'PASTY NET LTD', 'GRAVY TECH PLC', 'BOBBY NET LTD', 'CHUFFED AI PLC',
        'KNOCKERS LTD', 'BARMY CORP PLC', 'WOTCHA LTD', 'DODGY SYS PLC', 'GUV NET LTD', 'BISCUIT AI PLC',
        'PUDDING NET LTD', 'CUPPA LTD', 'SPIFFING PLC', 'BLIGHTY CO LTD', 'GAFFER SYS PLC', 'CHIPPY AI LTD',
        'SARNIE NET PLC', 'BANGERS LTD', 'MASH CORP PLC', 'PINT AI LTD', 'PROPER NET PLC', 'UNION SYS LTD',
        'YORKIE LTD', 'CHEEKY NET PLC', 'PORRIDGE AI LTD', 'BROLLY CORP PLC', 'KNACKERED SYS LTD', 'PLONKER NET PLC',
        'JAMMY LTD', 'CRISP AI PLC', 'TROLLEY NET LTD', 'GRAVY SYS PLC', 'CHUFFED NET LTD', 'WOTCHA AI PLC',
        'SPIFFING LTD', 'BLIGHTY NET PLC', 'GAFFER AI LTD', 'SARNIE SYS PLC', 'PASTY LTD', 'BOBBY CORP PLC',
        'RUDDY NET LTD', 'WELLY AI PLC'
    ])

import hashlib
import re
def strings_to_decimal(*strings):
    # Concatenate all strings
    combined = ''.join(strings)
    
    # Convert to binary representation (as a string of bits)
    binary_str = ''.join(format(ord(char), '08b') for char in combined)
    
    # Convert binary string to decimal integer
    decimal_int = int(binary_str, 2)
    
    return decimal_int

def generate_j_awac(attr_name: str, table_name: str, entity_so_far: dict, table_data_frame_copy: pd.DataFrame, primary_keys: list[str], initial_partition_date: datetime, time_step: int, seconds_per_time_step: int):
    return random.choice(['5'])

def generate_j_duec(attr_name: str, table_name: str, entity_so_far: dict, table_data_frame_copy: pd.DataFrame, primary_keys: list[str], initial_partition_date: datetime, time_step: int, seconds_per_time_step: int):
    """
    Generates a sample code from a fixed set of codes.
    """
    codes = ['EUR']
    return random.choice(codes)

def generate_j_bbci(attr_name: str, table_name: str, entity_so_far: dict, table_data_frame_copy: pd.DataFrame, primary_keys: list[str], initial_partition_date: datetime, time_step: int, seconds_per_time_step: int):
    return fake.name()

def generate_j_mlac(attr_name: str, table_name: str, entity_so_far: dict, table_data_frame_copy: pd.DataFrame, primary_keys: list[str], initial_partition_date: datetime, time_step: int, seconds_per_time_step: int):
    """
    Generates a sample code for j_mlac from a fixed set of values.
    """
    codes = [
        'M', 'A', 'C', 'J', 'E', 'H', 'L', 'F', 'K', 'I', 'G', 'P', 'O', 'D', 'N', 'B'
    ]
    return random.choice(codes)

def generate_j_rdbc(attr_name: str, table_name: str, entity_so_far: dict, table_data_frame_copy: pd.DataFrame, primary_keys: list[str], initial_partition_date: datetime, time_step: int, seconds_per_time_step: int):
    """
    Generates a sample code for j_rdbc from a fixed sequence of values.
    """
    return random.choice(['A', 'B', 'C'])

def generate_j_bcuc(attr_name: str, table_name: str, entity_so_far: dict, table_data_frame_copy: pd.DataFrame, primary_keys: list[str], initial_partition_date: datetime, time_step: int, seconds_per_time_step: int):
    """
    Generates a sample value for cami_j_bcuc from a fixed sequence.
    """
    return random.choice(['F', 'A', 'B', 'C', 'E'])

# ACCOUNT ===============================================================================

def generate_amnt_last_cr_cust(attr_name: str, table_name: str, entity_so_far: dict, table_data_frame_copy: pd.DataFrame, primary_keys: list[str], initial_partition_date: datetime, time_step: int, seconds_per_time_step: int):
    return str(round(random.uniform(1, 1000), 2))

def generate_available_bal(attr_name: str, table_name: str, entity_so_far: dict, table_data_frame_copy: pd.DataFrame, primary_keys: list[str], initial_partition_date: datetime, time_step: int, seconds_per_time_step: int):
    return str(round(random.uniform(-1000, 1000), 2))

def generate_currency(attr_name: str, table_name: str, entity_so_far: dict, table_data_frame_copy: pd.DataFrame, primary_keys: list[str], initial_partition_date: datetime, time_step: int, seconds_per_time_step: int):
    return random.choice(['USD'])

def generate_last_modified_date_kyc(attr_name: str, table_name: str, entity_so_far: dict, table_data_frame_copy: pd.DataFrame, primary_keys: list[str], initial_partition_date: datetime, time_step: int, seconds_per_time_step: int):
    return (datetime.now() - timedelta(days=random.randint(0, 4))).strftime('%d/%m/%Y %H:%M:%S')

def generate_other_account_source_cd(attr_name: str, table_name: str, entity_so_far: dict, table_data_frame_copy: pd.DataFrame, primary_keys: list[str], initial_partition_date: datetime, time_step: int, seconds_per_time_step: int):
    # This field is always 'ACBS'
    return 'ACBS'

def generate_j_cjmc(attr_name: str, table_name: str, entity_so_far: dict, table_data_frame_copy: pd.DataFrame, primary_keys: list[str], initial_partition_date: datetime, time_step: int, seconds_per_time_step: int):
    return random.choice(['100', '500', '600'])


def generate_local_ref_account(attr_name: str, table_name: str, entity_so_far: dict, table_data_frame_copy: pd.DataFrame, primary_keys: list[str], initial_partition_date: datetime, time_step: int, seconds_per_time_step: int):
    return '0!1!2!3!4!5!6!7!8!9!10!11!12!13!14!15!16!17!18!19!301663!21!22!23'

# generate a list of dates in before initial_partition_date in numerical format
def generate_cap_date_charge(attr_name: str, table_name: str, entity_so_far: dict, table_data_frame_copy: pd.DataFrame, primary_keys: list[str], initial_partition_date: datetime, time_step: int, seconds_per_time_step: int):
    # select a random number of dates to add
    dates_n = random.randint(0, 20)
    dates = []
    for _ in range(dates_n):
        if(len(dates) == 0):
            # generate a random date within two months of the previous
            random_date_str = (datetime.strptime(initial_partition_date, '%Y-%m-%d') - timedelta(days=random.randint(1, 60))).strftime('%Y-%m-%d')
            dates.append(random_date_str)
            dates.append('!')
        else:
            last_date = dates[-2]
            random_date_str = (datetime.strptime(last_date, '%Y-%m-%d') - timedelta(days=random.randint(1, 60))).strftime('%Y-%m-%d')
            dates.append(random_date_str)
            dates.append('!')
    # flatten the list
    dates_flattened = ''.join(dates)
    dates_flattened = dates_flattened.replace('-', '')
    return dates_flattened

def generate_acct_credit_int(attr_name: str, table_name: str, entity_so_far: dict, table_data_frame_copy: pd.DataFrame, primary_keys: list[str], initial_partition_date: datetime, time_step: int, seconds_per_time_step: int):
    # select a random number of dates to add
    dates_n = random.randint(0, 20)
    dates = []
    for _ in range(dates_n):
        if(len(dates) == 0):
            # generate a random date within two months of the previous
            random_date_str = (datetime.strptime(initial_partition_date, '%Y-%m-%d') - timedelta(days=random.randint(1, 60))).strftime('%Y-%m-%d')
            dates.append(random_date_str)
            dates.append('!')
        else:
            last_date = dates[-2]
            random_date_str = (datetime.strptime(last_date, '%Y-%m-%d') - timedelta(days=random.randint(1, 60))).strftime('%Y-%m-%d')
            dates.append(random_date_str)
            dates.append('!')
    # reverse the list. This field has ascending dates
    dates.reverse()
    # flatten the list
    dates_flattened = ''.join(dates)
    dates_flattened = dates_flattened.replace('-', '')
    return dates_flattened

def generate_generic_delimited_field(attr_name: str, table_name: str, entity_so_far: dict, table_data_frame_copy: pd.DataFrame, primary_keys: list[str], initial_partition_date: datetime, time_step: int, seconds_per_time_step: int):
    return '0!1!2!3!4!5!6!7!8!9!10!11!12!13!14!15!16!17!18!19!20!21!22!23'

# I have taken a subset of what appears to be random categories. I do not know what this means
def generate_category(attr_name: str, table_name: str, entity_so_far: dict, table_data_frame_copy: pd.DataFrame, primary_keys: list[str], initial_partition_date: datetime, time_step: int, seconds_per_time_step: int):
    return random.choice(['1130', '1041', '18300', '14652', '1035', '1445'])

# generate a random opening date between 60 and 1000 days before initial_partition_date
def generate_opening_date(attr_name: str, table_name: str, entity_so_far: dict, table_data_frame_copy: pd.DataFrame, primary_keys: list[str], initial_partition_date: datetime, time_step: int, seconds_per_time_step: int):
    random_date_str = (datetime.strptime(initial_partition_date, '%Y-%m-%d') - timedelta(days=random.randint(60, 1000))).strftime('%Y-%m-%d').replace('-', '')
    return random_date_str

# Used for 
def generate_closure_date(attr_name: str, table_name: str, entity_so_far: dict, table_data_frame_copy: pd.DataFrame, primary_keys: list[str], initial_partition_date: datetime, time_step: int, seconds_per_time_step: int):
    # Small chance of generating a closure date.
    # A closure date should be between opening date and initial_partition_date
    closure_chance = 0.1
    if(random.uniform(0.0, 1.0) < closure_chance):
        opening_date_str = entity_so_far.get('opening_date')
        opening_date = datetime.strptime(opening_date_str, '%Y%m%d')
        current_date = datetime.strptime(initial_partition_date, '%Y-%m-%d')
        closing_date_str = (opening_date + timedelta(days=random.randint(0, (current_date - opening_date).days))).strftime('%Y%m%d')
        return closing_date_str
    # Otherwise return a string of an empty string
    else:
        return '""'
    
# Should be YES or NO. However, I have not seen the existence of a YES - only empty strings
def generate_allow_netting(attr_name: str, table_name: str, entity_so_far: dict, table_data_frame_copy: pd.DataFrame, primary_keys: list[str], initial_partition_date: datetime, time_step: int, seconds_per_time_step: int):
    return random.choice(['NO', '""', ''])

# I have never seen this value as anything other than false
def generate_edh_ingest_delete_flag(attr_name: str, table_name: str, entity_so_far: dict, table_data_frame_copy: pd.DataFrame, primary_keys: list[str], initial_partition_date: datetime, time_step: int, seconds_per_time_step: int):
    return 'false'




def generate_open_cleared_bal(attr_name: str, table_name: str, entity_so_far: dict, table_data_frame_copy: pd.DataFrame, primary_keys: list[str], initial_partition_date: datetime, time_step: int, seconds_per_time_step: int):
    return str(round(random.uniform(1, 10000), 2))

def generate_open_actual_bal(attr_name: str, table_name: str, entity_so_far: dict, table_data_frame_copy: pd.DataFrame, primary_keys: list[str], initial_partition_date: datetime, time_step: int, seconds_per_time_step: int):
    return entity_so_far.get('open_cleared_bal')
    



# CUSTOMER ==============================================================================================================

# Dependency Group =====
def generate_first_name (attr_name: str, table_name: str, entity_so_far: dict, table_data_frame_copy: pd.DataFrame, primary_keys: list[str], initial_partition_date: datetime, time_step: int, seconds_per_time_step: int):
    gender = entity_so_far.get('gender')
    if(gender == 'M' or gender == 'm' or gender =='Male' or gender == 'male' or gender == 'man'):
        return fake.first_name_male().replace("'", "")
    else:
        return fake.first_name_female().replace("'", "")

def generate_second_name (attr_name: str, table_name: str, entity_so_far: dict, table_data_frame_copy: pd.DataFrame, primary_keys: list[str], initial_partition_date: datetime, time_step: int, seconds_per_time_step: int):
    return fake.last_name()
    
def generate_short_name(attr_name: str, table_name: str, entity_so_far: dict, table_data_frame_copy: pd.DataFrame, primary_keys: list[str], initial_partition_date: datetime, time_step: int, seconds_per_time_step: int):
    return entity_so_far.get('name_1') + ' ' + entity_so_far.get('name_2')

# Dependency Group =====
def generate_gender(attr_name: str, table_name: str, entity_so_far: dict, table_data_frame_copy: pd.DataFrame, primary_keys: list[str], initial_partition_date: datetime, time_step: int, seconds_per_time_step: int):
    return  True, random.choice(['Male', 'Female'])


# Dependency Group =====
def generate_country_code(attr_name: str, table_name: str, entity_so_far: dict, table_data_frame_copy: pd.DataFrame, primary_keys: list[str], initial_partition_date: datetime, time_step: int, seconds_per_time_step: int):
    return random.choice(SUPPORTED_COUNTRY_CODES)

# Generates a city name using a Faker instance localised to entity_so_far.get('country_code']
def generate_city(attr_name: str, table_name: str, entity_so_far: dict, table_data_frame_copy: pd.DataFrame, primary_keys: list[str], initial_partition_date: datetime, time_step: int, seconds_per_time_step: int):
    country_code = entity_so_far.get('country_code')
    localized_fake = _get_localised_faker(country_code)
    return localized_fake.city()

# Generates a postcode using a Faker instance localised to entity_so_far.get('country_code'] (generated after city, per depends_on config)
def generate_postcode(attr_name: str, table_name: str, entity_so_far: dict, table_data_frame_copy: pd.DataFrame, primary_keys: list[str], initial_partition_date: datetime, time_step: int, seconds_per_time_step: int):
    country_code = entity_so_far.get('country_code')
    localized_fake = _get_localised_faker(country_code)
    return localized_fake.postcode()

def generate_street(attr_name: str, table_name: str, entity_so_far: dict, table_data_frame_copy: pd.DataFrame, primary_keys: list[str], initial_partition_date: datetime, time_step: int, seconds_per_time_step: int):
    country_code = entity_so_far.get('country_code')
    localized_fake = _get_localised_faker(country_code)
    return localized_fake.street_name()

def generate_address(attr_name: str, table_name: str, entity_so_far: dict, table_data_frame_copy: pd.DataFrame, primary_keys: list[str], initial_partition_date: datetime, time_step: int, seconds_per_time_step: int):
    return (entity_so_far.get('street') + ' ' + entity_so_far.get('post_code') + ' ' + entity_so_far.get('country')).replace("'", "")
   
# Dependency Group =====








# MM_MONEY_MARKET ===

def generate_principal(attr_name: str, table_name: str, entity_so_far: dict, table_data_frame_copy: pd.DataFrame, primary_keys: list[str], initial_partition_date: datetime, time_step: int, seconds_per_time_step: int):
    return str(round(random.uniform(100, 10000), 2))


def generate_deal_date (attr_name: str, table_name: str, entity_so_far: dict, table_data_frame_copy: pd.DataFrame, primary_keys: list[str], initial_partition_date: datetime, time_step: int, seconds_per_time_step: int):
    # generate a random date before edh_partition_dt
    random_date_str = (datetime.strptime(initial_partition_date, '%Y-%m-%d') - timedelta(days=random.randint(60, 5000))).strftime('%Y-%m-%d').replace('-', '')
    return random_date_str

def generate_rollover_date (attr_name: str, table_name: str, entity_so_far: dict, table_data_frame_copy: pd.DataFrame, primary_keys: list[str], initial_partition_date: datetime, time_step: int, seconds_per_time_step: int):
    random_date_str = (datetime.strptime(initial_partition_date, '%Y-%m-%d') - timedelta(days=random.randint(60, 5000))).strftime('%Y-%m-%d').replace('-', '')
    return random_date_str

# generate a YYYYMMDD date after deal_date but before edh_partition_dt
def generate_value_date(attr_name: str, table_name: str, entity_so_far: dict, table_data_frame_copy: pd.DataFrame, primary_keys: list[str], initial_partition_date: datetime, time_step: int, seconds_per_time_step: int):
    deal_date_str = str(entity_so_far.get('deal_date'))
    deal_date = datetime.strptime(deal_date_str, '%Y%m%d')
    current_date = datetime.strptime(initial_partition_date, '%Y-%m-%d')
    closing_date_str = (deal_date + timedelta(days=random.randint(0, (current_date - deal_date).days))).strftime('%Y%m%d')
    return closing_date_str


# generate a YYYYMMDD date after value_date
def generate_maturity_date(attr_name: str, table_name: str, entity_so_far: dict, table_data_frame_copy: pd.DataFrame, primary_keys: list[str], initial_partition_date: datetime, time_step: int, seconds_per_time_step: int):
    value_date_str = str(entity_so_far.get('value_date'))
    value_date = datetime.strptime(value_date_str, '%Y%m%d')
    maturity_date_str = (value_date + timedelta(days=random.randint(0, 1000))).strftime('%Y%m%d')
    return maturity_date_str


def generate_interest_rate(attr_name: str, table_name: str, entity_so_far: dict, table_data_frame_copy: pd.DataFrame, primary_keys: list[str], initial_partition_date: datetime, time_step: int, seconds_per_time_step: int):
    return str(round(random.uniform(0, 4), 2))

def generate_accural_param(attr_name: str, table_name: str, entity_so_far: dict, table_data_frame_copy: pd.DataFrame, primary_keys: list[str], initial_partition_date: datetime, time_step: int, seconds_per_time_step: int):
    return 'FIRST'

def generate_tot_interest_amt(attr_name: str, table_name: str, entity_so_far: dict, table_data_frame_copy: pd.DataFrame, primary_keys: list[str], initial_partition_date: datetime, time_step: int, seconds_per_time_step: int):
    return str(round(random.uniform(100, 10000), 2))

def generate_mis_interest_rate(attr_name: str, table_name: str, entity_so_far: dict, table_data_frame_copy: pd.DataFrame, primary_keys: list[str], initial_partition_date: datetime, time_step: int, seconds_per_time_step: int):
    return str(round(random.uniform(3, 15), 2))

def generate_auto_rollover(attr_name: str, table_name: str, entity_so_far: dict, table_data_frame_copy: pd.DataFrame, primary_keys: list[str], initial_partition_date: datetime, time_step: int, seconds_per_time_step: int):
    return random.choice(['Y', 'N'])

def generate_int_period_start(attr_name: str, table_name: str, entity_so_far: dict, table_data_frame_copy: pd.DataFrame, primary_keys: list[str], initial_partition_date: datetime, time_step: int, seconds_per_time_step: int):
    return entity_so_far.get('value_date')
    
def generate_int_period_end(attr_name: str, table_name: str, entity_so_far: dict, table_data_frame_copy: pd.DataFrame, primary_keys: list[str], initial_partition_date: datetime, time_step: int, seconds_per_time_step: int):
    int_period_start_str = str(entity_so_far.get('int_period_start'))
    int_period_start = datetime.strptime(int_period_start_str, '%Y%m%d')
    int_period_end_str = (int_period_start + timedelta(days=random.randint(100, 4000))).strftime('%Y%m%d')
    return int_period_end_str


def generate_category(attr_name: str, table_name: str, entity_so_far: dict, table_data_frame_copy: pd.DataFrame, primary_keys: list[str], initial_partition_date: datetime, time_step: int, seconds_per_time_step: int):
    cat_string = '210' + random.choice(['75', '21', '01', '22', '79', '23', '25', '24', '26', '50'])
    return cat_string


def generate_int_rate_type(attr_name: str, table_name: str, entity_so_far: dict, table_data_frame_copy: pd.DataFrame, primary_keys: list[str], initial_partition_date: datetime, time_step: int, seconds_per_time_step: int):
    return '1'

def generate_interest_basis(attr_name: str, table_name: str, entity_so_far: dict, table_data_frame_copy: pd.DataFrame, primary_keys: list[str], initial_partition_date: datetime, time_step: int, seconds_per_time_step: int):
    return random.choice(['B', 'E'])


def generate_dept_code(attr_name: str, table_name: str, entity_so_far: dict, table_data_frame_copy: pd.DataFrame, primary_keys: list[str], initial_partition_date: datetime, time_step: int, seconds_per_time_step: int):
    return random.randint(1, 99)

# STMT_ENTRY ---------------------


def generate_value_date_stmt_entry(attr_name: str, table_name: str, entity_so_far: dict, table_data_frame_copy: pd.DataFrame, primary_keys: list[str], initial_partition_date: datetime, time_step: int, seconds_per_time_step: int):
    # generate a random date 1-3 days before initial_partition_date
    random_date_str = (datetime.strptime(initial_partition_date, '%Y-%m-%d') - timedelta(days=random.randint(1, 3))).strftime('%Y-%m-%d').replace('-', '')
    return random_date_str

def generate_processing_date(attr_name: str, table_name: str, entity_so_far: dict, table_data_frame_copy: pd.DataFrame, primary_keys: list[str], initial_partition_date: datetime, time_step: int, seconds_per_time_step: int):
    value_date_str = str(entity_so_far.get('value_date'))
    value_date = datetime.strptime(value_date_str, '%Y%m%d')
    current_date = datetime.strptime(initial_partition_date, '%Y-%m-%d')
    closing_date_str = (value_date + timedelta(days=random.randint(0, (current_date - value_date).days))).strftime('%Y%m%d')
    return closing_date_str


def generate_amount_lcy(attr_name: str, table_name: str, entity_so_far: dict, table_data_frame_copy: pd.DataFrame, primary_keys: list[str], initial_partition_date: datetime, time_step: int, seconds_per_time_step: int):
    return str(round(random.uniform(-1000, 1000), 2))


def generate_exchange_rate(attr_name: str, table_name: str, entity_so_far: dict, table_data_frame_copy: pd.DataFrame, primary_keys: list[str], initial_partition_date: datetime, time_step: int, seconds_per_time_step: int):
    currency = str(entity_so_far.get('currency'))
    if(not currency == 'GBP'):
        return str(round(random.uniform(1, 2), 2))
    else:
        return '""'
       

# return an amount x exchange_rate when currency field is not GBP
# return "''" when currency field is GBP
def generate_amount_fcy(attr_name: str, table_name: str, entity_so_far: dict, table_data_frame_copy: pd.DataFrame, primary_keys: list[str], initial_partition_date: datetime, time_step: int, seconds_per_time_step: int):
    currency = str(entity_so_far.get('currency'))
    if(not currency == 'GBP'):
        amount = float(str(entity_so_far.get('amount_lcy')))
        exchange_rate = float(str(entity_so_far.get('exchange_rate')))
        return str(  round((amount * exchange_rate), 2)  )
    else:
        return '""'
        

# CATEG_ENTRY

def generate_value_date_categ_entry(attr_name: str, table_name: str, entity_so_far: dict, table_data_frame_copy: pd.DataFrame, primary_keys: list[str], initial_partition_date: datetime, time_step: int, seconds_per_time_step: int):
    # generate a random date 1-3 days before initial_partition_date
    random_date_str = (datetime.strptime(initial_partition_date, '%Y-%m-%d') - timedelta(days=random.randint(1, 3))).strftime('%Y-%m-%d').replace('-', '')
    return random_date_str

def generate_processing_date_categ_entry(attr_name: str, table_name: str, entity_so_far: dict, table_data_frame_copy: pd.DataFrame, primary_keys: list[str], initial_partition_date: datetime, time_step: int, seconds_per_time_step: int):
    random_date_str = (datetime.strptime(initial_partition_date, '%Y-%m-%d') - timedelta(days=random.randint(1, 1))).strftime('%Y-%m-%d').replace('-', '')
    return random_date_str


# LMM_ACCOUNT_BALANCES ---------------------

def generate_stmt_no(attr_name: str, table_name: str, entity_so_far: dict, table_data_frame_copy: pd.DataFrame, primary_keys: list[str], initial_partition_date: datetime, time_step: int, seconds_per_time_step: int):
    count = random.randint(1, 10)
    random_numbers = [str(random.randint(180000000, 190000000)) + '.07' for _ in range(count)]
    return '!'.join(random_numbers)



# CURRENCY ==============================================================================================================

def generate_mid_reval_rate(attr_name: str, table_name: str, entity_so_far: dict, table_data_frame_copy: pd.DataFrame, primary_keys: list[str], initial_partition_date: datetime, time_step: int, seconds_per_time_step: int):
    currency_code = str(entity_so_far.get('id'))
    ['USD','EUR', 'NZD', 'AUD', 'CAD', 'JPY', 'NOK', 'ZAR', 'HKD', 'DKK']
    try:
        fx_rate = int(FX_RATES.loc[FX_RATES["to_currency_code"] == entity_so_far.get('currency_code'), "fx_rate"].iloc[0])
    except:
        # Fall back to GBP
        fx_rate = 1

    amount_gbp = np.random.randint(1000,100000)
    return amount_gbp * fx_rate

    


def generate_date_time_currency(attr_name: str, table_name: str, entity_so_far: dict, table_data_frame_copy: pd.DataFrame, primary_keys: list[str], initial_partition_date: datetime, time_step: int, seconds_per_time_step: int):
    # Applicable for base loads
    edh_partition_dt_str = str(entity_so_far.get('edh_partition_dt'))
    
    date = datetime.strptime(edh_partition_dt_str, '%Y-%m-%d') - timedelta(days=random.randint(0, 0))

    # Generate a random time within the adjusted day
    date_time = date.replace(hour=random.randint(0, 23), minute=random.randint(0, 59)).strftime('%y%m%d%H%M')
    return date_time

    # Applicable for base loads where edh_partition_dt is not present

# GENERIC FUNCTIONS: =============================================
# edh_partition_dt should be independent from source extract to test decoupling
# ingestion yyyy/mm/dd based on today's timestamp
# ---------------------------------------------------------------------------

def generate_edh_partition_dt(attr_name: str, table_name: str, entity_so_far: dict, table_data_frame_copy: pd.DataFrame, primary_keys: list[str], initial_partition_date: datetime, time_step: int, seconds_per_time_step: int):
    return initial_partition_date

def generate_edh_source_extract_ts(attr_name: str, table_name: str, entity_so_far: dict, table_data_frame_copy: pd.DataFrame, primary_keys: list[str], initial_partition_date: datetime, time_step: int, seconds_per_time_step: int):
    return global_src_extract_ts

def generate_ingestion_year(attr_name: str, table_name: str, entity_so_far: dict, table_data_frame_copy: pd.DataFrame, primary_keys: list[str], initial_partition_date: datetime, time_step: int, seconds_per_time_step: int):
    # check to see if edh_partition_dt. If it does, extract year from it
    year_regex = r"\d{4}"
    year_match = re.search(year_regex, entity_so_far.get('edh_partition_dt'))
    year = year_match.group()
    return year

def generate_ingestion_month(attr_name: str, table_name: str, entity_so_far: dict, table_data_frame_copy: pd.DataFrame, primary_keys: list[str], initial_partition_date: datetime, time_step: int, seconds_per_time_step: int):
    # check to see if edh_partition_dt. If it does, extract year from it
    month_regex = r"\d{4}-(\d{2})-\d{2}"
    month_match = re.search(month_regex, entity_so_far.get('edh_partition_dt'))
    month = month_match.group(1)
    # remove leading zeroes
    month = int(month)
    return month

def generate_ingestion_day(attr_name: str, table_name: str, entity_so_far: dict, table_data_frame_copy: pd.DataFrame, primary_keys: list[str], initial_partition_date: datetime, time_step: int, seconds_per_time_step: int):
    # check to see if edh_partition_dt. If it does, extract year from it
    day_regex =  r"\d{4}-\d{2}-(\d{2})"
    day_match = re.search(day_regex, entity_so_far.get('edh_partition_dt'))
    day = day_match.group(1)
    # remove leading zeroes
    day = int(day)
    return day



# ------------------------


def generate_date_yyyymmdd(attr_name: str, table_name: str, entity_so_far: dict, table_data_frame_copy: pd.DataFrame, primary_keys: list[str], initial_partition_date: datetime, time_step: int, seconds_per_time_step: int):
    simulated_date = initial_partition_date - timedelta(seconds=time_step*seconds_per_time_step)
    return simulated_date.strftime('%Y%m%d')
    
def generate_j_crpi_profit_centre_ref(attr_name: str, table_name: str, entity_so_far: dict, table_data_frame_copy: pd.DataFrame, primary_keys: list[str], initial_partition_date: datetime, time_step: int, seconds_per_time_step: int):
    return random.choice(['FAF', 'FAB', 'FAR'])


#------------------------------------------------------------------------------------------------------------------------------
# AUDIT COLUMN GENERATOR FUNCTIONS - called by add_audit_cols.py once per audit column per file (not once
# per row), resolved the same way as a regular field's default_function: the schema's default_function if
# set, else the generate_<field_name> naming convention (e.g. "bts_batch_dt" -> generate_bts_batch_dt).

def template_audit_col_gen_func(field_name: str, table_name: str, df: pd.DataFrame, simulated_datetime: datetime, file_type: str) -> Any:
    """
    Parameters:
        - field_name (str): Name of the audit column to be generated
        - table_name (str): Name of the table this file belongs to
        - df (pd.DataFrame): The file's already-generated (non-audit) column values - one row per record
        - simulated_datetime (datetime): The checkpoint's simulated datetime (from the folder name it was saved under)
        - file_type (str): "positive" / "negative" (a delta file) or "snapshot"
    Returns:
        Either a single value (broadcast to every row) or a list/array of len(df) values, one per row
    """
    pass

def generate_delta_flag(field_name: str, table_name: str, df: pd.DataFrame, simulated_datetime: datetime, file_type: str):
    # 'I' for a positive delta (insert), 'D' for a negative delta (delete) - blank for a snapshot, since
    # that's the table's full current state rather than a change.
    return {"positive": "I", "negative": "D"}.get(file_type)

def generate_bts_ingestion_ts(field_name: str, table_name: str, df: pd.DataFrame, simulated_datetime: datetime, file_type: str):
    # The real wall-clock time this file was processed at, not the simulated time - BigQuery TIMESTAMP
    # literals require "YYYY-MM-DD HH:MM:SS[ time zone]", e.g. "2026-05-08 23:57:56 UTC".
    return datetime.now().strftime('%Y-%m-%d %H:%M:%S UTC')

def generate_bts_ingest_map(field_name: str, table_name: str, df: pd.DataFrame, simulated_datetime: datetime, file_type: str):
    return [f"bts_ingest_map_{i}" for i in range(len(df))]

def generate_bts_batch_dt(field_name: str, table_name: str, df: pd.DataFrame, simulated_datetime: datetime, file_type: str):
    # BigQuery DATE literals require "YYYY-MM-DD", e.g. "2026-05-08".
    return simulated_datetime.strftime('%Y-%m-%d')

def generate_bts_flag(field_name: str, table_name: str, df: pd.DataFrame, simulated_datetime: datetime, file_type: str):
    return [random.choice([True, False]) for _ in range(len(df))]




# ============== MACROS =========== #


def macro_update_j_clla_balance_from_j_cldt(action_name: str, entities_already_selected: tuple, tables_by_ref: dict, tables_by_value: dict, initial_partition_date: datetime, time_step: int, seconds_per_time_step: int) -> None:
    # "Most recent j_cldt record" = the one this action just created - entities_already_selected already
    # hands us that exact row, so there's no need to guess at it via dataframe/insertion order.
    j_cldt_entity = dict(entities_already_selected).get("j_cldt")
    if j_cldt_entity is None:
        return  # defensive - this post_action only makes sense when j_cldt was actually created this action

    j_cldt_record = dict(j_cldt_entity)
    j_rjoi = j_cldt_record["j_rjoi"]
    j_rjpi = j_cldt_record["j_rjpi"]
    transaction_amount = float(j_cldt_record["j_rjy_"])


    print(f"[macro_update_j_clla_balance_from_j_cldt] decrementing j_clla (j_meyi={j_rjoi}, j_mezi={j_rjpi}) by {transaction_amount}", flush=True)
    # each wildcard ? is substituted in-order by variables in the 2nd parameter list
    run_sql(tables_by_ref, (
        "UPDATE j_clla SET j_cjmc = CAST(CAST(j_cjmc AS DOUBLE) - ? AS VARCHAR) WHERE j_meyi = ? AND j_mezi = ?",
        [transaction_amount, j_rjoi, j_rjpi],
    ))