from django.conf import settings
from budget_app.constants import is_privileged_user_account


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
    from budget_app.services import (
        is_view_only_user,
        is_executive_view_only_user,
        is_district_view_only_user,
        can_access_dashboard,
        can_access_gl_actual_template,
    )

    is_view_only = is_view_only_user(request)
    is_executive = is_executive_view_only_user(request)
    is_district = is_district_view_only_user(request)

    is_privileged = is_privileged_user_account(request.user) and not is_view_only

    settings_obj = SystemSettings.load()
    current_year = datetime.now().year
    can_mutate_when_frozen = is_privileged or not bool(settings_obj.is_frozen)
    is_auth_writable = getattr(request.user, 'is_authenticated', False) is True and not is_view_only

    # Any authenticated, non-view-only user may create, edit, and cancel their own
    # documents while the budget is open (system_frozen=0). Once frozen (budget closed),
    # only privileged users (ALL_BRANCH_USERNAMES / superusers) keep create, edit,
    # and cancel controls.
    can_edit_own_documents = is_auth_writable and can_mutate_when_frozen
    can_add_budget = is_auth_writable and can_mutate_when_frozen
    return {
        'system_frozen': settings_obj.is_frozen,
        'frozen_message': settings_obj.frozen_message,
        'active_budget_year': settings_obj.active_budget_year,
        'is_privileged_user': is_privileged,
        'is_executive_view_only': is_executive,
        'is_district_view_only': is_district,
        'is_view_only': is_view_only,
        'can_edit_own_documents': can_edit_own_documents,
        'can_add_budget': can_add_budget,
        'can_access_dashboard': can_access_dashboard(request),
        'can_access_gl_actual_template': can_access_gl_actual_template(request),
        'budget_year_options': range(current_year - 1, current_year + 4),
    }
