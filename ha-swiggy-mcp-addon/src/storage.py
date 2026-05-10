"""Encrypted token storage in /data/tokens.json (add-on persistent volume)."""
import json
import os
from pathlib import Path

DATA_PATH = Path("/data/tokens.json")


def load_tokens() -> dict:
    if DATA_PATH.exists():
        try:
            return json.loads(DATA_PATH.read_text())
        except Exception:
            pass
    return {}


def save_tokens(data: dict) -> None:
    DATA_PATH.write_text(json.dumps(data, indent=2))


def clear_tokens() -> None:
    if DATA_PATH.exists():
        DATA_PATH.unlink()
