from rest_framework.permissions import BasePermission
from rest_framework.exceptions import PermissionDenied


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
        owner = None
        role = u.role.name

        if role in ('main_owner', 'owner'):
            owner = u
        elif role == 'branch_owner':
            from restaurant.models_restaurant import Restaurant as _R
            branch = _R.objects.filter(branch_owner=u).first()
            if branch and branch.parent_restaurant:
                owner = branch.parent_restaurant.main_owner
            else:
                owner = u
        elif u.owner:
            direct = u.owner
            if hasattr(direct, 'role') and direct.role and direct.role.name == 'branch_owner':
                from restaurant.models_restaurant import Restaurant as _R
                branch = _R.objects.filter(branch_owner=direct).first()
                if branch and branch.parent_restaurant:
                    owner = branch.parent_restaurant.main_owner
                else:
                    owner = direct
            else:
                owner = direct

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
