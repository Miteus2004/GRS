FROM netubuntu:latest

WORKDIR /app

# install python and pip on top of the base lab image so engine reuses same base
RUN apt-get update && apt-get install -y python3 python3-pip \
	&& rm -rf /var/lib/apt/lists/*

COPY requirements.txt /app/requirements.txt
RUN python3 -m pip install --no-cache-dir -r requirements.txt

COPY engine /app/engine
COPY intent.example.yaml /app/intent.example.yaml
COPY ryu_app /app/ryu_app
EXPOSE 8000
ENTRYPOINT []
CMD ["uvicorn", "engine.app:app", "--host", "0.0.0.0", "--port", "8000"]
