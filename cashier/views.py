from django.shortcuts import render, get_object_or_404, redirect
from django.contrib.auth.decorators import login_required
from django.contrib import messages
from django.http import JsonResponse
from django.db.models import Q, Sum, Prefetch
from django.views.decorators.http import require_http_methods
from django.utils import timezone
from decimal import Decimal, InvalidOperation
import json
import logging

logger = logging.getLogger(__name__)

from accounts.models import get_owner_filter
from orders.models import Order, OrderItem
from restaurant.models import TableInfo, Product
from waste_management.models import FoodWasteLog
from .models import Payment, OrderItemPayment, VoidTransaction
from orders.printing import auto_print_receipt, auto_print_bill  # Auto-print receipt and bill


@login_required
def cashier_dashboard(request):
    """Main cashier dashboard with table filtering and order display - CASHIER ONLY"""
    if not request.user.is_cashier():
        messages.error(request, "Access denied. Cashier role required.")
        return redirect('accounts:profile')
    
    owner = get_owner_filter(request.user)
    
    # Get filters from request
    table_filter = request.GET.get('table', '')
    status_filter = request.GET.get('status', '')
    period = request.GET.get('period', 'today')
    staff_filter = request.GET.get('staff', 'all')  # Changed from customer_care_filter
    staff_role = request.GET.get('staff_role', 'all')  # New: filter by role
    
    # Base queryset for orders with period filter
    from datetime import timedelta
    today_start = timezone.now().replace(hour=0, minute=0, second=0, microsecond=0)
    
    if period == 'today':
        orders = Order.objects.filter(
            table_info__owner=owner,
            created_at__gte=today_start,
            created_at__lt=today_start + timedelta(days=1)
        )
    elif period == 'weekly':
        week_start = today_start - timedelta(days=today_start.weekday())
        orders = Order.objects.filter(
            table_info__owner=owner,
            created_at__gte=week_start
        )
    else:
        orders = Order.objects.filter(
            table_info__owner=owner,
            created_at__gte=today_start,
            created_at__lt=today_start + timedelta(days=1)
        )
    
    # Apply staff filter (by specific user)
    if staff_filter != 'all':
        orders = orders.filter(ordered_by_id=staff_filter)
    # Apply staff role filter (by role type)
    elif staff_role == 'customer_care':
        orders = orders.filter(ordered_by__role__name='customer_care')
    elif staff_role == 'cashier':
        orders = orders.filter(ordered_by__role__name='cashier')
    
    # Apply filters
    if table_filter:
        orders = orders.filter(table_info__tbl_no__icontains=table_filter)
    
    if status_filter:
        orders = orders.filter(payment_status=status_filter)
    
    # Prefetch related data
    orders = orders.select_related('table_info', 'ordered_by').prefetch_related(
        Prefetch('order_items', queryset=OrderItem.objects.select_related('product')),
        'payments'
    ).order_by('-created_at')
    
    # Get all tables for dropdown
    tables = TableInfo.objects.filter(owner=owner).order_by('tbl_no')
    
    # Get customer care users for filter
    from django.contrib.auth import get_user_model
    from django.db.models import Q
    User = get_user_model()
    
    customer_care_users = User.objects.filter(role__name='customer_care')
    if hasattr(owner, 'branch_owner'):
        customer_care_users = customer_care_users.filter(branch_owner=owner)
    elif hasattr(owner, 'owner'):
        customer_care_users = customer_care_users.filter(owner=owner)
    else:
        customer_care_users = customer_care_users.filter(Q(owner=owner) | Q(branch_owner=owner))
    customer_care_users = customer_care_users.order_by('first_name', 'username')
    
    # Get cashier users for filter
    cashier_users = User.objects.filter(role__name='cashier')
    if hasattr(owner, 'branch_owner'):
        cashier_users = cashier_users.filter(branch_owner=owner)
    elif hasattr(owner, 'owner'):
        cashier_users = cashier_users.filter(owner=owner)
    else:
        cashier_users = cashier_users.filter(Q(owner=owner) | Q(branch_owner=owner))
    cashier_users = cashier_users.order_by('first_name', 'username')
    
    # Get products for waste recording modal
    waste_products = Product.objects.filter(main_category__owner=owner).order_by('name')
    
    # Calculate payment summaries for each order
    for order in orders:
        total_paid = order.payments.filter(is_voided=False).aggregate(
            total=Sum('amount'))['total'] or Decimal('0.00')
        order.total_paid = total_paid
        order.balance_due = order.total_amount - total_paid
        order.is_fully_paid = order.balance_due <= Decimal('0.00')
    
    context = {
        'orders': orders,
        'tables': tables,
        'table_filter': table_filter,
        'status_filter': status_filter,
        'period': period,
        'staff_filter': staff_filter,
        'staff_role': staff_role,
        'customer_care_users': customer_care_users,
        'cashier_users': cashier_users,
        'payment_status_choices': Order.PAYMENT_STATUS_CHOICES,
        'waste_products': waste_products,
    }
    
    return render(request, 'cashier/dashboard.html', context)


