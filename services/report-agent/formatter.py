"""
Markdown report formatter.

Takes the aggregated data dicts from aggregator.py and renders
a clean markdown report string suitable for Slack/Teams webhooks
or email body (with HTML wrapper).
"""

from __future__ import annotations

from datetime import date
from typing import Any


# ── Helpers ───────────────────────────────────────────────────────────────────


def _pct_bar(pct: float, width: int = 10) -> str:
    """Simple ASCII progress bar: ████░░░░░░ 75%."""
    filled = round(pct / 100 * width)
    return "█" * filled + "░" * (width - filled) + f" {pct:.0f}%"


def _status_icon(status: str) -> str:
    return {
        "healthy": "✅",
        "warning": "⚠️",
        "critical": "🔴",
        "unknown": "❓",
        "unreachable": "🔴",
    }.get(status.lower(), "❓")


def _severity_icon(severity: str) -> str:
    return {
        "low": "🟢",
        "medium": "🟡",
        "high": "🟠",
        "critical": "🔴",
    }.get((severity or "").lower(), "⚪")


# ── Section renderers ─────────────────────────────────────────────────────────


def _render_fleet_health(fleet: list[dict]) -> str:
    if not fleet:
        return "_No server data for this period._\n"

    lines = [
        "| Server | Status | CPU % | Mem % | Disk % | GPU Temp |",
        "|--------|--------|-------|-------|--------|----------|",
    ]
    critical_count = 0
    for s in fleet:
        metrics = s.get("metrics") or {}
        status = s.get("status", "unknown")
        if status in ("critical", "unreachable"):
            critical_count += 1
        icon = _status_icon(status)
        hostname = s.get("hostname") or f"srv-{str(s.get('server_id', '?'))[:8]}"
        cpu = metrics.get("cpu_pct", "—")
        mem = metrics.get("mem_pct", "—")
        disk = metrics.get("disk_pct", "—")
        gpu_temp = metrics.get("gpu_temp_c", "—")
        cpu_str = f"{cpu}%" if isinstance(cpu, (int, float)) else str(cpu)
        mem_str = f"{mem}%" if isinstance(mem, (int, float)) else str(mem)
        disk_str = f"{disk}%" if isinstance(disk, (int, float)) else str(disk)
        gpu_str = f"{gpu_temp}°C" if isinstance(gpu_temp, (int, float)) else str(gpu_temp)
        lines.append(
            f"| {icon} {hostname} | {status} | {cpu_str} | {mem_str} | {disk_str} | {gpu_str} |"
        )

    summary = f"\n**{len(fleet)} servers checked**"
    if critical_count:
        summary += f" — **⚠️ {critical_count} critical/unreachable**"
    return "\n".join(lines) + "\n" + summary + "\n"


def _render_weekly_fleet(
    fleet_range: dict[str, list[dict]],
    uptime_pct: dict[str, float],
) -> str:
    if not fleet_range:
        return "_No server data for this period._\n"

    lines = [
        "| Server | 7-day Uptime | Healthy Days | Total Days |",
        "|--------|-------------|-------------|-----------|",
    ]
    for server_id, days_data in fleet_range.items():
        hostname = days_data[0].get("hostname", f"srv-{server_id[:8]}") if days_data else server_id
        total = len(days_data)
        healthy = sum(1 for d in days_data if d.get("status") == "healthy")
        uptime = uptime_pct.get(server_id, 0.0)
        bar = _pct_bar(uptime, width=8)
        lines.append(f"| {hostname} | {bar} | {healthy} | {total} |")

    return "\n".join(lines) + "\n"


def _render_ticket_stats(tickets: dict[str, Any]) -> str:
    total = tickets.get("total", 0)
    resolved = tickets.get("resolved", 0)
    failed = tickets.get("failed", 0)
    escalated = tickets.get("escalated", 0)
    in_progress = tickets.get("in_progress", 0)
    rate = tickets.get("resolution_rate_pct", 0.0)
    avg_min = tickets.get("avg_resolution_min", 0.0)

    lines = [
        f"| Metric | Value |",
        f"|--------|-------|",
        f"| Total tickets | **{total}** |",
        f"| Resolved | {resolved} ({rate:.1f}%) |",
        f"| Failed | {failed} |",
        f"| Escalated | {'**' + str(escalated) + '**' if escalated else '0'} |",
        f"| In progress | {in_progress} |",
        f"| Avg resolution time | {avg_min:.1f} min |",
    ]
    return "\n".join(lines) + "\n"


def _render_escalations(escalations: list[dict]) -> str:
    if not escalations:
        return "_No escalations in this period._\n"

    lines = [
        "| # | Severity | Description | Created |",
        "|---|----------|-------------|---------|",
    ]
    for i, e in enumerate(escalations, 1):
        icon = _severity_icon(e.get("severity", ""))
        desc = (e.get("description") or "")[:80].replace("|", "\\|")
        created = str(e.get("created_at", ""))[:16]
        lines.append(f"| {i} | {icon} {e.get('severity', '?').upper()} | {desc} | {created} |")

    return "\n".join(lines) + "\n"


