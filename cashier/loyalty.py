"""Loyalty points: settings per business, earning on paid orders, redeeming as a payment.

Earning is reconciled per order (like recipe stock): when an order becomes fully paid the
customer earns floor(money paid / spend_per_point) points; if a payment is voided and the
order is no longer paid, those points are taken back. Money paid *with* points earns nothing.
Redeeming: the cashier picks "Loyalty points" as the payment method; the points are taken
in the same transaction as the payment, and given back if that payment is voided.
"""
import hmac
import logging
import math
import secrets
from decimal import Decimal, InvalidOperation

from django.core.cache import cache
from django.core.exceptions import ValidationError
from django.db import transaction
from django.db.models import Sum

from .models_loyalty import LoyaltyOrderCustomer, LoyaltyProgram, LoyaltyRedeemCode, LoyaltyTransaction

logger = logging.getLogger(__name__)

MAX_CODE_FAILURES = 5          # wrong redeem codes per customer …
CODE_LOCK_SECONDS = 15 * 60    # … within this time lock redeeming for that customer
NOT_PAYABLE_STATUSES = {'cancelled', 'customer_refused', 'kitchen_error', 'quality_issue', 'wasted'}


def redeem_code(customer, rotate=False):
    """The customer's current 6-digit code for spending points (made on first use)."""
    obj, created = LoyaltyRedeemCode.objects.get_or_create(
        customer=customer, defaults={'code': f'{secrets.randbelow(10 ** 6):06d}'})
    if rotate and not created:
        obj.code = f'{secrets.randbelow(10 ** 6):06d}'
        obj.save(update_fields=['code', 'updated_at'])
    return obj.code


def _check_code(customer, code):
    key = f'loyalty-code-fail:{customer.pk}'
    if (cache.get(key) or 0) >= MAX_CODE_FAILURES:
        raise ValidationError('Too many wrong codes. Points can be used again in 15 minutes.')
    real = redeem_code(customer)
    if not hmac.compare_digest(str(code or '').strip(), real):
        try:
            cache.add(key, 0, CODE_LOCK_SECONDS)
            cache.incr(key)
        except Exception:
            pass
        raise ValidationError("Wrong points code. Ask the customer for the code shown in their app under 'My Points'.")
    cache.delete(key)


def mask_name(user):
    first = (user.first_name or user.username or '').strip()
    last = (user.last_name or '').strip()
    return f'{first} {last[0]}.' if last else first


def mask_phone(phone):
    digits = ''.join(ch for ch in (phone or '') if ch.isdigit())
    return f'••• {digits[-3:]}' if len(digits) >= 3 else ''


def business_owner(owner):
    """Branches share their main restaurant's programme."""
    if owner is None:
        return None
    from restaurant.models_restaurant import Restaurant
    r = Restaurant.objects.filter(branch_owner=owner, main_owner__isnull=False).select_related('main_owner') \
        .order_by('-is_main_restaurant').first()
    return r.main_owner if r else owner


def program_for_owner(owner, enabled_only=True):
    p = LoyaltyProgram.objects.filter(owner=business_owner(owner)).first()
    if p is None or (enabled_only and not p.enabled):
        return None
    return p


def _order_owner(order):
    from orders.push import _restaurant_owner
    return _restaurant_owner(order)


def order_customer(order):
    """The registered customer who earns / pays with points for this order, if any."""
    link = LoyaltyOrderCustomer.objects.filter(order=order).select_related('customer').first()
    if link is not None:
        return link.customer
    customer = order.ordered_by
    return customer if customer is not None and customer.is_customer() else None


def balance(program_owner, customer):
    return LoyaltyTransaction.objects.filter(program_owner=program_owner, customer=customer) \
        .aggregate(t=Sum('points'))['t'] or 0


def money_value(program, points):
    return (Decimal(points) * program.point_value).quantize(Decimal('0.01'))


# ---------------------------------------------------------------------------
# Earning
# ---------------------------------------------------------------------------

