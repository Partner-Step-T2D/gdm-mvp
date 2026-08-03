# goals/views.py
from django.shortcuts import render, get_object_or_404, redirect
from django.contrib import messages
from django.http import HttpResponse
from core.models import Participant
from .targets import run_weekly_algorithm
from goals.notifications import send_goal_notification
from datetime import date, timedelta
import logging
from io import StringIO
from goals.notifications import send_goal_notification, create_email_content
from django.contrib.admin.views.decorators import staff_member_required

class LogCapture:
    def __init__(self):
        self.log_stream = StringIO()
        self.handler = logging.StreamHandler(self.log_stream)
        self.handler.setLevel(logging.INFO)
        
    def start_capture(self):
        logger = logging.getLogger('goals.targets')  # Your module's logger
        logger.addHandler(self.handler)
        
    def stop_capture(self):
        logger = logging.getLogger('goals.targets')
        logger.removeHandler(self.handler)
        messages = self.log_stream.getvalue()
        self.log_stream.close()
        return messages
        
@staff_member_required
def calculate_weekly_goals(request, participant_id):
    participant = get_object_or_404(Participant, pk=participant_id)
        
    # Create capture setup
    log_capture_string = StringIO()
    capture_handler = logging.StreamHandler(log_capture_string)
    capture_handler.setLevel(logging.DEBUG)  # Lower threshold
    capture_handler.setFormatter(logging.Formatter('%(message)s'))
    
    # Get logger
    targets_logger = logging.getLogger('goals.targets')
    
    # Add our handler
    targets_logger.addHandler(capture_handler)
    targets_logger.setLevel(logging.DEBUG)
    
    try:
        
        result = run_weekly_algorithm(participant)
        
        # Get captured content
        log_contents = log_capture_string.getvalue()
        
        context = {
            "success": True if result else False,
            "message": f"Weekly goal calculated: {result['new_target']} steps" if result else "No goal calculated",
            "detailed_log": log_contents or "No logs captured",
            "debug_info": f"Logger: {targets_logger.name}, Level: {targets_logger.level}, Handlers: {len(targets_logger.handlers)}"
        }
        
    finally:
        targets_logger.removeHandler(capture_handler)
        log_capture_string.close()
    
    return render(request, "admin/popup_result.html", context)

@staff_member_required
def send_notification_view(request, participant_id):
    try:
        participant = Participant.objects.get(id=participant_id)
        
        # Find the most recent goal from today or yesterday
        today = date.today()
        yesterday = today - timedelta(days=1)
        
        today_key = today.strftime("%Y-%m-%d")
        yesterday_key = yesterday.strftime("%Y-%m-%d")
        
        targets = participant.targets or {}
        recent_goal = None
        goal_date = None
        
        # Check today first, then yesterday
        if today_key in targets and targets[today_key].get('new_target'):
            recent_goal = targets[today_key]
            goal_date = today_key
        elif yesterday_key in targets and targets[yesterday_key].get('new_target'):
            recent_goal = targets[yesterday_key]
            goal_date = yesterday_key
        
        if recent_goal:
            goal_data = {
                'average_steps': recent_goal.get('average_steps'),
                'new_target': recent_goal.get('new_target'),
                'previous_target': recent_goal.get('previous_target'),
                'target_was_met': recent_goal.get('average_steps', 0) >= recent_goal.get('previous_target', 0) if recent_goal.get('previous_target') else None
            }
            
            # Create message content
            subject, message_body = create_email_content(participant, goal_data)
            
            # Try to send notification
            email_success = send_goal_notification(participant, goal_data)
            
            # Build detailed log
            detailed_info = f"""Notification for {participant.user.email}
			Goal Date: {goal_date}
			Subject: {subject}

			Message Content:
			{message_body}

			Status: {'✅ Email sent successfully' if email_success else '⚠️ Message logged but email sending failed'}"""
            
            context = {
                "success": email_success,
                "message": f"Notification processed for {participant.user.email}",
                "error": None if email_success else "Email sending failed - check configuration",
                "detailed_log": detailed_info
            }
        else:
            context = {
                "success": False,
                "error": "No recent goals found to notify about"
            }
            
    except Exception as e:
        context = {
            "success": False,
            "error": f"Error: {str(e)}"
        }
    
    return render(request, "admin/popup_result.html", context)