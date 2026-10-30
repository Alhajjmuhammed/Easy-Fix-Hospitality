"""Customer ratings & feedback: who may rate, saving a rating, staff replies, alerts."""
from datetime import timedelta

from django.core.exceptions import ValidationError
from django.db import IntegrityError, transaction
from django.db.models import Avg, Count, Q
from django.utils import timezone

from .models_feedback import OrderRating

RATEABLE_STATUSES = ('served', 'delivered')
RATING_WINDOW = timedelta(days=7)
MAX_COMMENT = 1000
# Staff roles that can work with feedback (owners always can, unless the module is switched off)
FEEDBACK_ROLES = ('manager', 'customer_care', 'cashier')


def module_enabled(owner):
    """False when the restaurant (or its main business) switched Customer Feedback off in Module Access."""
    from restaurant.models_restaurant import Restaurant
    owners = {owner.pk}
    owners.update(Restaurant.objects.filter(branch_owner=owner, main_owner__isnull=False)
                  .values_list('main_owner_id', flat=True))
    from accounts.models import RestaurantSubscription
    return not RestaurantSubscription.objects.filter(
        restaurant_owner_id__in=owners, disabled_features__slug='view_feedback').exists()


def can_rate(order, user):
    from .push import _restaurant_owner
    if not (user.is_authenticated and user.is_customer() and order.ordered_by_id == user.id
            and order.status in RATEABLE_STATUSES
            and order.created_at >= timezone.now() - RATING_WINDOW
            and not OrderRating.objects.filter(order=order).exists()):
        return False
    owner = _restaurant_owner(order)
    return owner is not None and module_enabled(owner)


def _clean_text(value):
    if not isinstance(value, str):
        return ''
    return value.replace('\x00', '').strip()[:MAX_COMMENT]


def _stars(value, label, required=True):
    if value in (None, ''):
        if required:
            raise ValidationError(f'Please choose 1 to 5 stars for {label}.')
        return None
    text = str(value).strip() if isinstance(value, (str, int)) and not isinstance(value, bool) else ''
    if text not in ('1', '2', '3', '4', '5'):   # whole stars only: '2.5', '²', True are refused
        raise ValidationError(f'Please choose 1 to 5 stars for {label}.')
    return int(text)


def submit_rating(order, user, food, delivery=None, comment=''):
    from .push import _restaurant_owner
    if not can_rate(order, user):
        raise ValidationError('This order can no longer be rated.')
    owner = _restaurant_owner(order)
    if owner is None:
        raise ValidationError('This order can no longer be rated.')
    food = _stars(food, 'the food')
    delivery = _stars(delivery, 'the delivery', required=False) if order.order_type == 'delivery' else None
    try:
        with transaction.atomic():
            rating = OrderRating.objects.create(
                order=order, customer=user, restaurant_owner=owner, food_stars=food, delivery_stars=delivery,
                comment=_clean_text(comment))
    except IntegrityError:  # double tap / two devices at once
        raise ValidationError('You have already rated this order.')
    if rating.is_low:
        from .push import notify_low_rating
        notify_low_rating(rating)
    return rating


def ratings_for_owner(owner):
    """Ratings a staff owner may see: their own restaurant, plus their branches for a main owner."""
    from restaurant.models_restaurant import Restaurant
    branch_owners = Restaurant.objects.filter(main_owner=owner, branch_owner__isnull=False) \
        .values_list('branch_owner_id', flat=True)
    return OrderRating.objects.filter(Q(restaurant_owner=owner) | Q(restaurant_owner_id__in=branch_owners))


def summary(qs):
    data = qs.aggregate(avg=Avg('food_stars'), count=Count('id'), delivery_avg=Avg('delivery_stars'),
                        low=Count('id', filter=Q(food_stars__lte=2) | Q(delivery_stars__lte=2)),
                        unreplied=Count('id', filter=Q(reply='')))
    data['avg'] = round(data['avg'], 1) if data['avg'] is not None else None
    data['delivery_avg'] = round(data['delivery_avg'], 1) if data['delivery_avg'] is not None else None
    return data


def save_reply(rating, user, text):
    """One reply per rating. Only the first succeeds, so a double click can't send two notifications."""
    text = _clean_text(text)
    if not text:
        raise ValidationError('Please write a reply.')
    updated = OrderRating.objects.filter(pk=rating.pk, reply='').update(
        reply=text, replied_by=user, replied_at=timezone.now())
    if not updated:
        raise ValidationError('This rating already has a reply.')
    rating.refresh_from_db()
    from .push import notify_rating_reply
    notify_rating_reply(rating)
    return rating


def rating_to_dict(rating, staff=False):
    data = {
        'id': rating.id,
        'order_id': rating.order_id,
        'food_stars': rating.food_stars,
        'delivery_stars': rating.delivery_stars,
        'comment': rating.comment,
        'reply': rating.reply,
        'replied_at': rating.replied_at.isoformat() if rating.replied_at else None,
        'created_at': rating.created_at.isoformat(),
    }
    if staff:
        data.update({
            'order_number': rating.order.order_number,
            'order_type': rating.order.order_type,
            'customer_name': rating.customer.get_full_name() or rating.customer.username,
            'is_low': rating.is_low,
        })
    return data
