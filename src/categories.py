"""
FoodSight — Category Definitions
Reads src/reference/categories.json, the single place where every column with a fixed
set of values is defined.

Scrapers, cleaners, the profiler and the validator take their value lists
from here instead of keeping their own copy. To add, rename or remove a
value, edit categories.json only.

Columns are named "table.column", for example "price_range.tier".

The validator checks every list; the database has no CHECK copy of any of
them, so changing a list here needs no migration.
"""

import json
from functools import lru_cache
from pathlib import Path

CATEGORIES_PATH = Path(__file__).resolve().parent / "reference" / "categories.json"


@lru_cache(maxsize=None)
def load_categories():
    """Return {"table.column": definition} for every categorised column."""
    with open(CATEGORIES_PATH, "r", encoding="utf-8") as f:
        return json.load(f)["columns"]


def get_column(column):
    """Return the full definition of one column (meaning, pick, values, ...)."""
    try:
        return load_categories()[column]
    except KeyError:
        raise KeyError(f"'{column}' is not defined in {CATEGORIES_PATH.name}") from None


def allowed_values(column):
    """Return the allowed values of a column, in the order written in the file."""
    return list(get_column(column)["values"])


def value_definitions(column):
    """Return {value: one-line definition} for a column."""
    return {
        value: detail["definition"] if isinstance(detail, dict) else detail
        for value, detail in get_column(column)["values"].items()
    }