@login_required
def my_orders(request):
    """Cashier's own orders - orders they created"""
    if not request.user.is_cashier():
        messages.error(request, "Access denied. Cashier role required.")
        return redirect('accounts:profile')
    
    owner = get_owner_filter(request.user)
    
    # Get only orders created by this cashier
    orders = Order.objects.filter(
        table_info__owner=owner,
        ordered_by=request.user
    ).select_related('table_info', 'ordered_by').prefetch_related(
        Prefetch('order_items', queryset=OrderItem.objects.select_related('product')),
        'payments'
    ).order_by('-created_at')
    
    # Calculate payment summaries
    for order in orders:
        total_paid = order.payments.filter(is_voided=False).aggregate(
            total=Sum('amount'))['total'] or Decimal('0.00')
        order.total_paid = total_paid
        order.balance_due = order.total_amount - total_paid
        order.is_fully_paid = order.balance_due <= Decimal('0.00')
    
    context = {
        'orders': orders,
        'payment_status_choices': Order.PAYMENT_STATUS_CHOICES,
    }
    
    return render(request, 'cashier/my_orders.html', context)


@login_required
@require_http_methods(["GET", "POST"])
def process_payment(request, order_id):
    """Process payment for an order - full or partial"""
    if not (request.user.is_cashier() or request.user.is_customer_care() or request.user.is_owner() or request.user.is_main_owner() or request.user.is_branch_owner()):
        return JsonResponse({'error': 'Access denied'}, status=403)
    
    owner = get_owner_filter(request.user)
    order = get_object_or_404(Order, id=order_id, table_info__owner=owner)
    
    if request.method == 'GET':
        # Return order details for payment form
        order_items = []
        for item in order.order_items.all():
            # Calculate how much of this item has been paid
            paid_quantity = OrderItemPayment.objects.filter(
                order_item=item,
                payment__is_voided=False
            ).aggregate(total=Sum('quantity_paid'))['total'] or 0
            
            remaining_quantity = item.quantity - paid_quantity
            
            if remaining_quantity > 0:
                order_items.append({
                    'id': item.id,
                    'product_name': item.product.name,
                    'unit_price': float(item.unit_price),
                    'total_quantity': item.quantity,
                    'paid_quantity': paid_quantity,
                    'remaining_quantity': remaining_quantity,
                    'remaining_amount': float(item.unit_price * remaining_quantity)
                })
        
        total_paid = order.payments.filter(is_voided=False).aggregate(
            total=Sum('amount'))['total'] or Decimal('0.00')
        
        return JsonResponse({
            'order_number': order.order_number,
            'table_number': order.table_info.tbl_no,
            'total_amount': float(order.total_amount),
            'total_paid': float(total_paid),
            'balance_due': float(order.total_amount - total_paid),
            'items': order_items
        })
    
    # POST - Process payment
    try:
        data = json.loads(request.body)
        
        # Better amount handling and validation
        amount_input = data.get('amount', '0')
        try:
            # Handle both string and numeric inputs
            if isinstance(amount_input, str):
                amount_input = amount_input.strip().replace(',', '')  # Remove commas
            amount = Decimal(str(amount_input))
        except (ValueError, TypeError, InvalidOperation):
            return JsonResponse({'error': 'Invalid payment amount format'}, status=400)
        
        payment_method = data.get('payment_method', 'cash')
        selected_items = data.get('selected_items', [])
        reference_number = data.get('reference_number', '')
        notes = data.get('notes', '')
        
        # Validate amount
        if amount <= 0:
            return JsonResponse({'error': 'Payment amount must be greater than zero'}, status=400)
        
        # Check if order is already fully paid
        total_paid = order.payments.filter(is_voided=False).aggregate(
            total=Sum('amount'))['total'] or Decimal('0.00')
        
        remaining_balance = order.total_amount - total_paid
        
        if remaining_balance <= 0:
            return JsonResponse({'error': 'Order is already fully paid'}, status=400)
        
        if amount > remaining_balance:
            return JsonResponse({
                'error': f'Payment amount (${amount}) exceeds remaining balance (${remaining_balance})'
            }, status=400)
        
        # Create payment record
        payment = Payment.objects.create(
            order=order,
            amount=amount,
            payment_method=payment_method,
            processed_by=request.user,
            reference_number=reference_number,
            notes=notes
        )
        
        # If specific items selected, create item payment records
        if selected_items:
            total_item_amount = Decimal('0.00')
            for item_data in selected_items:
                order_item = get_object_or_404(OrderItem, id=item_data['id'])
                quantity_paid = int(item_data['quantity'])
                item_amount = order_item.unit_price * quantity_paid
                
                OrderItemPayment.objects.create(
                    payment=payment,
                    order_item=order_item,
                    quantity_paid=quantity_paid,
                    amount_paid=item_amount
                )
                total_item_amount += item_amount
            
            # Update payment amount to match selected items
            payment.amount = total_item_amount
            payment.save()
        
        # Update order payment status
        total_paid = order.payments.filter(is_voided=False).aggregate(
            total=Sum('amount'))['total'] or Decimal('0.00')
        
        if total_paid >= order.total_amount:
            order.payment_status = 'paid'
            # Release the table when order is fully paid
            order.release_table()
        elif total_paid > 0:
            order.payment_status = 'partial'
        else:
            order.payment_status = 'unpaid'
        
        order.save()
        
        # Log payment event for audit trail
        try:
            from accounts.security_utils import log_security_event, get_client_ip
            log_security_event(
                event_type='payment_processed',
                user=request.user,
                description=f"Payment of ${amount} for Order #{order.order_number}",
                ip_address=get_client_ip(request),
                extra_data={
                    'order_id': order.id,
                    'order_number': order.order_number,
                    'amount': str(amount),
                    'payment_method': payment_method,
                    'payment_status': order.payment_status,
                    'payment_id': str(payment.id),
                }
            )
        except Exception as audit_error:
            logger.warning(f"Failed to log payment audit: {audit_error}")
        
        # ✨ AUTO-PRINT RECEIPT (NO BROWSER DIALOG!)
        receipt_printed = False
        try:
            print_result = auto_print_receipt(payment)
            receipt_printed = print_result.get('receipt_printed', False)
            if receipt_printed:
                logger.info(f"Auto-printed receipt for Payment #{payment.id}")
            else:
                logger.warning(f"Receipt auto-print returned False for Payment #{payment.id}")
        except Exception as e:
            # Print error doesn't stop payment processing
            logger.warning(f"Receipt auto-print failed: {str(e)}", exc_info=True)
        
        return JsonResponse({
            'success': True,
            'message': f'Payment of ${amount} processed successfully',
            'payment_id': payment.id,
            'new_balance': float(order.total_amount - total_paid),
            'receipt_printed': receipt_printed
        })
        
    except Exception as e:
        logger.error(f'Error processing payment: {str(e)}')
        return JsonResponse({'error': 'Error processing payment. Please try again.'}, status=400)


