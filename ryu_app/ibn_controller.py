"""IBN Ryu controller — manages OpenFlow rules and exposes a REST API."""

from __future__ import annotations

import json

from ryu.app.wsgi import ControllerBase, Response, WSGIApplication, route
from ryu.base import app_manager
from ryu.controller import ofp_event
from ryu.controller.handler import CONFIG_DISPATCHER, MAIN_DISPATCHER, set_ev_cls
from ryu.lib.packet import ethernet, packet
from ryu.ofproto import ofproto_v1_3


class IBNController(app_manager.RyuApp):
    """OpenFlow 1.3 controller with REST API for the IBN engine.

    Start with:
        ryu-manager ryu_app/ibn_controller.py --wsapi-port 8080
    """

    OFP_VERSIONS = [ofproto_v1_3.OFP_VERSION]
    _CONTEXTS    = {"wsgi": WSGIApplication}

    def __init__(self, *args, **kwargs) -> None:
        super().__init__(*args, **kwargs)
        self.datapaths: dict[int, object] = {}
        wsgi: WSGIApplication = kwargs["wsgi"]
        wsgi.register(IBNRestAPI, {"controller": self})

    # ── OpenFlow event handlers ──────────────────────────────────────────────

    @set_ev_cls(ofp_event.EventOFPSwitchFeatures, CONFIG_DISPATCHER)
    def switch_features_handler(self, ev) -> None:
        dp = ev.msg.datapath
        self.datapaths[dp.id] = dp
        self.logger.info("Switch connected: dpid=%016x", dp.id)
        self._install_table_miss(dp)

    def _install_table_miss(self, dp) -> None:
        """Send unmatched packets to the controller (lowest priority)."""
        ofp    = dp.ofproto
        parser = dp.ofproto_parser
        match  = parser.OFPMatch()
        actions = [parser.OFPActionOutput(ofp.OFPP_CONTROLLER, ofp.OFPCML_NO_BUFFER)]
        self._add_flow(dp, 0, match, actions)

    @set_ev_cls(ofp_event.EventOFPPacketIn, MAIN_DISPATCHER)
    def packet_in_handler(self, ev) -> None:
        """Default L2 flooding for packets not matched by installed flows."""
        msg    = ev.msg
        dp     = msg.datapath
        ofp    = dp.ofproto
        parser = dp.ofproto_parser
        actions = [parser.OFPActionOutput(ofp.OFPP_FLOOD)]
        out = parser.OFPPacketOut(
            datapath=dp, buffer_id=msg.buffer_id,
            in_port=msg.match["in_port"], actions=actions,
            data=msg.data if msg.buffer_id == ofp.OFP_NO_BUFFER else None,
        )
        dp.send_msg(out)

    # ── Internal helpers ─────────────────────────────────────────────────────

    def _add_flow(self, dp, priority: int, match, actions, hard_timeout: int = 0) -> None:
        ofp    = dp.ofproto
        parser = dp.ofproto_parser
        inst   = [parser.OFPInstructionActions(ofp.OFPIT_APPLY_ACTIONS, actions)]
        mod    = parser.OFPFlowMod(
            datapath=dp, priority=priority, match=match,
            instructions=inst, hard_timeout=hard_timeout,
        )
        dp.send_msg(mod)

    def install_flow(self, dpid: int, priority: int, match_dict: dict, action_list: list) -> dict:
        if dpid not in self.datapaths:
            return {"error": f"datapath {dpid} not connected"}
        dp     = self.datapaths[dpid]
        parser = dp.ofproto_parser
        match   = parser.OFPMatch(**match_dict)
        actions = [parser.OFPActionOutput(a["port"]) for a in action_list if a.get("type") == "OUTPUT"]
        self._add_flow(dp, priority, match, actions)
        self.logger.info("Flow installed: dpid=%d priority=%d match=%s", dpid, priority, match_dict)
        return {"status": "ok", "dpid": dpid, "priority": priority}

    def delete_flow(self, dpid: int, match_dict: dict) -> dict:
        if dpid not in self.datapaths:
            return {"error": f"datapath {dpid} not connected"}
        dp     = self.datapaths[dpid]
        parser = dp.ofproto_parser
        ofp    = dp.ofproto
        match  = parser.OFPMatch(**match_dict)
        mod    = parser.OFPFlowMod(
            datapath=dp, command=ofp.OFPFC_DELETE,
            out_port=ofp.OFPP_ANY, out_group=ofp.OFPG_ANY,
            match=match,
        )
        dp.send_msg(mod)
        return {"status": "deleted", "dpid": dpid}


# ── REST API ─────────────────────────────────────────────────────────────────

class IBNRestAPI(ControllerBase):
    """REST endpoints consumed by engine/sdn.py."""

    def __init__(self, req, link, data, **config) -> None:
        super().__init__(req, link, data, **config)
        self.ctrl: IBNController = data["controller"]

    @route("ibn", "/ibn/switches", methods=["GET"])
    def list_switches(self, req, **_):
        body = json.dumps({"switches": list(self.ctrl.datapaths.keys())})
        return Response(content_type="application/json", body=body)

    @route("ibn", "/ibn/flow", methods=["POST"])
    def add_flow(self, req, **_):
        body   = json.loads(req.body) if req.body else {}
        result = self.ctrl.install_flow(
            dpid        = body.get("dpid"),
            priority    = body.get("priority", 100),
            match_dict  = body.get("match", {}),
            action_list = body.get("actions", []),
        )
        return Response(content_type="application/json", body=json.dumps(result))

    @route("ibn", "/ibn/flow", methods=["DELETE"])
    def remove_flow(self, req, **_):
        body   = json.loads(req.body) if req.body else {}
        result = self.ctrl.delete_flow(
            dpid       = body.get("dpid"),
            match_dict = body.get("match", {}),
        )
        return Response(content_type="application/json", body=json.dumps(result))
