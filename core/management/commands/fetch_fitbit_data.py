# core/management/commands/fetch_fitbit_data.py
from django.core.management.base import BaseCommand
from django.utils import timezone
from core.models import Participant
from device_integration.fitbit import fetch_fitbit_data_for_participant, _log_status_flag
from device_integration.google_health import fetch_google_data_for_participant
import logging

logger = logging.getLogger(__name__)

class Command(BaseCommand):
    help = 'Fetch step data for all participants with connected accounts'
    
    def add_arguments(self, parser):
        parser.add_argument(
            '--participant-id',
            type=int,
            help='Fetch data for a specific participant ID only',
        )
        parser.add_argument(
            '--force',
            action='store_true',
            help='Force refetch all data from start date',
        )
    
    def handle(self, *args, **options):
        start_time = timezone.now()
        self.stdout.write(f"Starting data fetch at {start_time.strftime('%Y-%m-%d %H:%M:%S')}\n")
        
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
            all_participants = Participant.objects.select_related('user').all()
        
        # Separate participants by token status
        valid_token_participants = []
        invalid_token_participants = []
        
        for participant in all_participants:
            token = participant.fitbit_access_token
            google_token = participant.google_access_token
            if (not token or not token.strip()) and (not google_token or not google_token.strip()):
                invalid_token_participants.append(participant)
                _log_status_flag(
                    participant,
                    "fetch_fitbit_data_fail",
                    "No access token - device not connected"
                )
            else:
                valid_token_participants.append(participant)
        
        # Report on invalid tokens
        if invalid_token_participants:
            self.stdout.write(
                self.style.WARNING(
                    f"⚠️  {len(invalid_token_participants)} participant(s) without valid tokens:"
                )
            )
            for p in invalid_token_participants:
                self.stdout.write(f"   - {p.user.email}: Error logged to status_flags")
            self.stdout.write("")
        
        # Fetch for participants with valid tokens
        if not valid_token_participants:
            self.stdout.write(self.style.WARNING("No participants with valid tokens to process"))
            return
        
        self.stdout.write(f"Processing {len(valid_token_participants)} participant(s) with valid tokens...\n")
        
        success_count = 0
        api_error_count = 0
        
        for participant in valid_token_participants:
            try:
                if self.fetch_for_participant(participant, force=options['force']):
                    success_count += 1
                else:
                    api_error_count += 1
            except Exception as e:
                api_error_count += 1
                logger.exception(f"Unexpected error for participant {participant.id}")
                self.stdout.write(
                    self.style.ERROR(f"✗ {participant.user.email}: Unexpected error - {str(e)}")
                )
        
        # Summary
        end_time = timezone.now()
        duration = (end_time - start_time).total_seconds()
        
        self.stdout.write("\n" + "="*50)
        self.stdout.write(f"Completed in {duration:.1f} seconds")
        self.stdout.write(self.style.SUCCESS(f"  ✓ Successful: {success_count}"))
        if api_error_count > 0:
            self.stdout.write(self.style.ERROR(f"  ✗ API Errors: {api_error_count}"))
        if invalid_token_participants:
            self.stdout.write(self.style.WARNING(f"  ⚠  No Token: {len(invalid_token_participants)}"))
        self.stdout.write("="*50)
    
    def fetch_for_participant(self, participant, force=False):
        """Fetch data for a single participant and return success status"""
        try:
            if participant.google_access_token:
                # Clear any stale Fitbit error flags
                _log_status_flag(participant, "fetch_fitbit_data_fail")
                result, status = fetch_google_data_for_participant(
                    participant.id,
                    force_refetch=force
                )
            else:
                result, status = fetch_fitbit_data_for_participant(
                    participant.id,
                    force_refetch=force
                )

            if status == 200:
                steps_count = len(result.get('steps', []))
                message = result.get('message', '')
                if message:
                    self.stdout.write(
                        self.style.SUCCESS(f"✓ {participant.user.email}: {message}")
                    )
                else:
                    self.stdout.write(
                        self.style.SUCCESS(f"✓ {participant.user.email}: {steps_count} days fetched")
                    )
                return True
            else:
                error_msg = result.get('error', 'Unknown error')
                self.stdout.write(
                    self.style.ERROR(f"✗ {participant.user.email}: {error_msg}")
                )
                return False

        except Exception as e:
            self.stdout.write(
                self.style.ERROR(f"✗ {participant.user.email}: {str(e)}")
            )
            logger.exception(f"Error fetching data for participant {participant.id}")
            return False