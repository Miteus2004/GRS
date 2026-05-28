Project startup and resume instructions
=====================================

Quick steps to run this project after powering on the machine and logging in.

1) Open a terminal and change to the project directory

```bash
cd /home/miguel/Desktop/uni/GRS
```

2) Activate the Python virtual environment

If you use the repository virtualenv (recommended):

```bash
source .venv/bin/activate
```

If you don't have a virtualenv yet, create one and activate it:

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install --upgrade pip
```

3) Install Python dependencies (only if not already installed or after a fresh clone)

```bash
pip install -r requirements.txt
# or, if using pyproject.toml / poetry, use your chosen tool
```

4) Run tests to verify environment

```bash
pytest -q
```

5) Start required containers (Docker Compose)

Build and start the engine and Ryu (or the whole stack):

```bash
docker compose up -d --build --force-recreate engine ryu
# or to run the full stack:
docker compose up -d --build
```

6) Bootstrap / render templates (dry-run plan)

```bash
python -m engine.main --plan --intent /intent.yaml --templates templates --outdir out
```

7) Run the engine in reconciliation loop (continuous mode)

```bash
python -m engine.main --loop --interval 30 --intent /intent.yaml --templates templates --outdir out
```

8) Run the web dashboard/API (if not already running in Docker)

```bash
uvicorn engine.app:app --host 0.0.0.0 --port 5000
# Dashboard: http://localhost:5000/ (or container-mapped port)
```

9) Useful one-off commands

- Render and write bundle to `out/` without applying changes:

```bash
python -m engine.main --dry-run --intent /intent.yaml --templates templates --outdir out
```

- Show the planner output inside the container (example):

```bash
docker exec -it ibn_engine python -m engine.main --plan --intent /intent.yaml --templates /app/templates --outdir /app/out
```

## Demo Sequence

The demo is easiest to show with two terminals: one for the engine loop and one for the browser or ad-hoc checks.

1. Start the whole lab and open the dashboard.

```bash
docker compose up -d --build
```

Open `http://localhost:5000` and keep the dashboard visible. The new panels are `Sync Status`, `Traffic Path`, `Service Health`, `Delta on Last Run`, `Provisioning Log`, `OSPF Neighbors`, `BGP Summary`, `SDN`, and `Demo Results`.

2. Show a clean initial plan.

```bash
docker exec -it ibn_engine python -m engine.main --plan --intent /intent.yaml --templates /app/templates --outdir /app/out
```

3. Apply the initial configuration and then run the same command again to show idempotency.

```bash
docker exec -it ibn_engine python -m engine.main --provision --intent /intent.yaml --templates /app/templates --outdir /app/out
docker exec -it ibn_engine python -m engine.main --plan --intent /intent.yaml --templates /app/templates --outdir /app/out
```

4. Demonstrate delta provisioning by adding a 5th web replica to `intent.yaml`, then rerun provisioning.

After editing the intent locally, rerun:

```bash
docker exec -it ibn_engine python -m engine.main --provision --intent /intent.yaml --templates /app/templates --outdir /app/out
```

The dashboard should show a new provisioning log entry and `Sync Status` should reflect the delta.

5. Show DNS auto-generation.

When you add or change host entries in `intent.yaml`, rerun provisioning and then verify the generated record from the client container:

```bash
dig @172.16.123.138 www.myorg.net
```

6. Capture the baseline traffic path.

```bash
docker exec -it client traceroute 172.16.123.136
```

Use the `Traffic Path` panel to show whether the engine currently considers the primary or backup path active.

7. Inject congestion and refresh the monitor.

First inspect the client-facing interface name on the router you want to congest:

```bash
docker exec -it org1_router2 ip -br addr
```

Then add a netem delay to the relevant interface, rerun the monitor loop, and refresh the dashboard:

```bash
docker exec -it org1_router2 tc qdisc add dev eth0 root netem delay 200ms
docker exec -it ibn_engine python -m engine.main --monitor --intent /intent.yaml --templates /app/templates --outdir /app/out
```

Remove the delay to restore the interface:

```bash
docker exec -it org1_router2 tc qdisc del dev eth0 root
docker exec -it ibn_engine python -m engine.main --monitor --intent /intent.yaml --templates /app/templates --outdir /app/out
```

The controller now treats a `tc netem` delay on the router as a congestion signal, so this is the demo that should visibly flip the `Traffic Path` panel from `primary` to `backup` and then back again after recovery.

8. Verify SDN flow changes.

Use the dashboard `SDN` panel or inspect the OpenFlow table on a router directly:

```bash
docker compose exec -T router1 ovs-ofctl -O OpenFlow13 dump-flows br0
```

9. Demonstrate backend and router failure handling.

Stop one web backend and rerun reconciliation:

```bash
docker compose stop www4
docker exec -it ibn_engine python -m engine.main --provision --intent /intent.yaml --templates /app/templates --outdir /app/out
```

Then bring it back:

```bash
docker compose start www4
docker exec -it ibn_engine python -m engine.main --provision --intent /intent.yaml --templates /app/templates --outdir /app/out
```

If you want to show router failure behavior, stop a router container and watch the sync panel turn red while the log records the failed check:

```bash
docker compose stop router2
docker exec -it ibn_engine python -m engine.main --monitor --intent /intent.yaml --templates /app/templates --outdir /app/out
```

10. Finish by showing the dashboard history.

The `Provisioning Log` panel should now contain the plan, render, provisioning, and path-switch history that explains the sequence you just ran. The `Service Health` panel shows response times for DNS, the load balancer, and the web backends, `Delta on Last Run` highlights what the engine changed most recently, and `Demo Results` condenses the fault-tolerance counts, SDN path comparison, and timing values into a presentation-friendly summary.

Notes
- If containers fail to start, check `docker compose ps` and container logs with `docker compose logs <service>`.
- `intent.yaml` is mounted into the engine container at `/intent.yaml` in the provided setup; edit it locally and re-run the plan to preview changes.
- Adjust `--interval` to control how frequently the engine reconciles configuration drift.
