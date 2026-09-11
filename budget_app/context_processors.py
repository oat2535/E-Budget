from django.conf import settings
from budget_app.constants import ALL_BRANCH_USERNAMES


def session_idle_timeout(request):
    """Exposes the session's max idle time to templates, in seconds, so the
    client-side idle-timeout warning in base.html always matches
    SESSION_COOKIE_AGE instead of duplicating the number."""
    return {'session_idle_timeout_seconds': settings.SESSION_COOKIE_AGE}


def site_status(request):
    """System-wide freeze/active-year state, available on every page (the
    freeze modal and the year badge in base.html both need it regardless of
    which view rendered the page) plus the one permission flag every
    template that gates an edit control checks."""
    from datetime import datetime
    from budget_app.models import SystemSettings
    is_privileged = request.user.is_authenticated and request.user.username in ALL_BRANCH_USERNAMES
    settings_obj = SystemSettings.load()
    current_year = datetime.now().year
    return {
        'system_frozen': settings_obj.is_frozen,
        'frozen_message': settings_obj.frozen_message,
        'active_budget_year': settings_obj.active_budget_year,
        'is_privileged_user': is_privileged,
        'budget_year_options': range(current_year - 1, current_year + 4),
    }
