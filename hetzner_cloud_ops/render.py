from __future__ import annotations

from typing import Any

from .utils import format_kv_labels, format_table


def render_servers_list(servers: list[dict[str, Any]]) -> str:
    headers = ["NAME", "ID", "STATUS", "LOC", "TYPE", "IPV4", "IPV6", "CREATED", "LABELS"]
    rows: list[list[str]] = []
    for s in servers:
        public = s.get("public_net") if isinstance(s.get("public_net"), dict) else {}
        rows.append(
            [
                str(s.get("name") or "-"),
                str(s.get("id") or "-"),
                str(s.get("status") or "-"),
                str(s.get("location") or "-"),
                str(s.get("server_type") or "-"),
                str(public.get("ipv4") or "-"),
                str(public.get("ipv6") or "-"),
                str(s.get("created") or "-"),
                format_kv_labels(s.get("labels") if isinstance(s.get("labels"), dict) else {}),
            ]
        )
    table = format_table(headers, rows)
    return "```text\n" + table + "\n```"


def render_firewalls_list(firewalls: list[dict[str, Any]]) -> str:
    headers = ["NAME", "ID", "RULES", "APPLIED_TO", "CREATED", "LABELS"]
    rows: list[list[str]] = []
    for fw in firewalls:
        applied = fw.get("applied_to") if isinstance(fw.get("applied_to"), list) else []
        rows.append(
            [
                str(fw.get("name") or "-"),
                str(fw.get("id") or "-"),
                str(len(fw.get("rules") or [])),
                str(len(applied)),
                str(fw.get("created") or "-"),
                format_kv_labels(fw.get("labels") if isinstance(fw.get("labels"), dict) else {}),
            ]
        )
    table = format_table(headers, rows)
    return "```text\n" + table + "\n```"

