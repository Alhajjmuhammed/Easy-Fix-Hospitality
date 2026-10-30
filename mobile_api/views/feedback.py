"""Customer rating of a finished order (app)."""
from django.core.exceptions import ValidationError
from django.shortcuts import get_object_or_404
from rest_framework import status
from rest_framework.decorators import api_view, permission_classes
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response

from orders import feedback as svc
from orders.models import Order
from orders.models_feedback import OrderRating


@api_view(['GET', 'POST'])
@permission_classes([IsAuthenticated])
def order_rating(request, order_id):
    """GET → {can_rate, rating}; POST {food_stars, delivery_stars?, comment?} → {rating}."""
    order = get_object_or_404(Order, id=order_id, ordered_by=request.user)
    if request.method == 'GET':
        rating = OrderRating.objects.filter(order=order).first()
        return Response({
            'can_rate': rating is None and svc.can_rate(order, request.user),
            'rating': svc.rating_to_dict(rating) if rating else None,
        })
    try:
        rating = svc.submit_rating(order, request.user, request.data.get('food_stars'),
                                   request.data.get('delivery_stars'), request.data.get('comment', ''))
    except ValidationError as e:
        return Response({'error': ' '.join(e.messages)}, status=status.HTTP_400_BAD_REQUEST)
    return Response({'rating': svc.rating_to_dict(rating)}, status=status.HTTP_201_CREATED)
