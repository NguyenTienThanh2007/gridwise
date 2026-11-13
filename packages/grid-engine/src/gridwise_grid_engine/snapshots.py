"""Snapshots: a grid as canonical text, and back.

A snapshot is the exact input of a simulation. Its text is ``canonical_grid_text``, so its
SHA-256 is the grid's ``grid_hash``: the hash identifies the content, and anyone holding the
text can check it. Stored snapshots are never changed; a reader verifies the hash before
using one, so a damaged snapshot is refused rather than solved.

Pure Python, no numerical library.
"""

import json
from typing import Any

from gridwise_grid_engine.hashing import GRID_DOCUMENT_SCHEMA, canonical_grid_text, sha256_hex
from gridwise_grid_engine.model import (
    Bus,
    ExternalGrid,
    Generator,
    GridModel,
    Line,
    Load,
    Switch,
    TapChanger,
    Transformer,
)


class SnapshotError(ValueError):
    """The text is not a snapshot this engine can read, or does not match its hash."""


def snapshot_text(grid: GridModel) -> str:
    return canonical_grid_text(grid)


def snapshot_hash(text: str) -> str:
    return sha256_hex(text)


_TAP_INTEGERS = ("neutral_position", "min_position", "max_position", "position")


def _tap(document: dict[str, Any] | None) -> TapChanger | None:
    if document is None:
        return None
    values = dict(document)
    # The canonical form writes every number as a decimal; tap positions are integers.
    for name in _TAP_INTEGERS:
        value = values[name]
        if not (isinstance(value, (int, float)) and float(value).is_integer()):
            raise SnapshotError(f"tap {name} is not an integer")
        values[name] = int(value)
    return TapChanger(**values)


def grid_from_snapshot(text: str, *, expected_hash: str | None = None) -> GridModel:
    """Rebuild the grid a snapshot describes.

    With ``expected_hash``, the text's hash is checked first and a mismatch is refused.
    """
    if expected_hash is not None and snapshot_hash(text) != expected_hash:
        raise SnapshotError("the snapshot does not match its hash")
    try:
        document = json.loads(text)
    except json.JSONDecodeError as error:
        raise SnapshotError("the snapshot is not JSON") from error
    if not isinstance(document, dict) or document.get("schema") != GRID_DOCUMENT_SCHEMA:
        raise SnapshotError(f"the snapshot is not a {GRID_DOCUMENT_SCHEMA} document")
    grid = document["grid"]
    try:
        model = GridModel(
            name=grid["name"],
            frequency_hz=grid["frequency_hz"],
            buses=tuple(Bus(**item) for item in grid["buses"]),
            lines=tuple(Line(**item) for item in grid["lines"]),
            transformers=tuple(
                Transformer(**{**item, "tap": _tap(item["tap"])}) for item in grid["transformers"]
            ),
            loads=tuple(Load(**item) for item in grid["loads"]),
            generators=tuple(Generator(**item) for item in grid["generators"]),
            external_grids=tuple(ExternalGrid(**item) for item in grid["external_grids"]),
            switches=tuple(Switch(**item) for item in grid["switches"]),
        )
    except (KeyError, TypeError) as error:
        raise SnapshotError("the snapshot does not describe a grid") from error
    # The text must be the canonical form of what it describes, byte for byte.
    if canonical_grid_text(model) != text:
        raise SnapshotError("the snapshot is not in canonical form")
    return model
