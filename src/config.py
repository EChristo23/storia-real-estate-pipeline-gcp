import tomllib
from pathlib import Path

_CONFIG_PATH = Path(__file__).parent.parent / "config" / "pipeline.toml"


def load() -> dict:
    with open(_CONFIG_PATH, "rb") as f:
        return tomllib.load(f)
