# goals/targets.py
from datetime import datetime, date, timedelta
from django.utils import timezone
import logging

logger = logging.getLogger(__name__)

def _log_status_flag(participant, key, error_message=None):
    """
    Helper to set or clear status flags. 
    Duplicated from device_integration/fitbit.py to avoid circular imports.
    """
    # Get a mutable copy of status_flags to ensure Django detects the change
    flags = participant.status_flags.copy() if participant.status_flags else {}
    
    if error_message:
        flags[key] = True
        flags[f"{key}_last_error"] = error_message
        flags[f"{key}_last_error_time"] = timezone.now().isoformat()
    else:
        flags[key] = False
        flags.pop(f"{key}_last_error", None)
        flags.pop(f"{key}_last_error_time", None)
    
    # Reassign to trigger JSONField update detection
    participant.status_flags = flags
    participant.save(update_fields=["status_flags"])

def validate_step_data(step_value):
    """Validate that step data is reasonable"""
    if not isinstance(step_value, (int, float)):
        logger.warning(f"Invalid step data type: {type(step_value)}")
        return False
    
    if step_value < 1000:
        logger.warning(f"Step count too low (< 1000): {step_value}")
        return False
        
    if step_value > 100000:  # Unreasonably high
        logger.warning(f"Unusually high step count: {step_value}")
        return False
        
    return True

def _parse_increase_value(increase_str):
    """Convert increase string to comparable value for matrix logic"""
    if increase_str == "maintain":
        return 0
    elif increase_str == "increase to 10000":
        return "increase to 10000"
    else:
        try:
            return int(increase_str)
        except (ValueError, TypeError):
            return 0

def calculate_step_increase(current_avg, last_goal_data=None, target_was_met=True):
    """
    Calculate the appropriate step increase based on current average, previous increase, and performance.
    Translated from PHP research algorithm.
    
    Args:
        current_avg: Current week's average steps
        last_goal_data: Previous goal dictionary or None
        target_was_met: Whether previous target was achieved
    
    Returns:
        tuple: (increase_description, new_target_value)
    """
    
    # Safely convert to int first, then validate
    try:
        current_avg = int(current_avg)
    except (TypeError, ValueError):
        logger.warning(f"Invalid current_avg type, defaulting to 1000: {current_avg}")
        current_avg = 1000
    
    # Clamp to reasonable range
    current_avg = max(1000, min(current_avg, 50000))
    
    # First week logic (no previous goal)
    if not last_goal_data:
        return _calculate_first_week_target(current_avg)
    
    # Get previous increase for matrix logic
    previous_increase = _parse_increase_value(last_goal_data.get("increase"))
    
    # Subsequent weeks - use matrix logic from PHP
    if target_was_met:
        return _calculate_target_met_matrix(current_avg, previous_increase)
    else:
        return _calculate_target_missed_matrix(current_avg, previous_increase)

def is_target_day(participant_start_date):
    """Check if today is a target day for this participant"""
    today = date.today()
    delta_days = (today - participant_start_date).days
    return delta_days >= 7 and delta_days % 7 == 0
    
def _calculate_first_week_target(current_avg):
    """Calculate target for first week"""
    if current_avg < 5000:
        return "500", current_avg + 500
    elif current_avg < 7500:
        return "1000", current_avg + 1000
    elif current_avg < 9000:
        return "1000", current_avg + 1000
    elif current_avg < 10000:
        return "increase to 10000", 10000
    else:
        return "maintain", current_avg

