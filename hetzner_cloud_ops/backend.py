from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from .api_client import HetznerAPIClient
from .cli_adapter import HcloudCLIAdapter, HcloudInfo, detect_hcloud
from .errors import BackendError


@dataclass(frozen=True)
class BackendMeta:
    mode: str  # hcloud|api|hybrid
    hcloud: HcloudInfo


class HybridBackend:
    def __init__(self, *, token: str, prefer: str = "auto"):
        self._token = token
        self._prefer = prefer
        self._hcloud_info = detect_hcloud()
        self._api = HetznerAPIClient(token)
        self._cli = (
            HcloudCLIAdapter(token, hcloud_path=self._hcloud_info.path)
            if self._hcloud_info.available
            else None
        )

    @property
    def meta(self) -> BackendMeta:
        mode = "api"
        if self._prefer == "api":
            mode = "api"
        elif self._prefer == "hcloud":
            mode = "hcloud"
        elif self._hcloud_info.available:
            mode = "hybrid"
        return BackendMeta(mode=mode, hcloud=self._hcloud_info)

    def _want_cli(self) -> bool:
        if self._prefer == "api":
            return False
        if self._prefer == "hcloud":
            return True
        return self._cli is not None

    # ---- list resources (sync) ----
    def list_servers(self) -> list[dict[str, Any]]:
        if self._want_cli() and self._cli:
            try:
                return self._cli.list_servers()
            except BackendError:
                return self._api.list_servers()
        return self._api.list_servers()

    def list_volumes(self) -> list[dict[str, Any]]:
        if self._want_cli() and self._cli:
            try:
                return self._cli.list_volumes()
            except BackendError:
                return self._api.list_volumes()
        return self._api.list_volumes()

    def list_networks(self) -> list[dict[str, Any]]:
        if self._want_cli() and self._cli:
            try:
                return self._cli.list_networks()
            except BackendError:
                return self._api.list_networks()
        return self._api.list_networks()

    def list_firewalls(self) -> list[dict[str, Any]]:
        if self._want_cli() and self._cli:
            try:
                return self._cli.list_firewalls()
            except BackendError:
                return self._api.list_firewalls()
        return self._api.list_firewalls()

    def list_floating_ips(self) -> list[dict[str, Any]]:
        if self._want_cli() and self._cli:
            try:
                return self._cli.list_floating_ips()
            except BackendError:
                return self._api.list_floating_ips()
        return self._api.list_floating_ips()

    def list_load_balancers(self) -> list[dict[str, Any]]:
        if self._want_cli() and self._cli:
            try:
                return self._cli.list_load_balancers()
            except BackendError:
                return self._api.list_load_balancers()
        return self._api.list_load_balancers()

    # ---- detail/actions ----
    def get_server(self, server_id: int) -> dict[str, Any]:
        return self._api.get_server(server_id)

    def list_server_actions(self, server_id: int) -> list[dict[str, Any]]:
        return self._api.list_server_actions(server_id)

    # ---- write ops ----
    def create_server(
        self,
        *,
        name: str,
        image: str,
        server_type: str,
        location: str | None,
        ssh_keys: list[str] | None,
        user_data: str | None,
        user_data_from_file: str | None,
    ) -> dict[str, Any]:
        if self._want_cli() and self._cli and user_data is None:
            # Never replay a mutation through another backend after an ambiguous error.
            return self._cli.create_server(
                name=name,
                image=image,
                server_type=server_type,
                location=location,
                ssh_keys=ssh_keys,
                user_data_from_file=user_data_from_file,
            )

        api_user_data = user_data
        if api_user_data is None and user_data_from_file:
            try:
                from pathlib import Path

                api_user_data = (
                    Path(user_data_from_file).expanduser().read_text(encoding="utf-8")
                )
            except Exception as e:
                raise BackendError(
                    f"Failed to read user_data file: {user_data_from_file} ({e})"
                ) from None

        return self._api.create_server(
            name=name,
            image=image,
            server_type=server_type,
            location=location,
            ssh_keys=ssh_keys,
            user_data=api_user_data,
        )

    def server_power_action(self, ident: str, *, server_id: int, action: str) -> None:
        if self._want_cli() and self._cli:
            self._cli.server_power_action(ident, action)
            return
        self._api.server_power_action(server_id, action)

    def delete_server(self, server_id: int) -> None:
        if self._want_cli() and self._cli:
            self._cli.delete_server(str(server_id))
            return
        self._api.delete_server(server_id)

    def firewall_apply_to_server(
        self,
        firewall_ident: str,
        *,
        firewall_id: int,
        server_ident: str,
        server_id: int,
    ) -> None:
        if self._want_cli() and self._cli:
            self._cli.firewall_apply_to_server(firewall_ident, server_ident)
            return
        self._api.firewall_apply_to_server(firewall_id, server_id)
