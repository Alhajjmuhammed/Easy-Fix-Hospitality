"""
REST API for Print Clients
Allows restaurant's local print client to fetch and process print jobs
"""
from rest_framework import serializers, viewsets, status
from rest_framework.decorators import action
from rest_framework.response import Response
from rest_framework.permissions import IsAuthenticated, BasePermission
from rest_framework.throttling import UserRateThrottle
from django.utils import timezone
from django.core.exceptions import PermissionDenied
import logging

from .models_printjob import PrintJob

logger = logging.getLogger(__name__)

PENDING_POLL_LIMIT = 50   # print jobs handed to a print client per poll


class PrintClientRateThrottle(UserRateThrottle):
    """Custom rate throttle for print clients - allows more frequent polling"""
    rate = '60/minute'  # Print clients poll frequently


class IsRestaurantOwnerOrStaff(BasePermission):
    """
    Custom permission to only allow restaurant owners or their staff
    to access print jobs for their restaurant.
    """
    
    def has_permission(self, request, view):
        if not request.user or not request.user.is_authenticated:
            return False
        
        # Check if user has appropriate role
        if not hasattr(request.user, 'role') or not request.user.role:
            return False
        
        allowed_roles = ['owner', 'main_owner', 'branch_owner', 'manager', 'cashier', 'kitchen', 'bar', 'customer_care']
        return request.user.role.name in allowed_roles
    
    def has_object_permission(self, request, view, obj):
        """Verify user can access this specific print job"""
        from accounts.models import get_owner_filter
        
        try:
            user_restaurant = get_owner_filter(request.user)
            if user_restaurant is None:
                # Administrator - allow all
                return request.user.is_administrator() if hasattr(request.user, 'is_administrator') else False
            
            # Verify the print job belongs to this user's restaurant
            return obj.restaurant_id == user_restaurant.id
        except Exception as e:
            logger.warning(f"Permission check failed: {e}")
            return False


class PrintJobSerializer(serializers.ModelSerializer):
    """Serializer for Print Jobs"""
    
    restaurant_name = serializers.CharField(source='restaurant.restaurant_name', read_only=True)
    order_number = serializers.CharField(source='order.order_number', read_only=True, allow_null=True)
    
    class Meta:
        model = PrintJob
        fields = [
            'id', 'job_type', 'status', 'content',
            'restaurant_name', 'order_number',
            'created_at', 'printed_at', 'error_message',
            'retry_count', 'printer_name'
        ]
        read_only_fields = ['id', 'created_at']


