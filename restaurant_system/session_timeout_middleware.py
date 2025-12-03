"""
Session Timeout Middleware
Handles automatic logout after 15 minutes of inactivity
Shows user-friendly message when session expires
"""

from django.shortcuts import redirect
from django.contrib import messages
from django.urls import reverse
from django.utils.deprecation import MiddlewareMixin
from django.contrib.auth import logout
import time


class SessionTimeoutMiddleware(MiddlewareMixin):
    """
    Middleware to track user activity and automatically logout after inactivity
    
    How it works:
    1. On every request, checks last activity timestamp
    2. If more than 15 minutes passed → logout user
    3. If active → update timestamp
    4. Shows friendly message on timeout
    """
    
    # URLs that don't require authentication (skip timeout check)
    EXEMPT_URLS = [
        '/accounts/login/',
        '/accounts/logout/',
        '/accounts/register/',
        '/accounts/password-reset/',
        '/static/',
        '/media/',
        '/service-worker.js',
        '/manifest.json',
    ]
    
    def process_request(self, request):
        """
        Check if user session has timed out
        """
        # Skip if URL is exempt
        if self._is_exempt_url(request.path_info):
            return None
        
        # Skip if user is not authenticated
        if not request.user.is_authenticated:
            return None
        
        # Get current timestamp
        current_time = time.time()
        
        # Get last activity from session
        last_activity = request.session.get('last_activity')
        
        if last_activity:
            # Calculate inactivity duration
            inactive_duration = current_time - last_activity
            
            # Session timeout: 15 minutes (900 seconds)
            # Note: This is in addition to SESSION_COOKIE_AGE
            # This middleware provides more precise control
            timeout_seconds = 900  # 15 minutes
            
            if inactive_duration > timeout_seconds:
                # Session timed out - logout user
                messages.warning(
                    request,
                    'Your session has expired due to inactivity. '
                    'Please log in again to continue. '
                    f'(Auto-logout after {timeout_seconds // 60} minutes of inactivity)'
                )
                
                # Logout user
                logout(request)
                
                # Redirect to login page
                return redirect(reverse('accounts:login'))
        
        # Update last activity timestamp
        request.session['last_activity'] = current_time
        
        return None
    
    def _is_exempt_url(self, path):
        """
        Check if URL should skip timeout check
        """
        for exempt_url in self.EXEMPT_URLS:
            if path.startswith(exempt_url):
                return True
        return False


class SessionActivityTrackerMiddleware(MiddlewareMixin):
    """
    Optional: Track user activity details for analytics/security
    
    This middleware logs:
    - Last page visited
    - Activity count
    - Session duration
    """
    
    def process_request(self, request):
        """
        Track user activity details
        """
        if not request.user.is_authenticated:
            return None
        
        # Track activity count
        activity_count = request.session.get('activity_count', 0)
        request.session['activity_count'] = activity_count + 1
        
        # Track last page
        request.session['last_page'] = request.path
        
        # Track session start time (if not set)
        if 'session_start' not in request.session:
            request.session['session_start'] = time.time()
        
        return None
