import hashlib
from django.contrib.auth.backends import BaseBackend
from django.contrib.auth.models import User
from django.db import connections

class ImedxAuthBackend(BaseBackend):
    def authenticate(self, request, username=None, password=None, **kwargs):
        if not username or not password:
            return None
        
        try:
            with connections['imedx'].cursor() as cursor:
                cursor.execute("SELECT employee_id, password, prename, firstname, lastname FROM employee WHERE employee_id = %s", [username])
                row = cursor.fetchone()
                
                if row:
                    emp_id, db_password, prename, firstname, lastname = row
                    
                    # Hash provided password using MD5
                    encoded_password = hashlib.md5(password.encode('utf-8')).hexdigest()
                    
                    if encoded_password == db_password:
                        # Get or create the local Django user
                        user, created = User.objects.get_or_create(username=username)
                        
                        # Set full name
                        first_name_str = f"{prename or ''}{firstname or ''}"
                        user.first_name = first_name_str[:150]
                        user.last_name = (lastname or '')[:150]
                        
                        if created:
                            user.set_unusable_password()
                            user.is_staff = False
                            
                        user.save()
                        return user
        except Exception as e:
            print(f"ImedxAuthBackend Error: {e}")
            return None
            
        return None

    def get_user(self, user_id):
        try:
            return User.objects.get(pk=user_id)
        except User.DoesNotExist:
            return None
