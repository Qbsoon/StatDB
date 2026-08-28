#!/bin/sh
set -e

# Fix ownership of the data volume (Docker mounts volumes as root).
if [ -d /app/data ]; then
  chown -R 1000:1000 /app/data 2>/dev/null || true
fi

# Drop to non-root user and exec the command.
exec gosu statdb "$@"
