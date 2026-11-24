#!/bin/sh
DIR=/backups
KEEP="${BACKUP_KEEP:-7}"
EVERY="${BACKUP_EVERY_HOURS:-24}"
mkdir -p "$DIR"

status() {
  printf '{"state":"%s","action":"%s","file":"%s","message":"%s","at":"%s"}' \
    "$1" "$2" "$3" "$4" "$(date -u +%Y-%m-%dT%H:%M:%SZ)" > "$DIR/.status.tmp"
  mv "$DIR/.status.tmp" "$DIR/.status"
}

do_backup() {
  name="search-$(date -u +%Y-%m-%d_%H%M%S).sql.gz"
  status running backup "$name" ""
  if pg_dump -h db -U postgres -d search | gzip > "$DIR/$name.tmp"; then
    mv "$DIR/$name.tmp" "$DIR/$name"
    status ok backup "$name" ""
  else
    rm -f "$DIR/$name.tmp"
    status failed backup "$name" "pg_dump failed"
    return
  fi
  ls -1t "$DIR"/search-*.sql.gz 2>/dev/null | tail -n +$((KEEP + 1)) | xargs -r rm -f
}

do_restore() {
  name="$1"
  case "$name" in
    */*|*..*|"") status failed restore "$name" "bad name"; return ;;
    search-*.sql.gz) ;;
    *) status failed restore "$name" "bad name"; return ;;
  esac
  if [ ! -f "$DIR/$name" ]; then
    status failed restore "$name" "file not found"
    return
  fi
  status running restore "$name" ""
  pre="search-pre-restore-$(date -u +%Y-%m-%d_%H%M%S).sql.gz"
  if ! pg_dump -h db -U postgres -d search | gzip > "$DIR/$pre"; then
    rm -f "$DIR/$pre"
    status failed restore "$name" "safety backup failed"
    return
  fi
  if (echo "DROP SCHEMA public CASCADE; CREATE SCHEMA public;"; gunzip -c "$DIR/$name") \
    | psql -q -1 -v ON_ERROR_STOP=1 -h db -U postgres -d search > /dev/null 2>&1; then
    status ok restore "$name" "restart app and worker"
  else
    status failed restore "$name" "restore failed, database unchanged"
  fi
}

last=0
while true; do
  now=$(date +%s)
  if [ -f "$DIR/.restore" ]; then
    name=$(cat "$DIR/.restore")
    rm -f "$DIR/.restore"
    do_restore "$name"
  elif [ -f "$DIR/.backup" ]; then
    rm -f "$DIR/.backup"
    do_backup
    last=$now
  elif [ $((now - last)) -ge $((EVERY * 3600)) ]; then
    do_backup
    last=$now
  fi
  sleep 5
done
