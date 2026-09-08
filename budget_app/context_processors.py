from django.conf import settings


def session_idle_timeout(request):
    """Exposes the session's max idle time to templates, in seconds, so the
    client-side idle-timeout warning in base.html always matches
    SESSION_COOKIE_AGE instead of duplicating the number."""
    return {'session_idle_timeout_seconds': settings.SESSION_COOKIE_AGE}
