FROM python:3.11-slim

WORKDIR /app
RUN pip install --no-cache-dir fastapi uvicorn pydantic

COPY server.py /app/server.py
COPY entrypoint.sh /entrypoint.sh
RUN chmod +x /entrypoint.sh

# ENTRYPOINT (not CMD) so k8s `args:` get appended to our wrapper,
# which then execs uvicorn. The wrapper ignores unknown flags like
# --model <name> and --port 8000 (we hardcode port in the wrapper).
ENTRYPOINT ["/entrypoint.sh"]