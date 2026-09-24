#!/usr/bin/env bash
# Import a private Mac snapshot into the single-user Ubuntu deployment.
set -Eeuo pipefail

APP_DIR=/opt/study-agent
APP_USER=studyagent
SERVICE=study-agent
ARCHIVE=${1:-}

if [[ $EUID -ne 0 || -z $ARCHIVE || ! -f $ARCHIVE ]]; then
    echo "Usage (as root): $0 /path/to/study-agent-migrate-*.tar.gz" >&2
    exit 2
fi

STAGING=$(mktemp -d /root/study-agent-import.XXXXXXXX)
BACKUP=
STOPPED=0
INSTALL_STARTED=0
FILES=(study_agent.db mastery.db backend/patterns.yaml backend/settings.json .env)

finish() {
    local code=$?
    trap - EXIT
    if (( code != 0 && STOPPED == 1 )); then
        echo "Import failed; restoring the previous server data." >&2
        if (( INSTALL_STARTED == 1 )); then
            systemctl stop "$SERVICE" || true
            for relative in "${FILES[@]}"; do
                if [[ -f $BACKUP/$relative ]]; then
                    install -D -o "$APP_USER" -g "$APP_USER" -m 600 \
                        "$BACKUP/$relative" "$APP_DIR/$relative" || true
                else
                    rm -f -- "$APP_DIR/$relative"
                fi
            done
        fi
        systemctl start "$SERVICE" || true
    fi
    rm -rf -- "$STAGING"
    exit "$code"
}
trap finish EXIT

chmod 600 "$ARCHIVE"
python3 - "$ARCHIVE" "$STAGING" <<'PY'
import json
import os
import shutil
import sqlite3
import sys
import tarfile
from pathlib import Path

archive, staging = sys.argv[1], Path(sys.argv[2])
expected = {"study_agent.db", "mastery.db", "patterns.yaml", "settings.json", ".env"}
with tarfile.open(archive, "r:gz") as bundle:
    members = {member.name: member for member in bundle.getmembers()}
    if set(members) != expected or not all(member.isfile() for member in members.values()):
        raise SystemExit("Archive contents do not match the expected five files")
    for name in expected:
        source = bundle.extractfile(members[name])
        if source is None:
            raise SystemExit("Cannot read " + name)
        target = staging / name
        with source, target.open("wb") as destination:
            shutil.copyfileobj(source, destination)
        os.chmod(target, 0o600)

for name in ("study_agent.db", "mastery.db"):
    with sqlite3.connect(str(staging / name)) as db:
        if db.execute("PRAGMA integrity_check").fetchone()[0] != "ok":
            raise SystemExit(name + " failed SQLite integrity check")
with (staging / "settings.json").open(encoding="utf-8") as stream:
    if not isinstance(json.load(stream), dict):
        raise SystemExit("settings.json is not an object")
with sqlite3.connect(str(staging / "study_agent.db")) as db:
    count = db.execute("SELECT COUNT(*) FROM questions").fetchone()[0]
print(f"Archive validated; questions: {count}", flush=True)
PY

"$APP_DIR/.venv/bin/python" - "$STAGING/patterns.yaml" <<'PY'
import sys
import yaml
with open(sys.argv[1], encoding="utf-8") as stream:
    if not isinstance(yaml.safe_load(stream), dict):
        raise SystemExit("patterns.yaml is not a mapping")
PY

BACKUP=$(mktemp -d /root/study-agent-before-import.XXXXXXXX)
systemctl stop "$SERVICE"
STOPPED=1
for relative in "${FILES[@]}"; do
    if [[ -f $APP_DIR/$relative ]]; then
        mkdir -p "$BACKUP/$(dirname "$relative")"
        cp -a -- "$APP_DIR/$relative" "$BACKUP/$relative"
    fi
done
echo "Previous server data backed up to $BACKUP"

INSTALL_STARTED=1
install -o "$APP_USER" -g "$APP_USER" -m 600 "$STAGING/study_agent.db" "$APP_DIR/study_agent.db"
install -o "$APP_USER" -g "$APP_USER" -m 600 "$STAGING/mastery.db" "$APP_DIR/mastery.db"
install -o "$APP_USER" -g "$APP_USER" -m 600 "$STAGING/patterns.yaml" "$APP_DIR/backend/patterns.yaml"
install -o "$APP_USER" -g "$APP_USER" -m 600 "$STAGING/settings.json" "$APP_DIR/backend/settings.json"
install -o "$APP_USER" -g "$APP_USER" -m 600 "$STAGING/.env" "$APP_DIR/.env"

systemctl start "$SERVICE"
ready=0
for _ in $(seq 1 30); do
    if curl -fsS http://127.0.0.1:8000/openapi.json >/dev/null 2>&1; then
        ready=1
        break
    fi
    sleep 1
done
if (( ready != 1 )); then
    echo "Imported service did not become ready; rolling back" >&2
    exit 1
fi
echo "Import complete; service is ready. Backup: $BACKUP"