def _render_cost(cost: dict[str, Any], weekly_cost: dict[str, Any] | None = None) -> str:
    daily_usd = cost.get("daily_cost_usd", 0.0)
    rpm = cost.get("rpm_used", 0)
    tpm = cost.get("tpm_used", 0)

    lines = [
        "| Metric | Value |",
        "|--------|-------|",
        f"| Daily LLM spend | **${daily_usd:.4f}** |",
        f"| Requests/min (peak) | {rpm} |",
        f"| Tokens/min (peak) | {tpm:,} |",
    ]
    if weekly_cost:
        note = weekly_cost.get("note", "")
        if note:
            lines.append(f"| Note | _{note}_ |")

    return "\n".join(lines) + "\n"


# ── Entry points ──────────────────────────────────────────────────────────────


def format_daily_report(data: dict[str, Any]) -> str:
    """
    Render a daily markdown report from aggregate_daily() output.
    Returns the full markdown string.
    """
    report_date = data.get("date", str(date.today()))
    fleet = data.get("fleet", [])
    tickets = data.get("tickets", {})
    escalations = data.get("escalations", [])
    cost = data.get("cost", {})

    critical_servers = [s for s in fleet if s.get("status") in ("critical", "unreachable")]
    alert_prefix = "🔴 " if critical_servers else ""

    sections = [
        f"# {alert_prefix}Daily Operations Report — {report_date}\n",
        "---\n",
        "## 1. Fleet Health Summary\n",
        _render_fleet_health(fleet),
        "## 2. Ticket Summary\n",
        _render_ticket_stats(tickets),
        "## 3. System Cost Summary\n",
        _render_cost(cost),
    ]

    if escalations:
        sections += [
            "## 4. Alerts & Escalations\n",
            _render_escalations(escalations),
        ]
    else:
        sections.append("## 4. Alerts & Escalations\n\n_No escalations today._ ✅\n")

    # Recommended actions
    actions: list[str] = []
    for s in critical_servers:
        hostname = s.get("hostname") or f"srv-{str(s.get('server_id', '?'))[:8]}"
        actions.append(f"- Investigate **{hostname}** (status: {s.get('status')})")
    if tickets.get("escalated", 0) > 0:
        actions.append(
            f"- Review **{tickets['escalated']} escalated ticket(s)** requiring human intervention"
        )
    if tickets.get("resolution_rate_pct", 100) < 80:
        actions.append(
            f"- Resolution rate is **{tickets.get('resolution_rate_pct', 0):.1f}%** — below 80% threshold"
        )

    if actions:
        sections.append("## 5. Recommended Actions\n\n" + "\n".join(actions) + "\n")
    else:
        sections.append("## 5. Recommended Actions\n\n_No action required._ ✅\n")

    sections.append(f"\n---\n_Report generated by SentinelMAS · {report_date}_\n")
    return "\n".join(sections)


def format_weekly_report(data: dict[str, Any]) -> str:
    """
    Render a weekly markdown report from aggregate_weekly() output.
    Returns the full markdown string.
    """
    date_range = data.get("date_range", "last 7 days")
    fleet_range = data.get("fleet_range", {})
    uptime_pct = data.get("server_uptime_pct", {})
    tickets = data.get("tickets", {})
    escalations = data.get("escalations", [])
    cost = data.get("cost", {})
    weekly_cost = data.get("weekly_cost")

    low_uptime = [
        (sid, pct) for sid, pct in uptime_pct.items() if pct < 90.0
    ]

    alert_prefix = "🔴 " if low_uptime else ""

    sections = [
        f"# {alert_prefix}Weekly Operations Report — {date_range}\n",
        "---\n",
        "## 1. Fleet Health Trend (7 Days)\n",
        _render_weekly_fleet(fleet_range, uptime_pct),
        "## 2. Ticket Summary\n",
        _render_ticket_stats(tickets),
        "## 3. System Cost Summary\n",
        _render_cost(cost, weekly_cost),
    ]

    if escalations:
        sections += [
            "## 4. Alerts & Escalations\n",
            _render_escalations(escalations),
        ]
    else:
        sections.append("## 4. Alerts & Escalations\n\n_No escalations this week._ ✅\n")

    actions: list[str] = []
    for sid, pct in low_uptime:
        hostname = "unknown"
        if sid in fleet_range and fleet_range[sid]:
            hostname = fleet_range[sid][0].get("hostname", sid)
        actions.append(f"- **{hostname}** uptime {pct:.1f}% — below 90% threshold")
    if tickets.get("escalated", 0) > 3:
        actions.append(
            f"- High escalation volume: **{tickets['escalated']} tickets** escalated this week"
        )

    if actions:
        sections.append("## 5. Recommended Actions\n\n" + "\n".join(actions) + "\n")
    else:
        sections.append("## 5. Recommended Actions\n\n_No action required._ ✅\n")

    sections.append(f"\n---\n_Report generated by SentinelMAS · {date_range}_\n")
    return "\n".join(sections)


def wrap_html(markdown_body: str, subject: str) -> str:
    """Minimal HTML wrapper for SMTP delivery. Not a full HTML renderer."""
    escaped = (
        markdown_body
        .replace("&", "&amp;")
        .replace("<", "&lt;")
        .replace(">", "&gt;")
        .replace("\n", "<br>\n")
    )
    return f"""<!DOCTYPE html>
<html><head><meta charset="utf-8"><title>{subject}</title>
<style>body{{font-family:monospace;font-size:13px;line-height:1.5;max-width:900px;margin:0 auto;padding:20px}}</style>
</head><body>
<pre>{escaped}</pre>
</body></html>"""