def _calculate_target_met_matrix(current_avg, previous_increase):
    """Target met logic - direct translation from PHP algorithm"""
    
    # Matrix logic for when target was met
    if current_avg < 5000:
        if previous_increase == 250:
            return "500", current_avg + 500
        elif previous_increase == 500:
            return "500", current_avg + 500
    
    elif current_avg < 7500:
        if previous_increase == 250:
            return "500", current_avg + 500
        elif previous_increase == 500:
            return "1000", current_avg + 1000
        elif previous_increase == 1000:
            return "1000", current_avg + 1000
    
    elif current_avg < 9000:
        if previous_increase == 250:
            return "1000", current_avg + 1000
        elif previous_increase == 500:
            return "1000", current_avg + 1000
        elif previous_increase == 1000:
            return "1000", current_avg + 1000
    
    elif current_avg < 10000:
        if previous_increase == 250:
            return "500", current_avg + 500
        elif previous_increase == 500:
            return "500", current_avg + 500
        elif previous_increase == 1000:
            return "500", current_avg + 500
    
    elif current_avg >= 10000:
        return "maintain", current_avg
    
    # Fallback (shouldn't reach here with proper data)
    return "500", current_avg + 500

def _calculate_target_missed_matrix(current_avg, previous_increase):
    """Target missed logic - direct translation from PHP algorithm"""
       
    # DEBUG LOGGING
   	# logger.info(f"=== DEBUG _calculate_target_missed_matrix ===")
    # logger.info(f"current_avg: {current_avg} (type: {type(current_avg)})")
   	# logger.info(f"previous_increase: {previous_increase} (type: {type(previous_increase)})")
   	# logger.info(f"previous_increase == 1000: {previous_increase == 1000}")
    # logger.info(f"previous_increase == 'increase to 10000': {previous_increase == 'increase to 10000'}")
    
    # Special case: if previous was maintain, return 1000
    if previous_increase == 0:  # "maintain" parsed as 0
        return "1000", current_avg + 1000
    
    # Matrix logic for when target was missed
    if current_avg < 5000:
        if previous_increase == 250:
            return "250", current_avg + 250
        elif previous_increase == 500:
            return "250", current_avg + 250
        elif previous_increase == 1000:
            return "500", current_avg + 500
        elif previous_increase == "increase to 10000":
            return "1000", current_avg + 1000
    
    elif current_avg < 7500:
        if previous_increase == 250:
            return "250", current_avg + 250
        elif previous_increase == 500:
            return "500", current_avg + 500
        elif previous_increase == 1000:
            return "500", current_avg + 500
        elif previous_increase == "increase to 10000":
            return "1000", current_avg + 1000
    
    elif current_avg < 9000:
        if previous_increase == 500:
            return "500", current_avg + 500
        elif previous_increase == 1000:
            return "500", current_avg + 500
        elif previous_increase == "increase to 10000":
            return "1000", current_avg + 1000
    
    elif current_avg < 10000:
        if previous_increase == 500:
            return "500", current_avg + 500
        elif previous_increase == 1000:
            return "500", current_avg + 500
        elif previous_increase == "increase to 10000":
            return "increase to 10000", 10000
    
    elif current_avg >= 10000:
        return "maintain", current_avg
    
    # Fallback (shouldn't reach here with proper data)
    return "250", current_avg + 250

def compute_weekly_target(participant, weekly_average, week_start, week_end, last_goal_data=None):
    """
    Calculate this week's step target for a participant.

    Args:
        participant: Participant instance
        weekly_average: int, last week's average steps
        week_start: Start date of the week (based on participant start date)
        week_end: End date of the week
        last_goal_data: Previous goal dictionary or None
    
    Returns:
        dict: Goal data with increase, average_steps, new_target
    """
    
    logger.info(f"Computing weekly target for participant {participant.id}, "
               f"weekly_average: {weekly_average}, week: {week_start} to {week_end}, "
               f"has_last_goal: {last_goal_data is not None}")
    
    # Determine if previous target was met
    target_was_met = True
    previous_target = None
    
    if last_goal_data:
        previous_target = last_goal_data.get("new_target", 0)
        target_was_met = weekly_average >= previous_target
    
    # Calculate new target
    increase_description, new_target = calculate_step_increase(
        current_avg=weekly_average,
        last_goal_data=last_goal_data,
        target_was_met=target_was_met
    )
    
    # Return goal data as dictionary - USES ORIGINAL FIELD NAMES
    goal_data = {
        "increase": increase_description,
        "average_steps": weekly_average,  # RESTORED: was "step_value"
        "new_target": new_target,
        "week_start": week_start.strftime("%Y-%m-%d"),
        "week_end": week_end.strftime("%Y-%m-%d"),
        "previous_target": previous_target,
        "target_was_met": target_was_met if last_goal_data else None
    }
    
    logger.info(f"Computed goal: {goal_data}")
    return goal_data
    
