from __future__ import annotations

from typing import Any


def _get(d: dict[str, Any] | None, *path: str, default: Any = None) -> Any:
    cur: Any = d
    for p in path:
        if not isinstance(cur, dict):
            return default
        cur = cur.get(p)
    return cur if cur is not None else default


def normalize_server(obj: dict[str, Any]) -> dict[str, Any]:
    # Support both API shape and hcloud shape (best-effort)
    public_net = obj.get("public_net") if isinstance(obj.get("public_net"), dict) else {}
    ipv4 = _get(public_net, "ipv4", "ip") or obj.get("ipv4") or _get(obj, "public_net", "ipv4")
    ipv6 = _get(public_net, "ipv6", "ip") or obj.get("ipv6") or _get(obj, "public_net", "ipv6")

    location = _get(obj, "datacenter", "location", "name") or obj.get("location") or _get(obj, "datacenter", "location")
    server_type = _get(obj, "server_type", "name") or obj.get("type") or obj.get("server_type")
    image = _get(obj, "image", "name") or _get(obj, "image", "id") or obj.get("image")

    volumes = obj.get("volumes")
    if not isinstance(volumes, list):
        volumes = []

    # firewalls may appear as list of dicts or IDs
    firewalls_raw = obj.get("firewalls")
    firewalls: list[int] = []
    if isinstance(firewalls_raw, list):
        for fw in firewalls_raw:
            if isinstance(fw, int):
                firewalls.append(fw)
            elif isinstance(fw, dict) and isinstance(fw.get("id"), int):
                firewalls.append(int(fw["id"]))

    private_net = obj.get("private_net")
    private_out: list[dict[str, Any]] = []
    if isinstance(private_net, list):
        for n in private_net:
            if not isinstance(n, dict):
                continue
            network_id = _get(n, "network", "id") or n.get("network_id") or n.get("network")
            ip = n.get("ip")
            entry: dict[str, Any] = {}
            if isinstance(network_id, int):
                entry["network_id"] = network_id
            elif isinstance(network_id, str) and network_id.isdigit():
                entry["network_id"] = int(network_id)
            if isinstance(ip, str):
                entry["ip"] = ip
            if entry:
                private_out.append(entry)

    return {
        "id": int(obj.get("id")) if isinstance(obj.get("id"), int) or str(obj.get("id", "")).isdigit() else obj.get("id"),
        "name": obj.get("name") or "",
        "status": obj.get("status") or "",
        "created": obj.get("created") or "",
        "location": location or "",
        "server_type": server_type or "",
        "image": image or "",
        "public_net": {"ipv4": ipv4 or "", "ipv6": ipv6 or ""},
        "private_net": private_out,
        "volumes": [int(v) for v in volumes if isinstance(v, int) or (isinstance(v, str) and v.isdigit())],
        "firewalls": sorted(set(firewalls)),
        "labels": obj.get("labels") if isinstance(obj.get("labels"), dict) else {},
    }


def normalize_volume(obj: dict[str, Any]) -> dict[str, Any]:
    location = _get(obj, "location", "name") or obj.get("location") or _get(obj, "server", "datacenter", "location", "name")
    server_id = _get(obj, "server", "id") or obj.get("server")
    if isinstance(server_id, dict):
        server_id = server_id.get("id")
    server_id_out = None
    if isinstance(server_id, int) or (isinstance(server_id, str) and server_id.isdigit()):
        server_id_out = int(server_id)
    return {
        "id": obj.get("id"),
        "name": obj.get("name") or "",
        "size_gb": obj.get("size") if isinstance(obj.get("size"), (int, float)) else obj.get("size_gb"),
        "status": obj.get("status") or "",
        "created": obj.get("created") or "",
        "location": location or "",
        "server": server_id_out,
        "labels": obj.get("labels") if isinstance(obj.get("labels"), dict) else {},
    }


def normalize_network(obj: dict[str, Any]) -> dict[str, Any]:
    return {
        "id": obj.get("id"),
        "name": obj.get("name") or "",
        "ip_range": obj.get("ip_range") or "",
        "subnets": obj.get("subnets") if isinstance(obj.get("subnets"), list) else [],
        "routes": obj.get("routes") if isinstance(obj.get("routes"), list) else [],
        "labels": obj.get("labels") if isinstance(obj.get("labels"), dict) else {},
        "created": obj.get("created") or "",
    }


def normalize_firewall(obj: dict[str, Any]) -> dict[str, Any]:
    applied_to = obj.get("applied_to") if isinstance(obj.get("applied_to"), list) else []
    simplified_applied: list[dict[str, Any]] = []
    for a in applied_to:
        if not isinstance(a, dict):
            continue
        typ = a.get("type")
        if typ == "server":
            sid = _get(a, "server", "id")
            if isinstance(sid, int) or (isinstance(sid, str) and sid.isdigit()):
                simplified_applied.append({"type": "server", "server_id": int(sid)})
        elif typ == "label_selector":
            sel = a.get("label_selector") or a.get("selector")
            if isinstance(sel, str) and sel:
                simplified_applied.append({"type": "label_selector", "label_selector": sel})

    rules = obj.get("rules") if isinstance(obj.get("rules"), list) else []
    return {
        "id": obj.get("id"),
        "name": obj.get("name") or "",
        "created": obj.get("created") or "",
        "labels": obj.get("labels") if isinstance(obj.get("labels"), dict) else {},
        "rules": rules,
        "applied_to": simplified_applied,
    }


def normalize_floating_ip(obj: dict[str, Any]) -> dict[str, Any]:
    server_id = _get(obj, "server", "id") or obj.get("server")
    if isinstance(server_id, dict):
        server_id = server_id.get("id")
    server_id_out = None
    if isinstance(server_id, int) or (isinstance(server_id, str) and server_id.isdigit()):
        server_id_out = int(server_id)
    home = _get(obj, "home_location", "name") or obj.get("home_location") or ""
    return {
        "id": obj.get("id"),
        "name": obj.get("name") or "",
        "ip": obj.get("ip") or "",
        "type": obj.get("type") or "",
        "created": obj.get("created") or "",
        "server": server_id_out,
        "home_location": home,
        "labels": obj.get("labels") if isinstance(obj.get("labels"), dict) else {},
    }


def normalize_load_balancer(obj: dict[str, Any]) -> dict[str, Any]:
    location = _get(obj, "location", "name") or obj.get("location") or ""
    public_net = obj.get("public_net") if isinstance(obj.get("public_net"), dict) else {}
    ipv4 = _get(public_net, "ipv4", "ip") or obj.get("ipv4") or ""
    ipv6 = _get(public_net, "ipv6", "ip") or obj.get("ipv6") or ""
    lb_type = _get(obj, "load_balancer_type", "name") or obj.get("type") or ""
    return {
        "id": obj.get("id"),
        "name": obj.get("name") or "",
        "created": obj.get("created") or "",
        "location": location,
        "type": lb_type,
        "public_net": {"ipv4": ipv4, "ipv6": ipv6},
        "services": obj.get("services") if isinstance(obj.get("services"), list) else [],
        "labels": obj.get("labels") if isinstance(obj.get("labels"), dict) else {},
    }

