#!/bin/bash

# Path to .env file where your database credentials are stored
ENV_PATH="/home/bertrampetersen/health_project/.env"

# Source and destination for the database backup
DESTINATION="/media/bertrampetersen/ESD-USB/backups"
BACKUP_FILE="$DESTINATION/health_project_backup_$(date +\%Y\%m\%d\%H\%M\%S).sql"

# Log the start of the backup
echo "Starting backup at $(date)" >> /home/bertrampetersen/health_project/backup.log

# Source the .env file to load database credentials
export $(cat "$ENV_PATH" | grep -v '^#' | xargs)

# Check if the necessary variables exist in the .env file
if [ -z "$MYSQL_USER" ] || [ -z "$MYSQL_PASSWORD" ] || [ -z "$MYSQL_DB" ] || [ -z "$MYSQL_HOST" ]; then
  echo "Error: Missing database credentials in .env file" >> /home/bertrampetersen/health_project/backup.log
  exit 1
fi

# Log the backup file path to ensure it's correct
echo "Backup file will be saved to: $BACKUP_FILE" >> /home/bertrampetersen/health_project/backup.log

# Ensure the backup directory is writable by the script
chmod 777 /media/bertrampetersen/ESD-USB/backups

# Perform the database backup using mysqldump and log any output
/usr/bin/mysqldump -u "$MYSQL_USER" -p"$MYSQL_PASSWORD" -h "$MYSQL_HOST" "$MYSQL_DB" > "$BACKUP_FILE" 2>> /home/bertrampetersen/health_project/backup.log

# Check if the backup was successful
if [ $? -eq 0 ]; then
  echo "Backup completed successfully at $(date)" >> /home/bertrampetersen/health_project/backup.log
else
  echo "Backup failed at $(date)" >> /home/bertrampetersen/health_project/backup.log
  exit 1
fi

# Count the number of backup files in the backups directory
BACKUP_COUNT=$(ls -1 /media/bertrampetersen/ESD-USB/backups/health_project_backup_*.sql 2>/dev/null | wc -l)

# If there are more than 7 backups, delete the oldest
if [ "$BACKUP_COUNT" -gt 7 ]; then
  # Find and remove the oldest backup file
  OLDEST_BACKUP=$(ls -t /media/bertrampetersen/ESD-USB/backups/health_project_backup_*.sql | tail -n 1)
  echo "Removing oldest backup: $OLDEST_BACKUP" >> /home/bertrampetersen/health_project/backup.log
  rm "$OLDEST_BACKUP"
fi
