import calendar
from datetime import date, timedelta
from typing import List

def add_months(sourcedate: date, months: int) -> date:
    """Add calendar months to a date, clamping the day if the target month is shorter."""
    month = sourcedate.month - 1 + months
    year = sourcedate.year + month // 12
    month = month % 12 + 1
    day = min(sourcedate.day, calendar.monthrange(year, month)[1])
    return date(year, month, day)

def advance_date(base_date: date, freq: str, interval_days: int) -> date:
    """Advance a date by one frequency step."""
    if freq == "daily":
        return base_date + timedelta(days=1)
    elif freq == "weekly":
        return base_date + timedelta(weeks=1)
    elif freq == "monthly":
        return add_months(base_date, 1)
    elif freq == "custom":
        return base_date + timedelta(days=max(interval_days, 1))
    return base_date

def recalculate_next_date(freq: str, interval_days: int, is_floating: bool, current_due_date: str) -> str:
    """
    Recalculate next due date when completing a task.
    - If is_floating is True: Next occurrence is calculated from today (completion date).
    - If is_floating is False: Next occurrence is calculated from the previous due date.
      If it is overdue (earlier than today), it is advanced repeatedly until it's in the future.
    """
    today = date.today()
    try:
        event = date.fromisoformat(current_due_date)
    except ValueError:
        event = today

    if is_floating:
        # Floating task: next occurrence relative to today (completion date)
        next_event = advance_date(today, freq, interval_days)
    else:
        # Fixed task: next occurrence relative to the scheduled due date
        next_event = advance_date(event, freq, interval_days)
        # If the next date is still in the past or today, we advance it again
        # to ensure the next due date is strictly in the future.
        while next_event <= today:
            next_event = advance_date(next_event, freq, interval_days)
            
    return next_event.isoformat()

def get_occurrences(task: dict, months_ahead: int = 3) -> List[str]:
    """
    Return future occurrence dates for a task,
    from its due date up to months_ahead months from now.
    For 'none' tasks, returns just the event_date.
    """
    freq = task.get("freq", "none")
    if freq == "none":
        return [task["event_date"]]
        
    try:
        start = date.fromisoformat(task["event_date"])
    except ValueError:
        return []
        
    cutoff = date.today() + timedelta(days=months_ahead * 31)
    
    dates = []
    current = start
    dates.append(current.isoformat())
    while True:
        current = advance_date(current, freq, task.get("interval_days", 0))
        if current > cutoff:
            break
        dates.append(current.isoformat())
    return dates
