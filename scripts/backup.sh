#!/bin/sh
# scripts/backup.sh — daily Postgres dump with 14-file rotation (plan todo 17).
#
# Dumps the compose `nsysu_crs` database as a gzipped plain-SQL archive into
# deploy/backups/nsysu_crs-YYYYMMDD-HHMMSS.sql.gz, then deletes every archive
# beyond the newest 14. Files land on the HOST filesystem (deploy/backups),
# outside the Postgres container.
#
# Schedule: cron-style, daily at 03:17 Asia/Taipei (off the ingest tick):
#   17 3 * * * TZ=Asia/Taipei /absolute/path/to/repo/scripts/backup.sh >> /var/log/nsysu-crs-backup.log 2>&1
# (also documented in docs/runbook.md; a host systemd timer is an equivalent
# alternative - any host scheduler that runs this script daily works.)
#
# Exit 0 on success; non-zero leaves the partial file deleted and the newest
# backups untouched.

set -eu

REPO_ROOT=$(CDPATH='' cd -- "$(dirname -- "$0")/.." && pwd)
COMPOSE="docker compose -f $REPO_ROOT/deploy/docker-compose.yml"
BACKUP_DIR="$REPO_ROOT/deploy/backups"
NAME="nsysu_crs-$(TZ=Asia/Taipei date +%Y%m%d-%H%M%S).sql.gz"
TMP="$BACKUP_DIR/$NAME.partial"

mkdir -p "$BACKUP_DIR"

if ! $COMPOSE exec -T postgres pg_isready -U postgres -d nsysu_crs >/dev/null 2>&1; then
  echo "[backup.sh] FAIL: compose postgres is not healthy; nothing produced" >&2
  exit 1
fi

if ! $COMPOSE exec -T postgres pg_dump -U postgres -d nsysu_crs --format=plain | gzip -1 > "$TMP"; then
  echo "[backup.sh] FAIL: pg_dump pipeline broke" >&2
  rm -f "$TMP"
  exit 1
fi
mv "$TMP" "$BACKUP_DIR/$NAME"
SIZE=$(wc -c < "$BACKUP_DIR/$NAME" | tr -d ' ')
echo "[backup.sh] wrote deploy/backups/$NAME ($SIZE bytes)"

# Rotation: keep the newest 14 archives, delete the rest.
ls -1t "$BACKUP_DIR"/nsysu_crs-*.sql.gz 2>/dev/null | tail -n +15 | while IFS= read -r old; do
  echo "[backup.sh] rotating out ${old#$REPO_ROOT/}"
  rm -f "$old"
done
echo "[backup.sh] done: $(ls -1 "$BACKUP_DIR"/nsysu_crs-*.sql.gz 2>/dev/null | wc -l | tr -d ' ') archives kept"
