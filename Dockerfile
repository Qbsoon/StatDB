# ── build stage ─────────────────────────────────────────────
FROM python:3.12-slim AS builder

WORKDIR /build

# Install build deps (none needed now, but keeps layer cache stable).
RUN pip install --no-cache-dir --upgrade pip

COPY pyproject.toml requirements.txt ./
# Install into a prefix we'll copy later.
RUN pip install --no-cache-dir --prefix=/install -r requirements.txt

# ── runtime stage ──────────────────────────────────────────
FROM python:3.12-slim

# Non-root user + gosu for privilege dropping in entrypoint.
RUN apt-get update && apt-get install -y --no-install-recommends gosu \
 && rm -rf /var/lib/apt/lists/* \
 && groupadd --system --gid 1000 statdb \
 && useradd  --system --uid 1000 --gid statdb --home-dir /app --shell /sbin/nologin statdb \
 && mkdir -p /app/data \
 && chown -R statdb:statdb /app

WORKDIR /app

# Copy installed packages from builder.
COPY --from=builder /install /usr/local

# Copy application source + dev entry point (provides `app` ASGI object).
COPY --chown=statdb:statdb app/ ./app/
COPY --chown=statdb:statdb run.py pyproject.toml ./

# Ensure data dir is writable by non-root user (volume mount point).
RUN chown -R statdb:statdb /app/data

# Entrypoint fixes volume ownership before dropping to non-root user.
COPY docker-entrypoint.sh /usr/local/bin/
RUN chmod +x /usr/local/bin/docker-entrypoint.sh

# Expose the default port.
EXPOSE 5000

# Healthcheck: hit the public healthz endpoint.
HEALTHCHECK --interval=30s --timeout=5s --start-period=10s --retries=3 \
  CMD python -c "import urllib.request,sys; sys.exit(0 if urllib.request.urlopen('http://127.0.0.1:5000/api/healthz',timeout=3).status==200 else 1)"

# Run with Hypercorn (ASGI). The app auto-creates data/ and runs migrations
# on first request, so an empty mounted volume works out of the box.
ENV STATDB_HOST=0.0.0.0 \
    STATDB_PORT=5000 \
    STATDB_DATA_DIR=/app/data \
    PYTHONUNBUFFERED=1

ENTRYPOINT ["docker-entrypoint.sh"]
CMD ["hypercorn", "run:app", "--bind", "0.0.0.0:5000"]
