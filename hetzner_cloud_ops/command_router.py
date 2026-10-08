from __future__ import annotations

import argparse
from pathlib import Path
from typing import Any

from .backend import HybridBackend
from .config import HetznerConfig, config_path, default_state_dir, load_config
from .errors import BackendError, ConfigError, SyncError
from .normalizers import (
    normalize_firewall,
    normalize_floating_ip,
    normalize_load_balancer,
    normalize_network,
    normalize_server,
    normalize_volume,
)
from .render import render_firewalls_list, render_servers_list
from .state_store import StateStore
from .utils import is_int_string, mask_token, safe_eprint, safe_print


def _parse_args(argv: list[str]) -> argparse.Namespace:
    p = argparse.ArgumentParser(add_help=False)
    p.add_argument("--no-sync", action="store_true", help="Skip startup sync and use cached state.json")
    p.add_argument("--backend", choices=["auto", "hcloud", "api"], default="auto")
    p.add_argument("--state-dir", default=str(default_state_dir()))
    p.add_argument("-h", "--help", action="store_true")

    # First pass parse to see if user used subcommands
    ns, rest = p.parse_known_args(argv)
    ns._rest = rest
    return ns


def _guess_intent(argv_rest: list[str]) -> list[str]:
    if not argv_rest:
        return ["list"]
    cmd = argv_rest[0]
    known = {"sync", "list", "ls", "show", "diff", "ssh", "create", "power", "delete", "firewall", "help"}
    if cmd in known:
        return argv_rest

    text = " ".join(argv_rest).lower()

    def has(*keys: str) -> bool:
        return any(k in text for k in keys)

    if has("help", "usage"):
        return ["help"]
    if has("diff", "changes", "compare"):
        return ["diff"]
    if has("ssh", "login", "connect"):
        parts = argv_rest
        if len(parts) >= 2:
            return ["ssh", parts[-1]]
        return ["ssh"]
    if has("show", "detail", "describe"):
        if len(argv_rest) >= 2:
            return ["show", argv_rest[-1]]
        return ["show"]
    if has("list", "ls", "all"):
        return ["list"]
    if has("firewall"):
        return ["firewall", "list"]
    return ["help"]


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="hz",
        formatter_class=argparse.RawTextHelpFormatter,
        description="Hetzner Cloud Ops (auto sync + persisted snapshots + diff)",
    )
    parser.add_argument("--no-sync", action="store_true", help="Skip startup sync and use cached state.json")
    parser.add_argument("--backend", choices=["auto", "hcloud", "api"], default="auto", help="Backend selection: auto|hcloud|api")
    parser.add_argument("--state-dir", default=str(default_state_dir()), help=f"Snapshot directory (default: {default_state_dir()})")

    sub = parser.add_subparsers(dest="command", required=True)

    sub.add_parser("sync", help="Run sync only (fetch resources, write state.json, generate last_diff.md)")

    p_list = sub.add_parser("list", help="List servers")
    p_list.add_argument("--raw", action="store_true", help="Print servers from state.json directly (JSON)")
    p_ls = sub.add_parser("ls", help="Alias for list")
    p_ls.add_argument("--raw", action="store_true", help="Print servers from state.json directly (JSON)")

    p_show = sub.add_parser("show", help="Show details for a single server")
    p_show.add_argument("server", help="server name or id")

    sub.add_parser("diff", help="Show the change summary for the current vs previous snapshot")

    p_ssh = sub.add_parser("ssh", help="Print suggested ssh commands")
    p_ssh.add_argument("server", help="server name or id")

    p_create = sub.add_parser("create", help="Create a server (dry-run by default; add --apply to execute)")
    p_create.add_argument("--name", required=True)
    p_create.add_argument("--image", default=None)
    p_create.add_argument("--type", dest="server_type", default=None)
    p_create.add_argument("--location", default=None)
    p_create.add_argument("--ssh-key", action="append", default=[])
    p_create.add_argument("--user-data", default=None, help="Path to a cloud-init user_data file (contents are never echoed)")
    p_create.add_argument("--apply", action="store_true", help="Actually create the server (otherwise only print the dry-run plan)")
    p_create.add_argument("--show-root-password", action="store_true", help="Print root_password if returned by the API or CLI (sensitive)")

    p_power = sub.add_parser("power", help="start/stop/reboot server")
    p_power.add_argument("action", choices=["start", "stop", "reboot"])
    p_power.add_argument("server")
    p_power.add_argument("--apply", action="store_true")

    p_delete = sub.add_parser("delete", help="Delete a server (destructive: requires a second confirmation)")
    p_delete.add_argument("server")
    p_delete.add_argument("--confirm", default=None, help='Confirmation phrase, for example "CONFIRM DELETE 123456"')

    p_fw = sub.add_parser("firewall", help="firewall list / attach")
    fw_sub = p_fw.add_subparsers(dest="fw_cmd", required=True)
    fw_sub.add_parser("list", help="List firewalls")
    p_fw_attach = fw_sub.add_parser("attach", help="Attach a firewall to a server (dry-run by default; add --apply to execute)")
    p_fw_attach.add_argument("firewall", help="firewall name or id")
    p_fw_attach.add_argument("server", help="server name or id")
    p_fw_attach.add_argument("--apply", action="store_true")

    sub.add_parser("help", help="Show help")
    return parser


