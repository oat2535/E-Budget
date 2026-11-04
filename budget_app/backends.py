import hashlib
import logging

from django.contrib.auth.backends import BaseBackend, ModelBackend
from django.contrib.auth.models import User
from django.db import connections

logger = logging.getLogger(__name__)

class ImedxAuthBackend(BaseBackend):
    def authenticate(self, request, username=None, password=None, **kwargs):
        if not username or not password:
            return None
        
        try:
            with connections['imedx'].cursor() as cursor:
                cursor.execute(
                    "SELECT employee_id, password, prename, firstname, lastname, "
                    "bank_sub_name, bank_account_note, active "
                    "FROM employee WHERE employee_id = %s",
                    [username]
                )
                row = cursor.fetchone()
                
                if row:
                    emp_id, db_password, prename, firstname, lastname, bank_sub_name, bank_account_note, active = row
                    
                    # Hash provided password using MD5
                    encoded_password = hashlib.md5(password.encode('utf-8')).hexdigest()
                    
                    if encoded_password.lower() == str(db_password or '').strip().lower():
                        # 1. Check if employee is active in iMedX
                        if active is not None and str(active).strip() == '0':
                            logger.warning(f"ImedxAuthBackend: Login rejected for inactive employee '{username}'")
                            if request is not None:
                                request.auth_failure_reason = 'inactive_employee'
                            return None

                        # 2. Check required profile fields (bank_sub_name, bank_account_note)
                        sub_name_clean = (bank_sub_name or '').strip()
                        account_note_clean = (bank_account_note or '').strip()

                        # Existing local superusers bypass profile check to avoid lockout
                        is_superuser = User.objects.filter(username=username, is_superuser=True).exists()
                        if not is_superuser and (not sub_name_clean or not account_note_clean):
                            missing_fields = []
                            if not sub_name_clean:
                                missing_fields.append('bank_sub_name')
                            if not account_note_clean:
                                missing_fields.append('bank_account_note')

                            logger.warning(
                                f"ImedxAuthBackend: Login rejected for employee '{username}' "
                                f"due to missing iMedX profile fields: {', '.join(missing_fields)}"
                            )
                            if request is not None:
                                request.auth_failure_reason = 'missing_imedx_profile'
                                request.auth_missing_fields = missing_fields
                            return None

                        # Get or create the local Django user
                        user, created = User.objects.get_or_create(username=username)
                        
                        # Set full name
                        first_name_str = f"{prename or ''}{firstname or ''}"
                        user.first_name = first_name_str[:150]
                        user.last_name = (lastname or '')[:150]
                        
                        # Ensure user always has unusable local password so iMedX remains single source of truth
                        user.set_unusable_password()
                        if created:
                            user.is_staff = False
                            
                        user.save()
                        return user
        except Exception as e:
            logger.error(f"ImedxAuthBackend error authenticating {username}: {e}")
            return None
            
        return None

    def get_user(self, user_id):
        try:
            return User.objects.get(pk=user_id)
        except User.DoesNotExist:
            return None


class LocalModelBackend(ModelBackend):
    """
    Fallback authentication backend for purely local Django accounts (e.g. emergency superuser)
    that do not exist or are inactive in iMedX. If an account is an active iMedX employee,
    iMedX is the authoritative identity provider and local password authentication is strictly rejected.
    """
    def authenticate(self, request, username=None, password=None, **kwargs):
        if not username or not password:
            return None

        try:
            with connections['imedx'].cursor() as cursor:
                cursor.execute(
                    "SELECT active FROM employee WHERE employee_id = %s",
                    [username]
                )
                row = cursor.fetchone()
                if row and row[0] is not None and str(row[0]).strip() == '1':
                    logger.warning(
                        f"LocalModelBackend: Denied local password login for active iMedX employee '{username}'. "
                        "Authentication must be performed against iMedX."
                    )
                    return None
        except Exception as e:
            logger.error(f"LocalModelBackend: Error checking iMedX for '{username}': {e}")

        return super().authenticate(request, username=username, password=password, **kwargs)
