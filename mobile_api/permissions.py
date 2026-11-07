from rest_framework.permissions import BasePermission
from rest_framework.exceptions import PermissionDenied


def resolve_subscription_owner(u):
    """
    Return the owner whose RestaurantSubscription governs this user's access:
    owners use their own; branch owners (and their staff) use the main owner of
    the parent restaurant, because a branch has no subscription of its own.
    Returns None for staff with no restaurant assignment.
    """
    role = u.role.name if getattr(u, 'role', None) else None
    if role in ('main_owner', 'owner'):
        return u
    if role == 'branch_owner':
        return _branch_subscription_owner(u)
    direct = getattr(u, 'owner', None)
    if direct is None:
        return None
    if getattr(direct, 'role', None) and direct.role.name == 'branch_owner':
        return _branch_subscription_owner(direct)
    return direct


def _branch_subscription_owner(branch_owner):
    from restaurant.models_restaurant import Restaurant as _R
    branch = _R.objects.filter(branch_owner=branch_owner).first()
    if branch and branch.parent_restaurant:
        return branch.parent_restaurant.main_owner
    return branch_owner


class IsSubscriptionActive(BasePermission):
    """
    Blocks access for restaurant owners and staff whose subscription is
    expired or blocked.  Must run AFTER DRF authentication so request.user
    is the real user (not AnonymousUser).

    Mirrors the logic in subscription_middleware.py but runs inside the DRF
    permission pipeline so it works for token-authenticated mobile API calls.
    """

    def has_permission(self, request, view):
        u = request.user
        if not u.is_authenticated:
            return True  # authentication permission handles unauthenticated users

        # Superusers and customers are never subscription-blocked
        if u.is_superuser:
            return True
        if not hasattr(u, 'role') or not u.role:
            return True
        if u.role.name == 'customer':
            return True

        # Determine which owner's subscription to check
        owner = resolve_subscription_owner(u)

        if not owner:
            # Staff with no restaurant assignment should not be granted access
            raise PermissionDenied({'error': 'No restaurant associated with this account. Contact your administrator.'})

        try:
            from accounts.models import RestaurantSubscription
            sub = RestaurantSubscription.objects.get(restaurant_owner=owner)
            if not sub.is_active:
                raise PermissionDenied(
                    detail={
                        'error': 'access_blocked',
                        'message': (
                            f"Restaurant access blocked: {sub.block_reason}"
                            if sub.is_blocked_by_admin
                            else "Your restaurant subscription has expired or is inactive"
                        ),
                    }
                )
        except RestaurantSubscription.DoesNotExist:
            pass  # no subscription record → allow (middleware auto-creates one)

        return True


class IsStaffUser(BasePermission):
    """Cashier, Customer Care, Owner, Manager"""
    def has_permission(self, request, view):
        u = request.user
        return u.is_authenticated and (
            u.is_cashier() or u.is_customer_care() or
            u.is_owner() or u.is_main_owner() or
            u.is_branch_owner() or u.is_manager()
        )


class IsPaymentStaff(BasePermission):
    """Users allowed to process payments"""
    def has_permission(self, request, view):
        u = request.user
        return u.is_authenticated and (
            u.is_cashier() or u.is_customer_care() or
            u.is_owner() or u.is_main_owner() or
            u.is_branch_owner() or u.is_manager()
        )


class IsBillStaff(BasePermission):
    """Users allowed to manage bill requests"""
    def has_permission(self, request, view):
        u = request.user
        return u.is_authenticated and (
            u.is_cashier() or u.is_customer_care() or
            u.is_owner() or u.is_main_owner() or
            u.is_branch_owner() or u.is_manager()
        )
