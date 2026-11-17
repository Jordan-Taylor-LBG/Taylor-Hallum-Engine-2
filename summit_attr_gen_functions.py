from datetime import datetime, timedelta
import random
import uuid

from acbsuk_attr_gen_functions import *


def generate_summit_asset_id(attr_name, table_name, entity_so_far, table_data_frame_copy, primary_keys, initial_partition_date, time_step, seconds_per_time_step):
    return f'SUMMIT-{uuid.uuid4().hex.upper()}'


def generate_maturity_from_effdate(attr_name, table_name, entity_so_far, table_data_frame_copy, primary_keys, initial_partition_date, time_step, seconds_per_time_step):
    effective_date = datetime.strptime(str(entity_so_far['effdate']), '%Y%m%d')
    return (effective_date + timedelta(days=random.randint(30, 1000))).strftime('%Y%m%d')


def generate_summit_effective_date(attr_name, table_name, entity_so_far, table_data_frame_copy, primary_keys, initial_partition_date, time_step, seconds_per_time_step):
    if isinstance(initial_partition_date, datetime):
        current_date = initial_partition_date
    else:
        current_date = datetime.strptime(str(initial_partition_date), '%Y-%m-%d')
    return (current_date - timedelta(days=random.randint(60, 5000))).strftime('%Y%m%d')