def _find_server(state: dict[str, Any], ident: str) -> dict[str, Any] | None:
    servers = (state.get("resources") or {}).get("servers") or []
    if is_int_string(ident):
        for s in servers:
            if str(s.get("id")) == ident.strip():
                return s
        return None
    # exact match first
    for s in servers:
        if s.get("name") == ident:
            return s
    return None


def _find_firewall(state: dict[str, Any], ident: str) -> dict[str, Any] | None:
    fws = (state.get("resources") or {}).get("firewalls") or []
    if is_int_string(ident):
        for fw in fws:
            if str(fw.get("id")) == ident.strip():
                return fw
        return None
    for fw in fws:
        if fw.get("name") == ident:
            return fw
    return None


def _ssh_key_suggestions() -> list[str]:
    candidates = [
        "~/.ssh/id_ed25519",
        "~/.ssh/id_rsa",
        "~/.ssh/id_ecdsa",
        "~/.ssh/id_dsa",
    ]
    out: list[str] = []
    for c in candidates:
        p = Path(c).expanduser()
        if p.exists():
            out.append(str(p))
    return out


class CommandRouter:
    def run(self, argv: list[str]) -> int:
        pre = _parse_args(argv)
        if pre.help:
            safe_print(_build_parser().format_help())
            return 0

        rest = _guess_intent(pre._rest)
        parser = _build_parser()
        args = parser.parse_args(["--no-sync"] * int(pre.no_sync) + ["--backend", pre.backend, "--state-dir", pre.state_dir] + rest)

        try:
            cfg = load_config(backend=args.backend, state_dir=Path(args.state_dir))
        except ConfigError as e:
            cfg_path = config_path(Path(args.state_dir).expanduser())
            safe_eprint("❌", e)
            safe_eprint("Next steps:")
            safe_eprint("- Confirm HETZNER_ADMIN_TOKEN is exported (project API token), then reopen or refresh the shell")

            if args.command == "help":
                safe_print(self._help_text(parser))
                return 0
            return 2

        secrets = [cfg.token]
        backend = HybridBackend(token=cfg.token, prefer=cfg.backend)
        store = StateStore(cfg.state_dir)

        # ---- always try sync (unless --no-sync) ----
        if not args.no_sync:
            try:
                resources = self._sync_resources(backend)
                meta = {
                    "schema_version": 1,
                    "backend": backend.meta.mode,
                    "token_source": cfg.token_source,
                    "hcloud": {
                        "available": backend.meta.hcloud.available,
                        "version": backend.meta.hcloud.version,
                    },
                }
                store.sync(meta=meta, resources=resources)
            except BackendError as e:
                safe_eprint("❌ Sync failed:", str(e), secrets=secrets)
                if getattr(e, "hint", None):
                    safe_eprint("Next step:", e.hint, secrets=secrets)
                safe_eprint("Tip: you can also continue from cached state with `--no-sync`.", secrets=secrets)
                if args.command == "help":
                    safe_print(parser.format_help())
                    return 0
                return 3
            except SyncError as e:
                safe_eprint("❌ Failed to persist sync output:", str(e), secrets=secrets)
                return 3

        # ---- execute command ----
        state = store.load_state()
        cmd = args.command
        if cmd in {"list", "ls"}:
            servers = ((state.get("resources") or {}).get("servers")) or []
            if getattr(args, "raw", False):
                safe_print(json_dump(servers), secrets=secrets)
                return 0
            safe_print(render_servers_list(servers), secrets=secrets)
            return 0

        if cmd == "sync":
            safe_print("✅ Sync complete:", str(store.paths.state), secrets=secrets)
            safe_print("Diff summary:", str(store.paths.last_diff), secrets=secrets)
            return 0

        if cmd == "diff":
            prev = store.load_prev_state()
            cur = state
            from .diff_engine import render_diff_markdown  # noqa: WPS433

            md = render_diff_markdown(prev, cur)
            safe_print(md, secrets=secrets)
            return 0

        if cmd == "show":
            server = _find_server(state, args.server)
            if not server:
                safe_eprint("❌ Server not found:", args.server, secrets=secrets)
                safe_eprint("Next step: run `hz list` to confirm the name or ID, or use `--no-sync` to read the existing state.json.")
                return 4
            self._render_server_detail(state, backend, server, secrets=secrets)
            return 0

        if cmd == "ssh":
            server = _find_server(state, args.server)
            if not server:
                safe_eprint("❌ Server not found:", args.server, secrets=secrets)
                return 4
            ipv4 = ((server.get("public_net") or {}).get("ipv4") if isinstance(server.get("public_net"), dict) else "") or ""
            if not ipv4:
                safe_eprint("❌ This server does not have an available IPv4 address.", secrets=secrets)
                return 4
            keys = _ssh_key_suggestions()
            safe_print("## Suggested SSH Commands")
            safe_print(f"- Basic: `ssh root@{ipv4}`")
            if keys:
                safe_print("- Detected common local private key paths (paths only; contents are never read):")
                for k in keys[:3]:
                    safe_print(f"  - `{k}`")
                safe_print(f"- More specific: `ssh -i {keys[0]} root@{ipv4}`")
            safe_print("- If you do not use root, replace it with the image's default user (for example `ubuntu`).")
            return 0

        if cmd == "create":
            return self._cmd_create(cfg, backend, args, secrets=secrets)

        if cmd == "power":
            return self._cmd_power(state, backend, args, secrets=secrets)

        if cmd == "delete":
            return self._cmd_delete(state, backend, args, secrets=secrets)

        if cmd == "firewall":
            if args.fw_cmd == "list":
                fws = ((state.get("resources") or {}).get("firewalls")) or []
                safe_print(render_firewalls_list(fws), secrets=secrets)
                return 0
            if args.fw_cmd == "attach":
                return self._cmd_firewall_attach(state, backend, args, secrets=secrets)

        if cmd == "help":
            safe_print(self._help_text(parser))
            return 0

        safe_print(parser.format_help())
        return 0

    def _sync_resources(self, backend: HybridBackend) -> dict[str, Any]:
        servers_raw = backend.list_servers()
        volumes_raw = backend.list_volumes()
        networks_raw = backend.list_networks()
        firewalls_raw = backend.list_firewalls()
        fips_raw = backend.list_floating_ips()
        lbs_raw = backend.list_load_balancers()

        servers = sorted([normalize_server(s) for s in servers_raw if isinstance(s, dict)], key=lambda x: str(x.get("id")))
        volumes = sorted([normalize_volume(v) for v in volumes_raw if isinstance(v, dict)], key=lambda x: str(x.get("id")))
        networks = sorted([normalize_network(n) for n in networks_raw if isinstance(n, dict)], key=lambda x: str(x.get("id")))
        firewalls = sorted([normalize_firewall(fw) for fw in firewalls_raw if isinstance(fw, dict)], key=lambda x: str(x.get("id")))
        floating_ips = sorted([normalize_floating_ip(f) for f in fips_raw if isinstance(f, dict)], key=lambda x: str(x.get("id")))
        load_balancers = sorted([normalize_load_balancer(lb) for lb in lbs_raw if isinstance(lb, dict)], key=lambda x: str(x.get("id")))

        return {
            "servers": servers,
            "volumes": volumes,
            "networks": networks,
            "firewalls": firewalls,
            "floating_ips": floating_ips,
            "load_balancers": load_balancers,
        }

    def _render_server_detail(self, state: dict[str, Any], backend: HybridBackend, server: dict[str, Any], *, secrets: list[str]) -> None:
        sid = int(server.get("id"))
        safe_print("# Server")
        safe_print(f"- Name: `{server.get('name')}`")
        safe_print(f"- ID: `{server.get('id')}`")
        safe_print(f"- Status: `{server.get('status')}`")
        safe_print(f"- Type: `{server.get('server_type')}`")
        safe_print(f"- Location: `{server.get('location')}`")
        safe_print(f"- Image: `{server.get('image')}`")
        safe_print(f"- Created: `{server.get('created')}`")
        labels = server.get("labels") if isinstance(server.get("labels"), dict) else {}
        safe_print(f"- Labels: `{labels or {}}`")

        public = server.get("public_net") if isinstance(server.get("public_net"), dict) else {}
        safe_print("")
        safe_print("## Network")
        safe_print(f"- IPv4: `{public.get('ipv4') or '-'}`")
        safe_print(f"- IPv6: `{public.get('ipv6') or '-'}`")
        private = server.get("private_net") if isinstance(server.get("private_net"), list) else []
        if private:
            safe_print("- Private:")
            for n in private:
                safe_print(f"  - network_id={n.get('network_id')} ip={n.get('ip')}")
        else:
            safe_print("- Private: `-`")

        vols = server.get("volumes") if isinstance(server.get("volumes"), list) else []
        all_vols = ((state.get("resources") or {}).get("volumes")) or []
        vols_by_id = {str(v.get("id")): v for v in all_vols if isinstance(v, dict)}
        safe_print("")
        safe_print("## Volumes")
        if vols:
            for vid in vols:
                v = vols_by_id.get(str(vid)) or {}
                safe_print(f"- {v.get('name') or '-'} ({vid}) size={v.get('size_gb')}GB status={v.get('status')}")
        else:
            safe_print("- `-`")

        safe_print("")
        safe_print("## Firewalls")
        fws = server.get("firewalls") if isinstance(server.get("firewalls"), list) else []
        all_fws = ((state.get("resources") or {}).get("firewalls")) or []
        fws_by_id = {str(fw.get("id")): fw for fw in all_fws if isinstance(fw, dict)}
        if fws:
            for fw_id in fws:
                fw = fws_by_id.get(str(fw_id)) or {}
                safe_print(f"- {fw.get('name') or '-'} ({fw_id})")
        else:
            safe_print("- `-`")

        safe_print("")
        safe_print("## Recent Actions")
        try:
            actions = backend.list_server_actions(sid)
        except BackendError as e:
            safe_print(f"- (failed to fetch actions: {e})", secrets=secrets)
            return
        for a in actions[:10]:
            if not isinstance(a, dict):
                continue
            safe_print(f"- {a.get('command')} status={a.get('status')} started={a.get('started')} finished={a.get('finished')}")

    def _cmd_create(self, cfg: HetznerConfig, backend: HybridBackend, args: argparse.Namespace, *, secrets: list[str]) -> int:
        name = args.name
        image = args.image or cfg.defaults.image
        server_type = args.server_type or cfg.defaults.type
        location = args.location or cfg.defaults.location
        ssh_keys = [k for k in (args.ssh_key or []) if k]
        user_data_file = args.user_data
        user_data = None
        user_data_from_file = None
        if user_data_file:
            p = Path(user_data_file).expanduser()
            if not p.exists():
                safe_eprint("❌ user_data file does not exist:", str(p))
                return 4
            user_data_from_file = str(p)

        safe_print("# Create Plan")
        safe_print(f"- Name: `{name}`")
        safe_print(f"- Image: `{image}`")
        safe_print(f"- Type: `{server_type}`")
        safe_print(f"- Location: `{location}`")
        safe_print(f"- SSH Keys: `{ssh_keys or []}`")
        safe_print(f"- UserData: `{user_data_file or '-'}` (contents are never echoed)")
        safe_print("")
        safe_print("One write backend is selected before execution; failed writes are never replayed automatically.")
        safe_print("(token redacted)", f"`{mask_token(cfg.token)}`")

        # show planned commands (redacted)
        safe_print("")
        safe_print("## Dry-run Command (redacted)")
        if backend.meta.hcloud.available and cfg.backend != "api":
            hcloud_cmd = ["hcloud", "server", "create", "--name", name, "--type", server_type, "--image", image, "--location", location]
            for k in ssh_keys:
                hcloud_cmd += ["--ssh-key", k]
            if user_data_from_file:
                hcloud_cmd += ["--user-data-from-file", user_data_from_file]
            hcloud_cmd += ["-o", "json"]
            safe_print("- hcloud:")
            safe_print("  - `HCLOUD_TOKEN=" + mask_token(cfg.token) + " " + " ".join(hcloud_cmd) + "`")

        safe_print("- HTTP API:")
        safe_print("  - `curl -sS -H 'Authorization: Bearer " + mask_token(cfg.token) + "' \\")
        safe_print("      -H 'Content-Type: application/json' \\")
        safe_print("      -d '{\"name\":\"" + name + "\",\"image\":\"" + image + "\",\"server_type\":\"" + server_type + "\",\"location\":\"" + location + "\"}' \\")
        safe_print("      https://api.hetzner.cloud/v1/servers`")

        if not args.apply:
            safe_print("")
            safe_print("✅ Dry-run complete (nothing created). Add `--apply` to execute.")
            return 0

        try:
            resp = backend.create_server(
                name=name,
                image=image,
                server_type=server_type,
                location=location,
                ssh_keys=ssh_keys or None,
                user_data=user_data,
                user_data_from_file=user_data_from_file,
            )
        except BackendError as e:
            safe_eprint("❌ Create failed:", str(e), secrets=secrets)
            if getattr(e, "hint", None):
                safe_eprint("Next step:", e.hint, secrets=secrets)
            return 5

        server_obj = resp.get("server") if isinstance(resp, dict) else None
        server_id = None
        if isinstance(server_obj, dict):
            server_id = server_obj.get("id")
        safe_print("")
        safe_print("✅ Server created")
        if server_id:
            safe_print(f"- Server ID: `{server_id}`")
            safe_print(f"- Next step: `hz show {server_id}` or `hz ssh {server_id}`")
        root_pw = resp.get("root_password") if isinstance(resp, dict) else None
        if root_pw and args.show_root_password:
            safe_print(f"- root_password (sensitive): `{root_pw}`")
        elif root_pw:
            safe_print("- root_password was returned (sensitive): hidden by default; add `--show-root-password` to display it.")
        return 0

    def _cmd_power(self, state: dict[str, Any], backend: HybridBackend, args: argparse.Namespace, *, secrets: list[str]) -> int:
        server = _find_server(state, args.server)
        if not server:
            safe_eprint("❌ Server not found:", args.server, secrets=secrets)
            return 4
        sid = int(server.get("id"))
        ident = str(server.get("id"))
        action = {"start": "poweron", "stop": "poweroff", "reboot": "reboot"}[args.action]
        safe_print("# Power Plan")
        safe_print(f"- Target: {server.get('name')} ({sid})")
        safe_print(f"- Action: {args.action}")
        if not args.apply:
            safe_print("Dry-run: add --apply to submit the power action.")
            return 0
        try:
            backend.server_power_action(ident, server_id=sid, action=action)
        except BackendError as e:
            safe_eprint("❌ Power action failed:", str(e), secrets=secrets)
            return 5
        safe_print("✅ Power action submitted. Next step: wait a moment, then run `hz show` to confirm the status.")
        return 0

    def _cmd_delete(self, state: dict[str, Any], backend: HybridBackend, args: argparse.Namespace, *, secrets: list[str]) -> int:
        server = _find_server(state, args.server)
        if not server:
            safe_eprint("❌ Server not found:", args.server, secrets=secrets)
            return 4
        sid = int(server.get("id"))
        phrase = f"CONFIRM DELETE {sid}"
        safe_print("# Delete Plan (irreversible)")
        safe_print(f"- Target: {server.get('name')} ({sid})")
        safe_print("- Impact: this server will be permanently deleted, and the data is not recoverable unless you have separate backups.")
        safe_print("")
        safe_print("To execute the deletion, run it again with this confirmation phrase:")
        safe_print(f"- `{phrase}`")
        safe_print(f"Example: `hz delete {sid} --confirm \"{phrase}\"`")

        if (args.confirm or "").strip() != phrase:
            safe_eprint("❌ Confirmation phrase missing or incorrect; refusing to continue.")
            return 6

        try:
            backend.delete_server(sid)
        except BackendError as e:
            safe_eprint("❌ Delete failed:", str(e), secrets=secrets)
            return 5
        safe_print("✅ Server deleted. Next step: run `hz list` to confirm it is gone.")
        return 0

    def _cmd_firewall_attach(self, state: dict[str, Any], backend: HybridBackend, args: argparse.Namespace, *, secrets: list[str]) -> int:
        fw = _find_firewall(state, args.firewall)
        srv = _find_server(state, args.server)
        if not fw:
            safe_eprint("❌ Firewall not found:", args.firewall)
            return 4
        if not srv:
            safe_eprint("❌ Server not found:", args.server)
            return 4
        fw_id = int(fw.get("id"))
        srv_id = int(srv.get("id"))
        safe_print("# Firewall Attach Plan")
        safe_print(f"- Firewall: {fw.get('name')} ({fw_id})")
        safe_print(f"- Server: {srv.get('name')} ({srv_id})")
        safe_print("- Risk: the rules may affect connectivity, for example by blocking SSH. Confirm the rules before applying them.")
        safe_print("")
        safe_print("Dry-run command (redacted):")
        token_mask = mask_token(secrets[0]) if secrets else "***"
        if backend.meta.hcloud.available:
            safe_print(f"- `HCLOUD_TOKEN={token_mask} hcloud firewall apply-to-resource --type server --server {srv_id} {fw_id}`")
        safe_print(f"- `curl -sS -H 'Authorization: Bearer {token_mask}' -H 'Content-Type: application/json' \\")
        safe_print(f"    -d '{{\"apply_to\":[{{\"type\":\"server\",\"server\":{{\"id\":{srv_id}}}}}]}}' \\")
        safe_print(f"    https://api.hetzner.cloud/v1/firewalls/{fw_id}/actions/apply_to_resources`")

        if not args.apply:
            safe_print("")
            safe_print("✅ Dry-run complete (not executed). Add `--apply` to execute.")
            return 0

        try:
            backend.firewall_apply_to_server(str(fw_id), firewall_id=fw_id, server_ident=str(srv_id), server_id=srv_id)
        except BackendError as e:
            safe_eprint("❌ Attach failed:", str(e), secrets=secrets)
            return 5
        safe_print("✅ Attach submitted. Next step: run `hz show <server>` and inspect the `firewalls` field.")
        return 0

    def _help_text(self, parser: argparse.ArgumentParser) -> str:
        examples = "\n".join(
            [
                "# Hetzner Cloud Ops - Usage",
                "",
                "## Quick Start",
                "- `hz list`",
                "- `hz show <name|id>`",
                "- `hz diff`",
                "- `hz ssh <name|id>`",
                "",
                "## Startup Sync And Snapshots",
                f"- Every command syncs first by default and writes under `{default_state_dir()}`: `state.json`, `state.prev.json`, `last_diff.md`",
                "- Skip sync: `hz --no-sync list` (use cached `state.json`)",
                "",
                "## Write Safety",
                "- `create`, `power` and `firewall attach` are dry-run by default; add `--apply` to execute",
                "- `delete` requires a second confirmation: `CONFIRM DELETE <server_id>`",
                "",
                "## Common Troubleshooting",
                "- token/permissions: confirm `HETZNER_ADMIN_TOKEN` is correct and not revoked (project API token)",
                "- network: use `--no-sync` with cached state first, then inspect DNS, proxy, and VPN settings",
                "",
                "## Command Help (argparse)",
                "",
                parser.format_help().rstrip(),
                "",
            ]
        )
        return examples


def json_dump(obj: Any) -> str:
    import json

    return json.dumps(obj, ensure_ascii=False, sort_keys=True, indent=2)
