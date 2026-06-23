# core/management/commands/calculate_weekly_targets.py
from django.core.management.base import BaseCommand
from django.utils import timezone
from datetime import date, timedelta
from core.models import Participant
from goals.targets import run_weekly_algorithm, is_target_day, _log_status_flag
from goals.notifications import send_goal_notification, create_message_history_entry
import logging

logger = logging.getLogger(__name__)

class Command(BaseCommand):
    help = 'Calculate weekly step targets and send notifications for participants on their target day'

    def add_arguments(self, parser):
        parser.add_argument(
            '--participant-id',
            type=int,
            help='Calculate target for specific participant ID only',
        )
        parser.add_argument(
            '--skip-notifications',
            action='store_true',
            help='Calculate targets but skip sending notifications',
        )

    def handle(self, *args, **options):
        today = date.today()
        skip_notifications = options.get('skip_notifications', False)

        self.stdout.write(f"Calculating weekly targets for {today.strftime('%Y-%m-%d')}...\n")

        # If specific participant requested
        participant_id = options.get('participant_id')
        if participant_id:
            try:
                participant = Participant.objects.get(id=participant_id)
                self.calculate_for_participant(participant, skip_notifications)
            except Participant.DoesNotExist:
                self.stdout.write(self.style.ERROR(f"Participant {participant_id} not found"))
            return

        # Get all participants
        all_participants = Participant.objects.select_related('user').all()

        # Filter to those on target day AND active
        # Safety: Filter out participants with missing/invalid start_date first
        target_day_participants = []
        for p in all_participants:
            if not p.user or not p.user.is_active:
                continue
            if not p.start_date:
                logger.warning(f"Participant {p.id} has no start_date - skipping")
                continue
            try:
                if is_target_day(p.start_date):
                    target_day_participants.append(p)
            except Exception as e:
                logger.error(f"Error checking target day for participant {p.id}: {e}")
                continue

        if not target_day_participants:
            self.stdout.write(self.style.WARNING("No active participants on target day today"))
            return

        self.stdout.write(f"Found {len(target_day_participants)} active participants on target day:\n")

        success_count = 0
        notification_sent_count = 0
        notification_failed_count = 0
        no_target_count = 0
        no_data_today_count = 0
        already_exists_count = 0
        skipped_week_count = 0
        error_count = 0

        for participant in target_day_participants:
            result = self.calculate_for_participant(participant, skip_notifications)

            if result['status'] == 'success':
                success_count += 1
                if result.get('notification_sent'):
                    notification_sent_count += 1
                elif result.get('notification_failed'):
                    notification_failed_count += 1
            elif result['status'] == 'no_target':
                no_target_count += 1
            elif result['status'] == 'no_data_today':
                no_data_today_count += 1
            elif result['status'] == 'already_exists':
                already_exists_count += 1
            elif result['status'] == 'skipped_week':
                skipped_week_count += 1
            else:
                error_count += 1

        # Summary
        self.stdout.write("\n" + "="*60)
        self.stdout.write("Calculation Summary:")
        self.stdout.write(self.style.SUCCESS(f"  ✓ Targets Calculated: {success_count}"))
        if notification_sent_count > 0:
            self.stdout.write(self.style.SUCCESS(f"  ✓ Notifications Sent: {notification_sent_count}"))
        if notification_failed_count > 0:
            self.stdout.write(self.style.ERROR(f"  ✗ Notifications Failed: {notification_failed_count}"))
        if already_exists_count > 0:
            self.stdout.write(f"  ℹ  Already Calculated: {already_exists_count}")
        if no_data_today_count > 0:
            self.stdout.write(self.style.WARNING(f"  ⚠  No Target Day Data Yet: {no_data_today_count}"))
        if skipped_week_count > 0:
            self.stdout.write(self.style.WARNING(f"  ⚠  Weeks Skipped (insufficient data): {skipped_week_count}"))
        if no_target_count > 0:
            self.stdout.write(self.style.WARNING(f"  ⚠  No Target (insufficient data): {no_target_count}"))
        if error_count > 0:
            self.stdout.write(self.style.ERROR(f"  ✗ Errors: {error_count}"))
        self.stdout.write("="*60)

    def calculate_for_participant(self, participant, skip_notifications=False):
        """Calculate target for a single participant and optionally send notification"""
        result = {
            'status': None,
            'notification_sent': False,
            'notification_failed': False,
            'error_details': None
        }

        try:
            today = date.today()
            today_str = today.strftime('%Y-%m-%d')

            # Check if target already exists for today
            targets = participant.targets or {}
            if today_str in targets and targets[today_str].get('new_target'):
                self.stdout.write(
                    f"  {participant.user.email}: Target already exists for today - skipping"
                )
                result['status'] = 'already_exists'
                return result

            # CRITICAL: Check for target day data before calculating
            daily_steps = participant.daily_steps or []

            def safe_int(value, default=0):
                """Safely convert value to int"""
                try:
                    return int(value) if value else default
                except (ValueError, TypeError):
                    return default

            has_today_data = any(
                entry.get('date') == today_str and safe_int(entry.get('value')) > 0
                for entry in daily_steps
            )

            if not has_today_data:
                # No data for today - check if it's time for fallback (17:00 or later Toronto time)
                from zoneinfo import ZoneInfo
                
                now_utc = timezone.now()
                toronto_tz = ZoneInfo('America/Toronto')
                now_toronto = now_utc.astimezone(toronto_tz)
                
                if now_toronto.hour >= 22:
                    # It's 5 PM or later - use fallback logic
                    self.stdout.write(
                        self.style.WARNING(
                            f"⚠  {participant.user.email}: No data for target day by 22:00 - using fallback logic"
                        )
                    )
                    return self.calculate_with_fallback(participant, skip_notifications)
                else:
                    # Not 5 PM yet - wait for next hour
                    self.stdout.write(
                        self.style.WARNING(
                            f"⚠  {participant.user.email}: No step data from today yet (currently {now_toronto.strftime('%H:%M')} Toronto time) - skipping calculation"
                        )
                    )
                    result['status'] = 'no_data_today'
                    return result

            # Now safe to calculate - we know all 7 days are synced
            goal_data = run_weekly_algorithm(participant)

            if goal_data:
                self.stdout.write(
                    self.style.SUCCESS(
                        f"✓ {participant.user.email}: Target calculated - {goal_data['new_target']} steps/day"
                    )
                )
                result['status'] = 'success'

                # Handle notification
                if not skip_notifications:
                    notification_result = send_goal_notification(participant, goal_data)
                    
                    if notification_result['success']:
                        result['notification_sent'] = True
                        self.stdout.write(f"  → Notification sent successfully")
                        
                        # FIXED: Clear notification errors using helper function
                        _log_status_flag(participant, "send_notification_fail")
                        
                    else:
                        result['notification_failed'] = True
                        result['error_details'] = notification_result['error_message']
                        self.stdout.write(
                            self.style.WARNING(
                                f"  → Notification failed: {notification_result['error_message']}"
                            )
                        )
                        
                        # FIXED: Log error using helper function
                        _log_status_flag(
                            participant,
                            "send_notification_fail",
                            notification_result['error_message']
                        )
                    
                    # Add to message history (regardless of email success)
                    message_entry = create_message_history_entry(
                        notification_result, 
                        goal_data, 
                        participant.language
                    )
                    
                    # FIXED: Use copy/reassign pattern for JSONField
                    message_history = (participant.message_history or []).copy()
                    message_history.append(message_entry)
                    participant.message_history = message_history
                    
                    # Save participant with message history (status_flags already saved by _log_status_flag)
                    participant.save(update_fields=['message_history'])
                    logger.info(f"Message logged for participant {participant.id}")
                        
                else:
                    self.stdout.write(f"  → Notification skipped")

                return result
            else:
                self.stdout.write(
                    self.style.WARNING(
                        f"⚠  {participant.user.email}: No target calculated (insufficient data or first week)"
                    )
                )
                result['status'] = 'no_target'
                return result

        except Exception as e:
            self.stdout.write(
                self.style.ERROR(f"✗ {participant.user.email}: {str(e)}")
            )
            logger.exception(f"Error calculating target for participant {participant.id}")
            result['status'] = 'error'
            return result
    
    def calculate_with_fallback(self, participant, skip_notifications=False):
        """
        Fallback logic when target day has no data by 17:00.
        - If >= 4 days of data in past 7 days: Calculate from those days
        - If < 4 days: Skip week, keep previous target
        """
        result = {
            'status': None,
            'notification_sent': False,
            'notification_failed': False,
            'error_details': None
        }
        
        try:
            today = date.today()
            today_str = today.strftime('%Y-%m-%d')
            
            # Count days with data in the past 7 days (not including today)
            daily_steps = participant.daily_steps or []
            
            def safe_int(value, default=0):
                """Safely convert value to int"""
                try:
                    return int(value) if value else default
                except (ValueError, TypeError):
                    return default
            
            # Get past 7 days (yesterday and 6 days before)
            past_7_days = [today - timedelta(days=i) for i in range(1, 8)]
            days_with_data = []
            
            for check_date in past_7_days:
                check_date_str = check_date.strftime('%Y-%m-%d')
                for entry in daily_steps:
                    if entry.get('date') == check_date_str and safe_int(entry.get('value')) > 0:
                        days_with_data.append(check_date_str)
                        break
            
            days_count = len(days_with_data)
            
            self.stdout.write(f"    Found {days_count} day(s) with data in past 7 days")
            
            if days_count >= 4:
                # Sufficient data - calculate from partial week
                self.stdout.write(
                    self.style.SUCCESS(
                        f"  ✓ {participant.user.email}: Using {days_count} days of data for calculation"
                    )
                )
                
                # Call run_weekly_algorithm with fallback mode
                goal_data = run_weekly_algorithm(participant, use_fallback=True, fallback_days_count=days_count)
                
                if not goal_data:
                    self.stdout.write(
                        self.style.ERROR(
                            f"    ✗ Failed to calculate target from {days_count} days of data"
                        )
                    )
                    result['status'] = 'no_target'
                    return result
                
                # CRITICAL VALIDATION: Verify the target was actually saved with correct metadata
                # Refresh participant from database to get latest targets
                participant.refresh_from_db()
                targets = participant.targets or {}
                
                if today_str not in targets:
                    self.stdout.write(
                        self.style.ERROR(
                            f"    ✗ Target was not saved to database (key {today_str} missing)"
                        )
                    )
                    result['status'] = 'error'
                    result['error_details'] = 'Target not persisted to database'
                    return result
                
                saved_target = targets[today_str]
                
                # Verify it has the partial_data metadata
                if saved_target.get('calculation_method') != 'partial_data':
                    self.stdout.write(
                        self.style.ERROR(
                            f"    ✗ Target saved but missing partial_data metadata"
                        )
                    )
                    result['status'] = 'error'
                    result['error_details'] = 'Target missing calculation_method metadata'
                    return result
                
                if saved_target.get('days_with_data') != days_count:
                    self.stdout.write(
                        self.style.WARNING(
                            f"    ⚠ Target saved but days_with_data mismatch (expected {days_count}, got {saved_target.get('days_with_data')})"
                        )
                    )
                
                # Validation passed
                self.stdout.write(
                    self.style.SUCCESS(
                        f"  ✓ Target calculated and validated: {goal_data['new_target']} steps/day (partial data from {days_count} days)"
                    )
                )
                result['status'] = 'success'
                
                # Send notification
                if not skip_notifications:
                    notification_result = send_goal_notification(participant, goal_data)
                    
                    if notification_result['success']:
                        result['notification_sent'] = True
                        self.stdout.write(f"    → Notification sent")
                        _log_status_flag(participant, "send_notification_fail")
                    else:
                        result['notification_failed'] = True
                        result['error_details'] = notification_result['error_message']
                        self.stdout.write(
                            self.style.WARNING(
                                f"    → Notification failed: {notification_result['error_message']}"
                            )
                        )
                        _log_status_flag(
                            participant,
                            "send_notification_fail",
                            notification_result['error_message']
                        )
                    
                    # Add to message history
                    message_entry = create_message_history_entry(
                        notification_result, 
                        goal_data, 
                        participant.language
                    )
                    message_history = (participant.message_history or []).copy()
                    message_history.append(message_entry)
                    participant.message_history = message_history
                    participant.save(update_fields=['message_history'])
                
                return result
                    
            else:
                # Insufficient data - skip this week
                self.stdout.write(
                    self.style.WARNING(
                        f"  ⚠  {participant.user.email}: Only {days_count} day(s) of data - skipping week, keeping previous target"
                    )
                )
                
                # Get previous target
                targets = participant.targets or {}
                previous_target = None
                
                # Find most recent valid target (skip back over any previous skipped weeks)
                check_date = today - timedelta(days=7)
                for _ in range(10):  # Check up to 10 weeks back
                    check_date_str = check_date.strftime('%Y-%m-%d')
                    if check_date_str in targets:
                        target_data = targets[check_date_str]
                        if target_data.get('calculation_method') != 'skipped_week':
                            previous_target = target_data.get('new_target')
                            break
                    check_date -= timedelta(days=7)
                
                if previous_target is None:
                    self.stdout.write(
                        self.style.ERROR(
                            f"    ✗ No previous target found - cannot skip week"
                        )
                    )
                    result['status'] = 'error'
                    return result
                
                # Save skipped week with previous target
                targets[today_str] = {
                    'new_target': previous_target,
                    'average_steps': 'insufficient_data',
                    'previous_target': previous_target,
                    'target_was_met': None,
                    'calculation_method': 'skipped_week',
                    'days_with_data': days_count,
                    'reason': f'Less than 4 days of data ({days_count} days)'
                }
                participant.targets = targets
                participant.save(update_fields=['targets'])
                
                # Create goal_data for notification
                goal_data = {
                    'new_target': previous_target,
                    'average_steps': 'insufficient_data',
                    'target_was_met': None,
                    'previous_target': previous_target
                }
                
                self.stdout.write(
                    f"    → Week skipped, continuing with target: {previous_target} steps/day"
                )
                result['status'] = 'skipped_week'
                
                # Send notification about skipped week
                if not skip_notifications:
                    notification_result = send_goal_notification(participant, goal_data)
                    
                    if notification_result['success']:
                        result['notification_sent'] = True
                        self.stdout.write(f"    → Notification sent")
                        _log_status_flag(participant, "send_notification_fail")
                    else:
                        result['notification_failed'] = True
                        result['error_details'] = notification_result['error_message']
                        _log_status_flag(
                            participant,
                            "send_notification_fail",
                            notification_result['error_message']
                        )
                    
                    # Add to message history
                    message_entry = create_message_history_entry(
                        notification_result, 
                        goal_data, 
                        participant.language
                    )
                    message_history = (participant.message_history or []).copy()
                    message_history.append(message_entry)
                    participant.message_history = message_history
                    participant.save(update_fields=['message_history'])
                
                return result
                
        except Exception as e:
            self.stdout.write(
                self.style.ERROR(f"    ✗ Fallback calculation failed: {str(e)}")
            )
            logger.exception(f"Error in fallback calculation for participant {participant.id}")
            result['status'] = 'error'
            result['error_details'] = str(e)
            return result