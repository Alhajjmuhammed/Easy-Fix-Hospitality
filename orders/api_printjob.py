"""
REST API for Print Clients
Allows restaurant's local print client to fetch and process print jobs
"""
from rest_framework import serializers, viewsets, status
from rest_framework.decorators import action
from rest_framework.response import Response
from rest_framework.permissions import IsAuthenticated
from django.utils import timezone
from .models_printjob import PrintJob


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


class PrintJobViewSet(viewsets.ModelViewSet):
    """
    API ViewSet for Print Jobs
    Used by print clients to fetch and update print jobs
    """
    serializer_class = PrintJobSerializer
    permission_classes = [IsAuthenticated]
    
    def get_queryset(self):
        """Return print jobs for authenticated user's restaurant only"""
        user = self.request.user
        
        # Get restaurant owner (support for staff users)
        from accounts.models import get_owner_filter
        restaurant = get_owner_filter(user)
        
        return PrintJob.objects.filter(restaurant=restaurant)
    
    @action(detail=False, methods=['get'])
    def pending(self, request):
        """
        Get all pending print jobs for this restaurant
        Endpoint: /api/print-jobs/pending/
        """
        pending_jobs = self.get_queryset().filter(status='pending').order_by('created_at')
        serializer = self.get_serializer(pending_jobs, many=True)
        
        return Response({
            'count': pending_jobs.count(),
            'jobs': serializer.data
        })
    
    @action(detail=True, methods=['post'])
    def start_printing(self, request, pk=None):
        """
        Mark print job as printing
        Endpoint: /api/print-jobs/{id}/start_printing/
        """
        job = self.get_object()
        
        if job.status != 'pending':
            return Response(
                {'error': 'Job is not pending'},
                status=status.HTTP_400_BAD_REQUEST
            )
        
        client_id = request.data.get('client_id', 'unknown')
        job.mark_printing(client_id)
        
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
        error_msg = request.data.get('error', 'Unknown error')
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
