# core/management/commands/backup_database_s3.py
#
# AWS version of backup_database.py. Same behaviour (pg_dump -> upload ->
# rotate old backups -> email), but stores backups in Amazon S3 using the
# EC2 instance's IAM role (no credentials file needed).
# The original backup_database.py (Google Cloud Storage) is left untouched
# so Render keeps working until cutover.
from django.core.management.base import BaseCommand
from django.conf import settings
from django.core.mail import send_mail
from django.utils import timezone
import subprocess
import os
import logging
from datetime import datetime, timedelta
import boto3

logger = logging.getLogger(__name__)


class Command(BaseCommand):
    help = 'Create PostgreSQL backup and upload to Amazon S3 with automatic rotation'

    # Configuration
    RETENTION_WEEKS = 52
    BUCKET_NAME = 'partnersteps-t2d-dev-backups'  # S3 bucket name
    BACKUP_FOLDER = 'backups'  # Folder (key prefix) within bucket
    AWS_REGION = 'ca-central-1'

    def add_arguments(self, parser):
        parser.add_argument(
            '--dry-run',
            action='store_true',
            help='Show what would be done without actually doing it',
        )
        parser.add_argument(
            '--test-connection',
            action='store_true',
            help='Test S3 connection and exit',
        )

    def handle(self, *args, **options):
        start_time = timezone.now()
        self.stdout.write(f"Starting backup at {start_time.strftime('%Y-%m-%d %H:%M:%S')}\n")

        self.dry_run = options['dry_run']

        if self.dry_run:
            self.stdout.write(self.style.WARNING("DRY RUN MODE - No actual backup or upload\n"))

        # Test connection mode
        if options['test_connection']:
            return self.test_s3_connection()

        backup_file = None  # Track the file for cleanup
        try:
            # Step 1: Create database dump
            self.stdout.write("Step 1: Creating database dump...")
            backup_file = self.create_database_dump()

            if not backup_file:
                raise Exception("Failed to create database dump")

            self.stdout.write(self.style.SUCCESS(f"✓ Created dump: {backup_file}"))

            # Step 2: Upload to S3
            self.stdout.write("\nStep 2: Uploading to Amazon S3...")
            s3_key = self.upload_to_s3(backup_file)

            if not s3_key:
                raise Exception("Failed to upload to Amazon S3")

            self.stdout.write(self.style.SUCCESS(f"✓ Uploaded to: s3://{self.BUCKET_NAME}/{s3_key}"))

            # Step 3: Clean up old backups
            self.stdout.write("\nStep 3: Cleaning up old backups...")
            deleted_count = self.cleanup_old_backups()
            self.stdout.write(self.style.SUCCESS(f"✓ Deleted {deleted_count} old backup(s)"))

            # Success!
            end_time = timezone.now()
            duration = (end_time - start_time).total_seconds()

            success_message = f"""
Backup completed successfully in {duration:.1f} seconds

Database: {self.get_database_name()}
Backup file: s3://{self.BUCKET_NAME}/{s3_key}
Size: {self.get_file_size_mb(backup_file):.2f} MB
Retention: {self.RETENTION_WEEKS} weeks
"""

            self.stdout.write(self.style.SUCCESS("\n" + "="*70))
            self.stdout.write(self.style.SUCCESS(success_message))
            self.stdout.write(self.style.SUCCESS("="*70))

            # Send success email
            self.send_notification_email(
                success=True,
                message=success_message,
                backup_path=f"s3://{self.BUCKET_NAME}/{s3_key}"
            )

        except Exception as e:
            error_message = f"Backup failed: {str(e)}"
            logger.error(error_message)
            self.stderr.write(self.style.ERROR(f"\n✗ {error_message}"))

            # Send failure email
            self.send_notification_email(
                success=False,
                message=error_message,
                error=str(e)
            )

            raise
        finally:
            # Always clean up local file, even on failure
            if backup_file and not self.dry_run and os.path.exists(backup_file):
                try:
                    os.remove(backup_file)
                    self.stdout.write(self.style.SUCCESS(f"✓ Cleaned up local file"))
                except Exception as cleanup_error:
                    logger.warning(f"Failed to cleanup {backup_file}: {cleanup_error}")

    def get_s3_client(self):
        """Get S3 client. Credentials come from the EC2 instance's IAM role."""
        return boto3.client('s3', region_name=self.AWS_REGION)

    def get_database_config(self):
        """Extract database configuration from Django settings."""
        db_config = settings.DATABASES['default']

        # Handle dj-database-url format
        db_url = os.environ.get('DATABASE_URL')
        if db_url:
            # Parse DATABASE_URL: postgres://user:pass@host:port/dbname?sslmode=require
            from urllib.parse import urlparse, unquote, parse_qs
            parsed = urlparse(db_url)

            # Handle both postgres:// and postgresql:// schemes
            if parsed.scheme not in ('postgres', 'postgresql'):
                logger.warning(f"Unexpected database scheme: {parsed.scheme}")

            sslmode = parse_qs(parsed.query).get('sslmode', [None])[0]

            return {
                'host': parsed.hostname,
                'port': parsed.port or 5432,
                'user': unquote(parsed.username) if parsed.username else None,
                'password': unquote(parsed.password) if parsed.password else None,
                'name': parsed.path[1:],  # Remove leading slash
                'sslmode': sslmode,
            }

        return {
            'host': db_config.get('HOST', 'localhost'),
            'port': db_config.get('PORT', 5432),
            'user': db_config.get('USER'),
            'password': db_config.get('PASSWORD'),
            'name': db_config.get('NAME'),
            'sslmode': None,
        }

    def get_database_name(self):
        """Get the database name for logging."""
        config = self.get_database_config()
        return config['name']

    def create_database_dump(self):
        """Create a compressed PostgreSQL dump using pg_dump."""
        if self.dry_run:
            return "/tmp/gdm-backup-dry-run.dump"

        config = self.get_database_config()
        timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
        backup_filename = f"gdm-backup-{timestamp}.dump"
        backup_path = os.path.join('/tmp', backup_filename)

        # Build pg_dump command
        # Using custom format (-Fc) which is compressed and optimal for pg_restore
        cmd = [
            'pg_dump',
            '-Fc',  # Custom format (compressed)
            '-h', config['host'],
            '-p', str(config['port']),
            '-U', config['user'],
            '-d', config['name'],
            '-f', backup_path,
        ]

        # Set password (and SSL mode, if the URL specifies one) via environment
        env = os.environ.copy()
        env['PGPASSWORD'] = config['password']
        if config.get('sslmode'):
            env['PGSSLMODE'] = config['sslmode']

        try:
            result = subprocess.run(
                cmd,
                env=env,
                capture_output=True,
                text=True,
                check=True
            )

            # Verify file was created and has content
            if os.path.exists(backup_path) and os.path.getsize(backup_path) > 0:
                return backup_path
            else:
                logger.error("Backup file not created or is empty")
                return None

        except subprocess.CalledProcessError as e:
            logger.error(f"pg_dump failed: {e.stderr}")
            return None

    def upload_to_s3(self, local_file):
        """Upload backup file to Amazon S3."""
        if self.dry_run:
            return f"{self.BACKUP_FOLDER}/{os.path.basename(local_file)}"

        try:
            s3 = self.get_s3_client()

            # Prepare S3 key
            filename = os.path.basename(local_file)
            key = f"{self.BACKUP_FOLDER}/{filename}"

            # Upload file (bucket default encryption applies automatically)
            s3.upload_file(local_file, self.BUCKET_NAME, key)

            return key

        except Exception as e:
            logger.error(f"S3 upload failed: {e}")
            raise Exception(f"Failed to upload to Amazon S3: {str(e)}")

    def cleanup_old_backups(self):
        """Delete backups older than RETENTION_WEEKS."""
        if self.dry_run:
            return 0

        try:
            s3 = self.get_s3_client()

            # Calculate cutoff date - timezone.now() returns UTC-aware datetime
            cutoff_date = timezone.now() - timedelta(weeks=self.RETENTION_WEEKS)

            deleted_count = 0
            paginator = s3.get_paginator('list_objects_v2')
            for page in paginator.paginate(Bucket=self.BUCKET_NAME, Prefix=f"{self.BACKUP_FOLDER}/"):
                for obj in page.get('Contents', []):
                    # LastModified is timezone-aware UTC from boto3
                    if obj['LastModified'] < cutoff_date:
                        s3.delete_object(Bucket=self.BUCKET_NAME, Key=obj['Key'])
                        deleted_count += 1
                        self.stdout.write(f"  Deleted: {obj['Key']}")

            return deleted_count

        except Exception as e:
            logger.error(f"S3 cleanup error: {e}")
            return 0

    def get_file_size_mb(self, filepath):
        """Get file size in MB."""
        if self.dry_run or not os.path.exists(filepath):
            return 0.0
        return os.path.getsize(filepath) / (1024 * 1024)

    def send_notification_email(self, success, message, backup_path=None, error=None):
        """Send email notification about backup status."""
        if self.dry_run:
            self.stdout.write("Would send email notification")
            return

        # Get email settings
        from_email = getattr(settings, 'DEFAULT_FROM_EMAIL', 'john.dowling@rimuhc.ca')
        admin_emails = getattr(settings, 'ADMIN_NOTIFICATION_EMAIL', [from_email])

        # Handle both single email (string) and multiple emails (list)
        recipient_list = admin_emails if isinstance(admin_emails, list) else [admin_emails]

        if success:
            subject = "✓ Database Backup Successful"
            body = f"""Database Backup Completed Successfully

{message}

Amazon S3 Path: {backup_path}

This is an automated notification from the backup system.
"""
        else:
            subject = "✗ Database Backup FAILED"
            body = f"""Database Backup Failed

Error: {error}

Details:
{message}

Action Required: Please investigate the backup system immediately.

This is an automated notification from the backup system.
"""

        try:
            send_mail(
                subject=subject,
                message=body,
                from_email=from_email,
                recipient_list=recipient_list,
                fail_silently=False,
            )
            logger.info(f"Sent backup notification email to {recipient_list}")
        except Exception as e:
            logger.error(f"Failed to send notification email: {e}")
            # Don't raise - backup succeeded even if email failed

    def test_s3_connection(self):
        """Test S3 connection and display bucket info."""
        self.stdout.write("Testing Amazon S3 connection...\n")

        try:
            s3 = self.get_s3_client()

            # Check that the bucket exists and we have access
            s3.head_bucket(Bucket=self.BUCKET_NAME)

            self.stdout.write(self.style.SUCCESS("✓ Connection successful!"))
            self.stdout.write(f"\nBucket: {self.BUCKET_NAME}")
            self.stdout.write(f"Region: {self.AWS_REGION}")

            # List existing backups
            objects = []
            paginator = s3.get_paginator('list_objects_v2')
            for page in paginator.paginate(Bucket=self.BUCKET_NAME, Prefix=f"{self.BACKUP_FOLDER}/"):
                objects.extend(page.get('Contents', []))

            self.stdout.write(f"\n✓ Backup folder: {self.BACKUP_FOLDER}/")
            self.stdout.write(f"  Contains {len(objects)} file(s)")

            if objects:
                self.stdout.write("\n  Recent backups:")
                for obj in sorted(objects, key=lambda o: o['LastModified'], reverse=True)[:5]:
                    size_mb = obj['Size'] / (1024 * 1024)
                    self.stdout.write(f"    - {obj['Key']} ({size_mb:.2f} MB, {obj['LastModified'].strftime('%Y-%m-%d %H:%M')})")

        except Exception as e:
            self.stderr.write(self.style.ERROR(f"✗ Connection failed: {e}"))