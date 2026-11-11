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

    is_privileged = request.user.is_authenticated and (
        request.user.username in ALL_BRANCH_USERNAMES or request.user.is_superuser
    ) and not is_view_only

    # Any authenticated user may edit and cancel documents they created themselves,
    # except view-only users (Executive: CHRO, CFO, COO and District/Director:
    # DISTRICT MANAGER, DIRECTOR) who have read-only visibility.
    # Privileged users (nattchai_u, kanchana, pattida_y, and superusers) can edit
    # and cancel any document (their own + others).
    can_edit_own_documents = request.user.is_authenticated and not is_view_only
    settings_obj = SystemSettings.load()
    current_year = datetime.now().year
    can_add_budget = not is_view_only and (is_privileged or not settings_obj.is_frozen)
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
