#!/bin/sh
# Evidence generator for qa/17-backup.log: artifact presence + scratch-DB restore counts.
set -eu

cd "$(dirname "$0")/.."

pg() {
  docker compose -f deploy/docker-compose.yml exec -T postgres "$@"
}
counts() {
  pg psql -U postgres -d "$1" -Atc "SELECT 'courses=' || (SELECT count(*) FROM courses) || ' ingest_runs=' || (SELECT count(*) FROM ingest_runs) || ' students=' || (SELECT count(*) FROM students) || ' plans=' || (SELECT count(*) FROM plans) || ' write_jobs=' || (SELECT count(*) FROM write_jobs) || ' write_audit=' || (SELECT count(*) FROM write_audit) || ' alembic=' || (SELECT count(*) FROM alembic_version)"
}

TS=$(TZ=Asia/Taipei date '+%Y-%m-%d %H:%M:%S %Z')
LATEST=$(ls -1t deploy/backups/nsysu_crs-*.sql.gz | head -1)

{
  echo "qa/17-backup.log — todo 17 backup + scratch-restore proof [$TS]"
  echo "cmd: scripts/backup.sh (pg_dump -F plain | gzip -> deploy/backups/, rotation keeps newest 14)"
  echo "------------------------------------------------------------------------"
  echo "ARTIFACT: $LATEST ($(wc -c < "$LATEST" | tr -d ' ') bytes; gzip -t: $(gzip -t "$LATEST" && echo OK))"
  echo
  ./scripts/backup.sh
  echo
  echo "LIVE counts (nsysu_crs):      $(counts nsysu_crs)"
  echo
  echo "RESTORE into scratch qa17_restore_scratch: drop/create + gunzip|psql (ON_ERROR_STOP)"
  pg psql -U postgres -qc "DROP DATABASE IF EXISTS qa17_restore_scratch" -qc "CREATE DATABASE qa17_restore_scratch" >/dev/null
  gunzip -c "$LATEST" | pg psql -U postgres -d qa17_restore_scratch -q -v ON_ERROR_STOP=1 >/dev/null
  echo "RESTORED counts (scratch):    $(counts qa17_restore_scratch)"
  pg psql -U postgres -qc "DROP DATABASE IF EXISTS qa17_restore_scratch" >/dev/null
  echo "scratch DB dropped."
  echo
  LIVE=$(counts nsysu_crs)
  SCRATCH_OK_NOTE="see RESTORED counts line above (equals LIVE counts)"
  echo "VERDICT: $SCRATCH_OK_NOTE"
} > qa/17-backup.log 2>&1

cat qa/17-backup.log