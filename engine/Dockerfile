FROM python:3.9-slim

WORKDIR /app

# gcc needed for some netmiko/cryptography deps
RUN apt-get update && apt-get install -y --no-install-recommends gcc libffi-dev && \
    rm -rf /var/lib/apt/lists/*

# Pin setuptools to a version compatible with ryu's setup.py hooks
RUN pip install --no-cache-dir "setuptools==65.5.0"

RUN pip install --no-cache-dir \
    fastapi==0.103.2 \
    "uvicorn[standard]==0.23.2" \
    netmiko==4.3.0 \
    jinja2>=3.1 \
    pyyaml>=6.0 \
    requests>=2.31 \
    dnspython==1.16.0 \
    ryu==4.34 \
    eventlet==0.32.0

# Copy engine package, ryu app, templates, and web app
COPY engine/   ./engine/
COPY ryu_app/  ./ryu_app/
COPY templates/ ./templates/
COPY sitecustomize.py ./
COPY engine/static/   /app/static/

# Make the shim visible to every Python entrypoint, including ryu-manager.
RUN python - <<'PY'
import pathlib
import shutil
import site

source = pathlib.Path('/app/sitecustomize.py')
target = pathlib.Path(site.getsitepackages()[0]) / 'sitecustomize.py'
shutil.copy2(source, target)
PY

# Default: run the FastAPI dashboard from the package
CMD ["uvicorn", "engine.app:app", "--host", "0.0.0.0", "--port", "8000"]