@login_required
@require_http_methods(["POST"])
def void_payment(request, payment_id):
    """Void a payment transaction"""
    if not (request.user.is_cashier() or request.user.is_customer_care() or request.user.is_owner() or request.user.is_main_owner() or request.user.is_branch_owner()):
        return JsonResponse({'error': 'Access denied'}, status=403)
    
    owner = get_owner_filter(request.user)
    payment = get_object_or_404(Payment, id=payment_id, order__table_info__owner=owner)
    
    if payment.is_voided:
        return JsonResponse({'error': 'Payment already voided'}, status=400)
    
    try:
        data = json.loads(request.body)
        void_reason = data.get('reason', '')
        refund_method = data.get('refund_method', payment.payment_method)
        
        # Create void transaction record
        void_transaction = VoidTransaction.objects.create(
            original_payment=payment,
            voided_by=request.user,
            void_reason=void_reason,
            refund_amount=payment.amount,
            refund_method=refund_method
        )
        
        # Mark payment as voided
        payment.is_voided = True
        payment.voided_by = request.user
        payment.void_reason = void_reason
        payment.voided_at = timezone.now()
        payment.save()
        
        # Update order payment status
        order = payment.order
        total_paid = order.payments.filter(is_voided=False).aggregate(
            total=Sum('amount'))['total'] or Decimal('0.00')
        
        if total_paid >= order.total_amount:
            order.payment_status = 'paid'
            # Release the table when order is fully paid
            order.release_table()
        elif total_paid > 0:
            order.payment_status = 'partial'
            # Re-occupy table if payment becomes partial after void
            order.occupy_table()
        else:
            order.payment_status = 'unpaid'
            # Re-occupy table if payment becomes unpaid after void
            order.occupy_table()
        
        order.save()
        
        # Log void event for audit trail
        try:
            from accounts.security_utils import log_security_event, get_client_ip
            log_security_event(
                event_type='payment_voided',
                user=request.user,
                description=f"Payment #{payment.id} voided for Order #{order.order_number}. Reason: {void_reason[:100] if void_reason else 'Not specified'}",
                ip_address=get_client_ip(request),
                extra_data={
                    'order_id': order.id,
                    'order_number': order.order_number,
                    'voided_amount': str(payment.amount),
                    'void_reason': void_reason,
                    'refund_method': refund_method,
                    'payment_id': str(payment.id),
                }
            )
        except Exception as audit_error:
            logger.warning(f"Failed to log void audit: {audit_error}")
        
        return JsonResponse({
            'success': True,
            'message': f'Payment voided successfully. Refund: ${payment.amount}',
            'void_id': void_transaction.id
        })
        
    except Exception as e:
        logger.error(f'Error voiding payment: {str(e)}')
        return JsonResponse({'error': 'Error voiding payment. Please try again.'}, status=400)


