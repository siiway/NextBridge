# services/utils.py

import os

def get_data_path():
    path = get_env('BRIDGE_DATA_PATH')
    return path.strip() if path else 'data'

def get_env(env: str):
    return os.environ.get(env)

