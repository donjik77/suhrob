#!/bin/bash
# PostgreSQL backup script
# Add to cron: 0 3 * * * /path/to/backup.sh

BACKUP_DIR="/var/backups/suhrob_bot"
DATE=$(date +%Y%m%d_%H%M%S)
CONTAINER="suhrob_bot-db-1"
DB_USER="suhrob"
DB_NAME="suhrob_bot"
KEEP_DAYS=7

mkdir -p "$BACKUP_DIR"

docker exec "$CONTAINER" pg_dump -U "$DB_USER" -d "$DB_NAME" -Fc \
    > "$BACKUP_DIR/backup_${DATE}.dump"

# Remove old backups
find "$BACKUP_DIR" -name "backup_*.dump" -mtime "+${KEEP_DAYS}" -delete

echo "Backup completed: backup_${DATE}.dump"
