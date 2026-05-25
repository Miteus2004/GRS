"""Offline tests for the Nagios monitor client using mocked HTTP responses."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest

from engine.monitor import NagiosClient


FAKE_RESPONSE = {
    "data": {
        "servicelist": {
            "svc1": {"host_name": "router1", "description": "PING", "status": 0},
            "svc2": {"host_name": "router2", "description": "PING", "status": 0},
            "svc3": {"host_name": "lb",      "description": "HTTP", "status": 0},
        }
    }
}

CONGESTED_RESPONSE = {
    "data": {
        "servicelist": {
            "svc1": {"host_name": "router1", "description": "PING", "status": 0},
            "svc2": {"host_name": "router2", "description": "PING", "status": 1},  # WARNING
            "svc3": {"host_name": "router2", "description": "HTTP", "status": 2},  # CRITICAL
        }
    }
}


def _mock_client(response_data):
    client = NagiosClient("http://172.16.123.139")
    mock_resp = MagicMock()
    mock_resp.json.return_value = response_data
    mock_resp.raise_for_status = MagicMock()
    with patch("engine.monitor.requests") as mock_req:
        mock_req.get.return_value = mock_resp
        yield client, mock_req


@patch("engine.monitor.requests")
def test_fetch_state_parses_hosts(mock_req):
    mock_resp = MagicMock()
    mock_resp.json.return_value = FAKE_RESPONSE
    mock_req.get.return_value = mock_resp

    client = NagiosClient("http://172.16.123.139")
    state = client.fetch_state()
    assert "router1" in state
    assert "lb" in state


@patch("engine.monitor.requests")
def test_all_hosts_up_when_all_ok(mock_req):
    mock_resp = MagicMock()
    mock_resp.json.return_value = FAKE_RESPONSE
    mock_req.get.return_value = mock_resp

    client = NagiosClient("http://172.16.123.139")
    assert client.all_hosts_up() is True


@patch("engine.monitor.requests")
def test_all_hosts_up_false_when_critical(mock_req):
    mock_resp = MagicMock()
    mock_resp.json.return_value = CONGESTED_RESPONSE
    mock_req.get.return_value = mock_resp

    client = NagiosClient("http://172.16.123.139")
    assert client.all_hosts_up() is False


@patch("engine.monitor.requests")
def test_congested_hosts_returns_affected(mock_req):
    mock_resp = MagicMock()
    mock_resp.json.return_value = CONGESTED_RESPONSE
    mock_req.get.return_value = mock_resp

    client = NagiosClient("http://172.16.123.139")
    bad = client.congested_hosts()
    assert "router2" in bad
    assert "router1" not in bad


@patch("engine.monitor.requests")
def test_is_congested_true_for_warning(mock_req):
    mock_resp = MagicMock()
    mock_resp.json.return_value = CONGESTED_RESPONSE
    mock_req.get.return_value = mock_resp

    client = NagiosClient("http://172.16.123.139")
    assert client.is_congested("router2") is True
    assert client.is_congested("router1") is False
