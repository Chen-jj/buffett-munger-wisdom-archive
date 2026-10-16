"""Deterministic JSON serialization used by translation domain identities."""

from __future__ import annotations

from enum import Enum
import hashlib
import json
from typing import Any, Mapping, Sequence


def _json_value(value: object) -> Any:
    if hasattr(value, "to_dict"):
        return _json_value(value.to_dict())  # type: ignore[union-attr]
    if isinstance(value, Enum):
        return value.value
    if isinstance(value, Mapping):
        if not all(isinstance(key, str) for key in value):
            raise ValueError("canonical JSON object keys must be strings")
        return {key: _json_value(item) for key, item in value.items()}
    if isinstance(value, Sequence) and not isinstance(
        value, (str, bytes, bytearray)
    ):
        return [_json_value(item) for item in value]
    if value is None or isinstance(value, (str, int, float, bool)):
        return value
    raise ValueError(f"value is not JSON serializable: {type(value).__name__}")


def canonical_json_bytes(value: object) -> bytes:
    """Serialize a JSON value with stable mapping order and no extra whitespace."""

    try:
        text = json.dumps(
            _json_value(value),
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
            allow_nan=False,
        )
    except (TypeError, ValueError) as error:
        raise ValueError("value must contain only finite JSON values") from error
    return text.encode("utf-8")


def canonical_json_sha256(value: object) -> str:
    """Return the SHA-256 digest of a canonical JSON value."""

    return hashlib.sha256(canonical_json_bytes(value)).hexdigest()
