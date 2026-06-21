#!/bin/bash

set -a; source /opt/luas/.env; set +a

DATE=$(date +%Y%m%d)
BACKUP_DIR="/var/backups/luas"
BACKUP_FILE="$BACKUP_DIR/luas_$DATE.sql.gz"

mkdir -p $BACKUP_DIR

# Dump and compress
pg_dump "$DB_URL" | gzip > $BACKUP_FILE

if [ $? -eq 0 ]; then
    echo "Dump created: $BACKUP_FILE"
else
    echo "ERROR: pg_dump failed"
    exit 1
fi

# Upload to Google Drive
rclone copy $BACKUP_FILE gdrive:luas-backups/

if [ $? -eq 0 ]; then
    echo "Uploaded to Google Drive"
else
    echo "ERROR: Upload failed"
    exit 1
fi

# Keep only last 7 backups locally
find $BACKUP_DIR -name "*.sql.gz" -mtime +7 -delete

echo "Backup complete: $BACKUP_FILE"
