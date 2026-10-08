from __future__ import annotations

from typing import Any


def _by_id(items: list[dict[str, Any]]) -> dict[str, dict[str, Any]]:
    out: dict[str, dict[str, Any]] = {}
    for it in items:
        if not isinstance(it, dict):
            continue
        rid = it.get("id")
        if rid is None:
            continue
        out[str(rid)] = it
    return out


def _set_str(values: Any) -> set[str]:
    if not isinstance(values, list):
        return set()
    return {str(v) for v in values}


def _labels_diff(prev: dict[str, str] | None, cur: dict[str, str] | None) -> list[str]:
    p = prev or {}
    c = cur or {}
    keys = sorted(set(p.keys()) | set(c.keys()))
    changes: list[str] = []
    for k in keys:
        pv = p.get(k)
        cv = c.get(k)
        if pv != cv:
            if pv is None:
                changes.append(f"+{k}={cv}")
            elif cv is None:
                changes.append(f"-{k}={pv}")
            else:
                changes.append(f"{k}: {pv} -> {cv}")
    return changes


def diff_servers(prev: list[dict[str, Any]], cur: list[dict[str, Any]]) -> dict[str, Any]:
    p = _by_id(prev)
    c = _by_id(cur)
    added = [c[i] for i in sorted(set(c.keys()) - set(p.keys()))]
    removed = [p[i] for i in sorted(set(p.keys()) - set(c.keys()))]

    changed: list[dict[str, Any]] = []
    for sid in sorted(set(p.keys()) & set(c.keys())):
        a = p[sid]
        b = c[sid]
        changes: list[str] = []

        def ch(field: str, label: str | None = None) -> None:
            if a.get(field) != b.get(field):
                changes.append(f"{label or field}: {a.get(field)} -> {b.get(field)}")

        ch("status")
        ch("location")
        ch("server_type", "type")

        ipv4_a = ((a.get("public_net") or {}).get("ipv4") if isinstance(a.get("public_net"), dict) else None) or ""
        ipv4_b = ((b.get("public_net") or {}).get("ipv4") if isinstance(b.get("public_net"), dict) else None) or ""
        if ipv4_a != ipv4_b:
            changes.append(f"ipv4: {ipv4_a or '-'} -> {ipv4_b or '-'}")

        ipv6_a = ((a.get("public_net") or {}).get("ipv6") if isinstance(a.get("public_net"), dict) else None) or ""
        ipv6_b = ((b.get("public_net") or {}).get("ipv6") if isinstance(b.get("public_net"), dict) else None) or ""
        if ipv6_a != ipv6_b:
            changes.append(f"ipv6: {ipv6_a or '-'} -> {ipv6_b or '-'}")

        labels_changes = _labels_diff(a.get("labels"), b.get("labels"))
        if labels_changes:
            changes.append("labels: " + "; ".join(labels_changes))

        vols_a = _set_str(a.get("volumes"))
        vols_b = _set_str(b.get("volumes"))
        if vols_a != vols_b:
            changes.append(f"volumes: {sorted(vols_a) or '-'} -> {sorted(vols_b) or '-'}")

        fws_a = _set_str(a.get("firewalls"))
        fws_b = _set_str(b.get("firewalls"))
        if fws_a != fws_b:
            changes.append(f"firewalls: {sorted(fws_a) or '-'} -> {sorted(fws_b) or '-'}")

        if changes:
            changed.append({"id": sid, "name": b.get("name") or a.get("name") or "", "changes": changes})

    return {"added": added, "removed": removed, "changed": changed}


def diff_generic(prev: list[dict[str, Any]], cur: list[dict[str, Any]], *, fields: list[str]) -> dict[str, Any]:
    p = _by_id(prev)
    c = _by_id(cur)
    added = [c[i] for i in sorted(set(c.keys()) - set(p.keys()))]
    removed = [p[i] for i in sorted(set(p.keys()) - set(c.keys()))]
    changed: list[dict[str, Any]] = []
    for rid in sorted(set(p.keys()) & set(c.keys())):
        a = p[rid]
        b = c[rid]
        changes: list[str] = []
        for f in fields:
            if a.get(f) != b.get(f):
                changes.append(f"{f}: {a.get(f)} -> {b.get(f)}")
        labels_changes = _labels_diff(a.get("labels"), b.get("labels"))
        if labels_changes:
            changes.append("labels: " + "; ".join(labels_changes))
        if changes:
            changed.append({"id": rid, "name": b.get("name") or a.get("name") or "", "changes": changes})
    return {"added": added, "removed": removed, "changed": changed}


def render_diff_markdown(prev_state: dict[str, Any], cur_state: dict[str, Any]) -> str:
    prev_res = (prev_state.get("resources") or {}) if isinstance(prev_state.get("resources"), dict) else {}
    cur_res = (cur_state.get("resources") or {}) if isinstance(cur_state.get("resources"), dict) else {}

    if not prev_res:
        return "\n".join(
            [
                "# Hetzner Cloud Diff",
                "",
                "- First sync: no previous snapshot found (state.prev.json)",
                "",
            ]
        )

    servers = diff_servers(prev_res.get("servers") or [], cur_res.get("servers") or [])
    volumes = diff_generic(prev_res.get("volumes") or [], cur_res.get("volumes") or [], fields=["size_gb", "status", "server", "location"])
    networks = diff_generic(prev_res.get("networks") or [], cur_res.get("networks") or [], fields=["ip_range"])
    firewalls = diff_generic(prev_res.get("firewalls") or [], cur_res.get("firewalls") or [], fields=[])
    fips = diff_generic(prev_res.get("floating_ips") or [], cur_res.get("floating_ips") or [], fields=["ip", "server", "home_location"])
    lbs = diff_generic(prev_res.get("load_balancers") or [], cur_res.get("load_balancers") or [], fields=["type", "location"])

    def section(title: str, d: dict[str, Any]) -> list[str]:
        lines: list[str] = []
        lines.append(f"## {title}")
        if not d["added"] and not d["removed"] and not d["changed"]:
            lines.append("- No changes")
            lines.append("")
            return lines

        if d["added"]:
            lines.append(f"- Added: {len(d['added'])}")
            for it in d["added"]:
                lines.append(f"  - + {it.get('name') or '-'} ({it.get('id')})")
        if d["removed"]:
            lines.append(f"- Removed: {len(d['removed'])}")
            for it in d["removed"]:
                lines.append(f"  - - {it.get('name') or '-'} ({it.get('id')})")
        if d["changed"]:
            lines.append(f"- Changed: {len(d['changed'])}")
            for it in d["changed"]:
                prefix = f"{it.get('name') or '-'} ({it.get('id')})"
                for ch in it.get("changes") or []:
                    lines.append(f"  - * {prefix}: {ch}")
        lines.append("")
        return lines

    out: list[str] = []
    out.append("# Hetzner Cloud Diff")
    out.append("")
    out.extend(section("Servers", servers))
    out.extend(section("Volumes", volumes))
    out.extend(section("Networks", networks))
    out.extend(section("Firewalls", firewalls))
    out.extend(section("Floating IPs", fips))
    out.extend(section("Load Balancers", lbs))
    return "\n".join(out).rstrip() + "\n"
