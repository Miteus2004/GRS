"""Tests for the FastAPI dashboard helpers."""

from __future__ import annotations

from engine.app import parse_bgp


FAKE_BGP_ESTABLISHED = """
BGP router identifier 1.1.1.1, local AS number 65001
Neighbor        V    AS MsgRcvd MsgSent   TblVer  InQ OutQ Up/Down  State/PfxRcd
172.31.255.252  4 65002     120     118        0    0    0 01:02:03 0
"""


FAKE_BGP_ACTIVE = """
BGP router identifier 1.1.1.1, local AS number 65001
Neighbor        V    AS MsgRcvd MsgSent   TblVer  InQ OutQ Up/Down  State/PfxRcd
172.31.255.252  4 65002       0       0        0    0    0 never    Active
"""


def test_parse_bgp_marks_established_sessions():
    result = parse_bgp(FAKE_BGP_ESTABLISHED)
    peer = result["peers"][0]
    assert peer["state"] == "Established"
    assert peer["pfx_rcd"] == "0"


def test_parse_bgp_keeps_non_established_state():
    result = parse_bgp(FAKE_BGP_ACTIVE)
    peer = result["peers"][0]
    assert peer["state"] == "Active"
    assert peer["pfx_rcd"] is None
