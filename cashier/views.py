from django.shortcuts import render, get_object_or_404, redirect
from django.contrib.auth.decorators import login_required
from django.contrib import messages
from django.http import JsonResponse
from django.db.models import Q, Sum, Prefetch
from django.views.decorators.http import require_http_methods
from django.utils import timezone
from decimal import Decimal, InvalidOperation
import json

from accounts.models import get_owner_filter
from orders.models import Order, OrderItem
from restaurant.models import TableInfo, Product
from waste_management.models import FoodWasteLog
from .models import Payment, OrderItemPayment, VoidTransaction
from orders.printing import auto_print_receipt  # Auto-print receipt


@login_required
def cashier_dashboard(request):
    """Main cashier dashboard with table filtering and order display - CASHIER ONLY"""
    if not request.user.is_cashier():
        messages.error(request, "Access denied. Cashier role required.")
        return redirect('accounts:profile')
    
    owner = get_owner_filter(request.user)
    
    # Get table filter from request
    table_filter = request.GET.get('table', '')
    status_filter = request.GET.get('status', '')
    
    # Base queryset for orders
    orders = Order.objects.filter(table_info__owner=owner)
    
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
        'payment_status_choices': Order.PAYMENT_STATUS_CHOICES,
        'waste_products': waste_products,
    }
    
    return render(request, 'cashier/dashboard.html', context)


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
        
        # ✨ AUTO-PRINT RECEIPT (NO BROWSER DIALOG!)
        receipt_printed = False
        try:
            print_result = auto_print_receipt(payment)
            receipt_printed = print_result.get('receipt_printed', False)
            if receipt_printed:
                print(f"✓ Auto-printed receipt for Payment #{payment.id}")
            else:
                print(f"⚠ Receipt auto-print returned False for Payment #{payment.id}")
        except Exception as e:
            # Print error doesn't stop payment processing
            print(f"⚠ Receipt auto-print failed: {str(e)}")
            import traceback
            traceback.print_exc()
        
        return JsonResponse({
            'success': True,
            'message': f'Payment of ${amount} processed successfully',
            'payment_id': payment.id,
            'new_balance': float(order.total_amount - total_paid),
            'receipt_printed': receipt_printed
        })
        
    except Exception as e:
        return JsonResponse({'error': str(e)}, status=400)


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
        
        return JsonResponse({
            'success': True,
            'message': f'Payment voided successfully. Refund: ${payment.amount}',
            'void_id': void_transaction.id
        })
        
    except Exception as e:
        return JsonResponse({'error': str(e)}, status=400)


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
        return JsonResponse({'error': str(e)}, status=400)


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