class PrintJobViewSet(viewsets.ReadOnlyModelViewSet):
    """
    API ViewSet for Print Jobs
    Used by print clients to fetch and update print jobs. Read-only apart from the status actions
    below: nobody can rewrite a queued receipt's content or delete jobs through the API.
    """
    serializer_class = PrintJobSerializer
    permission_classes = [IsAuthenticated, IsRestaurantOwnerOrStaff]
    throttle_classes = [PrintClientRateThrottle]
    
    def get_queryset(self):
        """Return print jobs for authenticated user's restaurant only"""
        user = self.request.user
        
        # Get restaurant owner (support for staff users)
        from accounts.models import get_owner_filter
        
        try:
            restaurant = get_owner_filter(user)
            if restaurant is None:
                # If no owner filter (shouldn't happen due to permission class)
                logger.warning(f"No restaurant filter for user: {user.username}")
                return PrintJob.objects.none()
            
            return PrintJob.objects.filter(restaurant=restaurant).select_related('restaurant', 'order')
        except PermissionDenied:
            logger.warning(f"Permission denied for user: {user.username}")
            return PrintJob.objects.none()
        except Exception as e:
            logger.error(f"Error getting print jobs: {e}")
            return PrintJob.objects.none()
    
    @action(detail=False, methods=['get'])
    def pending(self, request):
        """
        Get all pending print jobs for this restaurant.
        Also auto-resets stale 'printing' jobs (stuck > 10 min) back to 'pending'
        so the client can retry them.
        Endpoint: /api/print-jobs/pending/
        """
        from django.utils import timezone
        from datetime import timedelta

        # Reset stale 'printing' jobs that got stuck (client crashed mid-job). Measured from when
        # printing started, so a job queued long ago and just picked up is not handed out twice.
        from django.db.models import Q
        stale_threshold = timezone.now() - timedelta(minutes=10)
        stale_jobs = self.get_queryset().filter(status='printing').filter(
            Q(printed_at__lt=stale_threshold) | Q(printed_at__isnull=True, created_at__lt=stale_threshold)
        )
        if stale_jobs.exists():
            count = stale_jobs.count()
            stale_jobs.update(status='pending', printed_by_client='')
            logger.info(f"Auto-reset {count} stale 'printing' job(s) to 'pending'")

        # Oldest first, at most PENDING_POLL_LIMIT per poll: a client that was offline for a
        # day must not pull (and the server serialise) the whole backlog in one response.
        # Nothing is dropped: the rest comes on the next polls, still oldest first.
        pending_jobs = self.get_queryset().filter(status='pending').order_by('created_at', 'id')
        total_pending = pending_jobs.count()
        batch = list(pending_jobs[:PENDING_POLL_LIMIT])
        serializer = self.get_serializer(batch, many=True)

        return Response({
            'count': total_pending,              # all pending jobs (unchanged meaning)
            'returned': len(batch),
            'has_more': total_pending > len(batch),
            'jobs': serializer.data
        })
    
    @action(detail=True, methods=['post'])
    def start_printing(self, request, pk=None):
        """
        Mark print job as printing
        Endpoint: /api/print-jobs/{id}/start_printing/
        """
        job = self.get_object()
        client_id = str(request.data.get('client_id', 'unknown'))[:255]
        from django.utils import timezone
        # Claim it atomically: two print clients polling at once must not both print it
        if not PrintJob.objects.filter(pk=job.pk, status='pending').update(
                status='printing', printed_by_client=client_id, printed_at=timezone.now()):
            return Response(
                {'error': 'Job is not pending'},
                status=status.HTTP_400_BAD_REQUEST
            )
        job.refresh_from_db()
        
        return Response({
            'message': 'Job marked as printing',
            'job_id': job.id,
            'status': job.status
        })
    
    @action(detail=True, methods=['post'])
    def mark_completed(self, request, pk=None):
        """
        Mark print job as completed
        Endpoint: /api/print-jobs/{id}/mark_completed/
        """
        job = self.get_object()
        job.mark_completed()
        
        return Response({
            'message': 'Job marked as completed',
            'job_id': job.id,
            'status': job.status
        })
    
    @action(detail=True, methods=['post'])
    def mark_failed(self, request, pk=None):
        """
        Mark print job as failed
        Endpoint: /api/print-jobs/{id}/mark_failed/
        """
        job = self.get_object()
        # The print client sends 'error_message'; older clients may send 'error'
        error_msg = request.data.get('error_message') or request.data.get('error') or 'Unknown error'
        job.mark_failed(error_msg)
        
        return Response({
            'message': 'Job marked as failed',
            'job_id': job.id,
            'status': job.status,
            'error': error_msg
        })
    
    @action(detail=True, methods=['post'])
    def retry(self, request, pk=None):
        """
        Retry a failed print job
        Endpoint: /api/print-jobs/{id}/retry/
        """
        job = self.get_object()
        
        if job.retry():
            return Response({
                'message': 'Job queued for retry',
                'job_id': job.id,
                'status': job.status
            })
        else:
            return Response(
                {'error': 'Job is not in failed status'},
                status=status.HTTP_400_BAD_REQUEST
            )
    
    @action(detail=False, methods=['get'])
    def stats(self, request):
        """
        Get print job statistics for this restaurant
        Endpoint: /api/print-jobs/stats/
        """
        queryset = self.get_queryset()
        
        from django.db.models import Count
        stats_by_status = queryset.values('status').annotate(count=Count('id'))
        stats_by_type = queryset.filter(status='pending').values('job_type').annotate(count=Count('id'))
        
        return Response({
            'by_status': list(stats_by_status),
            'pending_by_type': list(stats_by_type),
            'total_jobs': queryset.count()
        })
