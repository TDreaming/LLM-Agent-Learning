import os

def get_model_name() -> str:
    return os.getenv("MODEL_NAME") or ""
