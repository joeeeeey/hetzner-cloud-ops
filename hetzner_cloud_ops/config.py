from __future__ import annotations

import json
import os
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from .errors import ConfigError
from .utils import ensure_dir


@dataclass(frozen=True)
class Defaults:
    image: str = "ubuntu-24.04"
    type: str = "cpx11"
    location: str = "fsn1"


@dataclass(frozen=True)
class HetznerConfig:
    token: str
    token_source: str
    state_dir: Path
    defaults: Defaults
    backend: str = "auto"  # auto|hcloud|api


STATE_DIR_ENV = "HETZNER_CLOUD_OPS_STATE_DIR"


def default_state_dir() -> Path:
    override = (os.getenv(STATE_DIR_ENV) or "").strip()
    if override:
        return Path(override).expanduser()

    xdg_state_home = (os.getenv("XDG_STATE_HOME") or "").strip()
    if xdg_state_home:
        return Path(xdg_state_home).expanduser() / "hetzner-cloud-ops"

    if sys.platform == "darwin":
        return Path.home() / "Library" / "Application Support" / "hetzner-cloud-ops"

    if os.name == "nt":
        local_app_data = (os.getenv("LOCALAPPDATA") or "").strip()
        if local_app_data:
            return Path(local_app_data).expanduser() / "hetzner-cloud-ops"
        return Path.home() / "AppData" / "Local" / "hetzner-cloud-ops"

    return Path.home() / ".local" / "state" / "hetzner-cloud-ops"


def config_path(state_dir: Path) -> Path:
    return state_dir / "config.json"


def _load_json(path: Path) -> dict[str, Any]:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError:
        return {}
    except json.JSONDecodeError as e:
        raise ConfigError(f"Config file is not valid JSON: {path} ({e})") from e


def load_config(
    *, backend: str = "auto", state_dir: Path | None = None
) -> HetznerConfig:
    sd = (state_dir or default_state_dir()).expanduser()
    ensure_dir(sd)

    token = (
        os.getenv("HCLOUD_TOKEN") or os.getenv("HETZNER_ADMIN_TOKEN") or ""
    ).strip()
    token_source = "env"
    cfg = _load_json(config_path(sd))

    if not token:
        raise ConfigError(
            f"Missing HCLOUD_TOKEN (legacy HETZNER_ADMIN_TOKEN also supported)"
        )

    defaults_cfg = (
        (cfg.get("defaults") or {}) if isinstance(cfg.get("defaults"), dict) else {}
    )
    defaults = Defaults(
        image=str(defaults_cfg.get("image") or Defaults.image),
        type=str(defaults_cfg.get("type") or Defaults.type),
        location=str(defaults_cfg.get("location") or Defaults.location),
    )

    return HetznerConfig(
        token=token,
        token_source=token_source,
        state_dir=sd,
        defaults=defaults,
        backend=backend,
    )
