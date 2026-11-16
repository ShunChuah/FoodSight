import json
from functools import lru_cache
from pathlib import Path


@lru_cache(maxsize=1)
def load_response_templates() -> dict:
    path = Path(__file__).resolve().parents[2] / "knowledge_graph" / "response_templates.json"
    return json.loads(path.read_text(encoding="utf-8"))


def response(key: str, **values: object) -> str:
    section, name = key.split(".", 1)
    return load_response_templates()[section][name].format(**values)

