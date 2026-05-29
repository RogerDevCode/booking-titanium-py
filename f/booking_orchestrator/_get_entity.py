# /// script
# requires-python = ">=3.13"
# dependencies = []
# ///
from __future__ import annotations

from typing import Any

"""
PRE-FLIGHT
Mission          : Simple entity extractor helper.
DB Tables        : NONE
Concurrency Risk : NO
GCal Calls       : NO
Idempotency Key  : NO
RLS Tenant ID    : NO
Zod Schemas      : NO
"""


def get_entity(entities: dict[str, Any], key: str) -> str | None:
    """Extracts a value from the entities dictionary, returning None if not found."""
    val = entities.get(key)
    if isinstance(val, str) and val:
        return val.strip() or None
    return None
