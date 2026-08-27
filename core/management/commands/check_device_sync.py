# core/management/commands/check_device_sync.py
from django.core.management.base import BaseCommand
from django.utils import timezone
from django.conf import settings
from core.models import Participant
from datetime import datetime, timedelta, date
import logging

logger = logging.getLogger(__name__)


class Command(BaseCommand):
    help = 'Check for participants with device sync issues and send notifications'
    
    # Alert thresholds (in days)
    PARTICIPANT_ALERT_DAYS = 1
    ADMIN_ALERT_DAYS = 2
    
    def add_arguments(self, parser):
        parser.add_argument(
            '--participant-id',
            type=int,
            help='Check sync for a specific participant ID only',
        )
        parser.add_argument(
            '--dry-run',
            action='store_true',
            help='Show what would be done without sending notifications or updating database',
        )
        parser.add_argument(
            '--verbose',
            action='store_true',
            help='Show detailed output for all participants',
        )
    
    def handle(self, *args, **options):
        start_time = timezone.now()
        self.stdout.write(f"Starting device sync check at {start_time.strftime('%Y-%m-%d %H:%M:%S')}\n")
        
        self.dry_run = options['dry_run']
        self.verbose = options['verbose']
        
        if self.dry_run:
            self.stdout.write(self.style.WARNING("DRY RUN MODE - No notifications will be sent, no database changes\n"))
        
        # Get participants to process
        if options['participant_id']:
            try:
                participant = Participant.objects.get(id=options['participant_id'])
                all_participants = [participant]
            except Participant.DoesNotExist:
                self.stderr.write(
                    self.style.ERROR(f"Participant {options['participant_id']} not found")
                )
                return
        else:
            # Get only participants with active users
            all_participants = Participant.objects.select_related('user').filter(
                user__is_active=True
            ).all()
        
        if not all_participants:
            self.stdout.write(self.style.WARNING("No active participants to check"))
            return
        
        self.stdout.write(f"Checking {len(all_participants)} active participant(s)...\n")
        
        # Get today's date for checking sync status
        today = timezone.now().date()
        
        # Counters for summary
        syncing_ok = 0
        new_participant_warnings = 0
        new_admin_warnings = 0
        already_warned = 0
        warnings_cleared = 0
        
        for participant in all_participants:
            result = self.check_participant_sync(participant, today)
            
            if result == 'syncing_ok':
                syncing_ok += 1
            elif result == 'new_participant_warning':
                new_participant_warnings += 1
            elif result == 'new_admin_warning':
                new_admin_warnings += 1
            elif result == 'already_warned':
                already_warned += 1
            elif result == 'warning_cleared':
                warnings_cleared += 1
        
        # Summary
        end_time = timezone.now()
        duration = (end_time - start_time).total_seconds()
        
        self.stdout.write("\n" + "="*70)
        self.stdout.write(f"Completed in {duration:.1f} seconds")
        self.stdout.write(self.style.SUCCESS(f"  ✓ Syncing OK: {syncing_ok}"))
        
        if new_participant_warnings > 0:
            self.stdout.write(
                self.style.WARNING(f"  ⚠  New Participant Warnings: {new_participant_warnings}")
            )
        if new_admin_warnings > 0:
            self.stdout.write(
                self.style.ERROR(f"  ✗ New Admin Warnings: {new_admin_warnings}")
            )
        if already_warned > 0:
            self.stdout.write(f"  ℹ  Already Warned: {already_warned}")
        if warnings_cleared > 0:
            self.stdout.write(
                self.style.SUCCESS(f"  ✓ Warnings Cleared: {warnings_cleared}")
            )
        self.stdout.write("="*70)
    
    def check_participant_sync(self, participant, today):
        """
        Check a single participant's sync status and send notifications if needed.
        Returns a status string for summary reporting.
        """
        # Safety check - ensure participant has a user with email
        if not participant.user or not participant.user.email:
            if self.verbose:
                self.stdout.write(f"  Participant ID {participant.id}: No user or email - skipping")
            return 'syncing_ok'
        
        email = participant.user.email
        
        # Check if we previously had an error but it's now cleared
        # Safely handle device_sync_status (could be None)
        current_status = participant.device_sync_status or {}
        had_fitbit_error_before = current_status.get('had_fitbit_error', False)
        
        # Safely check status_flags (could be None)
        status_flags = participant.status_flags or {}
        has_fitbit_error_now = (
            status_flags.get('fetch_fitbit_data_fail', False) or
            status_flags.get('refresh_fitbit_token_fail', False)
        )
        
        # If error was cleared, reset warnings to start fresh
        # (Previous warnings were for technical issues, now it's a user sync issue)
        if had_fitbit_error_before and not has_fitbit_error_now:
            if self.verbose:
                self.stdout.write(f"  {email}: Fitbit error cleared - resetting warnings")
            if not self.dry_run:
                self.clear_device_sync_warning(participant)
            # Reset current_status since we just cleared it
            current_status = {}
        
        # Get today's step data
        daily_steps_dict = {}
        if participant.daily_steps is not None:
            for entry in participant.daily_steps:
                date_key = entry.get('date')
                steps_value = entry.get('value')
                if date_key and steps_value is not None:
                    daily_steps_dict[date_key] = int(steps_value)
        
        today_str = today.strftime('%Y-%m-%d')
        today_steps = daily_steps_dict.get(today_str, 0)
        
        # STEP 1: Check if today has >= 1 step (device is syncing)
        if today_steps >= 1:
            # Device is syncing! Clear any warnings if they exist
            if current_status.get('warning_started_date'):
                # Had a warning, now cleared
                if self.verbose:
                    self.stdout.write(
                        self.style.SUCCESS(f"✓ {email}: Syncing resumed ({today_steps} steps today)")
                    )
                if not self.dry_run:
                    self.clear_device_sync_warning(participant)
                return 'warning_cleared'
            else:
                # No warning, all good
                if self.verbose:
                    self.stdout.write(f"  {email}: OK ({today_steps} steps today)")
                return 'syncing_ok'
        
        # STEP 2: No data for today - count consecutive missing days
        consecutive_missing = self.count_consecutive_missing_days(participant, today, daily_steps_dict)
        
        if consecutive_missing < self.PARTICIPANT_ALERT_DAYS:
            # Less than threshold - just monitoring
            if self.verbose:
                if consecutive_missing == 1:
                    self.stdout.write(f"  {email}: 1 day missing - monitoring")
                else:
                    self.stdout.write(f"  {email}: OK (recent data)")
            return 'syncing_ok'
        
        # STEP 3: threshold+ days missing - check for Fitbit API/token errors FIRST
        has_fitbit_error = has_fitbit_error_now  # Use the value we calculated earlier
        
        participant_notified = current_status.get('participant_notified_date')
        admin_notified = current_status.get('admin_notified_date')
        
        if has_fitbit_error:
            # Technical error detected - notify admin regardless of day count
            if not admin_notified:
                error_msg = ""
                if status_flags.get('fetch_fitbit_data_fail'):
                    error_msg = status_flags.get('fetch_fitbit_data_fail_last_error', 'Unknown error')
                elif status_flags.get('refresh_fitbit_token_fail'):
                    error_msg = status_flags.get('refresh_fitbit_token_fail_last_error', 'Unknown error')
                
                self.stdout.write(
                    self.style.ERROR(
                        f"✗ {email}: {consecutive_missing} days missing + FITBIT ERROR - SENDING ADMIN NOTIFICATION"
                    )
                )
                if self.verbose:
                    self.stdout.write(f"   Error: {error_msg}")
                
                if not self.dry_run:
                    self.send_admin_notification_technical(participant, consecutive_missing, error_msg)
                    self.mark_admin_notified(participant, consecutive_missing, has_error=True)
                return 'new_admin_warning'
            else:
                # Admin already notified about the error
                if self.verbose:
                    self.stdout.write(
                        f"  {email}: {consecutive_missing} days missing + Fitbit error - admin already notified on {admin_notified}"
                    )
                if not self.dry_run:
                    self.update_device_sync_status(participant, consecutive_missing, has_error=True)
                return 'already_warned'
        
        # STEP 4: No technical error - follow normal user/admin flow
        if consecutive_missing >= self.ADMIN_ALERT_DAYS:
            # threshold+ days missing - admin notification needed
            if not admin_notified:
                self.stdout.write(
                    self.style.ERROR(
                        f"✗ {email}: {consecutive_missing} days missing - SENDING ADMIN NOTIFICATION"
                    )
                )
                if not self.dry_run:
                    self.send_admin_notification(participant, consecutive_missing)
                    self.mark_admin_notified(participant, consecutive_missing, has_error=False)
                return 'new_admin_warning'
            else:
                # Admin already notified
                if self.verbose:
                    self.stdout.write(
                        f"  {email}: {consecutive_missing} days missing - admin already notified on {admin_notified}"
                    )
                if not self.dry_run:
                    self.update_device_sync_status(participant, consecutive_missing, has_error=False)
                return 'already_warned'
        
        elif consecutive_missing >= self.PARTICIPANT_ALERT_DAYS:
            # threshold days missing - participant notification needed
            if not participant_notified:
                self.stdout.write(
                    self.style.WARNING(
                        f"⚠  {email}: {consecutive_missing} days missing - SENDING PARTICIPANT NOTIFICATION"
                    )
                )
                if not self.dry_run:
                    self.send_participant_notification(participant, consecutive_missing)
                    self.mark_participant_notified(participant, consecutive_missing, has_error=False)
                return 'new_participant_warning'
            else:
                # Participant already notified
                if self.verbose:
                    self.stdout.write(
                        f"  {email}: {consecutive_missing} days missing - participant already notified on {participant_notified}"
                    )
                if not self.dry_run:
                    self.update_device_sync_status(participant, consecutive_missing, has_error=False)
                return 'already_warned'
        # Should never reach here, but safety fallback
        logger.warning(f"Unexpected path in check_participant_sync for {email}")
        return 'syncing_ok'
    
    def count_consecutive_missing_days(self, participant, today, daily_steps_dict):
        """
        Count consecutive days with missing data, working backwards from yesterday.
        Only counts days that should have data (not future dates).
        Returns the count of consecutive missing days.
        """
        consecutive_missing = 0
        check_date = today - timedelta(days=1)  # Start from yesterday
        
        # Don't go back before study start date (if it exists)
        start_date = participant.start_date
        if start_date is None:
            # If no start_date, we can't determine a valid range
            # Default to checking last 30 days as a reasonable limit
            start_date = today - timedelta(days=30)
        
        while check_date >= start_date:
            check_date_str = check_date.strftime('%Y-%m-%d')
            steps = daily_steps_dict.get(check_date_str, 0)
            
            if steps == 0:
                # No data for this day (or zero steps recorded)
                consecutive_missing += 1
                check_date -= timedelta(days=1)
            else:
                # Found data, stop counting
                break
        
        return consecutive_missing
    
    def get_last_data_date(self, participant, today, daily_steps_dict):
        """Find the most recent date with step data >= 1."""
        check_date = today - timedelta(days=1)
        
        # Don't go back before study start date (if it exists)
        start_date = participant.start_date
        if start_date is None:
            # If no start_date, default to checking last 30 days
            start_date = today - timedelta(days=30)
        
        while check_date >= start_date:
            check_date_str = check_date.strftime('%Y-%m-%d')
            steps = daily_steps_dict.get(check_date_str, 0)
            if steps >= 1:
                return check_date
            check_date -= timedelta(days=1)
        
        return None
    
    def update_device_sync_status(self, participant, consecutive_missing_days, has_error=False):
        """Update device sync tracking status."""
        status = participant.device_sync_status.copy() if participant.device_sync_status else {}
        
        status['consecutive_missing_days'] = consecutive_missing_days
        status['last_check_date'] = timezone.now().date().isoformat()
        status['had_fitbit_error'] = has_error
        
        # Set warning_started_date if this is a new warning
        if consecutive_missing_days >= self.PARTICIPANT_ALERT_DAYS and 'warning_started_date' not in status:
            status['warning_started_date'] = timezone.now().date().isoformat()
        
        participant.device_sync_status = status
        participant.save(update_fields=['device_sync_status'])
    
    def mark_participant_notified(self, participant, consecutive_missing_days, has_error=False):
        """Mark that participant notification was sent."""
        status = participant.device_sync_status.copy() if participant.device_sync_status else {}
        
        status['consecutive_missing_days'] = consecutive_missing_days
        status['last_check_date'] = timezone.now().date().isoformat()
        status['participant_notified_date'] = timezone.now().date().isoformat()
        status['had_fitbit_error'] = has_error
        
        if 'warning_started_date' not in status:
            status['warning_started_date'] = timezone.now().date().isoformat()
        
        # Add to notification history
        if 'notification_history' not in status:
            status['notification_history'] = []
        status['notification_history'].append({
            'type': 'participant',
            'date': timezone.now().date().isoformat(),
            'days_missing': consecutive_missing_days,
            'reason': 'technical_error' if has_error else 'user_sync_issue'
        })
        
        participant.device_sync_status = status
        participant.save(update_fields=['device_sync_status'])
    
    def mark_admin_notified(self, participant, consecutive_missing_days, has_error=False):
        """Mark that admin notification was sent."""
        status = participant.device_sync_status.copy() if participant.device_sync_status else {}
        
        status['consecutive_missing_days'] = consecutive_missing_days
        status['last_check_date'] = timezone.now().date().isoformat()
        status['admin_notified_date'] = timezone.now().date().isoformat()
        status['had_fitbit_error'] = has_error
        
        if 'warning_started_date' not in status:
            status['warning_started_date'] = timezone.now().date().isoformat()
        
        # Add to notification history
        if 'notification_history' not in status:
            status['notification_history'] = []
        status['notification_history'].append({
            'type': 'admin',
            'date': timezone.now().date().isoformat(),
            'days_missing': consecutive_missing_days,
            'reason': 'technical_error' if has_error else 'user_sync_issue'
        })
        
        participant.device_sync_status = status
        participant.save(update_fields=['device_sync_status'])
    
    def clear_device_sync_warning(self, participant):
        """Clear sync warning when device starts syncing again."""
        participant.device_sync_status = {}
        participant.save(update_fields=['device_sync_status'])
    
    def send_participant_notification(self, participant, consecutive_missing_days):
        """Send email notification to participant about missing data."""
        from django.core.mail import EmailMessage

        language = participant.language or 'en'  # Default to English if None
        if language == 'fr':
            subject = "Action requise : Veuillez synchroniser votre appareil Fitbit"
            days_text = "jour" if consecutive_missing_days == 1 else "jours"

            message = f"""Bonjour,
Nous avons remarqué que votre appareil Fitbit n'a pas synchronisé de données depuis {consecutive_missing_days} {days_text}.

Pour vous assurer que vos données d'activité sont bien enregistrées, veuillez :

Vérifier que le Bluetooth est activé sur votre cellulaire

Ouvrir l'application Fitbit

Attendre que votre appareil se synchronise (vous devriez voir une animation de synchronisation)

Vérifier que le nombre de pas d'aujourd'hui s'affiche dans votre application

Si vous éprouvez des difficultés à synchroniser votre appareil, veuillez répondre à ce courriel ou nous appeler au 438-346-0479 et nous vous aiderons à résoudre le problème.

Merci de votre participation à notre étude!

Cordialement,
L'équipe de recherche
"""

        else:
            subject = "Action Required: Please Sync Your Fitbit Device"
            days_text = "day" if consecutive_missing_days == 1 else "days"

            message = f"""Hello,

We noticed that your Fitbit device hasn't synced data for the past {consecutive_missing_days} {days_text}.

To ensure your activity data is being recorded properly, please:

1. Make sure Bluetooth is enabled on your phone
2. Open the Google Health app
3. Wait for your device to sync (you should see a sync animation)
4. Verify that today's steps are showing in your app

If you're having trouble syncing your device, please reply to this email or call us at 438-346-0479 and we'll help you troubleshoot.

Thank you for your participation in our study!

Best regards,
The Research Team
"""

        from_email = getattr(settings, 'DEFAULT_FROM_EMAIL', 'john.dowling@rimuhc.ca')
        backup_email = participant.user.backup_email
        participant_cc = [backup_email] if backup_email else []

        try:
            email = EmailMessage(
                subject=subject,
                body=message,
                from_email=from_email,
                to=[participant.user.email],
                cc=participant_cc,
            )
            email.send(fail_silently=False)
            logger.info(f"Sent participant sync notification to {participant.user.email}")
            return {'success': True, 'error_message': None}
        except Exception as e:
            error_msg = f"Failed to send email: {str(e)}"
            logger.error(f"Failed to send participant notification to {participant.user.email}: {error_msg}")
            self.stderr.write(
                self.style.ERROR(f"Failed to send email to {participant.user.email}: {error_msg}")
            )
            return {'success': False, 'error_message': error_msg}
    
    def send_admin_notification_technical(self, participant, consecutive_missing_days, error_message):
        """Send email notification to admin about participant with Fitbit API/token error."""
        from django.core.mail import send_mail
        
        subject = f"Admin Alert: Fitbit Technical Error - {participant.user.email}"
        
        message = f"""Admin Alert: Fitbit Technical Error Detected

Participant: {participant.user.email}
Participant ID: {participant.id}
Consecutive Missing Days: {consecutive_missing_days}
Error Type: Fitbit API/Token Error

Technical Error Message:
{error_message}

This participant has missing data AND a Fitbit API or token error. This is likely a 
technical issue on our end, not a user sync issue.

Action Required:
1. Check the participant's Fitbit connection status
2. Review error logs for API failures
3. May need to re-authenticate the participant's Fitbit account
4. Contact participant only AFTER resolving technical issues

View participant details: {settings.BASE_URL}/admin/participant/{participant.id}/

This is an automated notification from the device sync monitoring system.
NOTE: Participant was NOT notified since this appears to be a technical issue.
"""
        
        from_email = getattr(settings, 'DEFAULT_FROM_EMAIL', 'john.dowling@rimuhc.ca')
        admin_email = getattr(settings, 'ADMIN_NOTIFICATION_EMAIL', from_email)

        # Handle both single email (string) and multiple emails (list)
        recipient_list = admin_email if isinstance(admin_email, list) else [admin_email]

        try:
            send_mail(
                subject=subject,
                message=message,
                from_email=from_email,
                recipient_list=recipient_list,
                fail_silently=False,
            )
            logger.info(f"Sent admin technical error notification for participant {participant.user.email}")
            return {'success': True, 'error_message': None}
        except Exception as e:
            error_msg = f"Failed to send email: {str(e)}"
            logger.error(f"Failed to send admin notification for {participant.user.email}: {error_msg}")
            self.stderr.write(
                self.style.ERROR(f"Failed to send admin notification: {error_msg}")
            )
            return {'success': False, 'error_message': error_msg}
    
    def send_admin_notification(self, participant, consecutive_missing_days):
        """Send email notification to admin about participant with extended missing data."""
        from django.core.mail import send_mail
        
        subject = f"Admin Alert: Participant {participant.user.email} - {consecutive_missing_days} Days No Data"
        
        # Get last sync date info
        daily_steps_dict = {}
        if participant.daily_steps is not None:
            for entry in participant.daily_steps:
                date_key = entry.get('date')
                steps_value = entry.get('value')
                if date_key and steps_value is not None:
                    daily_steps_dict[date_key] = int(steps_value)
        
        last_data_date = self.get_last_data_date(participant, timezone.now().date(), daily_steps_dict)
        last_data_str = last_data_date.strftime('%Y-%m-%d') if last_data_date else "No data found"
        
        message = f"""Admin Alert: Extended Data Gap Detected

Participant: {participant.user.email}
Participant ID: {participant.id}
Consecutive Missing Days: {consecutive_missing_days}
Last Data Received: {last_data_str}

This participant's Fitbit device has not synced for {consecutive_missing_days} days. 
A notification was previously sent to the participant after {self.PARTICIPANT_ALERT_DAYS} days of missing data.

Action Required:
Please follow up with this participant directly to:
- Verify they are still wearing their device
- Check if they are experiencing technical issues
- Provide additional support if needed

View participant details: {settings.BASE_URL}/admin/participant/{participant.id}/

This is an automated notification from the device sync monitoring system.
"""
        
        from_email = getattr(settings, 'DEFAULT_FROM_EMAIL', 'john.dowling@rimuhc.ca')
        admin_email = getattr(settings, 'ADMIN_NOTIFICATION_EMAIL', from_email)

        # Handle both single email (string) and multiple emails (list)
        recipient_list = admin_email if isinstance(admin_email, list) else [admin_email]

        try:
            send_mail(
                subject=subject,
                message=message,
                from_email=from_email,
                recipient_list=recipient_list,
                fail_silently=False,
            )
            logger.info(f"Sent admin notification for participant {participant.user.email}")
            return {'success': True, 'error_message': None}
        except Exception as e:
            error_msg = f"Failed to send email: {str(e)}"
            logger.error(f"Failed to send admin notification for {participant.user.email}: {error_msg}")
            self.stderr.write(
                self.style.ERROR(f"Failed to send admin notification: {error_msg}")
            )
            return {'success': False, 'error_message': error_msg}