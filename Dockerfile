FROM python:3.12-slim@sha256:02108f5d322dd89f1c9e552442c25acb0543dfdbc455693a5599624f20d9155d

# Stdlib-only lab: no pip dependencies. Run as a non-root user.
WORKDIR /app
COPY board_server.py dashboard.py agent.py decoy_server.py detect.py control.py run_integrity.py post_metrics.py /app/
RUN adduser --disabled-password --gecos "" appuser \
    && mkdir -p /data && chown appuser /data
USER appuser

# default command is overridden per-service in docker-compose.yml
CMD ["python", "agent.py"]
