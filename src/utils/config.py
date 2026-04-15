import yaml
from typing import Any, Dict
from pathlib import Path


def load_config(config_path: str) -> Dict[str, Any]:
    config_file = Path(config_path)
    # Fail early with a clear error when config path is wrong.
    if not config_file.exists():
        raise FileNotFoundError(f"Configuration file was not found: {config_file}")

    with config_file.open("r", encoding="utf-8") as config_stream:
        loaded = yaml.safe_load(config_stream) or {}

    # Enforce top-level mapping shape for predictable key lookups.
    if not isinstance(loaded, dict):
        raise ValueError("Configuration file must contain a mapping at the top level.")

    return loaded


def save_config(config_path: str, config_data: Dict[str, Any]) -> None:
    config_file = Path(config_path)
    config_file.parent.mkdir(parents=True, exist_ok=True)
    with config_file.open("w", encoding="utf-8") as config_stream:
        yaml.safe_dump(config_data, config_stream, sort_keys=False)