def sync_order_points(order):
    """Make the points earned for this order match its payments. Never raises."""
    from orders.models import Order
    try:
        with transaction.atomic():
            order = Order.objects.select_for_update().filter(pk=order.pk).first()
            if order is None:
                return
            program = program_for_owner(_order_owner(order), enabled_only=False)
            customer = order_customer(order)
            earned = LoyaltyTransaction.objects.filter(order=order, kind__in=('earn', 'reverse'))
            if program is None or customer is None:
                return  # no programme / no customer
            wanted = 0
            # Programme switched off: nothing new is earned, but a void still takes points back
            if order.payment_status == 'paid' and program.enabled:
                money = order.payments.filter(is_voided=False).exclude(payment_method='loyalty') \
                    .aggregate(t=Sum('amount'))['t'] or Decimal('0')
                wanted = int(money // program.spend_per_point)
            have = earned.filter(customer=customer).aggregate(t=Sum('points'))['t'] or 0
            diff = wanted - have
            if diff > 0 and not program.enabled:
                return
            if diff:
                LoyaltyTransaction.objects.create(
                    program_owner=program.owner, customer=customer, order=order, points=diff,
                    kind='earn' if diff > 0 else 'reverse',
                    note=f'Order #{order.order_number}' + ('' if diff > 0 else ' — payment voided'))
    except Exception:
        logger.warning('Loyalty points update failed for order %s', getattr(order, 'pk', None), exc_info=True)


# ---------------------------------------------------------------------------
# Redeeming (called by the payment endpoints, inside their transaction, with the order locked)
# ---------------------------------------------------------------------------

def prepare_redeem(order, amount, code):
    """Check a loyalty payment of `amount` on `order`. Returns (program, customer, points).
    The customer's code proves they agree. Locks the programme row so two tills can't
    spend the same points at once."""
    if order.status in NOT_PAYABLE_STATUSES:
        raise ValidationError('This order is cancelled.')
    owner = business_owner(_order_owner(order))
    program = LoyaltyProgram.objects.select_for_update().filter(owner=owner, enabled=True).first()
    if program is None:
        raise ValidationError('Loyalty points are not switched on for this restaurant.')
    customer = order_customer(order)
    if customer is None:
        raise ValidationError('This order has no registered customer. Link the customer by phone number first.')
    try:
        amount = Decimal(str(amount))
    except (InvalidOperation, ValueError, TypeError):
        raise ValidationError('Invalid amount.')
    points = math.ceil(amount / program.point_value)
    if points < program.min_redeem_points:
        raise ValidationError(f'At least {program.min_redeem_points} points must be used at once '
                              f'({money_value(program, program.min_redeem_points)}).')
    available = balance(program.owner, customer)
    if points > available:
        raise ValidationError(f'Not enough points: this needs {points}, the customer has {available}.')
    _check_code(customer, code)
    return program, customer, points


def record_redeem(program, customer, payment, points, user):
    LoyaltyTransaction.objects.create(
        program_owner=program.owner, customer=customer, order=payment.order, payment=payment,
        points=-points, kind='redeem', note=f'Paid on order #{payment.order.order_number}', created_by=user)
    redeem_code(customer, rotate=True)   # a used code never works again


def refund_voided_payment(payment):
    """A voided loyalty payment gives its points back (once)."""
    if payment.payment_method != 'loyalty' or not payment.is_voided:
        return
    with transaction.atomic():
        redeem = LoyaltyTransaction.objects.select_for_update().filter(payment=payment, kind='redeem').first()
        if redeem is None or LoyaltyTransaction.objects.filter(payment=payment, kind='refund').exists():
            return
        LoyaltyTransaction.objects.create(
            program_owner=redeem.program_owner, customer=redeem.customer, order=redeem.order, payment=payment,
            points=-redeem.points, kind='refund', note=f'Payment voided on order #{payment.order.order_number}')


def order_summary(order):
    """What the payment screens show: can points be used here, and how many."""
    program = program_for_owner(_order_owner(order))
    if program is None:
        return {'enabled': False}
    customer = order_customer(order)
    data = {
        'enabled': True,
        'point_value': str(program.point_value),
        'spend_per_point': str(program.spend_per_point),
        'min_redeem_points': program.min_redeem_points,
        'customer': None,
    }
    if customer is not None:
        pts = balance(program.owner, customer)
        # Masked: staff of any restaurant can look customers up by phone, so never show full details
        data['customer'] = {
            'name': mask_name(customer),
            'phone': mask_phone(getattr(customer, 'phone_number', '')),
            'points': pts,
            'worth': str(money_value(program, max(pts, 0))),
            'linked': LoyaltyOrderCustomer.objects.filter(order=order).exists(),
        }
    return data


def link_customer(order, phone, user):
    """Cashier links a walk-in order to a registered customer by phone (only while unpaid)."""
    from accounts.models import User
    if order.payment_status == 'paid':
        raise ValidationError('This order is already paid.')
    if order.ordered_by is not None and order.ordered_by.is_customer():
        raise ValidationError('This order already belongs to a customer account.')
    digits = ''.join(ch for ch in (phone or '') if ch.isdigit())
    if len(digits) < 6:
        raise ValidationError('Enter the customer\'s phone number.')
    # Numbers are saved in many formats ("0712 345 678", "+255712345678"): narrow down in the
    # database on the last 3 digits, then compare the last 9 digits exactly.
    key = digits[-9:]
    matches = [u for u in User.objects.filter(role__name='customer', is_active=True,
                                              phone_number__contains=digits[-3:])
               if ''.join(ch for ch in (u.phone_number or '') if ch.isdigit()).endswith(key)]
    if not matches:
        raise ValidationError('No registered customer with this phone number.')
    if len(matches) > 1:
        raise ValidationError('More than one customer has this number. Please ask for their full number.')
    LoyaltyOrderCustomer.objects.update_or_create(order=order, defaults={'customer': matches[0], 'linked_by': user})
    return matches[0]
