# syntax=docker/dockerfile:1.7
# PIC API and worker image (same image; the worker runs `python -m app.pic.worker`).
#   docker build -t pic-api backend
#   docker build --build-arg WITH_OTEL=true -t pic-api backend      # include the OpenTelemetry SDK + OTLP exporter
# Python 3.14: the code uses uuid.uuid7().

ARG PYTHON_IMAGE=python:3.14-slim-bookworm

FROM ${PYTHON_IMAGE} AS build
ARG WITH_OTEL=false
ENV PIP_NO_CACHE_DIR=1 PIP_DISABLE_PIP_VERSION_CHECK=1
RUN python -m venv /opt/venv
ENV PATH=/opt/venv/bin:$PATH
COPY requirements.txt requirements-otel.txt ./
RUN pip install --upgrade pip && pip install -r requirements.txt \
 && if [ "$WITH_OTEL" = "true" ]; then pip install -r requirements-otel.txt; fi
COPY app /src/app
COPY pic_migrations /src/pic_migrations
COPY alembic /src/alembic
COPY alembic.ini alembic_pic.ini /src/
COPY data /src/data
COPY capability_twin.db /src/capability_twin.db
# Pre-compile so a read-only root filesystem never needs to write .pyc files.
RUN python -m compileall -q /src/app /src/pic_migrations /opt/venv

FROM ${PYTHON_IMAGE} AS runtime
LABEL org.opencontainers.image.title="pic-api" \
      org.opencontainers.image.description="AlphaHelion Purchasing Intelligence Cloud API and worker" \
      org.opencontainers.image.source="https://github.com/OWNER/supplier-capability-twin"
RUN apt-get update && apt-get upgrade -y && apt-get install -y --no-install-recommends libpq5 \
 && rm -rf /var/lib/apt/lists/* \
 && groupadd --gid 10001 pic && useradd --uid 10001 --gid 10001 --no-create-home --home-dir /app --shell /usr/sbin/nologin pic
ENV PATH=/opt/venv/bin:$PATH PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 \
    PIC_ENV=production PIC_LOG_FORMAT=json PIC_WORKER_HEARTBEAT_FILE=/tmp/pic-worker.heartbeat \
    FORWARDED_ALLOW_IPS=*
WORKDIR /app
COPY --from=build /opt/venv /opt/venv
COPY --from=build --chown=root:root /src /app
USER 10001:10001
EXPOSE 8080
HEALTHCHECK --interval=15s --timeout=3s --start-period=20s --retries=3 \
  CMD ["python", "-c", "import sys,urllib.request;sys.exit(0 if urllib.request.urlopen('http://127.0.0.1:8080/healthz',timeout=2).status==200 else 1)"]
# FORWARDED_ALLOW_IPS: the API is reachable only through the web BFF / ingress (NetworkPolicy); narrow it if that changes.
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8080", "--proxy-headers", "--no-server-header", "--no-access-log", "--timeout-graceful-shutdown", "20"]
