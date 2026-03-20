"""
Tests for formatter.py — markdown report rendering.
No external dependencies.
"""

import sys
import os

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from formatter import (
    format_daily_report,
    format_weekly_report,
    wrap_html,
    _pct_bar,
    _status_icon,
    _severity_icon,
)


# ── Helpers ────────────────────────────────────────────────────────────────────


def test_pct_bar_full():
    bar = _pct_bar(100.0, width=10)
    assert "██████████" in bar
    assert "100" in bar


def test_pct_bar_half():
    bar = _pct_bar(50.0, width=10)
    assert "█████" in bar
    assert "░░░░░" in bar


def test_pct_bar_zero():
    bar = _pct_bar(0.0, width=10)
    assert bar.startswith("░")


def test_status_icon_healthy():
    assert _status_icon("healthy") == "✅"


def test_status_icon_critical():
    assert _status_icon("critical") == "🔴"


def test_status_icon_unknown():
    assert _status_icon("unknown") == "❓"


def test_severity_icon_critical():
    assert _severity_icon("critical") == "🔴"


def test_severity_icon_case_insensitive():
    assert _severity_icon("HIGH") == _severity_icon("high")


# ── Daily report ───────────────────────────────────────────────────────────────


DAILY_DATA = {
    "period": "daily",
    "date": "2026-03-20",
    "fleet": [
        {
            "server_id": "srv-001",
            "hostname": "gpu-01",
            "date": "2026-03-20",
            "status": "healthy",
            "metrics": {"cpu_pct": 55.0, "mem_pct": 72.0, "disk_pct": 41.0, "gpu_temp_c": 72},
        },
        {
            "server_id": "srv-002",
            "hostname": "gpu-02",
            "date": "2026-03-20",
            "status": "critical",
            "metrics": {"cpu_pct": 98.0, "mem_pct": 95.0, "disk_pct": 80.0, "gpu_temp_c": 91},
        },
    ],
    "tickets": {
        "total": 10,
        "resolved": 8,
        "failed": 1,
        "escalated": 1,
        "in_progress": 0,
        "resolution_rate_pct": 80.0,
        "avg_resolution_min": 14.5,
    },
    "escalations": [
        {
            "ticket_id": "t-abc",
            "server_id": "srv-002",
            "severity": "CRITICAL",
            "description": "GPU memory error on training job",
            "summary": None,
            "created_at": "2026-03-20T10:23:00",
        }
    ],
    "cost": {"daily_cost_usd": 0.2345, "rpm_used": 40, "tpm_used": 120000},
}


def test_daily_report_contains_header():
    text = format_daily_report(DAILY_DATA)
    assert "Daily Operations Report" in text
    assert "2026-03-20" in text


def test_daily_report_contains_fleet():
    text = format_daily_report(DAILY_DATA)
    assert "gpu-01" in text
    assert "gpu-02" in text


def test_daily_report_critical_prefix():
    text = format_daily_report(DAILY_DATA)
    # critical server → 🔴 prefix in title
    assert "🔴" in text


def test_daily_report_no_critical_no_prefix():
    data = {**DAILY_DATA, "fleet": [DAILY_DATA["fleet"][0]], "escalations": []}
    text = format_daily_report(data)
    assert not text.startswith("# 🔴")


def test_daily_report_ticket_stats():
    text = format_daily_report(DAILY_DATA)
    assert "80.0%" in text or "80%" in text
    assert "14.5 min" in text


def test_daily_report_escalations_section():
    text = format_daily_report(DAILY_DATA)
    assert "Escalations" in text
    assert "GPU memory error" in text


def test_daily_report_recommended_actions_for_critical():
    text = format_daily_report(DAILY_DATA)
    assert "Recommended Actions" in text
    assert "gpu-02" in text


def test_daily_report_no_fleet():
    data = {**DAILY_DATA, "fleet": []}
    text = format_daily_report(data)
    assert "No server data" in text


# ── Weekly report ──────────────────────────────────────────────────────────────


WEEKLY_DATA = {
    "period": "weekly",
    "date_range": "2026-03-13 to 2026-03-20",
    "fleet_range": {
        "srv-001": [
            {"date": f"2026-03-{i:02d}", "status": "healthy", "hostname": "gpu-01"}
            for i in range(14, 21)
        ],
        "srv-002": [
            {"date": f"2026-03-{i:02d}", "status": "critical" if i > 18 else "healthy", "hostname": "gpu-02"}
            for i in range(14, 21)
        ],
    },
    "server_uptime_pct": {"srv-001": 100.0, "srv-002": 71.4},
    "tickets": {
        "total": 45,
        "resolved": 40,
        "failed": 2,
        "escalated": 3,
        "in_progress": 0,
        "resolution_rate_pct": 88.9,
        "avg_resolution_min": 12.3,
    },
    "escalations": [],
    "cost": {"daily_cost_usd": 0.3, "rpm_used": 55, "tpm_used": 180000},
    "weekly_cost": {"note": "Full weekly cost available after Langfuse integration", "current_day_usd": 0.0},
}


def test_weekly_report_contains_header():
    text = format_weekly_report(WEEKLY_DATA)
    assert "Weekly Operations Report" in text
    assert "2026-03-13 to 2026-03-20" in text


def test_weekly_report_uptime_bar():
    text = format_weekly_report(WEEKLY_DATA)
    assert "100" in text  # srv-001 100%
    assert "71" in text   # srv-002 ~71%


def test_weekly_report_low_uptime_alert():
    text = format_weekly_report(WEEKLY_DATA)
    # srv-002 at 71.4% → recommended actions
    assert "gpu-02" in text
    assert "below 90%" in text


def test_weekly_report_no_escalations_message():
    text = format_weekly_report(WEEKLY_DATA)
    assert "No escalations this week" in text


def test_weekly_report_cost_note():
    text = format_weekly_report(WEEKLY_DATA)
    assert "Langfuse" in text


# ── HTML wrapper ───────────────────────────────────────────────────────────────


def test_wrap_html_basic():
    html = wrap_html("Hello **World**", "Test Subject")
    assert "<html>" in html
    assert "Hello" in html
    assert "Test Subject" in html


def test_wrap_html_escapes_lt_gt():
    html = wrap_html("<script>alert(1)</script>", "XSS Test")
    assert "<script>" not in html
    assert "&lt;script&gt;" in html
