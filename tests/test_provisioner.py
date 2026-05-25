"""Offline tests for the provisioner using mocked Netmiko connections."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest

from engine.provisioner import Provisioner


INVENTORY = {
    "router1": {"host": "10.0.1.2", "port": 22, "username": "root", "password": "root"},
    "router2": {"host": "10.0.1.18", "port": 22, "username": "root", "password": "root"},
}

FAKE_OSPF = """
Neighbor ID     Pri State         Dead Time Address         Interface
10.0.1.11         1 Full/DR       00:00:37  10.0.1.11       eth1:10.0.1.10
10.0.1.19         1 Full/Backup   00:00:38  10.0.1.19       eth0:10.0.1.3
"""

FAKE_BGP = """
BGP router identifier 1.1.1.1, local AS number 65001
Neighbor        V    AS MsgRcvd MsgSent   TblVer  InQ OutQ Up/Down  State/PfxRcd
172.31.255.252  4 65002     120     118        0    0    0 01:02:03 Established
"""


@patch("engine.provisioner.ConnectHandler")
def test_check_ospf_neighbors_returns_output(mock_ch):
    mock_conn = MagicMock()
    mock_conn.send_command.return_value = FAKE_OSPF
    mock_ch.return_value.__enter__ = lambda s: mock_conn
    mock_ch.return_value = mock_conn

    p = Provisioner(INVENTORY)
    result = p.check_ospf_neighbors("router1")
    assert "Full" in result


@patch("engine.provisioner.ConnectHandler")
def test_check_bgp_summary_established(mock_ch):
    mock_conn = MagicMock()
    mock_conn.send_command.return_value = FAKE_BGP
    mock_ch.return_value = mock_conn

    p = Provisioner(INVENTORY)
    result = p.check_bgp_summary("router1")
    assert "Established" in result


@patch("engine.provisioner.ConnectHandler")
def test_reload_quagga_calls_killall(mock_ch):
    mock_conn = MagicMock()
    mock_conn.send_command.return_value = "ospfd ok"
    mock_ch.return_value = mock_conn

    p = Provisioner(INVENTORY)
    p.reload_quagga("router1")
    assert mock_conn.send_command.called
    call_args = [str(c) for c in mock_conn.send_command.call_args_list]
    assert any("ospfd" in a for a in call_args)


@patch("engine.provisioner.ConnectHandler")
def test_apply_returns_result_per_router(mock_ch):
    mock_conn = MagicMock()
    mock_conn.send_command.return_value = "zebra ok"
    mock_ch.return_value = mock_conn

    p = Provisioner(INVENTORY)
    results = p.apply({})
    assert set(results.keys()) == {"router1", "router2"}


def test_from_intent_builds_inventory():
    intent = {
        "management": [
            {"name": "router1", "host": "10.0.1.2", "port": 22, "username": "root", "password": "root"},
        ]
    }
    p = Provisioner.from_intent(intent)
    assert "router1" in p.inventory
    assert p.inventory["router1"]["host"] == "10.0.1.2"


def test_missing_host_raises_on_connect():
    p = Provisioner({})
    with pytest.raises(KeyError):
        p._connect("nonexistent")
