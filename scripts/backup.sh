#!/bin/sh
KEEP="${BACKUP_KEEP:-7}"
EVERY="${BACKUP_EVERY_HOURS:-24}"
mkdir -p /backups
while true; do
  name="/backups/search-$(date +%Y-%m-%d_%H%M).sql.gz"
  if pg_dump -h db -U postgres -d search | gzip > "$name.tmp"; then
    mv "$name.tmp" "$name"
    echo "backup ok: $name"
  else
    rm -f "$name.tmp"
    echo "backup failed"
  fi
  ls -1t /backups/search-*.sql.gz 2>/dev/null | tail -n +$((KEEP + 1)) | xargs -r rm -f
  sleep $((EVERY * 3600))
done
