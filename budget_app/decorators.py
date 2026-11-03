from functools import wraps
from django.http import JsonResponse
from budget_app.constants import ALL_BRANCH_USERNAMES


def require_not_frozen(view_func):
    """Blocks POST access to a budget-mutating view while the system is
    frozen (budget closing), for everyone except ALL_BRANCH_USERNAMES —
    who need to keep working during a freeze to actually close things out
    or lift it. Enforced server-side regardless of what the UI shows, since
    the navbar's blocking modal is a UX affordance, not the real gate."""
    @wraps(view_func)
    def wrapper(request, *args, **kwargs):
        if request.method == 'POST' and request.user.username not in ALL_BRANCH_USERNAMES:
            from budget_app.models import SystemSettings
            settings_obj = SystemSettings.load()
            if settings_obj.is_frozen:
                return JsonResponse({'status': 'error', 'message': settings_obj.frozen_message}, status=403)
        return view_func(request, *args, **kwargs)
    return wrapper


def require_not_executive_view_only(view_func):
    """Blocks executive view-only users (CHRO, CFO, COO) from accessing
    budget creation views:
    - GET: redirects to budget_list
    - POST: returns 403 Forbidden JsonResponse
    Enforced server-side as defense-in-depth, matching the hidden 'Add Budget'
    sidebar menu in base.html."""
    @wraps(view_func)
    def wrapper(request, *args, **kwargs):
        from budget_app.services import is_executive_view_only_user
        if is_executive_view_only_user(request):
            if request.method == 'POST':
                return JsonResponse({
                    'status': 'error',
                    'message': 'ตำแหน่งของท่านมีสิทธิ์ดูข้อมูลเท่านั้น ไม่สามารถสร้างเอกสารได้'
                }, status=403)
            from django.shortcuts import redirect
            return redirect('budget_list')
        return view_func(request, *args, **kwargs)
    return wrapper
