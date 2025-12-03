# SaaS Subscription Access Control Middleware
# ==========================================

from django.shortcuts import redirect
from django.urls import reverse
from django.utils.deprecation import MiddlewareMixin
from django.http import JsonResponse
from accounts.models import RestaurantSubscription, User
import logging

logger = logging.getLogger(__name__)


class SubscriptionAccessMiddleware(MiddlewareMixin):
    """
    Middleware to enforce SaaS subscription access control
    Blocks access for expired/blocked restaurants
    """
    
    # URLs that are always accessible (authentication, system admin, etc.)
    EXEMPT_URLS = [
        '/accounts/login/',
        '/accounts/logout/',
        '/accounts/register/',
        '/accounts/access-blocked/',
        '/system-admin/',
        '/admin/',
        '/static/',
        '/media/',
        '/service-worker.js',
        '/health-check/',
        '/manifest.json'
    ]
    
    def process_request(self, request):
        """
        Process incoming request to check subscription access
        """
        # Skip middleware for exempted URLs
        if self._is_exempt_url(request.path_info):
            return None
            
        # Skip for unauthenticated users (they'll be redirected to login)
        if not request.user.is_authenticated:
            return None
            
        # Skip for superusers and system administrators
        if request.user.is_superuser or (hasattr(request.user, 'role') and 
                                        request.user.role and request.user.role.name == 'administrator'):
            return None
            
        # Check subscription access for restaurant owners and staff
        if hasattr(request.user, 'role') and request.user.role:
            role_name = request.user.role.name
            
            # Define all owner roles
            owner_roles = ['owner', 'main_owner', 'branch_owner']
            
            # Define all staff roles
            staff_roles = ['customer_care', 'kitchen', 'bar', 'cashier']
            
            if role_name in owner_roles or role_name in staff_roles:
                # Log this for debugging
                print(f"[SUBSCRIPTION MIDDLEWARE] Checking access for {request.user.username} (role: {role_name})")
                return self._check_subscription_access(request)
                
        return None
    
    def _is_exempt_url(self, path):
        """
        Check if the URL is exempt from subscription checking
        """
        for exempt_url in self.EXEMPT_URLS:
            if path.startswith(exempt_url):
                return True
        return False
    
    def _check_subscription_access(self, request):
        """
        Check subscription access for restaurant users
        Handles cascade blocking: main_owner → branches → staff
        """
        try:
            # Get the restaurant owner whose subscription should be checked
            role_name = request.user.role.name
            restaurant_owner = None
            
            # Determine which owner's subscription to check
            if role_name == 'owner':
                # Legacy SINGLE plan owner
                restaurant_owner = request.user
                print(f"[SUBSCRIPTION] Owner {request.user.username} - checking own subscription")
                
            elif role_name == 'main_owner':
                # PRO plan main owner - check their own subscription
                restaurant_owner = request.user
                print(f"[SUBSCRIPTION] Main owner {request.user.username} - checking own subscription")
                
            elif role_name == 'branch_owner':
                # Branch owner - need to check MAIN owner's subscription (cascade)
                from restaurant.models import Restaurant
                
                # Find the branch this owner manages
                branch_restaurant = Restaurant.objects.filter(branch_owner=request.user).first()
                
                if branch_restaurant and branch_restaurant.parent_restaurant:
                    # Check the main owner's subscription
                    restaurant_owner = branch_restaurant.parent_restaurant.main_owner
                    print(f"[SUBSCRIPTION] Branch owner {request.user.username} - checking main owner {restaurant_owner.username}'s subscription (cascade)")
                else:
                    # Branch owner has no parent - check their own subscription
                    restaurant_owner = request.user
                    print(f"[SUBSCRIPTION] Branch owner {request.user.username} - no parent, checking own subscription")
                    
            elif role_name in ['customer_care', 'kitchen', 'bar', 'cashier']:
                # Staff member - check their owner's subscription
                if request.user.owner:
                    direct_owner = request.user.owner
                    
                    # Check if direct owner is a branch_owner
                    if hasattr(direct_owner, 'role') and direct_owner.role.name == 'branch_owner':
                        # Staff of branch owner - need to check MAIN owner's subscription (cascade)
                        from restaurant.models import Restaurant
                        
                        branch_restaurant = Restaurant.objects.filter(branch_owner=direct_owner).first()
                        
                        if branch_restaurant and branch_restaurant.parent_restaurant:
                            restaurant_owner = branch_restaurant.parent_restaurant.main_owner
                            print(f"[SUBSCRIPTION] Staff {request.user.username} of branch owner {direct_owner.username} - checking main owner {restaurant_owner.username}'s subscription (cascade)")
                        else:
                            restaurant_owner = direct_owner
                            print(f"[SUBSCRIPTION] Staff {request.user.username} - checking direct owner {direct_owner.username}'s subscription")
                    else:
                        # Staff of regular owner or main_owner
                        restaurant_owner = direct_owner
                        print(f"[SUBSCRIPTION] Staff {request.user.username} - checking owner {restaurant_owner.username}'s subscription")
                else:
                    print(f"[SUBSCRIPTION] Staff {request.user.username} has NO OWNER!")
            else:
                return None
                
            if not restaurant_owner:
                logger.warning(f"Could not determine restaurant owner for {request.user.username}")
                return self._redirect_to_blocked_page(request, "Account configuration error")
                
            # Get subscription for this restaurant owner
            try:
                subscription = RestaurantSubscription.objects.get(
                    restaurant_owner=restaurant_owner
                )
                
                # Update subscription status automatically to ensure real-time blocking
                subscription.update_subscription_status()
                
                print(f"[SUBSCRIPTION DEBUG] User: {request.user.username}, Checking: {restaurant_owner.username}, Subscription Status: {subscription.subscription_status}, Is Active: {subscription.is_active}")
                
            except RestaurantSubscription.DoesNotExist:
                # Auto-create a default subscription for existing restaurants
                logger.info(f"Creating default subscription for existing restaurant owner {restaurant_owner.username}")
                from django.utils import timezone
                from datetime import timedelta
                
                try:
                    subscription = RestaurantSubscription.objects.create(
                        restaurant_owner=restaurant_owner,
                        subscription_start_date=timezone.now().date(),
                        subscription_end_date=timezone.now().date() + timedelta(days=30),
                        subscription_status='active',
                        created_by=restaurant_owner,  # Self-created for existing restaurants
                        is_blocked_by_admin=False
                    )
                    
                    # Log the auto-creation
                    from accounts.models import SubscriptionLog
                    SubscriptionLog.objects.create(
                        subscription=subscription,
                        action='auto_created',
                        description=f"Auto-created default 30-day subscription for existing restaurant",
                        old_status='none',
                        new_status='active',
                        performed_by=restaurant_owner
                    )
                    
                    logger.info(f"Default subscription created successfully for {restaurant_owner.username}")
                except Exception as create_error:
                    logger.error(f"Failed to create default subscription for {restaurant_owner.username}: {create_error}")
                    return self._redirect_to_blocked_page(request, "Unable to create subscription. Please contact administrator.")
                
            # Check if subscription allows access
            if not subscription.is_active:
                reason = "Your restaurant subscription has expired or is inactive"
                if subscription.is_blocked_by_admin:
                    reason = f"Restaurant access blocked: {subscription.block_reason}"
                    
                # Add context about cascade blocking
                if restaurant_owner != request.user:
                    if role_name == 'branch_owner':
                        reason += f" (Main restaurant subscription blocked)"
                    elif role_name in ['customer_care', 'kitchen', 'bar', 'cashier']:
                        reason += f" (Restaurant owner's subscription blocked)"
                    
                logger.info(f"Blocking access for {request.user.username}: {reason}")
                return self._redirect_to_blocked_page(request, reason)
                
        except Exception as e:
            logger.error(f"Error checking subscription access for {request.user.username}: {e}")
            # In case of error, allow access to prevent system breakdown
            return None
            
        return None
    
    def _redirect_to_blocked_page(self, request, reason):
        """
        Redirect to blocked access page
        """
        # For AJAX requests, return JSON response
        if request.headers.get('X-Requested-With') == 'XMLHttpRequest':
            return JsonResponse({
                'error': 'access_blocked',
                'message': reason,
                'redirect_url': reverse('accounts:access_blocked')
            }, status=403)
            
        # For regular requests, redirect to access blocked page
        from django.shortcuts import redirect
        from urllib.parse import urlencode
        
        # Pass the reason as a URL parameter
        blocked_url = reverse('accounts:access_blocked')
        params = urlencode({'reason': reason})
        return redirect(f"{blocked_url}?{params}")


# Additional utility functions for subscription management
def check_restaurant_subscription(restaurant_owner):
    """
    Utility function to check restaurant subscription status
    """
    try:
        subscription = RestaurantSubscription.objects.get(
            restaurant_owner=restaurant_owner
        )
        return subscription.is_active
    except RestaurantSubscription.DoesNotExist:
        return False