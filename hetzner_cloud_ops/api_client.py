from __future__ import annotations

import json
import socket
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass
from typing import Any, Iterable

from .errors import BackendError


@dataclass(frozen=True)
class APIResponse:
    data: dict[str, Any]
    status: int


class NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None

class HetznerAPIClient:
    def __init__(self, token: str, *, base_url: str = "https://api.hetzner.cloud/v1", timeout_s: int = 30):
        self._token = token
        self._base_url = base_url.rstrip("/")
        self._timeout_s = timeout_s

    def _request(
        self,
        method: str,
        path: str,
        *,
        params: dict[str, str] | None = None,
        json_body: dict[str, Any] | None = None,
        ok_status: Iterable[int] = (200, 201, 202, 204),
    ) -> APIResponse:
        url = f"{self._base_url}{path}"
        if params:
            url = f"{url}?{urllib.parse.urlencode(params)}"

        data_bytes: bytes | None = None
        headers = {
            "Authorization": f"Bearer {self._token}",
            "Accept": "application/json",
        }
        if json_body is not None:
            data_bytes = json.dumps(json_body).encode("utf-8")
            headers["Content-Type"] = "application/json"

        req = urllib.request.Request(url, method=method, headers=headers, data=data_bytes)

        try:
            with urllib.request.build_opener(NoRedirect()).open(req, timeout=self._timeout_s) as resp:
                status = int(getattr(resp, "status", 200))
                body = resp.read()
        except urllib.error.HTTPError as e:
            status = int(getattr(e, "code", 0) or 0)
            body = e.read() if hasattr(e, "read") else b""
            msg = "response body suppressed"
            hint = None
            if status == 401:
                hint = "Invalid token or insufficient permissions: check whether HETZNER_ADMIN_TOKEN (project-level) is correct and not revoked."
            raise BackendError(f"Hetzner API HTTP {status}: {msg}", hint=hint) from None
        except urllib.error.URLError as e:
            reason = getattr(e, "reason", e)
            hint = "Network, DNS, or proxy issue: try `--no-sync` with cached state first, then inspect network, VPN, and proxy configuration."
            raise BackendError(f"Hetzner API network error: {reason}", hint=hint) from None
        except socket.timeout:
            hint = "Request timed out: inspect the network or retry later. You can also use `--no-sync` with cached state."
            raise BackendError("Hetzner API request timed out", hint=hint) from None

        if status not in set(ok_status):
            msg = "response body suppressed"
            raise BackendError(f"Hetzner API returned unexpected status {status}: {msg}")

        if not body:
            return APIResponse(data={}, status=status)

        try:
            return APIResponse(data=json.loads(body.decode("utf-8")), status=status)
        except json.JSONDecodeError:
            raise BackendError("Hetzner API response is not valid JSON") from None

    def _paginate(self, path: str, key: str) -> list[dict[str, Any]]:
        page = 1
        per_page = 50
        out: list[dict[str, Any]] = []
        seen = set()
        while True:
            if page in seen or len(seen) >= 100:
                raise BackendError("Pagination repeated or exceeded 100 pages; narrow the inventory")
            seen.add(page)
            resp = self._request("GET", path, params={"page": str(page), "per_page": str(per_page)})
            items = resp.data.get(key) or []
            if not isinstance(items, list):
                raise BackendError(f"Hetzner API response field {key} is not a list")
            out.extend([i for i in items if isinstance(i, dict)])

            meta = resp.data.get("meta") or {}
            pagination = meta.get("pagination") or {}
            next_page = pagination.get("next_page")
            if not next_page:
                break
            page = int(next_page)
        return out

    # ---- list resources ----
    def list_servers(self) -> list[dict[str, Any]]:
        return self._paginate("/servers", "servers")

    def list_volumes(self) -> list[dict[str, Any]]:
        return self._paginate("/volumes", "volumes")

    def list_networks(self) -> list[dict[str, Any]]:
        return self._paginate("/networks", "networks")

    def list_firewalls(self) -> list[dict[str, Any]]:
        return self._paginate("/firewalls", "firewalls")

    def list_floating_ips(self) -> list[dict[str, Any]]:
        return self._paginate("/floating_ips", "floating_ips")

    def list_load_balancers(self) -> list[dict[str, Any]]:
        return self._paginate("/load_balancers", "load_balancers")

    # ---- server detail/actions ----
    def get_server(self, server_id: int) -> dict[str, Any]:
        resp = self._request("GET", f"/servers/{server_id}")
        server = resp.data.get("server")
        if not isinstance(server, dict):
            raise BackendError("Hetzner API /servers/{id} response is missing the server field")
        return server

    def list_server_actions(self, server_id: int, *, per_page: int = 25) -> list[dict[str, Any]]:
        resp = self._request("GET", f"/servers/{server_id}/actions", params={"page": "1", "per_page": str(per_page)})
        actions = resp.data.get("actions") or []
        if not isinstance(actions, list):
            raise BackendError("Hetzner API actions field is not a list")
        return [a for a in actions if isinstance(a, dict)]

    # ---- write operations ----
    def create_server(
        self,
        *,
        name: str,
        image: str,
        server_type: str,
        location: str | None = None,
        ssh_keys: list[str] | None = None,
        user_data: str | None = None,
    ) -> dict[str, Any]:
        body: dict[str, Any] = {
            "name": name,
            "image": image,
            "server_type": server_type,
        }
        if location:
            body["location"] = location
        if ssh_keys:
            body["ssh_keys"] = ssh_keys
        if user_data is not None:
            body["user_data"] = user_data

        resp = self._request("POST", "/servers", json_body=body, ok_status=(201,))
        return resp.data

    def server_power_action(self, server_id: int, action: str) -> dict[str, Any]:
        if action not in {"poweron", "poweroff", "reboot"}:
            raise BackendError(f"Unsupported power action: {action}")
        resp = self._request("POST", f"/servers/{server_id}/actions/{action}", ok_status=(201,))
        return resp.data

    def delete_server(self, server_id: int) -> None:
        self._request("DELETE", f"/servers/{server_id}", ok_status=(200, 204))

    def firewall_apply_to_server(self, firewall_id: int, server_id: int) -> dict[str, Any]:
        body = {"apply_to": [{"type": "server", "server": {"id": server_id}}]}
        resp = self._request("POST", f"/firewalls/{firewall_id}/actions/apply_to_resources", json_body=body, ok_status=(201,))
        return resp.data


def _extract_api_error_message(body: bytes) -> str | None:
    if not body:
        return None
    try:
        obj = json.loads(body.decode("utf-8"))
    except Exception:
        return body.decode("utf-8", errors="replace")[:400]
    err = obj.get("error")
    if isinstance(err, dict):
        return str(err.get("message") or err.get("code") or "API error")
    return None