def get_step_data_for_week(daily_steps, week_start, week_end):
    """
    Extract and validate step data for a specific week.
    
    Args:
        daily_steps: List of step data from participant
        week_start: Start date of week
        week_end: End date of week
    
    Returns:
        list: Valid step values for the week
    """
    week_steps = []
    
    for step_entry in daily_steps:
        try:
            # Handle both "date" and "dateTime" field names
            date_str = step_entry.get("date") or step_entry.get("dateTime")
            step_date = datetime.strptime(date_str, "%Y-%m-%d").date()
            step_value = int(step_entry["value"])
            
            # Validate: correct date range and reasonable step count
            if week_start <= step_date <= week_end and validate_step_data(step_value):
                week_steps.append(step_value)
                
        except (ValueError, KeyError, TypeError) as e:
            logger.warning(f"Invalid step entry: {step_entry}, error: {e}")
            continue
    
    return week_steps

def run_weekly_algorithm(participant, use_fallback=False, fallback_days_count=None):
    """
    Compute and save a weekly step goal for a participant.

    Rules:
    - Analyzes the most recently completed week of data
    - Sets goals for the current/upcoming week
    - Allows re-running on same day (for updated data scenarios)
    
    Args:
        participant: Participant object
        use_fallback: If True, calculation runs without target-day data (22:00 fallback);
                      the most recent day with data is excluded as possibly incomplete
        fallback_days_count: Number of days found when in fallback mode (for metadata)
    
    Returns:
        dict: Goal data or None
    """
    
    logger.info(f"Running weekly algorithm for participant {participant.id} (fallback={use_fallback})")
    
    today = date.today()
    
    if not is_target_day(participant.start_date):
        logger.warning(f"Cannot calculate goals - today is not a target day")
        return None
    
    try:
        daily_steps = participant.daily_steps or []
        
        # Calculate which week we're in since participant start
        days_since_start = (today - participant.start_date).days
        weeks_since_start = days_since_start // 7
        
        # Still in first week - no complete week to analyze yet
        if weeks_since_start == 0:
            logger.info(f"Still in first week (day {days_since_start}), no complete week to analyze")
            return None
        
        # Calculate the most recently completed week to analyze
        completed_week_number = weeks_since_start - 1
        analysis_week_start = participant.start_date + timedelta(days=completed_week_number * 7)
        analysis_week_end = analysis_week_start + timedelta(days=6)
        
        # Calculate the current week (where we set the goal)
        target_week_start = participant.start_date + timedelta(days=weeks_since_start * 7)
        target_week_end = target_week_start + timedelta(days=6)
        
        logger.info(f"Analyzing week {analysis_week_start} to {analysis_week_end}")
        logger.info(f"Setting goal for week {target_week_start} to {target_week_end}")
        
        # Get previous goal data - direct calculation approach
        last_goal_data = None
        if weeks_since_start > 1:  # Only look for previous goal if we're past week 2
            # Find most recent valid target (skip over any previous skipped weeks)
            previous_week_start = target_week_start - timedelta(days=7)
            
            # Look back up to 10 weeks to find a non-skipped target
            for lookback in range(10):
                check_week_start = previous_week_start - timedelta(days=7 * lookback)
                check_week_key = check_week_start.strftime("%Y-%m-%d")
                
                if participant.targets and check_week_key in participant.targets:
                    candidate_goal = participant.targets[check_week_key]
                    # Skip over weeks that were skipped due to insufficient data
                    if candidate_goal.get('calculation_method') != 'skipped_week':
                        last_goal_data = candidate_goal
                        logger.info(f"Found previous goal for week {check_week_key}: {last_goal_data}")
                        break
            
            if not last_goal_data and weeks_since_start > 1:
                # TRACK ERROR: Missing previous goal when expected
                error_msg = f"Missing previous goal data (checked back 10 weeks)"
                logger.warning(error_msg)
                _log_status_flag(participant, "target_calculation_fail", error_msg)
            
            logger.info(f"Using previous goal data: {last_goal_data}")
        else:
            logger.info("Week 2 - using first week logic (no previous goal)")
        
        # Get step data for the completed week
        if use_fallback:
            # No target-day data: the most recent day with data may be incomplete, so exclude it
            last_data_date = None
            for entry in daily_steps:
                try:
                    d = datetime.strptime(entry.get("date") or entry.get("dateTime"), "%Y-%m-%d").date()
                    if analysis_week_start <= d <= analysis_week_end and int(entry["value"]) > 0:
                        if last_data_date is None or d > last_data_date:
                            last_data_date = d
                except (ValueError, KeyError, TypeError):
                    continue
            effective_end = (last_data_date - timedelta(days=1)) if last_data_date else analysis_week_end
            week_steps = get_step_data_for_week(daily_steps, analysis_week_start, effective_end)
            logger.info(f"Fallback: excluded last data day {last_data_date}, using {len(week_steps)} days")
        else:
            week_steps = get_step_data_for_week(daily_steps, analysis_week_start, analysis_week_end)
        logger.info(f"Found {len(week_steps)} days of step data for analysis week")

        # Determine calculation method for metadata
        calculation_method = 'normal'
        if use_fallback:
            calculation_method = 'partial_data'
            logger.info(f"Using fallback mode with {fallback_days_count or len(week_steps)} days of data")

        # Calculate goal based on available data
        if len(week_steps) >= 4:
            week_avg = sum(week_steps) // len(week_steps)
            logger.info(f"Calculated average: {week_avg} steps from {len(week_steps)} days")
            
            goal_data = compute_weekly_target(
                participant=participant, 
                weekly_average=week_avg,
                week_start=target_week_start,
                week_end=target_week_end,
                last_goal_data=last_goal_data
            )
            
            # SUCCESS - Clear any previous errors
            _log_status_flag(participant, "target_calculation_fail")
            
        else:
            # TRACK ERROR: Insufficient data
            error_msg = f"Insufficient step data: only {len(week_steps)} days available (need 4+)"
            logger.warning(error_msg)
            
            _log_status_flag(participant, "target_calculation_fail", error_msg)
            
            # Don't calculate or send notification when insufficient data
            return None

        # Save the goal to participant.targets
        target_week_key = target_week_start.strftime("%Y-%m-%d")
        targets = participant.targets or {}
        targets[target_week_key] = {
            "increase": goal_data["increase"],
            "average_steps": goal_data["average_steps"],
            "new_target": goal_data["new_target"]
        }
        
        # Add metadata for fallback calculations
        if calculation_method == 'partial_data':
            targets[target_week_key]['calculation_method'] = 'partial_data'
            targets[target_week_key]['days_with_data'] = len(week_steps)
        
        participant.targets = targets
        participant.save(update_fields=["targets"])
        
        logger.info(f"Successfully created and saved weekly goal: {goal_data} (method: {calculation_method})")
        return goal_data
        
    except Exception as e:
        # TRACK ERROR: Unexpected exception
        error_msg = f"Unexpected error during target calculation: {str(e)}"
        logger.error(error_msg, exc_info=True)
        
        _log_status_flag(participant, "target_calculation_fail", error_msg)
        
        raise  # Re-raise to let caller handle