@login_required
@require_http_methods(["POST"])
def cancel_order(request, order_id):
    """Cancel an unpaid order"""
    if not (request.user.is_cashier() or request.user.is_customer_care() or request.user.is_owner() or request.user.is_main_owner() or request.user.is_branch_owner()):
        return JsonResponse({'error': 'Access denied'}, status=403)
    
    owner = get_owner_filter(request.user)
    order = get_object_or_404(Order, id=order_id, table_info__owner=owner)
    
    # Check if order has any non-voided payments
    has_payments = order.payments.filter(is_voided=False).exists()
    if has_payments:
        return JsonResponse({'error': 'Cannot cancel order with payments. Void payments first.'}, status=400)
    
    # Check if order is not already cancelled
    if order.status == 'cancelled':
        return JsonResponse({'error': 'Order already cancelled'}, status=400)
    
    try:
        data = json.loads(request.body)
        cancel_reason = data.get('reason', '')
        
        order.status = 'cancelled'
        order.payment_status = 'unpaid'
        order.reason_if_cancelled = cancel_reason
        # Release the table when order is cancelled
        order.release_table()
        order.save()
        
        return JsonResponse({
            'success': True,
            'message': f'Order {order.order_number} cancelled successfully'
        })
        
    except Exception as e:
        logger.error(f'Error cancelling order: {str(e)}')
        return JsonResponse({'error': 'Error cancelling order. Please try again.'}, status=400)


@login_required
def payment_history(request, order_id):
    """Get payment history for an order"""
    if not (request.user.is_cashier() or request.user.is_customer_care() or request.user.is_owner() or request.user.is_main_owner() or request.user.is_branch_owner()):
        return JsonResponse({'error': 'Access denied'}, status=403)
    
    owner = get_owner_filter(request.user)
    order = get_object_or_404(Order, id=order_id, table_info__owner=owner)
    
    payments = order.payments.select_related('processed_by', 'voided_by').order_by('-created_at')
    
    payment_data = []
    for payment in payments:
        payment_info = {
            'id': payment.id,
            'amount': float(payment.amount),
            'payment_method': payment.get_payment_method_display(),
            'processed_by': payment.processed_by.username,
            'created_at': payment.created_at.strftime('%Y-%m-%d %H:%M:%S'),
            'is_voided': payment.is_voided,
            'reference_number': payment.reference_number,
            'notes': payment.notes
        }
        
        if payment.is_voided:
            payment_info.update({
                'voided_by': payment.voided_by.username if payment.voided_by else '',
                'void_reason': payment.void_reason,
                'voided_at': payment.voided_at.strftime('%Y-%m-%d %H:%M:%S') if payment.voided_at else ''
            })
        
        payment_data.append(payment_info)
    
    return JsonResponse({
        'order_number': order.order_number,
        'payments': payment_data
    })


@login_required
def generate_receipt(request, payment_id):
    """Generate receipt for a specific payment"""
    if not (request.user.is_cashier() or request.user.is_customer_care() or request.user.is_owner() or request.user.is_main_owner() or request.user.is_branch_owner()):
        messages.error(request, "Access denied. Cashier, Customer Care, or Owner role required.")
        return redirect('accounts:profile')
    
    owner = get_owner_filter(request.user)
    payment = get_object_or_404(
        Payment, 
        id=payment_id, 
        order__table_info__owner=owner
    )
    
    # Get the order with all related data
    order = payment.order
    
    # Calculate change and remaining balance
    change_amount = payment.amount - order.get_total() if payment.payment_method == 'cash' and payment.amount > order.get_total() else Decimal('0.00')
    remaining_balance = order.get_total() - payment.amount if payment.amount < order.get_total() else Decimal('0.00')
    
    context = {
        'payment': payment,
        'order': order,
        'user': request.user,  # For restaurant info
        'change_amount': change_amount,
        'remaining_balance': remaining_balance,
    }
    
    return render(request, 'cashier/receipt.html', context)


