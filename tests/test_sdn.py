"""Offline tests for the Ryu REST client using mocked HTTP responses."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest

from engine.sdn import RyuClient, PATH_PROFILES, choose_path, path_summary


@patch("engine.sdn.requests")
def test_push_flow_posts_correct_payload(mock_req):
    mock_resp = MagicMock()
    mock_resp.json.return_value = {}
    mock_req.post.return_value = mock_resp

    client = RyuClient("http://localhost:8080")
    client.push_flow(1, 200, {"eth_type": 0x0800}, [{"type": "OUTPUT", "port": 1}])

    call_kwargs = mock_req.post.call_args
    payload = call_kwargs[1]["json"]
    assert payload["dpid"] == 1
    assert payload["priority"] == 200


@patch("engine.sdn.requests")
def test_activate_primary_path(mock_req):
    mock_resp = MagicMock()
    mock_resp.json.return_value = {}
    mock_req.post.return_value = mock_resp

    client = RyuClient()
    client.activate_path(1, "primary")

    payload = mock_req.post.call_args[1]["json"]
    assert payload["actions"][0]["port"] == PATH_PROFILES["primary"]["actions"][0]["port"]


@patch("engine.sdn.requests")
def test_activate_backup_path(mock_req):
    mock_resp = MagicMock()
    mock_resp.json.return_value = {}
    mock_req.post.return_value = mock_resp

    client = RyuClient()
    client.activate_path(1, "backup")

    payload = mock_req.post.call_args[1]["json"]
    assert payload["actions"][0]["port"] == PATH_PROFILES["backup"]["actions"][0]["port"]


@patch("engine.sdn.requests")
def test_list_switches_calls_get(mock_req):
    mock_resp = MagicMock()
    mock_resp.json.return_value = [1, 2]
    mock_req.get.return_value = mock_resp

    client = RyuClient()
    switches = client.list_switches()
    assert switches == [1, 2]
    mock_req.get.assert_called_once()


def test_invalid_profile_raises():
    client = RyuClient()
    with pytest.raises(KeyError):
        client.activate_path(1, "nonexistent_profile")


@patch("engine.sdn.requests")
def test_delete_flow_posts_to_correct_endpoint(mock_req):
    mock_resp = MagicMock()
    mock_resp.json.return_value = {}
    mock_req.post.return_value = mock_resp

    client = RyuClient()
    client.delete_flow(1, {"eth_type": 0x0800})

    url = mock_req.post.call_args[0][0]
    assert "delete" in url


def test_choose_path_returns_backup_when_congested():
    assert choose_path(["router2"]) == "backup"


def test_choose_path_returns_primary_when_clear():
    assert choose_path([]) == "primary"


def test_path_summary_includes_profiles_and_sorted_hosts():
    summary = path_summary(["router3", "router1"])
    assert summary["path"] == "backup"
    assert summary["congested_hosts"] == ["router1", "router3"]
    assert "primary" in summary["profiles"]
