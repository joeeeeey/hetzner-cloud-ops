from __future__ import annotations

import json
import os
import shutil
import subprocess
from dataclasses import dataclass
from typing import Any

from .errors import BackendError


@dataclass(frozen=True)
class HcloudInfo:
    available: bool
    path: str | None = None
    version: str | None = None


def detect_hcloud() -> HcloudInfo:
    path = shutil.which("hcloud")
    if not path:
        return HcloudInfo(available=False)
    version = None
    try:
        proc = subprocess.run(
            [path, "version"], capture_output=True, text=True, check=False, timeout=60
        )
        if proc.returncode == 0:
            version = (proc.stdout or proc.stderr).strip().splitlines()[0][:120]
    except Exception:
        version = None
    return HcloudInfo(available=True, path=path, version=version)


class HcloudCLIAdapter:
    def __init__(self, token: str, *, hcloud_path: str | None = None):
        self._token = token
        self._hcloud = hcloud_path or shutil.which("hcloud") or "hcloud"

    def _run_json(self, args: list[str]) -> Any:
        env = os.environ.copy()
        env["HCLOUD_TOKEN"] = self._token
        # Never pass the token through command-line arguments; use env only.
        cmd = [self._hcloud, *args, "-o", "json"]
        try:
            proc = subprocess.run(
                cmd, env=env, capture_output=True, text=True, check=False, timeout=60
            )
        except (OSError, subprocess.TimeoutExpired):
            raise BackendError(
                "hcloud failed or timed out; inspect target before retrying"
            ) from None
        if proc.returncode != 0:
            stderr = (proc.stderr or proc.stdout or "").strip()
            hint = None
            if "HCLOUD_TOKEN" in stderr or "token" in stderr.lower():
                hint = "hcloud authentication failed: check whether HETZNER_ADMIN_TOKEN is correct, or verify that an hcloud context is not overriding it."
            raise BackendError("hcloud command failed; output suppressed", hint=hint)
        try:
            return json.loads(proc.stdout)
        except json.JSONDecodeError as e:
            raise BackendError(
                f"hcloud output is not valid JSON: {' '.join(args)} ({e})"
            ) from None

    def _run_no_output(self, args: list[str]) -> None:
        env = os.environ.copy()
        env["HCLOUD_TOKEN"] = self._token
        cmd = [self._hcloud, *args]
        try:
            proc = subprocess.run(
                cmd, env=env, capture_output=True, text=True, check=False, timeout=60
            )
        except (OSError, subprocess.TimeoutExpired):
            raise BackendError(
                "hcloud failed or timed out; inspect target before retrying"
            ) from None
        if proc.returncode != 0:
            stderr = (proc.stderr or proc.stdout or "").strip()
            raise BackendError("hcloud command failed; output suppressed")

    # ---- list resources ----
    def list_servers(self) -> list[dict[str, Any]]:
        data = self._run_json(["server", "list"])
        return data if isinstance(data, list) else []

    def describe_server(self, ident: str) -> dict[str, Any]:
        data = self._run_json(["server", "describe", ident])
        return data if isinstance(data, dict) else {}

    def list_volumes(self) -> list[dict[str, Any]]:
        data = self._run_json(["volume", "list"])
        return data if isinstance(data, list) else []

    def list_networks(self) -> list[dict[str, Any]]:
        data = self._run_json(["network", "list"])
        return data if isinstance(data, list) else []

    def list_firewalls(self) -> list[dict[str, Any]]:
        data = self._run_json(["firewall", "list"])
        return data if isinstance(data, list) else []

    def list_floating_ips(self) -> list[dict[str, Any]]:
        data = self._run_json(["floating-ip", "list"])
        return data if isinstance(data, list) else []

    def list_load_balancers(self) -> list[dict[str, Any]]:
        data = self._run_json(["load-balancer", "list"])
        return data if isinstance(data, list) else []

    # ---- write operations ----
    def create_server(
        self,
        *,
        name: str,
        image: str,
        server_type: str,
        location: str | None = None,
        ssh_keys: list[str] | None = None,
        user_data_from_file: str | None = None,
    ) -> dict[str, Any]:
        args = [
            "server",
            "create",
            "--name",
            name,
            "--type",
            server_type,
            "--image",
            image,
        ]
        if location:
            args += ["--location", location]
        if ssh_keys:
            for k in ssh_keys:
                args += ["--ssh-key", k]
        if user_data_from_file:
            args += ["--user-data-from-file", user_data_from_file]
        data = self._run_json(args)
        return data if isinstance(data, dict) else {"raw": data}

    def server_power_action(self, ident: str, action: str) -> None:
        cmd = {"poweron": "poweron", "poweroff": "poweroff", "reboot": "reboot"}.get(
            action
        )
        if not cmd:
            raise BackendError(f"Unsupported power action: {action}")
        self._run_no_output(["server", cmd, ident])

    def firewall_apply_to_server(self, firewall_ident: str, server_ident: str) -> None:
        self._run_no_output(
            [
                "firewall",
                "apply-to-resource",
                "--type",
                "server",
                "--server",
                server_ident,
                firewall_ident,
            ]
        )

    def delete_server(self, ident: str, *, timeout_s: int = 15) -> None:
        """
        hcloud delete behavior can vary by version and may prompt interactively.
        Add a timeout so the CLI cannot hang forever; never replay ambiguous writes.
        """
        env = os.environ.copy()
        env["HCLOUD_TOKEN"] = self._token
        cmd = [self._hcloud, "--quiet", "server", "delete", ident]
        try:
            proc = subprocess.run(
                cmd,
                env=env,
                capture_output=True,
                text=True,
                check=False,
                timeout=timeout_s,
            )
        except subprocess.TimeoutExpired:
            raise BackendError(
                "hcloud delete timed out (it may be waiting for interactive confirmation)",
                hint="Retry with `--backend api`, or verify the local hcloud version and flag behavior.",
            ) from None
        if proc.returncode != 0:
            stderr = (proc.stderr or proc.stdout or "").strip()
            raise BackendError("hcloud delete failed; inspect target before retrying")
