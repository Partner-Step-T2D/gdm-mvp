# core/admin_dashboard_views.py
from datetime import date, timedelta, datetime
from django.contrib.admin.views.decorators import staff_member_required
from django.shortcuts import render
from django.http import Http404
from .models import Participant
from collections import defaultdict
from .reports import generate_weekly_excel, generate_daily_excel
import json

def get_next_target_day(start_date):
    today = date.today()
    delta_days = (today - start_date).days
    weeks = delta_days // 7
    if delta_days % 7 == 0 and delta_days >= 7:
        return today
    return start_date + timedelta(days=7 * (weeks + 1))

@staff_member_required
def dashboard_view(request):
    is_superuser = request.user.is_superuser
    is_manager = request.user.groups.filter(name="Managers").exists() and not is_superuser
    //raw_participants = Participant.objects.select_related('user').all().order_by('start_date')
    raw_participants = Participant.objects.select_related('user').filter(user__is_active=True).order_by('start_date')
    today = date.today()
    max_days = 7
    groups = defaultdict(list)
    header_days = {}

    for p in raw_participants:
        next_target = get_next_target_day(p.start_date)
        if not next_target:
            continue
        days_diff = (next_target - today).days
        if 0 <= days_diff < max_days:
            daily_steps_data = {}
            if p.daily_steps:
                try:
                    if isinstance(p.daily_steps, list):
                        for entry in p.daily_steps:
                            date_key = entry.get('date')
                            steps_value = entry.get('value')
                            if date_key and steps_value is not None:
                                daily_steps_data[date_key] = int(steps_value)
                    elif isinstance(p.daily_steps, dict):
                        daily_steps_data = p.daily_steps
                    else:
                        parsed_data = json.loads(p.daily_steps)
                        if isinstance(parsed_data, list):
                            for entry in parsed_data:
                                date_key = entry.get('date')
                                steps_value = entry.get('value')
                                if date_key and steps_value is not None:
                                    daily_steps_data[date_key] = int(steps_value)
                        else:
                            daily_steps_data = parsed_data
                except (json.JSONDecodeError, TypeError, KeyError):
                    daily_steps_data = {}

            groups[days_diff].append({
                "email": p.user.email,
                "next_target_day": next_target,
                "daily_steps": daily_steps_data,
                "participant_id": p.id,
                "participant_obj": p,
            })

    for days in groups.keys():
        block_date = groups[days][0]['next_target_day'] if groups[days] else today + timedelta(days=days)
        header_days[days] = [block_date - timedelta(days=delta) for delta in range(7, 0, -1)]

    for days in range(max_days):
        if days not in header_days:
            block_date = today + timedelta(days=days)
            header_days[days] = [block_date - timedelta(days=delta) for delta in range(7, 0, -1)]

    grouped_participants_with_headers = []
    for days in sorted(set(list(groups.keys()) + list(range(max_days)))):
        participants = groups[days] if days in groups else []
        if days not in header_days:
            block_date = today + timedelta(days=days)
            header_days[days] = [block_date - timedelta(days=delta) for delta in range(7, 0, -1)]

        block_date = participants[0]['next_target_day'] if participants else today + timedelta(days=days)

        processed_participants = []
        for p in participants:
            participant = p['participant_obj']

            steps_for_days = []
            cell_classes = []

            data_count = 0
            for day in header_days[days]:
                day_str = day.strftime('%Y-%m-%d')
                steps = p['daily_steps'].get(day_str, '-')
                if steps != '-':
                    data_count += 1
                steps_for_days.append(steps)

            for i, day in enumerate(header_days[days]):
                day_str = day.strftime('%Y-%m-%d')
                steps = p['daily_steps'].get(day_str, '-')

                if steps != '-':
                    cell_classes.append('has-data')
                else:
                    if day > today:
                        cell_classes.append('no-data-future')
                    elif days <= 1:
                        if data_count < 4:
                            cell_classes.append('no-data-critical')
                        else:
                            cell_classes.append('no-data-warning')
                    elif days <= 3:
                        if data_count < 3:
                            cell_classes.append('no-data-alert')
                        else:
                            cell_classes.append('no-data-caution')
                    else:
                        cell_classes.append('no-data-caution')

            steps_with_classes = []
            for i in range(len(steps_for_days)):
                steps_with_classes.append({
                    'steps': steps_for_days[i],
                    'class': cell_classes[i]
                })

            target_day_str = p['next_target_day'].strftime('%Y-%m-%d')
            target_day_steps = p['daily_steps'].get(target_day_str, '-')

            if target_day_steps != '-':
                target_day_class = 'has-data'
            elif p['next_target_day'] > today:
                target_day_class = 'no-data-future'
            elif days <= 1:
                if data_count < 4:
                    target_day_class = 'no-data-critical'
                else:
                    target_day_class = 'no-data-warning'
            elif days <= 3:
                if data_count < 3:
                    target_day_class = 'no-data-alert'
                else:
                    target_day_class = 'no-data-caution'
            else:
                target_day_class = 'no-data-caution'

            processed_participants.append({
                'email': p['email'],
                'next_target_day': p['next_target_day'],
                'participant_id': p['participant_id'],
                'steps_with_classes': steps_with_classes,
                'data_count': data_count,
                'target_day_steps': target_day_steps,
                'target_day_class': target_day_class,
                'has_errors': (
                    participant.status_flags.get('fetch_fitbit_data_fail', False) or
                    participant.status_flags.get('refresh_fitbit_token_fail', False) or
                    participant.status_flags.get('target_calculation_fail', False) or
                    participant.status_flags.get('send_notification_fail', False)
                ),
            })

        grouped_participants_with_headers.append({
            'days': days,
            'participants': processed_participants,
            'header_days': header_days[days],
            'block_date': block_date
        })

    context = {
        "is_superuser": is_superuser,
        "is_manager": is_manager,
        "grouped_participants_with_headers": grouped_participants_with_headers,
        "today": today,
        "user": request.user,
    }

    return render(request, "admin/dashboard.html", context)


