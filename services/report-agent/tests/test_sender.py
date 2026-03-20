"""
Tests for sender.py — webhook and SMTP delivery.
Uses unittest.mock to avoid real network calls.
"""

import sys
import os
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import sender as sender_mod


# ── Webhook tests ──────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_send_webhook_success():
    mock_resp = MagicMock()
    mock_resp.is_success = True
    mock_resp.status_code = 200

    mock_client = AsyncMock()
    mock_client.__aenter__ = AsyncMock(return_value=mock_client)
    mock_client.__aexit__ = AsyncMock(return_value=False)
    mock_client.post = AsyncMock(return_value=mock_resp)

    with patch.object(sender_mod.settings, "manager_webhook_url", "http://fake-webhook.test/hook"):
        with patch("sender.httpx.AsyncClient", return_value=mock_client):
            result = await sender_mod.send_webhook("Test report", "Test Subject")

    assert result is True


@pytest.mark.asyncio
async def test_send_webhook_no_url():
    with patch.object(sender_mod.settings, "manager_webhook_url", ""):
        result = await sender_mod.send_webhook("Test report")
    assert result is False


@pytest.mark.asyncio
async def test_send_webhook_non_2xx():
    mock_resp = MagicMock()
    mock_resp.is_success = False
    mock_resp.status_code = 500
    mock_resp.text = "Internal Server Error"

    mock_client = AsyncMock()
    mock_client.__aenter__ = AsyncMock(return_value=mock_client)
    mock_client.__aexit__ = AsyncMock(return_value=False)
    mock_client.post = AsyncMock(return_value=mock_resp)

    with patch.object(sender_mod.settings, "manager_webhook_url", "http://fake-webhook.test/hook"):
        with patch("sender.httpx.AsyncClient", return_value=mock_client):
            result = await sender_mod.send_webhook("Test report")

    assert result is False


@pytest.mark.asyncio
async def test_send_webhook_exception_returns_false():
    mock_client = AsyncMock()
    mock_client.__aenter__ = AsyncMock(return_value=mock_client)
    mock_client.__aexit__ = AsyncMock(return_value=False)
    mock_client.post = AsyncMock(side_effect=Exception("Connection refused"))

    with patch.object(sender_mod.settings, "manager_webhook_url", "http://fake-webhook.test/hook"):
        with patch("sender.httpx.AsyncClient", return_value=mock_client):
            result = await sender_mod.send_webhook("Test report")

    assert result is False


# ── SMTP tests ─────────────────────────────────────────────────────────────────


def test_send_email_no_config():
    with patch.object(sender_mod.settings, "smtp_host", ""):
        with patch.object(sender_mod.settings, "smtp_to", ""):
            result = sender_mod.send_email("Test report")
    assert result is False


def test_send_email_success():
    mock_smtp = MagicMock()
    mock_smtp.__enter__ = MagicMock(return_value=mock_smtp)
    mock_smtp.__exit__ = MagicMock(return_value=False)

    with patch.object(sender_mod.settings, "smtp_host", "smtp.test.local"):
    	with patch.object(sender_mod.settings, "smtp_port", 587):
            with patch.object(sender_mod.settings, "smtp_to", "admin@test.local"):
                with patch.object(sender_mod.settings, "smtp_from", "mas@test.local"):
                    with patch.object(sender_mod.settings, "smtp_user", ""):
                        with patch.object(sender_mod.settings, "smtp_password", ""):
                            with patch("sender.smtplib.SMTP", return_value=mock_smtp):
                                result = sender_mod.send_email("Test report", "Test Subject")

    assert result is True


def test_send_email_exception_returns_false():
    with patch.object(sender_mod.settings, "smtp_host", "smtp.test.local"):
        with patch.object(sender_mod.settings, "smtp_to", "admin@test.local"):
            with patch("sender.smtplib.SMTP", side_effect=Exception("Connection refused")):
                result = sender_mod.send_email("Test report")

    assert result is False


# ── deliver_report ─────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_deliver_report_both_succeed():
    with patch("sender.send_webhook", new_callable=AsyncMock, return_value=True):
        with patch("sender.send_email", return_value=True):
            result = await sender_mod.deliver_report("Test report", "Subject")

    assert result["webhook"] is True
    assert result["email"] is True


@pytest.mark.asyncio
async def test_deliver_report_only_webhook():
    with patch("sender.send_webhook", new_callable=AsyncMock, return_value=True):
        with patch("sender.send_email", return_value=False):
            result = await sender_mod.deliver_report("Test report", "Subject")

    assert result["webhook"] is True
    assert result["email"] is False


@pytest.mark.asyncio
async def test_deliver_report_none_succeed(caplog):
    import logging
    with patch("sender.send_webhook", new_callable=AsyncMock, return_value=False):
        with patch("sender.send_email", return_value=False):
            with caplog.at_level(logging.WARNING, logger="sender"):
                result = await sender_mod.deliver_report("Test report", "Subject")

    assert result == {"webhook": False, "email": False}
    assert "no delivery channel succeeded" in caplog.text.lower()
