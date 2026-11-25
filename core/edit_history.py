"""Non-destructive edit state with undo/redo.

An :class:`EditState` never holds pixels; it stores corners, rotation and
enhancement parameters. The original image stays untouched in memory/on disk
and every preview is recomputed from that state.
"""

from __future__ import annotations

import copy
from dataclasses import dataclass, field
from typing import Callable

import numpy as np

from . import enhancement, perspective


@dataclass(slots=True)
class EditState:
    corners: list[list[float]]
    rotation: int = 0
    auto_orientation: bool = True
    enhancement: dict = field(default_factory=lambda: dict(enhancement.DEFAULT_PARAMS))
    interpolation: str = "Cubic"

    def clone(self) -> "EditState":
        return EditState(
            corners=[list(point) for point in self.corners],
            rotation=self.rotation,
            auto_orientation=self.auto_orientation,
            enhancement=dict(self.enhancement),
            interpolation=self.interpolation,
        )

    def quad(self) -> np.ndarray:
        return perspective.as_quad(self.corners)

    def set_corners(self, points) -> None:
        self.corners = perspective.quad_to_list(points)

    def to_dict(self) -> dict:
        return {
            "corners": [list(point) for point in self.corners],
            "rotation": self.rotation,
            "auto_orientation": self.auto_orientation,
            "enhancement": dict(self.enhancement),
            "interpolation": self.interpolation,
        }

    @classmethod
    def from_dict(cls, data: dict, fallback_size: tuple[int, int] | None = None) -> "EditState":
        data = data if isinstance(data, dict) else {}
        corners = data.get("corners") or []
        if not isinstance(corners, list) or len(corners) != 4:
            corners = []
        try:
            corners = [list(map(float, point)) for point in corners]
        except (TypeError, ValueError):
            corners = []
        if len(corners) != 4:
            if fallback_size:
                width, height = fallback_size
                corners = [[0.0, 0.0], [float(width - 1), 0.0],
                           [float(width - 1), float(height - 1)], [0.0, float(height - 1)]]
            else:
                corners = [[0.0, 0.0], [1.0, 0.0], [1.0, 1.0], [0.0, 1.0]]
        enhancement_params = data.get("enhancement")
        if not isinstance(enhancement_params, dict):
            enhancement_params = None
        try:
            rotation = int(data.get("rotation", 0) or 0)
        except (TypeError, ValueError):
            rotation = 0
        return cls(
            corners=corners,
            rotation=rotation,
            auto_orientation=bool(data.get("auto_orientation", True)),
            enhancement=enhancement.normalize_params(enhancement_params),
            interpolation=str(data.get("interpolation", "Cubic")),
        )


class UndoStack:
    """Simple snapshot stack with labels and a change callback."""

    def __init__(self, initial: EditState, limit: int = 60) -> None:
        self._states: list[tuple[EditState, str]] = [(initial.clone(), "Initial")]
        self._index = 0
        self._limit = limit
        self._listeners: list[Callable[[], None]] = []
        self._suspended = 0

    # ------------------------------------------------------------- listeners
    def add_listener(self, callback: Callable[[], None]) -> None:
        self._listeners.append(callback)

    def _notify(self) -> None:
        for callback in self._listeners:
            callback()

    # ---------------------------------------------------------------- access
    @property
    def current(self) -> EditState:
        return self._states[self._index][0]

    @property
    def can_undo(self) -> bool:
        return self._index > 0

    @property
    def can_redo(self) -> bool:
        return self._index < len(self._states) - 1

    @property
    def undo_label(self) -> str:
        return self._states[self._index][1] if self.can_undo else ""

    @property
    def redo_label(self) -> str:
        return self._states[self._index + 1][1] if self.can_redo else ""

    def labels(self) -> list[str]:
        return [label for _, label in self._states]

    # --------------------------------------------------------------- changes
    def suspend(self, label: str = "Edit"):
        """Context manager that coalesces many changes into one snapshot.

        Mutations made while suspended do not create individual undo entries;
        on successful exit a single snapshot is pushed (with ``label``) if the
        state changed inside the block. If the block raises, no snapshot is
        pushed and the state keeps whatever value it had.
        """

        stack = self

        class _Suspension:
            def __enter__(self_inner):
                stack._suspended += 1
                self_inner._snapshot = stack.current.clone()
                return stack.current

            def __exit__(self_inner, exc_type, exc, tb):
                changed = stack.current.to_dict() != self_inner._snapshot.to_dict()
                stack._suspended = max(0, stack._suspended - 1)
                if exc_type is None and changed:
                    stack.push(label, stack.current)
                return False

        return _Suspension()

    def push(self, label: str, state: EditState | None = None) -> None:
        if self._suspended:
            return
        snapshot = (state or self.current).clone()
        # Duplicate detection must happen before the redo branch is truncated,
        # otherwise a no-op push after an undo silently destroys redo history.
        if self._states and self.current.to_dict() == snapshot.to_dict():
            return
        if self._index < len(self._states) - 1:
            self._states = self._states[: self._index + 1]
        self._states.append((snapshot, label))
        if len(self._states) > self._limit:
            self._states.pop(0)
        self._index = len(self._states) - 1
        self._notify()

    def replace_current(self, state: EditState) -> None:
        """Update the working state without creating an undo entry."""

        self._states[self._index] = (state.clone(), self._states[self._index][1])
        self._notify()

    def undo(self) -> EditState | None:
        if not self.can_undo:
            return None
        self._index -= 1
        self._notify()
        return self.current.clone()

    def redo(self) -> EditState | None:
        if not self.can_redo:
            return None
        self._index += 1
        self._notify()
        return self.current.clone()

    def reset(self, state: EditState, label: str = "Reset") -> None:
        self._states = [(state.clone(), label)]
        self._index = 0
        self._notify()

    def to_dict(self) -> dict:
        return {
            "states": [state.to_dict() for state, _ in self._states],
            "labels": [label for _, label in self._states],
            "index": self._index,
        }

    @classmethod
    def from_dict(cls, data: dict) -> "UndoStack":
        states = data.get("states") or []
        labels = data.get("labels") or []
        if not states:
            raise ValueError("Empty undo history")
        try:
            first = EditState.from_dict(states[0])
        except (TypeError, ValueError, AttributeError) as exc:
            raise ValueError("Corrupt undo history") from exc
        stack = cls(first)
        rebuilt: list[tuple[EditState, str]] = []
        for i, state in enumerate(states):
            if not isinstance(state, dict):
                continue  # corrupt (non-object) entries are dropped
            try:
                rebuilt.append(
                    (EditState.from_dict(state), labels[i] if i < len(labels) else f"Step {i}")
                )
            except (TypeError, ValueError, AttributeError):
                continue  # drop corrupt entries instead of failing the restore
        if not rebuilt:
            raise ValueError("Corrupt undo history")
        stack._states = rebuilt
        try:
            index = int(data.get("index", len(rebuilt) - 1))
        except (TypeError, ValueError):
            index = len(rebuilt) - 1
        stack._index = max(0, min(index, len(rebuilt) - 1))
        return stack


def corners_equal(a, b, tolerance: float = 0.5) -> bool:
    try:
        return bool(np.allclose(perspective.as_quad(a), perspective.as_quad(b), atol=tolerance))
    except perspective.InvalidQuadrilateral:
        return False


def copy_state(state: EditState) -> EditState:
    return copy.deepcopy(state)
