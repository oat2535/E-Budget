import time
import logging
from django.contrib import auth, messages
from django.http import JsonResponse
from django.shortcuts import redirect
from django.db import connections

logger = logging.getLogger(__name__)


class ImedxProfileValidationMiddleware:
    """
    Middleware that enforces active session permission validity.
    If an authenticated user's bank_sub_name or bank_account_note in iMedX
    is deleted/emptied, or if the employee is set to inactive (active != '1'),
    their session is immediately revoked, they are logged out, and redirected
    to the login page with a pop-up alert explaining that their permissions were removed.
    """
    EXEMPT_PATHS = ['/login/', '/logout/', '/static/']
    VALIDATION_INTERVAL_SECONDS = 15

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        if request.user.is_authenticated:
            # Emergency local admin account is exempt
            if request.user.username != 'admin':
                for exempt in self.EXEMPT_PATHS:
                    if request.path.startswith(exempt):
                        return self.get_response(request)

                now = time.time()
                last_checked = request.session.get('_imedx_profile_last_checked', 0)

                # Check periodically (every 15 seconds) or when not yet checked
                if now - last_checked > self.VALIDATION_INTERVAL_SECONDS:
                    try:
                        with connections['imedx'].cursor() as cursor:
                            cursor.execute(
                                "SELECT active, bank_sub_name, bank_account_note FROM employee WHERE employee_id = %s",
                                [request.user.username]
                            )
                            row = cursor.fetchone()

                        is_valid = False
                        reason = 'missing_imedx_profile'
                        if row:
                            active, bank_sub_name, bank_account_note = row
                            if str(active or '').strip() != '1':
                                reason = 'inactive_employee'
                            elif not (bank_sub_name or '').strip() or not (bank_account_note or '').strip():
                                reason = 'missing_imedx_profile'
                            else:
                                is_valid = True

                        if not is_valid:
                            username = request.user.username
                            auth.logout(request)
                            logger.warning(
                                f"ImedxProfileValidationMiddleware: Revoked active session for '{username}' "
                                f"(reason: {reason})"
                            )

                            is_ajax_or_api = (
                                request.path.startswith('/api/')
                                or request.headers.get('x-requested-with') == 'XMLHttpRequest'
                                or request.headers.get('content-type', '').startswith('application/json')
                            )
                            if is_ajax_or_api:
                                return JsonResponse({
                                    'status': 'error',
                                    'message': 'สิทธิ์การเข้าใช้งานระบบ E-Budget ของท่านถูกระงับ หรือไม่พบข้อมูลสาขา/ตำแหน่งในระบบ iMedX กรุณาติดต่อฝ่ายบัญชี (ACC) / แผนก IT'
                                }, status=403)

                            msg = (
                                '<div class="text-start" style="line-height: 1.6; font-size: 0.95rem;">'
                                'สิทธิ์การเข้าใช้งานระบบ E-Budget ของท่านถูกระงับ หรือไม่พบข้อมูลสาขา/ฝ่ายงาน (<code>bank_sub_name</code>) '
                                'และตำแหน่ง/บทบาทสิทธิ์ (<code>bank_account_note</code>) ในระบบ iMedX'
                                '<br><br>'
                                'กรุณาติดต่อผู้ดูแลระบบ หรือฝ่ายบัญชี (ACC) / แผนก IT เพื่อดำเนินการตรวจสอบข้อมูล'
                                '</div>'
                            )
                            messages.error(request, msg, extra_tags='imedx_profile warning')
                            return redirect('login')

                        # Mark as validated in session
                        request.session['_imedx_profile_last_checked'] = now
                    except Exception as e:
                        logger.error(f"ImedxProfileValidationMiddleware: Error validating profile for '{request.user.username}': {e}")

        return self.get_response(request)