@login_required  
def reprint_receipt(request, payment_id):
    """Reprint an existing receipt"""
    if not (request.user.is_cashier() or request.user.is_customer_care() or request.user.is_owner() or request.user.is_main_owner() or request.user.is_branch_owner()):
        messages.error(request, "Access denied. Cashier, Customer Care, or Owner role required.")
        return redirect('accounts:profile')
    
    owner = get_owner_filter(request.user)
    payment = get_object_or_404(
        Payment, 
        id=payment_id, 
        order__table_info__owner=owner
    )
    
    # Add a message indicating this is a reprint
    messages.info(request, f"Reprinting receipt #{payment.id:06d}")
    
    # Get the order with all related data
    order = payment.order
    
    # Calculate change and remaining balance
    change_amount = payment.amount - order.get_total() if payment.payment_method == 'cash' and payment.amount > order.get_total() else Decimal('0.00')
    remaining_balance = order.get_total() - payment.amount if payment.amount < order.get_total() else Decimal('0.00')
    
    context = {
        'payment': payment,
        'order': order,
        'user': request.user,
        'is_reprint': True,
        'change_amount': change_amount,
        'remaining_balance': remaining_balance,
    }

    return render(request, 'cashier/receipt.html', context)


@login_required
def receipt_management(request):
    """Manage receipts - search and reprint by order number or date - CASHIER ONLY"""
    if not request.user.is_cashier():
        messages.error(request, "Access denied. Cashier role required.")
        return redirect('accounts:profile')
    
    owner = get_owner_filter(request.user)
    
    # Get search parameters
    search_query = request.GET.get('search', '')
    date_from = request.GET.get('date_from', '')
    date_to = request.GET.get('date_to', '')
    
    # Base queryset for payments
    payments = Payment.objects.filter(
        order__table_info__owner=owner,
        is_voided=False
    ).select_related(
        'order', 'order__table_info', 'processed_by'
    ).order_by('-created_at')
    
    # Apply filters
    if search_query:
        payments = payments.filter(
            Q(order__order_number__icontains=search_query) |
            Q(id=search_query if search_query.isdigit() else 0)
        )
    
    if date_from:
        payments = payments.filter(created_at__date__gte=date_from)
    
    if date_to:
        payments = payments.filter(created_at__date__lte=date_to)
    
    # Limit results for performance
    payments = payments[:50]
    
    # Get products for waste recording modal
    waste_products = Product.objects.filter(main_category__owner=owner).order_by('name')
    
    context = {
        'payments': payments,
        'search_query': search_query,
        'date_from': date_from,
        'date_to': date_to,
        'waste_products': waste_products,
    }
    
    return render(request, 'cashier/receipt_management.html', context)


@login_required
@require_http_methods(["POST"])
def print_bill(request, order_id):
    """Print bill for an order (before payment) - shows what customer owes"""
    if not (request.user.is_cashier() or request.user.is_customer_care() or request.user.is_owner() or request.user.is_main_owner() or request.user.is_branch_owner()):
        return JsonResponse({'error': 'Access denied'}, status=403)
    
    owner = get_owner_filter(request.user)
    order = get_object_or_404(Order, id=order_id, table_info__owner=owner)
    
    # Check if order is cancelled
    if order.status == 'cancelled':
        return JsonResponse({'error': 'Cannot print bill for cancelled order'}, status=400)
    
    # Check if order is already fully paid
    total_paid = order.payments.filter(is_voided=False).aggregate(
        total=Sum('amount'))['total'] or Decimal('0.00')
    
    if total_paid >= order.total_amount:
        return JsonResponse({'error': 'Order is already fully paid. Use receipt instead.'}, status=400)
    
    try:
        # Print the bill using the receipt printer
        print_result = auto_print_bill(order, printed_by=request.user)
        bill_printed = print_result.get('bill_printed', False)
        
        if bill_printed:
            return JsonResponse({
                'success': True,
                'message': f'Bill printed successfully for Order #{order.order_number}'
            })
        else:
            errors = print_result.get('errors', ['Unknown error'])
            return JsonResponse({
                'success': False,
                'message': f'Bill print failed: {", ".join(errors)}'
            })
            
    except Exception as e:
        logger.error(f'Error printing bill: {str(e)}')
        return JsonResponse({'error': 'Error printing bill. Please try again.'}, status=400)


