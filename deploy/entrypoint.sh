#!/bin/sh
# Volumes mount owned by root: hand /data to the app user, then drop root for the command.
set -e
if [ "$(id -u)" = "0" ]; then
    mkdir -p /data
    chown app:app /data
    exec setpriv --reuid=app --regid=app --init-groups "$@"
fi
exec "$@"
