from functools import wraps
from django.contrib.auth.decorators import login_required
from django.core.exceptions import PermissionDenied
from accounts.models import Membership


def role_required(*roles, staff_allowed=True):
    def decorator(view):
        @login_required
        @wraps(view)
        def wrapped(request, *args, **kwargs):
            if staff_allowed and request.user.is_staff:
                request.membership = None
                return view(request, *args, **kwargs)
            memberships = request.user.memberships.filter(is_active=True, role__in=roles).select_related("organization")
            active_organization_id = request.session.get("active_organization_id")
            membership = memberships.filter(organization_id=active_organization_id).first() if active_organization_id else None
            membership = membership or memberships.order_by("created_at", "id").first()
            if not membership:
                raise PermissionDenied
            request.membership = membership
            request.session["active_organization_id"] = str(membership.organization_id)
            return view(request, *args, **kwargs)
        return wrapped
    return decorator


customer_required = role_required(Membership.Role.OWNER, Membership.Role.MANAGER, Membership.Role.VIEWER, staff_allowed=False)
technician_required = role_required(Membership.Role.TECHNICIAN)
operations_required = role_required(staff_allowed=True)
