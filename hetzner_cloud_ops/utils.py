from __future__ import annotations

import json
import os
import re
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable


def utc_now_iso() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def mask_token(token: str) -> str:
    return "[REDACTED]" if token else ""


def redact(text: str, secrets: Iterable[str]) -> str:
    redacted = text
    for secret in secrets:
        if not secret:
            continue
        redacted = redacted.replace(secret, mask_token(secret))
    return redacted


def safe_print(*parts: object, secrets: Iterable[str] = ()) -> None:
    msg = " ".join(str(p) for p in parts)
    msg = redact(msg, secrets)
    print(msg)


def safe_eprint(*parts: object, secrets: Iterable[str] = ()) -> None:
    msg = " ".join(str(p) for p in parts)
    msg = redact(msg, secrets)
    print(msg, file=sys.stderr)


def ensure_dir(path: Path) -> None:
    path.mkdir(parents=True, exist_ok=True)
    try:
        os.chmod(path, 0o700)
    except PermissionError:
        pass


def atomic_write_text(path: Path, text: str) -> None:
    import tempfile

    fd, name = tempfile.mkstemp(prefix=".snapshot-", dir=path.parent)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            f.write(text)
        os.replace(name, path)
    finally:
        if os.path.exists(name):
            os.unlink(name)


def stable_json_dumps(obj: Any) -> str:
    return json.dumps(obj, ensure_ascii=False, sort_keys=True, indent=2) + "\n"


def is_int_string(value: str) -> bool:
    return bool(re.fullmatch(r"[0-9]+", value.strip()))


def format_kv_labels(labels: dict[str, str] | None) -> str:
    if not labels:
        return "-"
    parts = [f"{k}={labels[k]}" for k in sorted(labels.keys())]
    return ",".join(parts)


def _truncate(s: str, max_len: int) -> str:
    if len(s) <= max_len:
        return s
    return s[: max(0, max_len - 1)] + "…"


def format_table(
    headers: list[str], rows: list[list[str]], *, max_col_width: int = 48
) -> str:
    widths = [len(h) for h in headers]
    for row in rows:
        for i, cell in enumerate(row):
            widths[i] = min(max(widths[i], len(cell)), max_col_width)

    def fmt_row(row: list[str]) -> str:
        cells: list[str] = []
        for i, cell in enumerate(row):
            cell = _truncate(cell, widths[i])
            cells.append(cell.ljust(widths[i]))
        return "  ".join(cells)

    out: list[str] = []
    out.append(fmt_row(headers))
    out.append("  ".join("-" * w for w in widths))
    for row in rows:
        out.append(fmt_row(row))
    return "\n".join(out)
