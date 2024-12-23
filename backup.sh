#!/bin/bash

# sti til credentials
ENV_PATH="/home/bertrampetersen/health_project/.env"

# afsender og destination
DESTINATION="/media/bertrampetersen/ESD-USB/backups"
BACKUP_FILE="$DESTINATION/health_project_backup_$(date +\%Y\%m\%d\%H\%M\%S).sql"

# log start af backup
echo "Starting backup at $(date)" >> /home/bertrampetersen/health_project/backup.log

# load med database credentials
export $(cat "$ENV_PATH" | grep -v '^#' | xargs)

# check om variabler fra .env mangler
if [ -z "$MYSQL_USER" ] || [ -z "$MYSQL_PASSWORD" ] || [ -z "$MYSQL_DB" ] || [ -z "$MYSQL_HOST" ]; then
  echo "Error: Missing database credentials in .env file" >> /home/bertrampetersen/health_project/backup.log
  exit 1
fi

# Log filen for at sikre det er korrekt
echo "Backup file will be saved to: $BACKUP_FILE" >> /home/bertrampetersen/health_project/backup.log

# skift rettigheder til mappen
chmod 777 /media/bertrampetersen/ESD-USB/backups

# Lav backup mysqldump
/usr/bin/mysqldump -u "$MYSQL_USER" -p"$MYSQL_PASSWORD" -h "$MYSQL_HOST" "$MYSQL_DB" > "$BACKUP_FILE" 2>> /home/bertrampetersen/health_project/backup.log

# check om succes
if [ $? -eq 0 ]; then
  echo "Backup completed successfully at $(date)" >> /home/bertrampetersen/health_project/backup.log
else
  echo "Backup failed at $(date)" >> /home/bertrampetersen/health_project/backup.log
  exit 1
fi

# Count the number of backup files in the backups directory
BACKUP_COUNT=$(ls -1 /media/bertrampetersen/ESD-USB/backups/health_project_backup_*.sql 2>/dev/null | wc -l)

# slet ældre backups > 7
if [ "$BACKUP_COUNT" -gt 7 ]; then
  # find og slet ældste
  OLDEST_BACKUP=$(ls -t /media/bertrampetersen/ESD-USB/backups/health_project_backup_*.sql | tail -n 1)
  echo "Removing oldest backup: $OLDEST_BACKUP" >> /home/bertrampetersen/health_project/backup.log
  rm "$OLDEST_BACKUP"
fi