@staff_member_required
def participant_detail_view(request, participant_id):
    try:
        participant = Participant.objects.select_related('user').get(id=participant_id)
    except Participant.DoesNotExist:
        raise Http404("Participant not found")

    is_superuser = request.user.is_superuser
    is_manager = request.user.groups.filter(name="Managers").exists() and not is_superuser

    weekly_summaries = calculate_weekly_summaries(participant)

    error_info = {
        'has_errors': False,
        'fitbit_data_error': None,
        'fitbit_token_error': None,
        'target_calculation_error': None,
        'notification_error': None,
    }

    if participant.status_flags.get('fetch_fitbit_data_fail'):
        error_info['has_errors'] = True
        error_info['fitbit_data_error'] = {
            'message': participant.status_flags.get('fetch_fitbit_data_fail_last_error', 'Unknown error'),
            'timestamp': participant.status_flags.get('fetch_fitbit_data_fail_last_error_time')
        }

    if participant.status_flags.get('refresh_fitbit_token_fail'):
        error_info['has_errors'] = True
        error_info['fitbit_token_error'] = {
            'message': participant.status_flags.get('refresh_fitbit_token_fail_last_error', 'Unknown error'),
            'timestamp': participant.status_flags.get('refresh_fitbit_token_fail_last_error_time')
        }

    if participant.status_flags.get('target_calculation_fail'):
        error_info['has_errors'] = True
        error_info['target_calculation_error'] = {
            'message': participant.status_flags.get('target_calculation_fail_last_error', 'Unknown error'),
            'timestamp': participant.status_flags.get('target_calculation_fail_last_error_time')
        }

    if participant.status_flags.get('send_notification_fail'):
        error_info['has_errors'] = True
        error_info['notification_error'] = {
            'message': participant.status_flags.get('send_notification_fail_last_error', 'Unknown error'),
            'timestamp': participant.status_flags.get('send_notification_fail_last_error_time')
        }

    context = {
        "participant": participant,
        "is_superuser": is_superuser,
        "is_manager": is_manager,
        "user": request.user,
        "weekly_summaries": weekly_summaries,
        "error_info": error_info,
    }

    return render(request, "admin/participant_detail.html", context)


def calculate_weekly_summaries(participant):
    summaries = []
    targets = participant.targets or {}

    if not targets:
        return summaries

    target_dates = sorted(targets.keys())

    messages = getattr(participant, "message_history", [])
    message_lookup = {}
    for msg in messages:
        gd = msg.get("goal_data", {})
        key = (
            gd.get("new_target"),
            gd.get("average_steps"),
            gd.get("target_was_met"),
        )
        message_lookup[key] = msg.get("content")

    for i, target_date_str in enumerate(target_dates):
        target_data = targets[target_date_str]
        target_date = datetime.strptime(target_date_str, '%Y-%m-%d').date()

        week_end = target_date - timedelta(days=1)
        week_start = week_end - timedelta(days=6)

        previous_week_target = None
        goal_met = None

        if i > 0:
            previous_target_data = targets[target_dates[i - 1]]
            previous_week_target = previous_target_data.get('new_target')

            current_average = target_data.get('average_steps')
            if previous_week_target and current_average is not None:
                if current_average == "insufficient data":
                    goal_met = None
                else:
                    try:
                        current_avg_num = float(current_average)
                        previous_target_num = float(previous_week_target)
                        goal_met = current_avg_num >= previous_target_num
                    except (ValueError, TypeError):
                        goal_met = None

        key = (
            target_data.get('new_target'),
            target_data.get('average_steps'),
            goal_met,
        )
        message_content = message_lookup.get(key, "")

        summary = {
            'week_start': week_start,
            'week_end': week_end,
            'week_number': i + 1,
            'weekly_average': target_data.get('average_steps'),
            'previous_week_target': previous_week_target,
            'goal_met': goal_met,
            'new_increase': target_data.get('increase'),
            'new_target': target_data.get('new_target'),
            'message_content': message_content,
        }

        summaries.append(summary)

    summaries.reverse()
    return summaries


@staff_member_required
def export_research_data_view(request):
    if request.method == 'POST':
        participant_id = request.POST.get('participant_id')
        export_type = request.POST.get('export_type', 'weekly')

        if export_type == 'daily':
            if participant_id and participant_id != 'all':
                return generate_daily_excel(participant_id=int(participant_id))
            else:
                return generate_daily_excel()
        else:
            if participant_id and participant_id != 'all':
                return generate_weekly_excel(participant_id=int(participant_id))
            else:
                return generate_weekly_excel()

    participants = Participant.objects.select_related('user').filter(
        user__is_staff=False,
        user__is_superuser=False
    ).order_by('user__email')

    context = {
        'participants': participants,
        'title': 'Export Research Data',
    }

    return render(request, 'admin/export_research_data.html', context)