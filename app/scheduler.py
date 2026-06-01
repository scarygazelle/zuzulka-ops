from datetime import datetime, timedelta

def recalculate_next_date(interval_days: int, is_floating: bool, current_due_date: str) -> str:
    today = datetime.now()
    if is_floating:
        next_date = today + timedelta(days=interval_days)
    else:
        try:
            base_date = datetime.strptime(current_due_date, "%Y-%m-%d")
            if base_date < today - timedelta(days=interval_days):
                base_date = today
        except ValueError:
            base_date = today
        next_date = base_date + timedelta(days=interval_days)

    return next_date.strftime("%Y-%m-%d")