@login_required
def cashier_reports(request):
    """Cashier Reports - showing only orders they processed payments for"""
    if not request.user.is_cashier():
        messages.error(request, "Access denied. Cashier role required.")
        return redirect('accounts:profile')
    
    from django.utils import timezone
    from django.db.models import Sum, Count, Q
    from datetime import datetime, timedelta
    from django.http import HttpResponse
    import csv
    
    owner = get_owner_filter(request.user)
    
    # Get filter parameters
    period = request.GET.get('period', 'today')
    payment_status = request.GET.get('payment_status', 'all')
    category_id = request.GET.get('category_id', 'all')
    subcategory_id = request.GET.get('subcategory_id', 'all')
    station_filter = request.GET.get('station_filter', 'all')
    staff_filter = request.GET.get('staff', 'all')  # Changed from customer_care_filter
    staff_role = request.GET.get('staff_role', 'all')  # New: filter by role
    export_format = request.GET.get('export')
    
    # Base queryset - cashier sees ALL orders from their restaurant
    orders = Order.objects.filter(table_info__owner=owner)
    
    # Apply staff filter (by specific user)
    if staff_filter != 'all':
        orders = orders.filter(ordered_by_id=staff_filter)
    # Apply staff role filter (by role type)
    elif staff_role == 'customer_care':
        orders = orders.filter(ordered_by__role__name='customer_care')
    elif staff_role == 'cashier':
        orders = orders.filter(ordered_by__role__name='cashier')
    
    # Apply period filter (only today and weekly)
    today = timezone.now().date()
    if period == 'today':
        orders = orders.filter(created_at__date=today)
    elif period == 'weekly':
        week_start = today - timedelta(days=today.weekday())
        orders = orders.filter(created_at__date__gte=week_start)
    
    # Apply payment status filter
    if payment_status != 'all':
        orders = orders.filter(payment_status=payment_status)
    
    # Apply category/subcategory/station filters using IDs approach
    order_ids = list(orders.values_list('id', flat=True))
    
    if category_id != 'all':
        filtered_items = OrderItem.objects.filter(
            order_id__in=order_ids,
            product__main_category_id=category_id
        ).values_list('order_id', flat=True).distinct()
        order_ids = list(set(order_ids) & set(filtered_items))
    
    if subcategory_id != 'all':
        filtered_items = OrderItem.objects.filter(
            order_id__in=order_ids,
            product__sub_category_id=subcategory_id
        ).values_list('order_id', flat=True).distinct()
        order_ids = list(set(order_ids) & set(filtered_items))
    
    if station_filter != 'all':
        filtered_items = OrderItem.objects.filter(
            order_id__in=order_ids,
            product__station=station_filter
        ).values_list('order_id', flat=True).distinct()
        order_ids = list(set(order_ids) & set(filtered_items))
    
    # Rebuild orders queryset with filtered IDs
    orders = Order.objects.filter(id__in=order_ids).select_related(
        'table_info', 'ordered_by'
    ).prefetch_related(
        'order_items__product__main_category',
        'order_items__product__sub_category',
        'payments'
    ).order_by('-created_at')
    
    # Calculate statistics
    total_revenue = Decimal('0.00')
    paid_amount = Decimal('0.00')
    unpaid_amount = Decimal('0.00')
    total_orders = orders.count()
    total_items = 0
    
    for order in orders:
        # Count all revenue from order
        total_revenue += order.total_amount
        total_items += order.order_items.count()
        
        # Calculate paid and unpaid amounts
        if order.payment_status == 'paid':
            paid_amount += order.total_amount
        elif order.payment_status == 'unpaid':
            unpaid_amount += order.total_amount
        elif order.payment_status == 'partial':
            # For partial payments, calculate what's been paid
            total_paid = order.payments.filter(is_voided=False).aggregate(
                total=Sum('amount'))['total'] or Decimal('0.00')
            paid_amount += total_paid
            unpaid_amount += (order.total_amount - total_paid)
    
    # Handle CSV export
    if export_format == 'csv':
        # Get currency symbol
        currency_symbol = request.user.get_currency_symbol()
        
        response = HttpResponse(content_type='text/csv')
        response['Content-Disposition'] = f'attachment; filename="cashier_report_{timezone.now().strftime("%Y%m%d_%H%M%S")}.csv"'
        
        writer = csv.writer(response)
        writer.writerow(['Order #', 'Date', 'Time', 'Table', 'Items', 'Categories', 'Stations', 'Ordered By', 'Paid By', 'Total Amount', 'Payment Status'])
        
        for order in orders:
            items_list = ', '.join([f"{item.quantity}x {item.product.name}" for item in order.order_items.all()])
            categories = ', '.join(set([item.product.main_category.name for item in order.order_items.all() if item.product.main_category]))
            stations = ', '.join(set([item.product.get_station_display() for item in order.order_items.all()]))
            
            # Get paid by information
            paid_by_list = []
            for payment in order.payments.filter(is_voided=False):
                name = payment.processed_by.get_full_name() or payment.processed_by.username
                if payment.processed_by.is_cashier():
                    paid_by_list.append(f"{name}-cs")
                elif payment.processed_by.is_customer_care():
                    paid_by_list.append(f"{name}-cc")
                else:
                    paid_by_list.append(f"{name}-staff")
            paid_by = ', '.join(paid_by_list) if paid_by_list else '-'
            
            writer.writerow([
                order.order_number,
                order.created_at.strftime('%Y-%m-%d'),
                order.created_at.strftime('%H:%M:%S'),
                order.table_info.tbl_no,
                items_list,
                categories,
                stations,
                order.ordered_by.get_full_name() or order.ordered_by.username,
                paid_by,
                f'{currency_symbol}{order.total_amount:.2f}',
                order.get_payment_status_display()
            ])
        
        return response
    
    # Handle PDF export
    if export_format == 'pdf':
        # Get currency symbol
        currency_symbol = request.user.get_currency_symbol()
        
        from reportlab.lib.pagesizes import A4, landscape
        from reportlab.lib import colors
        from reportlab.lib.units import inch
        from reportlab.platypus import SimpleDocTemplate, Table, TableStyle, Paragraph, Spacer
        from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
        from reportlab.lib.enums import TA_CENTER, TA_RIGHT
        from io import BytesIO
        
        buffer = BytesIO()
        doc = SimpleDocTemplate(buffer, pagesize=landscape(A4), topMargin=0.5*inch, bottomMargin=0.5*inch)
        elements = []
        styles = getSampleStyleSheet()
        
        # Title
        title_style = ParagraphStyle(
            'CustomTitle',
            parent=styles['Heading1'],
            fontSize=16,
            textColor=colors.HexColor('#2c5282'),
            spaceAfter=30,
            alignment=TA_CENTER
        )
        elements.append(Paragraph(f"Restaurant Sales Report - {owner.restaurant_name}", title_style))
        
        # Summary statistics - 2 rows
        summary_data = [
            ['Total Amount', 'Paid Amount', 'Unpaid Amount'],
            [f'{currency_symbol}{total_revenue:.2f}', f'{currency_symbol}{paid_amount:.2f}', f'{currency_symbol}{unpaid_amount:.2f}'],
            ['Total Orders', 'Items Sold', ''],
            [str(total_orders), str(total_items), '']
        ]
        summary_table = Table(summary_data, colWidths=[2.5*inch, 2.5*inch, 2.5*inch])
        summary_table.setStyle(TableStyle([
            ('BACKGROUND', (0, 0), (-1, 0), colors.HexColor('#2c5282')),
            ('TEXTCOLOR', (0, 0), (-1, 0), colors.whitesmoke),
            ('BACKGROUND', (0, 2), (-1, 2), colors.HexColor('#2c5282')),
            ('TEXTCOLOR', (0, 2), (-1, 2), colors.whitesmoke),
            ('ALIGN', (0, 0), (-1, -1), 'CENTER'),
            ('FONTNAME', (0, 0), (-1, 0), 'Helvetica-Bold'),
            ('FONTNAME', (0, 2), (-1, 2), 'Helvetica-Bold'),
            ('FONTSIZE', (0, 0), (-1, -1), 12),
            ('BOTTOMPADDING', (0, 0), (-1, -1), 12),
            ('BACKGROUND', (0, 1), (-1, 1), colors.white),
            ('BACKGROUND', (0, 3), (-1, 3), colors.white),
            ('GRID', (0, 0), (-1, -1), 1, colors.black)
        ]))
        elements.append(summary_table)
        elements.append(Spacer(1, 0.3*inch))
        
        # Orders table
        table_data = [['Order #', 'Date & Time', 'Table', 'Items', 'Category', 'Station', 'Ordered By', 'Paid By', 'Total', 'Payment']]
        
        for order in orders:
            items_str = ', '.join([f"{item.quantity}x {item.product.name[:15]}" for item in order.order_items.all()[:3]])
            if order.order_items.count() > 3:
                items_str += '...'
            
            categories = ', '.join(set([item.product.main_category.name[:15] for item in order.order_items.all() if item.product.main_category]))
            stations = ', '.join(set([item.product.get_station_display()[:10] for item in order.order_items.all()]))
            
            # Get paid by information
            paid_by_list = []
            for payment in order.payments.filter(is_voided=False):
                name = (payment.processed_by.get_full_name() or payment.processed_by.username)[:10]
                if payment.processed_by.is_cashier():
                    paid_by_list.append(f"{name}-cs")
                elif payment.processed_by.is_customer_care():
                    paid_by_list.append(f"{name}-cc")
                else:
                    paid_by_list.append(f"{name}-st")
            paid_by = ', '.join(paid_by_list)[:20] if paid_by_list else '-'
            
            table_data.append([
                order.order_number[:15],
                order.created_at.strftime('%Y-%m-%d %H:%M'),
                order.table_info.tbl_no,
                items_str[:30],
                categories[:20],
                stations[:15],
                (order.ordered_by.get_full_name() or order.ordered_by.username)[:15],
                paid_by,
                f'{currency_symbol}{order.total_amount:.2f}',
                order.get_payment_status_display()
            ])
        
        orders_table = Table(table_data, colWidths=[0.9*inch, 1.1*inch, 0.5*inch, 1.5*inch, 0.9*inch, 0.8*inch, 0.9*inch, 0.9*inch, 0.7*inch, 0.7*inch])
        orders_table.setStyle(TableStyle([
            ('BACKGROUND', (0, 0), (-1, 0), colors.HexColor('#2c5282')),
            ('TEXTCOLOR', (0, 0), (-1, 0), colors.whitesmoke),
            ('ALIGN', (0, 0), (-1, -1), 'LEFT'),
            ('FONTNAME', (0, 0), (-1, 0), 'Helvetica-Bold'),
            ('FONTSIZE', (0, 0), (-1, 0), 9),
            ('FONTSIZE', (0, 1), (-1, -1), 8),
            ('BOTTOMPADDING', (0, 0), (-1, 0), 8),
            ('BACKGROUND', (0, 1), (-1, -1), colors.white),
            ('GRID', (0, 0), (-1, -1), 0.5, colors.grey),
            ('VALIGN', (0, 0), (-1, -1), 'MIDDLE'),
        ]))
        elements.append(orders_table)
        
        doc.build(elements)
        pdf = buffer.getvalue()
        buffer.close()
        
        response = HttpResponse(content_type='application/pdf')
        response['Content-Disposition'] = f'attachment; filename="cashier_report_{timezone.now().strftime("%Y%m%d_%H%M%S")}.pdf"'
        response.write(pdf)
        return response
    
    # Get categories and subcategories for filters
    from restaurant.models import MainCategory, SubCategory
    from django.contrib.auth import get_user_model
    User = get_user_model()
    
    categories = MainCategory.objects.filter(owner=owner).order_by('name')
    subcategories = SubCategory.objects.filter(main_category__owner=owner).order_by('name')
    
    # Get customer care users for filter
    customer_care_users = User.objects.filter(
        role__name='customer_care'
    )
    # Filter by owner assignment
    if hasattr(owner, 'branch_owner'):
        customer_care_users = customer_care_users.filter(branch_owner=owner)
    elif hasattr(owner, 'owner'):
        customer_care_users = customer_care_users.filter(owner=owner)
    else:
        customer_care_users = customer_care_users.filter(Q(owner=owner) | Q(branch_owner=owner))
    
    customer_care_users = customer_care_users.order_by('first_name', 'username')
    
    # Get cashier users for filter
    cashier_users = User.objects.filter(role__name='cashier')
    if hasattr(owner, 'branch_owner'):
        cashier_users = cashier_users.filter(branch_owner=owner)
    elif hasattr(owner, 'owner'):
        cashier_users = cashier_users.filter(owner=owner)
    else:
        cashier_users = cashier_users.filter(Q(owner=owner) | Q(branch_owner=owner))
    cashier_users = cashier_users.order_by('first_name', 'username')
    
    # Station choices
    station_choices = [
        ('kitchen', 'Kitchen'),
        ('bar', 'Bar'),
        ('buffet', 'Buffet'),
        ('service', 'Service')
    ]
    
    context = {
        'orders': orders,
        'total_revenue': total_revenue,
        'paid_amount': paid_amount,
        'unpaid_amount': unpaid_amount,
        'total_orders': total_orders,
        'total_items': total_items,
        'categories': categories,
        'subcategories': subcategories,
        'station_choices': station_choices,
        'customer_care_users': customer_care_users,
        'cashier_users': cashier_users,
        'filters': {
            'period': period,
            'payment_status': payment_status,
            'category_id': category_id,
            'subcategory_id': subcategory_id,
            'station_filter': station_filter,
            'staff': staff_filter,
            'staff_role': staff_role,
        }
    }
    
    return render(request, 'cashier/reports.html', context)