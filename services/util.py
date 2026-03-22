import os


def get_data_path():
    path = get_env("NEXTBRIDGE_DATA_PATH") or get_env("nextbridge_data_path")
    return path.strip() if path else "data"


def get_env(env: str):
    return os.environ.get(env)
