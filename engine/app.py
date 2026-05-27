import os

from fastapi import FastAPI
from fastapi.responses import HTMLResponse, JSONResponse
from pathlib import Path
from engine.parser import load_intent as load_intent_file
from engine.renderer import TemplateRenderer
from engine.provisioner import Provisioner
from engine.sdn import RyuClient
from engine.status import collect_sync_status

app = FastAPI()

INTENT_FILE = Path("/intent.yaml")
RYU_URL = os.getenv("RYU_URL", "http://ibn_ryu:8080")
TEMPLATE_DIR = Path(os.getenv("IBN_TEMPLATE_DIR", "/app/templates"))
OUTPUT_DIR = Path(os.getenv("IBN_OUTDIR", "/app/out"))


def _ryu_client() -> RyuClient:
    return RyuClient(RYU_URL)


def build_inventory(intent: dict):
    inventory = {}
    for entry in intent.get("management", []):
        inventory[entry["name"]] = {
            "host": entry["host"],
            "port": entry.get("port", 22),
            "username": entry.get("username", "root"),
            "password": entry.get("password", "root"),
        }
    return inventory

def load_intent():
    return load_intent_file(INTENT_FILE)


@app.on_event("startup")
def bootstrap_output_bundle() -> None:
    """Render the current intent bundle so the dashboard can compare against a baseline."""
    intent = load_intent()
    renderer = TemplateRenderer(TEMPLATE_DIR)
    renderer.write_bundle(intent, OUTPUT_DIR)


def parse_ospf(text: str):
    """Parse `show ip ospf neighbor` output into list of dicts."""
    lines = [l.rstrip() for l in text.splitlines()]
    out = []
    if not lines:
        return out
    # find header line index
    header_idx = 0
    for i, l in enumerate(lines):
        if l.strip().startswith("Neighbor ID"):
            header_idx = i
            break
    for l in lines[header_idx + 1 :]:
        if not l.strip():
            continue
        parts = l.split()
        # neighbor_id, pri, state, dead, address, interface, rxmtl, rqstl, dbsml
        if len(parts) >= 9:
            neighbor = {
                "neighbor_id": parts[0],
                "pri": parts[1],
                "state": parts[2],
                "dead_time": parts[3],
                "address": parts[4],
                "interface": parts[5],
                "rxmtl": parts[6],
                "rqstl": parts[7],
                "dbsml": parts[8],
            }
        else:
            # fallback: keep raw line
            neighbor = {"raw": l}
        out.append(neighbor)
    return out


def parse_bgp(text: str):
    """Parse `show bgp summary` into structured dict with peers list."""
    lines = [l.rstrip() for l in text.splitlines()]
    peers = []
    in_table = False
    headers = []
    for l in lines:
        if not in_table and l.strip().startswith("Neighbor"):
            in_table = True
            headers = l.split()
            continue
        if in_table:
            if not l.strip():
                # end of table
                in_table = False
                continue
            parts = l.split()
            # try to map columns; neighbor is first column
            if len(parts) >= 10:
                state_or_pfx = parts[9:]
                if len(state_or_pfx) == 1 and state_or_pfx[0].isdigit():
                    state = "Established"
                    pfx_rcd = state_or_pfx[0]
                else:
                    state = " ".join(state_or_pfx)
                    pfx_rcd = None
                peer = {
                    "neighbor": parts[0],
                    "version": parts[1],
                    "remote_as": parts[2],
                    "msg_rcvd": parts[3],
                    "msg_sent": parts[4],
                    "tblver": parts[5],
                    "inq": parts[6],
                    "outq": parts[7],
                    "up_down": parts[8],
                    "state": state,
                    "pfx_rcd": pfx_rcd,
                }
            else:
                peer = {"raw": l}
            peers.append(peer)
    return {"peers": peers, "raw": text}

@app.get("/api/ospf_neighbors")
def ospf_neighbors():
    intent = load_intent()
    inv = build_inventory(intent)
    p = Provisioner(inv)
    results = {}
    for name in inv:
        try:
            raw = p.check_ospf_neighbors(name)
            results[name] = {"raw": raw, "parsed": parse_ospf(raw)}
        except Exception as e:
            results[name] = {"error": str(e)}
    return JSONResponse(results)

@app.get("/api/bgp_summary")
def bgp_summary():
    intent = load_intent()
    inv = build_inventory(intent)
    p = Provisioner(inv)
    results = {}
    for name in inv:
        try:
            raw = p.check_bgp_summary(name)
            results[name] = parse_bgp(raw)
        except Exception as e:
            results[name] = {"error": str(e)}
    return JSONResponse(results)


@app.get("/api/ryu/switches")
def ryu_switches():
    try:
        switches = _ryu_client().list_switches()
        return JSONResponse({"switches": switches})
    except Exception as exc:
        return JSONResponse({"error": str(exc)}, status_code=502)


@app.get("/api/sync_status")
def sync_status():
    try:
        intent = load_intent()
        status = collect_sync_status(intent, TEMPLATE_DIR, OUTPUT_DIR, RYU_URL)
        return JSONResponse(status)
    except Exception as exc:
        return JSONResponse({"error": str(exc)}, status_code=502)


@app.post("/api/ryu/activate_path")
def ryu_activate_path(payload: dict):
    profile = payload.get("profile", "primary")
    try:
        client = _ryu_client()
        switches = client.list_switches()
        results = []
        for dpid in switches:
            results.append(client.activate_path(dpid, profile))
        return JSONResponse({"profile": profile, "switches": switches, "results": results})
    except Exception as exc:
        return JSONResponse({"error": str(exc)}, status_code=502)

@app.get("/")
def index():
    html = Path("/app/static/index.html").read_text(encoding="utf-8")
    return HTMLResponse(html)
