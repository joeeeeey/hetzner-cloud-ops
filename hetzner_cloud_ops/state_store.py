from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from .diff_engine import render_diff_markdown
from .errors import SyncError
from .utils import atomic_write_text, ensure_dir, stable_json_dumps, utc_now_iso


@dataclass(frozen=True)
class StatePaths:
    state: Path
    prev: Path
    last_diff: Path


def default_state_paths(state_dir: Path) -> StatePaths:
    return StatePaths(
        state=state_dir / "state.json",
        prev=state_dir / "state.prev.json",
        last_diff=state_dir / "last_diff.md",
    )


class StateStore:
    def __init__(self, state_dir: Path):
        self._state_dir = state_dir.expanduser()
        ensure_dir(self._state_dir)
        self._paths = default_state_paths(self._state_dir)

    @property
    def paths(self) -> StatePaths:
        return self._paths

    def load_state(self) -> dict[str, Any]:
        try:
            return json.loads(self._paths.state.read_text(encoding="utf-8"))
        except FileNotFoundError:
            return {}
        except json.JSONDecodeError:
            raise SyncError(f"state.json is not valid JSON: {self._paths.state}")

    def load_prev_state(self) -> dict[str, Any]:
        try:
            return json.loads(self._paths.prev.read_text(encoding="utf-8"))
        except FileNotFoundError:
            return {}
        except json.JSONDecodeError:
            return {}

    def write_state(self, state: dict[str, Any]) -> None:
        atomic_write_text(self._paths.state, stable_json_dumps(state))

    def rotate_prev(self) -> None:
        if self._paths.state.exists():
            atomic_write_text(self._paths.prev, self._paths.state.read_text(encoding="utf-8"))

    def write_last_diff(self, markdown: str) -> None:
        atomic_write_text(self._paths.last_diff, markdown.rstrip() + "\n")

    def sync(self, *, meta: dict[str, Any], resources: dict[str, Any]) -> str:
        """
        Returns diff markdown (also persisted).
        """
        prev = self.load_state()
        self.rotate_prev()

        state = {"meta": {"synced_at": utc_now_iso(), **meta}, "resources": resources}
        self.write_state(state)

        diff_md = render_diff_markdown(prev, state)
        self.write_last_diff(diff_md)
        return diff_md
