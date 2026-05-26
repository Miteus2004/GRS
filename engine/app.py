from fastapi import FastAPI
from fastapi.responses import HTMLResponse, JSONResponse
from pathlib import Path
import yaml
from engine.provisioner import Provisioner

app = FastAPI()

INTENT_FILE = Path("/intent.example.yaml")


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
    with open(INTENT_FILE) as f:
        return yaml.safe_load(f)


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
                    "state": " ".join(parts[9:]),
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

@app.get("/")
def index():
    html = Path("/app/static/index.html").read_text(encoding="utf-8")
    return HTMLResponse(html)
