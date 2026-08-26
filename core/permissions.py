from functools import wraps
from django.contrib.auth.decorators import login_required
from django.core.exceptions import PermissionDenied
from accounts.models import Membership


def role_required(*roles, staff_allowed=True):
    def decorator(view):
        @login_required
        @wraps(view)
        def wrapped(request, *args, **kwargs):
            membership = request.user.memberships.filter(is_active=True).select_related("organization").first()
            if staff_allowed and request.user.is_staff:
                request.membership = membership
                return view(request, *args, **kwargs)
            if not membership or membership.role not in roles:
                raise PermissionDenied
            request.membership = membership
            return view(request, *args, **kwargs)
        return wrapped
    return decorator


customer_required = role_required(Membership.Role.OWNER, Membership.Role.MANAGER, Membership.Role.VIEWER, staff_allowed=False)
technician_required = role_required(Membership.Role.TECHNICIAN)
operations_required = role_required(Membership.Role.MANAGER, staff_allowed=True)
