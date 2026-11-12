from functools import wraps
from django.http import JsonResponse
from budget_app.constants import is_privileged_user_account


def require_not_frozen(view_func):
    """Blocks access to budget-creating and budget-mutating views/APIs while
    the system is frozen (budget closing), for everyone except privileged
    users (is_privileged_user_account: ALL_BRANCH_USERNAMES / superuser) —
    who need to keep working during a freeze to actually close things out
    or lift it.

    - /api/*, non-GET requests, and AJAX requests return 403 JsonResponse
      with settings_obj.frozen_message.
    - Browser GET requests to creation pages record a warning message
      (fail-silent when MessageMiddleware is absent in tests) and redirect
      to budget_list.
    Enforced server-side regardless of what the UI shows, since the navbar's
    blocking modal is a UX affordance, not the real gate."""
    @wraps(view_func)
    def wrapper(request, *args, **kwargs):
        if not is_privileged_user_account(getattr(request, 'user', None)):
            from budget_app.models import SystemSettings
            settings_obj = SystemSettings.load()
            if settings_obj.is_frozen:
                is_api_or_mutation = (
                    request.path.startswith('/api/')
                    or request.method != 'GET'
                    or request.headers.get('X-Requested-With') == 'XMLHttpRequest'
                )
                if is_api_or_mutation:
                    return JsonResponse({'status': 'error', 'message': settings_obj.frozen_message}, status=403)
                from django.contrib import messages
                from django.shortcuts import redirect
                messages.warning(request, settings_obj.frozen_message, fail_silently=True)
                return redirect('budget_list')
        return view_func(request, *args, **kwargs)
    return wrapper


def require_not_executive_view_only(view_func):
    """Blocks view-only users (Executive: CHRO, CFO, COO and District/Director:
    DISTRICT MANAGER, DIRECTOR) from accessing budget creation views:
    - GET: redirects to budget_list
    - POST: returns 403 Forbidden JsonResponse
    Enforced server-side as defense-in-depth, matching the hidden 'Add Budget'
    sidebar menu in base.html."""
    @wraps(view_func)
    def wrapper(request, *args, **kwargs):
        from budget_app.services import is_view_only_user
        if is_view_only_user(request):
            if request.method == 'POST':
                return JsonResponse({
                    'status': 'error',
                    'message': 'ตำแหน่งของท่านมีสิทธิ์ดูข้อมูลเท่านั้น ไม่สามารถสร้างเอกสารได้'
                }, status=403)
            from django.shortcuts import redirect
            return redirect('budget_list')
        return view_func(request, *args, **kwargs)
    return wrapper


require_not_view_only = require_not_executive_view_only


def require_gl_actual_template_access(view_func):
    """Restricts access to the GL Actual Template creation view strictly to
    GL_ACTUAL_TEMPLATE_ALLOWED_USERNAMES (nattchai_u, kanchana_a, pattida_y):
    - GET: redirects to budget_list
    - POST: returns 403 Forbidden JsonResponse"""
    @wraps(view_func)
    def wrapper(request, *args, **kwargs):
        from budget_app.services import can_access_gl_actual_template
        if not can_access_gl_actual_template(request):
            if request.method == 'POST':
                return JsonResponse({
                    'status': 'error',
                    'message': 'ท่านไม่มีสิทธิ์เข้าใช้งานเมนู GL Actual Template'
                }, status=403)
            from django.shortcuts import redirect
            return redirect('budget_list')
        return view_func(request, *args, **kwargs)
    return wrapper


def require_dashboard_access(view_func):
    """Restricts access to Dashboard views and APIs strictly to authorized roles:
    - /api/* or POST: returns 403 Forbidden JsonResponse
    - HTML GET: redirects to budget_list"""
    @wraps(view_func)
    def wrapper(request, *args, **kwargs):
        from budget_app.services import can_access_dashboard
        if not can_access_dashboard(request):
            is_api = request.path.startswith('/api/') or request.method != 'GET' or request.headers.get('X-Requested-With') == 'XMLHttpRequest'
            if is_api:
                return JsonResponse({
                    'status': 'error',
                    'message': 'ท่านไม่มีสิทธิ์เข้าใช้งานหน้า Dashboard'
                }, status=403)
            from django.shortcuts import redirect
            return redirect('budget_list')
        return view_func(request, *args, **kwargs)
    return wrapper
