from django.shortcuts import render, redirect, get_object_or_404
from django.contrib.auth.decorators import login_required
from django.contrib import messages
from django.http import JsonResponse
from django.views.decorators.http import require_POST
from django.views.decorators.csrf import csrf_protect
from django.db import transaction
from django.db.models import Q
from django.utils import timezone
from django.core.exceptions import PermissionDenied
from channels.layers import get_channel_layer
from asgiref.sync import async_to_sync
from decimal import Decimal
import json
import uuid
import logging

from .models import Order, OrderItem, BillRequest
from .forms import TableSelectionForm, OrderForm, OrderStatusForm, CancelOrderForm
from restaurant.models import TableInfo, Product, MainCategory
from accounts.models import User, get_owner_filter, check_owner_permission
from accounts.security_utils import (
    validate_session_restaurant_id, 
    validate_session_table,
    validate_cart_data,
    sanitize_special_instructions,
    require_restaurant_context,
    require_table_selection,
    ajax_restaurant_required,
    get_client_ip,
    log_security_event
)
from .printing import auto_print_order, auto_print_new_items  # Server-side printing

logger = logging.getLogger(__name__)

# Initialize channel layer for WebSocket communication
channel_layer = get_channel_layer()


@require_restaurant_context
def select_table(request):
    """Customer selects table from available tables in restaurant"""
    # Validate restaurant from session (already validated by decorator)
    restaurant = validate_session_restaurant_id(request.session)
    
    # For staff users, get their assigned restaurant
    if request.user.is_authenticated and (
        request.user.is_customer_care() or 
        request.user.is_kitchen_staff() or 
        request.user.is_bar_staff() or 
        request.user.is_buffet_staff() or 
        request.user.is_service_staff() or 
        request.user.is_cashier()
    ):
        restaurant = request.user.get_owner()
        if restaurant:
            request.session['selected_restaurant_id'] = restaurant.id
            request.session['selected_restaurant_name'] = restaurant.restaurant_name
        else:
            messages.error(request, 'You are not assigned to any restaurant. Please contact your administrator.')
            return redirect('accounts:login')
    
    if request.method == 'POST':
        # Handle table selection from visual interface
        selected_table_id = request.POST.get('table_id')
        action = request.POST.get('action')  # 'add' or 'new' for occupied tables
        
        if selected_table_id:
            try:
                # Validate table_id is numeric
                selected_table_id = int(selected_table_id)
                
                # Get the table by ID and verify it belongs to the restaurant
                if restaurant:
                    table = TableInfo.objects.get(id=selected_table_id, owner=restaurant)
                else:
                    owner_filter = get_owner_filter(request.user)
                    table = TableInfo.objects.get(id=selected_table_id, owner=owner_filter)
                
                # Store table selection regardless of availability
                request.session['selected_table'] = table.tbl_no
                request.session['selected_table_id'] = table.id
                # Store the restaurant owner for this session
                if restaurant:
                    request.session['selected_restaurant_owner'] = restaurant.id
                
                if table.is_truly_available():
                    # Table available - proceed to menu
                    messages.success(request, f'Table {table.tbl_no} selected. You can now browse the menu.')
                    return redirect('restaurant:menu')
                else:
                    # Table occupied - handle action from modal
                    if action == 'add':
                        # Add to existing order
                        return redirect('orders:add_to_existing_order')
                    elif action == 'new':
                        # Create new order
                        request.session['cart'] = {}
                        request.session['order_mode'] = 'new'
                        messages.info(request, f'Creating new order at Table {table.tbl_no}')
                        return redirect('restaurant:menu')
                    else:
                        # No action selected (shouldn't happen)
                        messages.error(request, 'Please select an action.')
                        return redirect('orders:select_table')
                        
            except (ValueError, TypeError):
                messages.error(request, 'Invalid table selection.')
                logger.warning(f"Invalid table_id format: {request.POST.get('table_id')} from IP {get_client_ip(request)}")
            except TableInfo.DoesNotExist:
                messages.error(request, 'Invalid table selection. Please try again.')
    
    # Get all available tables for the restaurant
    available_tables = []
    if restaurant:
        available_tables = TableInfo.objects.filter(owner=restaurant).order_by('tbl_no')
    elif request.user.is_authenticated:
        owner_filter = get_owner_filter(request.user)
        if owner_filter:
            available_tables = TableInfo.objects.filter(owner=owner_filter).order_by('tbl_no')
    
    # Determine base template based on user role
    if request.user.is_authenticated:
        if request.user.is_cashier() or request.user.is_customer_care():
            base_template = 'cashier_base.html'
        else:
            base_template = 'base.html'
    else:
        base_template = 'base.html'
    
    context = {
        'available_tables': available_tables,
        'restaurant': restaurant,
        'restaurant_name': request.session.get('selected_restaurant_name', 'Restaurant'),
        'base_template': base_template,
    }
    return render(request, 'orders/select_table.html', context)


@require_restaurant_context
@require_table_selection
def browse_menu(request):
    """Browse menu and add items to cart"""
    # Session validated by decorators
    table_number = request.session['selected_table']
    restaurant = validate_session_restaurant_id(request.session)
    
    # Filter categories by restaurant
    try:
        if restaurant:
            categories = MainCategory.objects.filter(
                is_active=True, 
                owner=restaurant
            ).prefetch_related('subcategories__products').order_by('name')
        elif request.user.is_authenticated:
            owner_filter = get_owner_filter(request.user)
            if owner_filter:
                categories = MainCategory.objects.filter(
                    is_active=True, 
                    owner=owner_filter
                ).prefetch_related('subcategories__products').order_by('name')
            else:
                categories = MainCategory.objects.filter(is_active=True).prefetch_related(
                    'subcategories__products'
                ).order_by('name')
        else:
            categories = MainCategory.objects.none()
    except PermissionDenied:
        messages.error(request, 'You are not associated with any restaurant.')
        return redirect('restaurant:home')
    
    # Get and validate cart from session
    cart = request.session.get('cart', {})
    cart = validate_cart_data(cart)
    request.session['cart'] = cart  # Store validated cart back
    
    cart_count = 0
    cart_total = 0
    
    if cart:
        cart_count = sum(item.get('quantity', 0) for item in cart.values())
        cart_total = sum(
            float(item.get('price', 0)) * item.get('quantity', 0) 
            for item in cart.values()
        )
    
    context = {
        'categories': categories,
        'table_number': table_number,
        'cart': cart,
        'cart_count': cart_count,
        'cart_total': cart_total,
    }
    
    return render(request, 'orders/browse_menu.html', context)


@csrf_protect
@require_POST
@ajax_restaurant_required
def add_to_cart(request):
    """Add item to cart via AJAX"""
    if 'selected_table' not in request.session:
        return JsonResponse({'success': False, 'message': 'Please select a table first.'})
    
    # Validate restaurant context
    restaurant = validate_session_restaurant_id(request.session)
    if not restaurant:
        return JsonResponse({'success': False, 'message': 'Restaurant context lost. Please scan QR code again.'})
    
    try:
        data = json.loads(request.body)
        product_id = data.get('product_id')
        quantity = int(data.get('quantity', 1))
        
        # Validate product_id
        try:
            product_id = int(product_id)
        except (ValueError, TypeError):
            logger.warning(f"Invalid product_id: {data.get('product_id')} from IP {get_client_ip(request)}")
            return JsonResponse({'success': False, 'message': 'Invalid product.'})
        
        # Validate quantity
        if quantity < 1 or quantity > 100:
            return JsonResponse({'success': False, 'message': 'Invalid quantity.'})
        
        # Get product and verify it belongs to this restaurant
        product = Product.objects.filter(
            id=product_id, 
            is_available=True,
            main_category__owner=restaurant
        ).first()
        
        if not product:
            return JsonResponse({'success': False, 'message': 'Product not found or not available.'})
        
        # Check stock
        if product.available_in_stock < quantity:
            return JsonResponse({
                'success': False, 
                'message': f'Only {product.available_in_stock} items available in stock.'
            })
        
        # Get and validate cart
        cart = validate_cart_data(request.session.get('cart', {}))
        
        if str(product_id) in cart:
            # Update existing item with current promotional pricing
            new_quantity = cart[str(product_id)]['quantity'] + quantity
            if new_quantity > product.available_in_stock:
                return JsonResponse({
                    'success': False,
                    'message': f'Cannot add more. Only {product.available_in_stock} items available.'
                })
            if new_quantity > 100:
                return JsonResponse({'success': False, 'message': 'Maximum quantity exceeded.'})
            
            # Update quantity and recalculate promotional pricing
            current_price = product.get_current_price()
            cart[str(product_id)].update({
                'quantity': new_quantity,
                'price': str(current_price),
                'original_price': str(product.price),
                'has_promotion': product.has_active_promotion(),
            })
        else:
            # Add new item with promotional pricing
            current_price = product.get_current_price()
            cart[str(product_id)] = {
                'name': product.name[:200],  # Limit name length
                'price': str(current_price),
                'original_price': str(product.price),
                'has_promotion': product.has_active_promotion(),
                'quantity': quantity,
                'image': product.get_image().url if product.get_image() else None,
            }
        
        request.session['cart'] = cart
        request.session.modified = True
        
        # Calculate cart totals
        cart_count = sum(item['quantity'] for item in cart.values())
        cart_total = sum(float(item['price']) * item['quantity'] for item in cart.values())
        
        return JsonResponse({
            'success': True,
            'message': f'{product.name} added to cart!',
            'cart_count': cart_count,
            'cart_total': cart_total,
        })
        
    except json.JSONDecodeError:
        return JsonResponse({'success': False, 'message': 'Invalid request data.'})
    except Exception as e:
        logger.error(f"Error in add_to_cart: {e}")
        return JsonResponse({'success': False, 'message': 'An error occurred.'})


@csrf_protect
@require_POST
@ajax_restaurant_required
def remove_from_cart(request):
    """Remove item from cart via AJAX"""
    try:
        # Validate restaurant context to prevent cross-restaurant manipulation
        restaurant = validate_session_restaurant_id(request.session)
        if not restaurant:
            return JsonResponse({'success': False, 'message': 'Invalid session. Please select a restaurant.'})
        
        data = json.loads(request.body)
        product_id = str(data.get('product_id'))
        
        # Validate product_id is numeric
        try:
            int(product_id)
        except (ValueError, TypeError):
            return JsonResponse({'success': False, 'message': 'Invalid product ID.'})
        
        cart = request.session.get('cart', {})
        
        if product_id in cart:
            del cart[product_id]
            request.session['cart'] = cart
            request.session.modified = True
            
            # Calculate cart totals
            cart_count = sum(item['quantity'] for item in cart.values())
            cart_total = sum(float(item['price']) * item['quantity'] for item in cart.values())
            
            return JsonResponse({
                'success': True,
                'message': 'Item removed from cart.',
                'cart_count': cart_count,
                'cart_total': cart_total,
            })
        
        return JsonResponse({'success': False, 'message': 'Item not found in cart.'})
        
    except json.JSONDecodeError:
        return JsonResponse({'success': False, 'message': 'Invalid request data.'})
    except Exception as e:
        logger.error(f"Error in remove_from_cart: {e}")
        return JsonResponse({'success': False, 'message': 'An error occurred.'})


@csrf_protect
@require_POST
@ajax_restaurant_required
def update_cart_quantity(request):
    """Update item quantity in cart via AJAX"""
    try:
        data = json.loads(request.body)
        product_id = str(data.get('product_id'))
        quantity = int(data.get('quantity'))
        
        if quantity <= 0:
            return JsonResponse({'success': False, 'message': 'Quantity must be greater than 0.'})
        
        if quantity > 100:
            return JsonResponse({'success': False, 'message': 'Maximum quantity is 100.'})
        
        # Validate product_id is numeric
        try:
            int(product_id)
        except ValueError:
            return JsonResponse({'success': False, 'message': 'Invalid product.'})
        
        # Validate restaurant context
        restaurant = validate_session_restaurant_id(request.session)
        if not restaurant:
            return JsonResponse({'success': False, 'message': 'Restaurant context lost.'})
        
        # Get product and verify it belongs to this restaurant
        product = Product.objects.filter(
            id=product_id,
            main_category__owner=restaurant
        ).first()
        
        if not product:
            return JsonResponse({'success': False, 'message': 'Product not found.'})
        
        if quantity > product.available_in_stock:
            return JsonResponse({
                'success': False,
                'message': f'Only {product.available_in_stock} items available.'
            })
        
        # Get and validate cart
        cart = validate_cart_data(request.session.get('cart', {}))
        
        if product_id in cart:
            # Update quantity and recalculate promotional pricing
            current_price = product.get_current_price()
            cart[product_id].update({
                'quantity': quantity,
                'price': str(current_price),
                'original_price': str(product.price),
                'has_promotion': product.has_active_promotion(),
            })
            request.session['cart'] = cart
            request.session.modified = True
            
            # Calculate cart totals
            cart_count = sum(item['quantity'] for item in cart.values())
            cart_total = sum(float(item['price']) * item['quantity'] for item in cart.values())
            item_total = float(cart[product_id]['price']) * quantity
            
            return JsonResponse({
                'success': True,
                'cart_count': cart_count,
                'cart_total': cart_total,
                'item_total': item_total,
            })
        
        return JsonResponse({'success': False, 'message': 'Item not found in cart.'})
        
    except json.JSONDecodeError:
        return JsonResponse({'success': False, 'message': 'Invalid request data.'})
    except (ValueError, TypeError):
        return JsonResponse({'success': False, 'message': 'Invalid quantity.'})
    except Exception as e:
        logger.error(f"Error in update_cart_quantity: {e}")
        return JsonResponse({'success': False, 'message': 'An error occurred.'})


@require_restaurant_context
@require_table_selection
def view_cart(request):
    """View cart contents"""
    # Get and validate cart
    cart = validate_cart_data(request.session.get('cart', {}))
    request.session['cart'] = cart  # Store validated cart back
    
    if not cart:
        messages.info(request, 'Your cart is empty.')
        return redirect('restaurant:menu')
    
    # Calculate totals
    cart_items = []
    cart_total = 0
    
    for product_id, item in cart.items():
        item_total = float(item['price']) * item['quantity']
        cart_total += item_total
        cart_items.append({
            'product_id': product_id,
            'name': item['name'],
            'price': float(item['price']),
            'quantity': item['quantity'],
            'total': item_total,
            'image': item.get('image'),
        })
    
    # Get restaurant owner's tax rate from validated session
    restaurant = validate_session_restaurant_id(request.session)
    tax_rate = float(restaurant.tax_rate) if restaurant else float(Decimal('0.0800'))
    
    # Calculate tax and final total
    tax_amount = cart_total * tax_rate
    final_total = cart_total + tax_amount
    
    # Determine base template based on user role
    if request.user.is_authenticated:
        if request.user.is_cashier() or request.user.is_customer_care():
            base_template = 'cashier_base.html'
        else:
            base_template = 'base.html'
    else:
        base_template = 'base.html'
    
    context = {
        'cart_items': cart_items,
        'cart_total': cart_total,
        'tax_amount': tax_amount,
        'tax_rate': tax_rate,
        'tax_percentage': int(tax_rate * 100),  # For display purposes
        'final_total': final_total,
        'table_number': request.session['selected_table'],
        'base_template': base_template,
    }
    
    return render(request, 'orders/view_cart.html', context)

@login_required
@require_restaurant_context
@require_table_selection
def place_order(request):
    """Place order from cart - handles both new orders and adding to existing"""
    # Validate cart
    cart = validate_cart_data(request.session.get('cart', {}))
    request.session['cart'] = cart
    
    if not cart:
        messages.error(request, 'Your cart is empty.')
        return redirect('restaurant:menu')
    
    # Check if we're adding to existing order
    add_to_order_id = request.session.get('add_to_order_id')
    
    if add_to_order_id:
        # Adding to existing order - process immediately
        return handle_add_to_existing_order(request, add_to_order_id, cart)
    
    # Creating new order - continue with normal flow
    
    if request.method == 'POST':
        form = OrderForm(request.POST)
        if form.is_valid():
            try:
                with transaction.atomic():
                    # Get current restaurant from validated session
                    current_restaurant = validate_session_restaurant_id(request.session)
                    
                    # For staff users, use their assigned restaurant
                    if request.user.is_customer_care() or request.user.is_kitchen_staff() or request.user.is_bar_staff() or request.user.is_buffet_staff() or request.user.is_service_staff() or request.user.is_cashier():
                        current_restaurant = request.user.get_owner()
                        if not current_restaurant:
                            messages.error(request, 'You are not assigned to any restaurant. Please contact your administrator.')
                            return redirect('orders:select_table')
                    
                    if not current_restaurant:
                        messages.error(request, 'Restaurant context not found. Please scan QR code again.')
                        return redirect('orders:select_table')
                    
                    # Validate table
                    table_number, table_id = validate_session_table(request.session, current_restaurant)
                    if not table_number:
                        messages.error(request, 'Invalid table selection.')
                        return redirect('orders:select_table')
                    
                    # Get table for the specific restaurant
                    try:
                        table = TableInfo.objects.get(
                            tbl_no=table_number,
                            owner=current_restaurant
                        )
                    except TableInfo.DoesNotExist:
                        messages.error(request, f'Table {table_number} not found in {current_restaurant.restaurant_name}.')
                        return redirect('orders:select_table')
                    except TableInfo.MultipleObjectsReturned:
                        table = TableInfo.objects.filter(
                            tbl_no=table_number,
                            owner=current_restaurant
                        ).first()
                    
                    # Sanitize special instructions
                    special_instructions = sanitize_special_instructions(
                        form.cleaned_data['special_instructions']
                    )
                    
                    # Create order
                    order = Order.objects.create(
                        order_number=f"ORD-{uuid.uuid4().hex[:8].upper()}",
                        table_info=table,
                        ordered_by=request.user,
                        special_instructions=special_instructions,
                        status='pending'
                    )
                    
                    # Create order items - verify each product belongs to restaurant
                    total_amount = 0
                    for product_id, item in cart.items():
                        product = Product.objects.filter(
                            id=product_id,
                            main_category__owner=current_restaurant
                        ).first()
                        
                        if not product:
                            raise Exception(f'Product not available')
                        
                        # Check stock again
                        if product.available_in_stock < item['quantity']:
                            raise Exception(f'Insufficient stock for {product.name}')
                        
                        # Create order item
                        OrderItem.objects.create(
                            order=order,
                            product=product,
                            quantity=item['quantity'],
                            unit_price=product.price
                        )
                        
                        # Update stock
                        product.available_in_stock -= item['quantity']
                        product.save()
                        
                        total_amount += float(item['price']) * item['quantity']
                    
                    # Update order total
                    order.total_amount = total_amount
                    order.save()
                    
                    # Log the order placement
                    log_security_event(
                        event_type='order_placed',
                        user=request.user,
                        description=f"Order {order.order_number} placed for table {table.tbl_no}",
                        ip_address=get_client_ip(request),
                        extra_data={
                            'order_id': order.id,
                            'order_number': order.order_number,
                            'table': table.tbl_no,
                            'total': str(total_amount),
                            'items_count': len(cart)
                        }
                    )
                    
                    # Send real-time notifications (non-blocking - failures won't break order)
                    try:
                        restaurant_id = current_restaurant.id
                        async_to_sync(channel_layer.group_send)(
                            f'restaurant_{restaurant_id}',
                            {
                                'type': 'new_order',
                                'order_id': str(order.id),
                                'order_number': order.order_number,
                                'table_number': str(table.tbl_no),
                                'customer_name': request.user.get_full_name() or request.user.username,
                                'items_count': len(cart),
                                'total_amount': str(total_amount),
                                'message': f'New order #{order.order_number} from Table {table.tbl_no}',
                                'timestamp': order.created_at.isoformat()
                            }
                        )
                        
                        async_to_sync(channel_layer.group_send)(
                            f'order_{order.id}',
                            {
                                'type': 'order_status_update',
                                'order_id': str(order.id),
                                'status': order.status,
                                'status_display': order.get_status_display(),
                                'message': 'Order placed successfully! Kitchen will start preparing your order soon.',
                                'updated_by': request.user.get_full_name() or request.user.username,
                                'timestamp': order.created_at.isoformat()
                            }
                        )
                    except Exception as ws_error:
                        # WebSocket notification failure shouldn't break order placement
                        logger.warning(f"WebSocket notification failed (non-critical): {ws_error}")
                    
                    # Clear cart but KEEP table selection for adding more orders
                    del request.session['cart']
                    # Do NOT clear selected_table - allows customer to order more at same table
                    # del request.session['selected_table']  # COMMENTED OUT
                    request.session.modified = True
                    
                    # ✨ SERVER-SIDE AUTO-PRINT (NO BROWSER DIALOG!)
                    try:
                        logger.info(f"Starting auto_print_order for Order #{order.order_number}")
                        logger.debug(f"Order ID: {order.id}, Table: {order.table_info.tbl_no}")
                        print_result = auto_print_order(order)
                        logger.info(f"Print result: {print_result}")
                        if print_result.get('kot_printed'):
                            messages.success(request, '🖨️ KOT printed automatically!')
                        if print_result.get('bot_printed'):
                            messages.success(request, '🖨️ BOT printed automatically!')
                        if print_result.get('buffet_printed'):
                            messages.success(request, '🖨️ BUFFET printed automatically!')
                        if print_result.get('service_printed'):
                            messages.success(request, '🖨️ SERVICE printed automatically!')
                        for error in print_result.get('errors', []):
                            messages.warning(request, f'Print warning: {error}')
                    except Exception as e:
                        # Print error doesn't stop order processing
                        messages.warning(request, 'Auto-print unavailable. Order was placed successfully.')
                        logger.exception(f"Auto-print exception for Order #{order.order_number}: {str(e)}")
                    
                    # Check if order has kitchen, bar, buffet, or service items for browser fallback
                    has_kitchen_items = any(item.product.station == 'kitchen' for item in order.order_items.all())
                    has_bar_items = any(item.product.station == 'bar' for item in order.order_items.all())
                    has_buffet_items = any(item.product.station == 'buffet' for item in order.order_items.all())
                    has_service_items = any(item.product.station == 'service' for item in order.order_items.all())
                    
                    # Store order ID and browser print flags (fallback if server print fails)
                    request.session['new_order_id'] = order.id
                    request.session['print_kot'] = has_kitchen_items and current_restaurant.auto_print_kot
                    request.session['print_bot'] = has_bar_items and current_restaurant.auto_print_bot
                    request.session['print_buffet'] = has_buffet_items and current_restaurant.auto_print_buffet
                    request.session['print_service'] = has_service_items and current_restaurant.auto_print_service
                    
                    messages.success(request, f'Order {order.order_number} placed successfully!')
                    return redirect('orders:order_confirmation', order_id=order.id)
                    
            except Exception as e:
                logger.error(f'Error placing order: {str(e)}')
                messages.error(request, 'Error placing order. Please try again.')
                return redirect('orders:view_cart')
    else:
        form = OrderForm()
    
    # Calculate cart total for display
    cart_total = sum(float(item['price']) * item['quantity'] for item in cart.values())
    
    # Get restaurant owner's tax rate
    try:
        selected_restaurant_id = request.session.get('selected_restaurant_id')
        if selected_restaurant_id:
            # Support all owner types: owner, main_owner, branch_owner
            restaurant_owner = User.objects.get(
                id=selected_restaurant_id,
                role__name__in=['owner', 'main_owner', 'branch_owner']
            )
            tax_rate = float(restaurant_owner.tax_rate)  # Convert decimal to float
        else:
            # Use default tax rate from User model default
            tax_rate = float(Decimal('0.0800'))  # Use same default as model
    except (User.DoesNotExist, TypeError):
        # Use default tax rate from User model default
        tax_rate = float(Decimal('0.0800'))  # Use same default as model
    
    # Calculate tax and final total
    tax_amount = cart_total * tax_rate
    final_total = cart_total + tax_amount
    
    # Determine base template based on user role
    if request.user.is_cashier() or request.user.is_customer_care():
        base_template = 'cashier_base.html'
    else:
        base_template = 'base.html'
    
    context = {
        'form': form,
        'cart': cart,
        'cart_total': cart_total,
        'tax_amount': tax_amount,
        'tax_rate': tax_rate,
        'tax_percentage': int(tax_rate * 100),  # For display purposes
        'final_total': final_total,
        'table_number': request.session['selected_table'],
        'base_template': base_template,
    }
    
    return render(request, 'orders/place_order.html', context)

@login_required
def order_confirmation(request, order_id):
    """Order confirmation page"""
    order = get_object_or_404(Order, id=order_id, ordered_by=request.user)
    
    # Check if we should auto-print KOT and/or BOT
    should_auto_print_kot = request.session.pop('print_kot', False)
    should_auto_print_bot = request.session.pop('print_bot', False)
    new_order_id = request.session.pop('new_order_id', None)
    
    # Verify the order has the appropriate items
    has_kitchen_items = any(item.product.station == 'kitchen' for item in order.order_items.all())
    has_bar_items = any(item.product.station == 'bar' for item in order.order_items.all())
    
    # Determine if auto-print should trigger (for popup windows)
    auto_print_kot = should_auto_print_kot and new_order_id == order.id and has_kitchen_items
    auto_print_bot = should_auto_print_bot and new_order_id == order.id and has_bar_items
    
    # Determine base template based on user role
    if request.user.is_cashier() or request.user.is_customer_care():
        base_template = 'cashier_base.html'
    else:
        base_template = 'base.html'
    
    context = {
        'order': order,
        'has_kitchen_items': has_kitchen_items,
        'has_bar_items': has_bar_items,
        'should_print_kot': auto_print_kot,  # For auto-print popup
        'should_print_bot': auto_print_bot,  # For auto-print popup
        'base_template': base_template,
    }
    
    return render(request, 'orders/order_confirmation.html', context)

@login_required
def my_orders(request):
    """View user's orders - customers see restaurant-specific, customer care sees all their orders"""
    # Get current restaurant from session
    selected_restaurant_id = request.session.get('selected_restaurant_id')
    restaurant = None
    
    if selected_restaurant_id:
        try:
            # Support all owner types: owner, main_owner, branch_owner
            restaurant = User.objects.get(
                id=selected_restaurant_id,
                role__name__in=['owner', 'main_owner', 'branch_owner']
            )
        except User.DoesNotExist:
            restaurant = None
    
    # Filter orders by user type
    orders_query = Order.objects.filter(ordered_by=request.user)
    
    if request.user.is_customer() and restaurant:
        # For universal customers, only show orders from current restaurant
        orders_query = orders_query.filter(
            table_info__owner=restaurant
        )
    elif request.user.is_customer() and request.user.owner:
        # For legacy customers tied to specific restaurant
        orders_query = orders_query.filter(
            table_info__owner=request.user.owner
        )
    elif request.user.is_customer_care():
        # For customer care users, show only their orders from their assigned restaurant
        try:
            owner_filter = get_owner_filter(request.user)
            if owner_filter:
                orders_query = orders_query.filter(table_info__owner=owner_filter)
            # If no restaurant assignment, show all their orders
        except PermissionDenied:
            # If no restaurant access, show all their orders
            pass
    
    orders = orders_query.select_related(
        'table_info', 'table_info__owner', 'confirmed_by'
    ).prefetch_related('order_items__product').order_by('-created_at')
    
    context = {
        'orders': orders,
        'restaurant_name': request.session.get('selected_restaurant_name', 'Restaurant'),
        'current_restaurant': restaurant,
        'is_customer_care': request.user.is_customer_care()
    }
    
    return render(request, 'orders/my_orders.html', context)

@login_required
def order_detail(request, order_id):
    """View order details with tracking information"""
    # Allow Customer Care, Owner, and Kitchen Staff to view any order from their restaurant
    if request.user.is_customer_care() or request.user.is_owner() or request.user.is_main_owner() or request.user.is_branch_owner() or request.user.is_kitchen_staff():
        owner = get_owner_filter(request.user)
        order = get_object_or_404(Order, id=order_id, table_info__owner=owner)
    else:
        # Regular customers can only view their own orders
        order = get_object_or_404(Order, id=order_id, ordered_by=request.user)
    
    # Define order progress steps with tracking information
    status_progress = [
        {'status': 'pending', 'label': 'Order Placed', 'icon': 'bi-receipt', 'description': 'Your order has been received'},
        {'status': 'confirmed', 'label': 'Order Confirmed', 'icon': 'bi-check-circle', 'description': 'Order confirmed by staff'},
        {'status': 'preparing', 'label': 'Preparing', 'icon': 'bi-hourglass-split', 'description': 'Kitchen is preparing your order'},
        {'status': 'ready', 'label': 'Ready', 'icon': 'bi-bell', 'description': 'Your order is ready for pickup'},
        {'status': 'served', 'label': 'Served', 'icon': 'bi-check2-all', 'description': 'Order has been served'},
    ]
    
    # Determine current step and completion status
    status_order = ['pending', 'confirmed', 'preparing', 'ready', 'served']
    try:
        current_step = status_order.index(order.status)
        completed_steps = current_step + 1 if order.status != 'cancelled' else 0
    except ValueError:
        current_step = -1
        completed_steps = 0
    
    # Payment status info
    payment_progress = {
        'unpaid': {'label': 'Payment Pending', 'icon': 'bi-credit-card', 'class': 'warning'},
        'partial': {'label': 'Partial Payment', 'icon': 'bi-credit-card-2-front', 'class': 'info'},
        'paid': {'label': 'Payment Complete', 'icon': 'bi-check-circle-fill', 'class': 'success'},
    }
    
    # Check for pending bill request for this table
    pending_bill_request = None
    if order.table_info and request.user.is_customer():
        pending_bill_request = BillRequest.objects.filter(
            table_info=order.table_info,
            status='pending'
        ).first()
    
    # Determine base template based on user role
    if request.user.is_authenticated:
        if request.user.is_cashier() or request.user.is_customer_care():
            base_template = 'cashier_base.html'
        else:
            base_template = 'base.html'
    else:
        base_template = 'base.html'
    
    context = {
        'order': order,
        'status_progress': status_progress,
        'current_step': current_step,
        'completed_steps': completed_steps,
        'payment_info': payment_progress.get(order.payment_status, payment_progress['unpaid']),
        'is_cancelled': order.status == 'cancelled',
        'pending_bill_request': pending_bill_request,
        'base_template': base_template,
    }
    
    return render(request, 'orders/order_detail.html', context)

@login_required
def track_order(request, order_number):
    """Track order by order number - for customer use"""
    order = get_object_or_404(Order, order_number=order_number, ordered_by=request.user)
    
    # Redirect to the detailed order tracking view
    return redirect('orders:order_detail', order_id=order.id)

@login_required
def order_list(request):
    """Order list with role-based filtering"""
    # Customer care users can only see their own orders
    if request.user.is_customer_care():
        orders = Order.objects.filter(ordered_by=request.user)
    else:
        # Filter by restaurant owner - each owner/staff sees only their restaurant's orders
        owner_filter = get_owner_filter(request.user)
        if owner_filter:
            orders = Order.objects.filter(table_info__owner=owner_filter)
        else:
            # Only system admin (no owner) can see all orders
            orders = Order.objects.all()
    
    # Order by most recent first
    orders = orders.select_related('table_info', 'ordered_by').prefetch_related('order_items__product').order_by('-created_at')
    
    context = {
        'orders': orders,
        'is_customer_care': request.user.is_customer_care(),
    }
    
    return render(request, 'orders/order_list.html', context)

@login_required
def create_order(request):
    """Placeholder for create order - redirect to table selection"""
    return redirect('orders:select_table')

@login_required
def kitchen_dashboard(request):
    """Kitchen staff dashboard to manage orders"""
    if not request.user.is_kitchen_staff():
        messages.error(request, 'Access denied. Kitchen staff privileges required.')
        return redirect('restaurant:home')
    
    # Get filter parameters
    status_filter = request.GET.get('status', 'pending')
    
    # Base queryset filtered by owner
    try:
        owner_filter = get_owner_filter(request.user)
        base_queryset = Order.objects.select_related('table_info', 'ordered_by', 'confirmed_by').prefetch_related('order_items__product')
        
        if owner_filter:
            # Filter orders where the customer belongs to the same owner as kitchen staff
            base_queryset = base_queryset.filter(table_info__owner=owner_filter)
        # If administrator or no owner filter, show all orders
        
    except PermissionDenied:
        messages.error(request, 'You are not associated with any restaurant.')
        return redirect('restaurant:home')
    
    # Only include orders that have at least one kitchen item
    def has_kitchen_items(order):
        return any(item.product.station == 'kitchen' for item in order.order_items.all())
    
    # Get orders by status and filter for kitchen items only
    pending_orders = [order for order in base_queryset.filter(status='pending').order_by('-created_at') if has_kitchen_items(order)]
    confirmed_orders = [order for order in base_queryset.filter(status='confirmed').order_by('-created_at') if has_kitchen_items(order)]
    preparing_orders = [order for order in base_queryset.filter(status='preparing').order_by('-created_at') if has_kitchen_items(order)]
    ready_orders = [order for order in base_queryset.filter(status='ready').order_by('-created_at') if has_kitchen_items(order)]
    served_orders = [order for order in base_queryset.filter(status='served').order_by('-created_at') if has_kitchen_items(order)]
    
    context = {
        'pending_orders': pending_orders,
        'confirmed_orders': confirmed_orders,
        'preparing_orders': preparing_orders,
        'ready_orders': ready_orders,
        'served_orders': served_orders,
        'pending_count': len(pending_orders),
        'confirmed_count': len(confirmed_orders),
        'preparing_count': len(preparing_orders),
        'ready_count': len(ready_orders),
        'served_count': len(served_orders),
        'status_choices': Order.STATUS_CHOICES,
    }
    
    return render(request, 'orders/kitchen_dashboard.html', context)

@login_required
def bar_dashboard(request):
    """Bar staff dashboard to manage bar orders"""
    if not (hasattr(request.user, 'role') and request.user.role and request.user.role.name == 'bar'):
        messages.error(request, 'Access denied. Bar staff privileges required.')
        return redirect('restaurant:home')

    # Get filter parameters
    status_filter = request.GET.get('status', 'pending')

    try:
        owner_filter = get_owner_filter(request.user)
        base_queryset = Order.objects.select_related('table_info', 'ordered_by', 'confirmed_by').prefetch_related('order_items__product')
        if owner_filter:
            base_queryset = base_queryset.filter(table_info__owner=owner_filter)
    except PermissionDenied:
        messages.error(request, 'You are not associated with any restaurant.')
        return redirect('restaurant:home')

    # Only include orders that have at least one bar item
    def has_bar_items(order):
        return any(item.product.station == 'bar' for item in order.order_items.all())

    pending_orders = [order for order in base_queryset.filter(status='pending').order_by('-created_at') if has_bar_items(order)]
    confirmed_orders = [order for order in base_queryset.filter(status='confirmed').order_by('-created_at') if has_bar_items(order)]
    preparing_orders = [order for order in base_queryset.filter(status='preparing').order_by('-created_at') if has_bar_items(order)]
    ready_orders = [order for order in base_queryset.filter(status='ready').order_by('-created_at') if has_bar_items(order)]
    served_orders = [order for order in base_queryset.filter(status='served').order_by('-created_at') if has_bar_items(order)]

    context = {
        'pending_orders': pending_orders,
        'confirmed_orders': confirmed_orders,
        'preparing_orders': preparing_orders,
        'ready_orders': ready_orders,
        'served_orders': served_orders,
        'pending_count': len(pending_orders),
        'confirmed_count': len(confirmed_orders),
        'preparing_count': len(preparing_orders),
        'ready_count': len(ready_orders),
        'served_count': len(served_orders),
        'status_choices': Order.STATUS_CHOICES,
    }
    return render(request, 'orders/bar_dashboard.html', context)

@login_required
def buffet_dashboard(request):
    """Buffet staff dashboard to manage buffet orders"""
    if not (hasattr(request.user, 'role') and request.user.role and request.user.role.name == 'buffet'):
        messages.error(request, 'Access denied. Buffet staff privileges required.')
        return redirect('restaurant:home')

    # Get filter parameters
    status_filter = request.GET.get('status', 'pending')

    try:
        owner_filter = get_owner_filter(request.user)
        base_queryset = Order.objects.select_related('table_info', 'ordered_by', 'confirmed_by').prefetch_related('order_items__product')
        
        # Filter by owner
        if owner_filter:
            base_queryset = base_queryset.filter(table_info__owner=owner_filter)
        
        # Filter to only include orders with buffet items (database-level)
        base_queryset = base_queryset.filter(order_items__product__station='buffet').distinct()
    except PermissionDenied:
        messages.error(request, 'You are not associated with any restaurant.')
        return redirect('restaurant:home')

    # Get orders by status
    pending_orders = base_queryset.filter(status='pending').order_by('-created_at')
    confirmed_orders = base_queryset.filter(status='confirmed').order_by('-created_at')
    preparing_orders = base_queryset.filter(status='preparing').order_by('-created_at')
    ready_orders = base_queryset.filter(status='ready').order_by('-created_at')
    served_orders = base_queryset.filter(status='served').order_by('-created_at')

    context = {
        'pending_orders': pending_orders,
        'confirmed_orders': confirmed_orders,
        'preparing_orders': preparing_orders,
        'ready_orders': ready_orders,
        'served_orders': served_orders,
        'pending_count': len(pending_orders),
        'confirmed_count': len(confirmed_orders),
        'preparing_count': len(preparing_orders),
        'ready_count': len(ready_orders),
        'served_count': len(served_orders),
        'status_choices': Order.STATUS_CHOICES,
    }
    return render(request, 'orders/buffet_dashboard.html', context)

@login_required
def service_dashboard(request):
    """Service staff dashboard to manage service orders"""
    if not (hasattr(request.user, 'role') and request.user.role and request.user.role.name == 'service'):
        messages.error(request, 'Access denied. Service staff privileges required.')
        return redirect('restaurant:home')

    # Get filter parameters
    status_filter = request.GET.get('status', 'pending')

    try:
        owner_filter = get_owner_filter(request.user)
        base_queryset = Order.objects.select_related('table_info', 'ordered_by', 'confirmed_by').prefetch_related('order_items__product')
        
        # Filter by owner
        if owner_filter:
            base_queryset = base_queryset.filter(table_info__owner=owner_filter)
        
        # Filter to only include orders with service items (database-level)
        base_queryset = base_queryset.filter(order_items__product__station='service').distinct()
    except PermissionDenied:
        messages.error(request, 'You are not associated with any restaurant.')
        return redirect('restaurant:home')

    # Get orders by status
    pending_orders = base_queryset.filter(status='pending').order_by('-created_at')
    confirmed_orders = base_queryset.filter(status='confirmed').order_by('-created_at')
    preparing_orders = base_queryset.filter(status='preparing').order_by('-created_at')
    ready_orders = base_queryset.filter(status='ready').order_by('-created_at')
    served_orders = base_queryset.filter(status='served').order_by('-created_at')

    context = {
        'pending_orders': pending_orders,
        'confirmed_orders': confirmed_orders,
        'preparing_orders': preparing_orders,
        'ready_orders': ready_orders,
        'served_orders': served_orders,
        'pending_count': len(pending_orders),
        'confirmed_count': len(confirmed_orders),
        'preparing_count': len(preparing_orders),
        'ready_count': len(ready_orders),
        'served_count': len(served_orders),
        'status_choices': Order.STATUS_CHOICES,
    }
    return render(request, 'orders/service_dashboard.html', context)

@login_required
def kitchen_reports(request):
    """Kitchen staff daily and weekly reports"""
    if not request.user.is_kitchen_staff():
        messages.error(request, 'Access denied. Kitchen staff privileges required.')
        return redirect('restaurant:home')
    
    try:
        owner_filter = get_owner_filter(request.user)
    except PermissionDenied:
        messages.error(request, 'You are not associated with any restaurant.')
        return redirect('restaurant:home')
    
    # Get date range filter
    period = request.GET.get('period', 'today')
    from datetime import timedelta
    
    today_start = timezone.now().replace(hour=0, minute=0, second=0, microsecond=0)
    
    if period == 'today':
        start_date = today_start
        end_date = today_start + timedelta(days=1)
        period_label = 'Today'
    elif period == 'weekly':
        week_start = today_start - timedelta(days=today_start.weekday())
        start_date = week_start
        end_date = today_start + timedelta(days=1)
        period_label = 'This Week'
    elif period == 'monthly':
        month_start = today_start.replace(day=1)
        start_date = month_start
        end_date = today_start + timedelta(days=1)
        period_label = 'This Month'
    else:
        start_date = today_start
        end_date = today_start + timedelta(days=1)
        period_label = 'Today'
    
    # Get all orders with kitchen items in the period
    base_queryset = Order.objects.filter(
        created_at__gte=start_date,
        created_at__lt=end_date
    ).select_related('table_info', 'ordered_by').prefetch_related('order_items__product')
    
    if owner_filter:
        base_queryset = base_queryset.filter(table_info__owner=owner_filter)
    
    # Filter orders that have kitchen items
    def has_kitchen_items(order):
        return any(item.product.station == 'kitchen' for item in order.order_items.all())
    
    orders_with_kitchen_items = [order for order in base_queryset if has_kitchen_items(order)]
    
    # Calculate statistics
    total_orders = len(orders_with_kitchen_items)
    
    status_counts = {
        'pending': len([o for o in orders_with_kitchen_items if o.status == 'pending']),
        'confirmed': len([o for o in orders_with_kitchen_items if o.status == 'confirmed']),
        'preparing': len([o for o in orders_with_kitchen_items if o.status == 'preparing']),
        'ready': len([o for o in orders_with_kitchen_items if o.status == 'ready']),
        'served': len([o for o in orders_with_kitchen_items if o.status == 'served']),
        'cancelled': len([o for o in orders_with_kitchen_items if o.status == 'cancelled']),
    }
    
    # Calculate total kitchen items prepared
    total_items = 0
    items_by_product = {}
    
    for order in orders_with_kitchen_items:
        for item in order.order_items.all():
            if item.product.station == 'kitchen':
                total_items += item.quantity
                product_name = item.product.name
                if product_name in items_by_product:
                    items_by_product[product_name]['quantity'] += item.quantity
                    items_by_product[product_name]['orders'] += 1
                else:
                    items_by_product[product_name] = {
                        'quantity': item.quantity,
                        'orders': 1,
                        'product': item.product
                    }
    
    # Sort items by quantity (most popular first)
    popular_items = sorted(items_by_product.items(), key=lambda x: x[1]['quantity'], reverse=True)[:10]
    
    # Calculate average preparation time (served orders only)
    served_orders = [o for o in orders_with_kitchen_items if o.status == 'served']
    if served_orders:
        total_prep_time = sum(
            (o.updated_at - o.created_at).total_seconds() / 60  # minutes
            for o in served_orders
        )
        avg_prep_time = total_prep_time / len(served_orders)
    else:
        avg_prep_time = 0
    
    # Get currency symbol
    currency_symbol = request.user.get_currency_symbol()
    
    context = {
        'period': period,
        'period_label': period_label,
        'start_date': start_date,
        'end_date': end_date,
        'total_orders': total_orders,
        'status_counts': status_counts,
        'total_items': total_items,
        'popular_items': popular_items,
        'avg_prep_time': round(avg_prep_time, 1),
        'orders': orders_with_kitchen_items,
        'currency_symbol': currency_symbol,
    }
    
    return render(request, 'orders/kitchen_reports.html', context)

@login_required
def bar_reports(request):
    """Bar staff daily and weekly reports"""
    if not request.user.is_bar_staff():
        messages.error(request, 'Access denied. Bar staff privileges required.')
        return redirect('restaurant:home')
    
    try:
        owner_filter = get_owner_filter(request.user)
    except PermissionDenied:
        messages.error(request, 'You are not associated with any restaurant.')
        return redirect('restaurant:home')
    
    # Get date range filter
    period = request.GET.get('period', 'today')
    from datetime import timedelta
    
    today_start = timezone.now().replace(hour=0, minute=0, second=0, microsecond=0)
    
    if period == 'today':
        start_date = today_start
        end_date = today_start + timedelta(days=1)
        period_label = 'Today'
    elif period == 'weekly':
        week_start = today_start - timedelta(days=today_start.weekday())
        start_date = week_start
        end_date = today_start + timedelta(days=1)
        period_label = 'This Week'
    else:
        start_date = today_start
        end_date = today_start + timedelta(days=1)
        period_label = 'Today'
    
    # Get all orders with bar items in the period
    base_queryset = Order.objects.filter(
        created_at__gte=start_date,
        created_at__lt=end_date
    ).select_related('table_info', 'ordered_by').prefetch_related('order_items__product')
    
    if owner_filter:
        base_queryset = base_queryset.filter(table_info__owner=owner_filter)
    
    # Filter orders that have bar items
    def has_bar_items(order):
        return any(item.product.station == 'bar' for item in order.order_items.all())
    
    orders_with_bar_items = [order for order in base_queryset if has_bar_items(order)]
    
    # Calculate statistics
    total_orders = len(orders_with_bar_items)
    
    status_counts = {
        'pending': len([o for o in orders_with_bar_items if o.status == 'pending']),
        'confirmed': len([o for o in orders_with_bar_items if o.status == 'confirmed']),
        'preparing': len([o for o in orders_with_bar_items if o.status == 'preparing']),
        'ready': len([o for o in orders_with_bar_items if o.status == 'ready']),
        'served': len([o for o in orders_with_bar_items if o.status == 'served']),
        'cancelled': len([o for o in orders_with_bar_items if o.status == 'cancelled']),
    }
    
    # Calculate total bar items prepared
    total_items = 0
    items_by_product = {}
    
    for order in orders_with_bar_items:
        for item in order.order_items.all():
            if item.product.station == 'bar':
                total_items += item.quantity
                product_name = item.product.name
                if product_name in items_by_product:
                    items_by_product[product_name]['quantity'] += item.quantity
                    items_by_product[product_name]['orders'] += 1
                else:
                    items_by_product[product_name] = {
                        'quantity': item.quantity,
                        'orders': 1,
                        'product': item.product
                    }
    
    # Sort items by quantity (most popular drinks first)
    popular_items = sorted(items_by_product.items(), key=lambda x: x[1]['quantity'], reverse=True)[:10]
    
    # Calculate average preparation time (served orders only)
    served_orders = [o for o in orders_with_bar_items if o.status == 'served']
    if served_orders:
        total_prep_time = sum(
            (o.updated_at - o.created_at).total_seconds() / 60  # minutes
            for o in served_orders
        )
        avg_prep_time = total_prep_time / len(served_orders)
    else:
        avg_prep_time = 0
    
    # Get currency symbol
    currency_symbol = request.user.get_currency_symbol()
    
    context = {
        'period': period,
        'period_label': period_label,
        'start_date': start_date,
        'end_date': end_date,
        'total_orders': total_orders,
        'status_counts': status_counts,
        'total_items': total_items,
        'popular_items': popular_items,
        'avg_prep_time': round(avg_prep_time, 1),
        'orders': orders_with_bar_items,
        'currency_symbol': currency_symbol,
    }
    
    return render(request, 'orders/bar_reports.html', context)

@login_required
@require_POST
def confirm_order(request, order_id):
    """Kitchen staff confirms a pending order"""
    if not request.user.is_kitchen_staff():
        return JsonResponse({'success': False, 'message': 'Access denied.'})
    
    try:
        # Get owner filter to ensure kitchen staff can only confirm their restaurant's orders
        owner_filter = get_owner_filter(request.user)
        if owner_filter:
            order = get_object_or_404(Order, id=order_id, status='pending', table_info__owner=owner_filter)
        else:
            order = get_object_or_404(Order, id=order_id, status='pending')
        
        order.status = 'confirmed'
        order.confirmed_by = request.user
        order.save()
        
        # Mark table as occupied when order is confirmed
        table = order.table_info
        table.is_available = False
        table.save()
        
        return JsonResponse({
            'success': True,
            'message': f'Order {order.order_number} confirmed successfully! Table {table.tbl_no} is now occupied.',
            'new_status': order.get_status_display()
        })
        
    except Exception as e:
        return JsonResponse({'success': False, 'message': 'An error occurred.'})

@login_required
@require_POST
def update_order_status(request, order_id):
    """Update order status"""
    if not (request.user.is_kitchen_staff() or request.user.is_bar_staff() or request.user.is_buffet_staff() or request.user.is_service_staff()):
        return JsonResponse({'success': False, 'message': 'Access denied.'})
    
    try:
        # Get owner filter for current user
        owner_filter = get_owner_filter(request.user)
        
        # Handle both JSON and form data
        if request.content_type == 'application/json':
            data = json.loads(request.body)
            new_status = data.get('status')
        else:
            # Handle form data
            new_status = request.POST.get('status')
        
        if new_status not in ['confirmed', 'preparing', 'ready', 'served', 'cancelled']:
            return JsonResponse({'success': False, 'message': 'Invalid status.'})
        
        # Get order with owner filtering
        if owner_filter:
            order = get_object_or_404(Order, id=order_id, table_info__owner=owner_filter)
        else:
            order = get_object_or_404(Order, id=order_id)
        
        # Check if bar staff is trying to update an order without bar items
        if request.user.is_bar_staff():
            has_bar_items = any(item.product.station == 'bar' for item in order.order_items.all())
            if not has_bar_items:
                return JsonResponse({'success': False, 'message': 'Access denied. This order contains no bar items.'})
        
        # Check if kitchen staff is trying to update an order without kitchen items
        if request.user.is_kitchen_staff():
            has_kitchen_items = any(item.product.station == 'kitchen' for item in order.order_items.all())
            if not has_kitchen_items:
                return JsonResponse({'success': False, 'message': 'Access denied. This order contains no kitchen items.'})
        
        # Check if buffet staff is trying to update an order without buffet items
        if request.user.is_buffet_staff():
            has_buffet_items = any(item.product.station == 'buffet' for item in order.order_items.all())
            if not has_buffet_items:
                return JsonResponse({'success': False, 'message': 'Access denied. This order contains no buffet items.'})
        
        # Check if service staff is trying to update an order without service items
        if request.user.is_service_staff():
            has_service_items = any(item.product.station == 'service' for item in order.order_items.all())
            if not has_service_items:
                return JsonResponse({'success': False, 'message': 'Access denied. This order contains no service items.'})
        
        # More flexible status transitions for mobile/real-world usage
        valid_transitions = {
            'pending': ['confirmed', 'cancelled'],
            'confirmed': ['preparing', 'cancelled'],
            'preparing': ['ready', 'cancelled'],
            'ready': ['served', 'cancelled'],
            'served': ['cancelled'],  # Allow cancellation even after served (refunds, etc.)
            'cancelled': []
        }
        
        # Allow kitchen staff and bar staff to change status backwards for corrections
        if request.user.is_kitchen_staff() or request.user.is_bar_staff() or request.user.is_buffet_staff() or request.user.is_service_staff() or request.user.is_owner() or request.user.is_main_owner() or request.user.is_branch_owner():
            valid_transitions.update({
                'confirmed': ['pending', 'preparing', 'cancelled'],
                'preparing': ['confirmed', 'ready', 'cancelled'], 
                'ready': ['preparing', 'served', 'cancelled'],
                'served': ['ready', 'cancelled']  # Allow corrections
            })
        
        if new_status not in valid_transitions.get(order.status, []):
            return JsonResponse({'success': False, 'message': 'Invalid status transition.'})
        
        # Handle cancellation reason
        if new_status == 'cancelled':
            cancel_reason = request.POST.get('cancel_reason', '') if request.content_type != 'application/json' else data.get('cancel_reason', '')
            order.reason_if_cancelled = cancel_reason
        
        order.status = new_status
        if new_status == 'confirmed' and not order.confirmed_by:
            order.confirmed_by = request.user
        
        # Release table if order is cancelled through status change
        if new_status == 'cancelled':
            order.release_table()
            
        order.save()

        # Send real-time notifications
        async_to_sync(channel_layer.group_send)(
            f'order_{order.id}',
            {
                'type': 'order_status_update',
                'message': {
                    'order_id': order.id,
                    'order_number': order.order_number,
                    'status': order.status,
                    'status_display': order.get_status_display(),
                    'updated_by': request.user.get_full_name() or request.user.username,
                    'timestamp': timezone.now().isoformat()
                }
            }
        )

        # Send notification to restaurant staff
        if order.ordered_by and hasattr(order.ordered_by, 'owner'):
            owner_id = order.ordered_by.owner.id
        else:
            owner_id = 'default'
            
        async_to_sync(channel_layer.group_send)(
            f'restaurant_{owner_id}',
            {
                'type': 'order_status_update',
                'message': {
                    'order_id': order.id,
                    'order_number': order.order_number,
                    'status': order.status,
                    'status_display': order.get_status_display(),
                    'customer': order.ordered_by.get_full_name() or order.ordered_by.username,
                    'updated_by': request.user.get_full_name() or request.user.username,
                    'timestamp': timezone.now().isoformat()
                }
            }
        )

        # Return appropriate response based on request type
        if request.content_type == 'application/json':
            return JsonResponse({
                'success': True,
                'message': f'Order {order.order_number} updated to {order.get_status_display()}!',
                'new_status': order.get_status_display()
            })
        else:
            # For form submissions, redirect based on user role
            messages.success(request, f'Order {order.order_number} updated to {order.get_status_display()}!')
            if request.user.is_bar_staff():
                return redirect('orders:bar_dashboard')
            elif request.user.is_buffet_staff():
                return redirect('orders:buffet_dashboard')
            elif request.user.is_service_staff():
                return redirect('orders:service_dashboard')
            else:
                return redirect('orders:kitchen_dashboard')
        
    except Exception as e:
        if request.content_type == 'application/json':
            return JsonResponse({'success': False, 'message': 'An error occurred.'})
        else:
            messages.error(request, 'An error occurred while updating the order.')
            if request.user.is_bar_staff():
                return redirect('orders:bar_dashboard')
            elif request.user.is_buffet_staff():
                return redirect('orders:buffet_dashboard')
            elif request.user.is_service_staff():
                return redirect('orders:service_dashboard')
            else:
                return redirect('orders:kitchen_dashboard')

@login_required
def cancel_order(request, order_id):
    """Cancel an order with reason"""
    if not request.user.is_kitchen_staff():
        if request.headers.get('Content-Type') == 'application/json':
            return JsonResponse({'success': False, 'message': 'Access denied. Kitchen staff privileges required.'})
        messages.error(request, 'Access denied. Kitchen staff privileges required.')
        return redirect('orders:kitchen_dashboard')
    
    try:
        owner_filter = get_owner_filter(request.user)
        
        # Get order with owner filtering
        if owner_filter:
            order = get_object_or_404(Order, id=order_id, table_info__owner=owner_filter)
        else:
            order = get_object_or_404(Order, id=order_id)
    except PermissionDenied:
        if request.headers.get('Content-Type') == 'application/json':
            return JsonResponse({'success': False, 'message': 'You are not associated with any restaurant.'})
        messages.error(request, 'You are not associated with any restaurant.')
        return redirect('orders:kitchen_dashboard')
    
    if order.status in ['served', 'cancelled']:
        if request.headers.get('Content-Type') == 'application/json':
            return JsonResponse({'success': False, 'message': 'Cannot cancel this order.'})
        messages.error(request, 'Cannot cancel this order.')
        return redirect('orders:kitchen_dashboard')
    
    if request.method == 'POST':
        # Handle AJAX request
        if request.headers.get('Content-Type') == 'application/json':
            try:
                data = json.loads(request.body)
                reason = data.get('reason', '').strip()
                
                if not reason:
                    return JsonResponse({'success': False, 'message': 'Cancellation reason is required.'})
                
                with transaction.atomic():
                    # Restore product stock
                    for item in order.order_items.all():
                        product = item.product
                        product.available_in_stock += item.quantity
                        product.save()
                    
                    # Update order
                    order.status = 'cancelled'
                    order.reason_if_cancelled = reason
                    # Release the table when order is cancelled
                    order.release_table()
                    order.save()
                    
                    return JsonResponse({
                        'success': True,
                        'message': f'Order {order.order_number} cancelled successfully.'
                    })
                    
            except Exception as e:
                return JsonResponse({'success': False, 'message': 'An error occurred while cancelling the order.'})
        
        # Handle regular form submission
        form = CancelOrderForm(request.POST)
        if form.is_valid():
            with transaction.atomic():
                # Restore product stock
                for item in order.order_items.all():
                    product = item.product
                    product.available_in_stock += item.quantity
                    product.save()
                
                # Update order
                order.status = 'cancelled'
                order.reason_if_cancelled = form.cleaned_data['reason']
                # Release the table when order is cancelled
                order.release_table()
                order.save()
                
                messages.success(request, f'Order {order.order_number} cancelled successfully.')
                return redirect('orders:kitchen_dashboard')
    else:
        form = CancelOrderForm()
    
    return render(request, 'orders/cancel_order.html', {'form': form, 'order': order})

@login_required
def customer_cancel_order(request, order_id):
    """Allow customers and customer care to cancel pending orders"""
    if not (request.user.is_customer() or request.user.is_customer_care()):
        messages.error(request, 'Access denied. Customer privileges required.')
        return redirect('restaurant:home')
    
    # Get the order - ensure it belongs to the user for customers
    if request.user.is_customer():
        order = get_object_or_404(Order, id=order_id, ordered_by=request.user)
    else:  # Customer care can cancel orders from their restaurant
        try:
            owner_filter = get_owner_filter(request.user)
            if owner_filter:
                order = get_object_or_404(Order, id=order_id, table_info__owner=owner_filter)
            else:
                order = get_object_or_404(Order, id=order_id)
        except PermissionDenied:
            messages.error(request, 'You are not associated with any restaurant.')
            return redirect('restaurant:home')
    
    # Check if order can be cancelled (only pending orders)
    if order.status != 'pending':
        if request.headers.get('Content-Type') == 'application/json':
            return JsonResponse({
                'success': False, 
                'message': 'Order cannot be cancelled. It has already been confirmed by the kitchen.'
            })
        messages.error(request, 'Order cannot be cancelled. It has already been confirmed by the kitchen.')
        return redirect('orders:my_orders' if request.user.is_customer() else 'orders:customer_care_dashboard')
    
    if request.method == 'POST':
        # Handle AJAX request
        if request.headers.get('Content-Type') == 'application/json':
            try:
                data = json.loads(request.body)
                reason = data.get('reason', 'Cancelled by customer').strip()
                
                with transaction.atomic():
                    # Restore product stock
                    for item in order.order_items.all():
                        product = item.product
                        product.available_in_stock += item.quantity
                        product.save()
                    
                    # Update order
                    order.status = 'cancelled'
                    order.reason_if_cancelled = reason
                    # Release the table when order is cancelled
                    order.release_table()
                    order.save()
                    
                    return JsonResponse({
                        'success': True,
                        'message': f'Order {order.order_number} cancelled successfully.'
                    })
                    
            except Exception as e:
                return JsonResponse({'success': False, 'message': 'An error occurred while cancelling the order.'})
        
        # Handle regular form submission
        reason = request.POST.get('reason', 'Cancelled by customer').strip()
        
        try:
            with transaction.atomic():
                # Restore product stock
                for item in order.order_items.all():
                    product = item.product
                    product.available_in_stock += item.quantity
                    product.save()
                
                # Update order
                order.status = 'cancelled'
                order.reason_if_cancelled = reason if reason else 'Cancelled by customer'
                # Release the table when order is cancelled
                order.release_table()
                order.save()
                
                messages.success(request, f'Order {order.order_number} cancelled successfully.')
                return redirect('orders:my_orders' if request.user.is_customer() else 'orders:customer_care_dashboard')
        except Exception as e:
            messages.error(request, 'An error occurred while cancelling the order.')
    
    context = {
        'order': order,
        'can_cancel': order.status == 'pending',
        'is_customer_care': request.user.is_customer_care()
    }
    
    return render(request, 'orders/customer_cancel_order.html', context)

@login_required
def kitchen_order_detail(request, order_id):
    """Detailed view of order for kitchen staff"""
    if not request.user.is_kitchen_staff():
        messages.error(request, 'Access denied. Kitchen staff privileges required.')
        return redirect('restaurant:home')
    
    try:
        owner_filter = get_owner_filter(request.user)
        
        # Get order with owner filtering
        if owner_filter:
            order = get_object_or_404(Order, id=order_id, table_info__owner=owner_filter)
        else:
            order = get_object_or_404(Order, id=order_id)
    except PermissionDenied:
        messages.error(request, 'You are not associated with any restaurant.')
        return redirect('orders:kitchen_dashboard')
        
    return render(request, 'orders/kitchen_order_detail.html', {'order': order})

@login_required
def customer_care_dashboard(request):
    """Customer care dashboard with orders placed by this customer care user from their restaurant only"""
    if not request.user.is_customer_care():
        messages.error(request, 'Access denied. Customer care privileges required.')
        return redirect('restaurant:home')
    
    # Set restaurant context for customer care users
    if request.user.owner:
        request.session['selected_restaurant_id'] = request.user.owner.id
        request.session['selected_restaurant_name'] = request.user.owner.restaurant_name
    
    try:
        # Get customer care user's assigned restaurant
        owner_filter = get_owner_filter(request.user)
        
        if owner_filter:
            # Get orders placed BY this customer care user from their assigned restaurant only
            user_orders = Order.objects.filter(
                ordered_by=request.user,
                table_info__owner=owner_filter
            )
        else:
            # If no restaurant assignment, show all their orders
            user_orders = Order.objects.filter(ordered_by=request.user)
            
    except PermissionDenied:
        messages.error(request, 'You are not associated with any restaurant.')
        return redirect('restaurant:home')
    
    # Calculate statistics for today
    today = timezone.now().date()
    today_orders = user_orders.filter(created_at__date=today)
    
    stats = {
        'total_orders': today_orders.count(),
        'pending_orders': today_orders.filter(status__in=['pending', 'confirmed']).count(),
        'completed_orders': today_orders.filter(status='served').count(),
        'cancelled_orders': today_orders.filter(status='cancelled').count(),
    }
    
    # Get recent orders (last 10) placed by this customer care user from their restaurant
    recent_orders = user_orders.select_related(
        'table_info', 'table_info__owner', 'confirmed_by'
    ).prefetch_related(
        'order_items__product'
    ).order_by('-created_at')[:10]
    
    # Get pending bill requests from the same restaurant
    pending_bill_requests = []
    if owner_filter:
        pending_bill_requests = BillRequest.objects.filter(
            table_info__owner=owner_filter,
            status='pending'
        ).select_related('table_info', 'requested_by').order_by('-created_at')
    
    context = {
        'stats': stats,
        'recent_orders': recent_orders,
        'pending_bill_requests': pending_bill_requests,
        'user': request.user,
        'restaurant': owner_filter if owner_filter else None,
        'restaurant_name': owner_filter.restaurant_name if owner_filter else 'Restaurant',
    }
    
    return render(request, 'orders/customer_care_dashboard.html', context)


@login_required
def customer_care_payments(request):
    """Customer Care payment processing interface - separate from cashier dashboard"""
    if not (request.user.is_customer_care() or request.user.is_owner() or 
            request.user.is_main_owner() or request.user.is_branch_owner()):
        messages.error(request, "Access denied. Customer Care or Owner role required.")
        return redirect('accounts:profile')
    
    owner = get_owner_filter(request.user)
    
    # Get filters from request
    table_filter = request.GET.get('table', '')
    status_filter = request.GET.get('status', '')
    period_filter = request.GET.get('period', 'today')
    
    # Apply period filter
    from django.utils import timezone
    today_start = timezone.now().replace(hour=0, minute=0, second=0, microsecond=0)
    
    if period_filter == 'weekly':
        # Start of week (Monday)
        days_since_monday = today_start.weekday()
        week_start = today_start - timezone.timedelta(days=days_since_monday)
        orders = Order.objects.filter(
            table_info__owner=owner,
            created_at__gte=week_start
        )
    else:  # today
        today_end = today_start + timezone.timedelta(days=1)
        orders = Order.objects.filter(
            table_info__owner=owner,
            created_at__gte=today_start,
            created_at__lt=today_end
        )
    
    # Customer care sees only their own orders (unless they're owner/manager)
    if request.user.is_customer_care() and not (request.user.is_owner() or 
                                                  request.user.is_main_owner() or 
                                                  request.user.is_branch_owner()):
        orders = orders.filter(ordered_by=request.user)
    
    # Apply filters
    if table_filter:
        orders = orders.filter(table_info__tbl_no__icontains=table_filter)
    
    if status_filter:
        orders = orders.filter(payment_status=status_filter)
    
    # Prefetch related data
    from django.db.models import Prefetch
    orders = orders.select_related('table_info', 'ordered_by').prefetch_related(
        Prefetch('order_items', queryset=OrderItem.objects.select_related('product')),
        'payments'
    ).order_by('-created_at')
    
    # Get all tables for dropdown
    tables = TableInfo.objects.filter(owner=owner).order_by('tbl_no')
    
    # Get products for waste recording modal
    products = Product.objects.filter(
        main_category__owner=owner,
        is_available=True
    ).select_related('main_category')
    
    context = {
        'orders': orders,
        'tables': tables,
        'products': products,
        'table_filter': table_filter,
        'status_filter': status_filter,
        'period_filter': period_filter,
        'user': request.user,
        'is_customer_care': True,  # Flag to identify this is customer care interface
    }
    
    return render(request, 'orders/customer_care_payments.html', context)


@login_required
def customer_care_receipt(request, payment_id):
    """Generate receipt for Customer Care - separate from cashier"""
    if not (request.user.is_customer_care() or request.user.is_owner() or 
            request.user.is_main_owner() or request.user.is_branch_owner()):
        messages.error(request, "Access denied. Customer Care or Owner role required.")
        return redirect('accounts:profile')
    
    from cashier.models import Payment
    from decimal import Decimal
    
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
        'user': request.user,  # Current user viewing the receipt
        'change_amount': change_amount,
        'remaining_balance': remaining_balance,
        'is_customer_care_interface': True,  # Flag for template
    }
    
    return render(request, 'orders/customer_care_receipt.html', context)


@login_required
def customer_care_reprint_receipt(request, payment_id):
    """Reprint receipt for Customer Care"""
    if not (request.user.is_customer_care() or request.user.is_owner() or 
            request.user.is_main_owner() or request.user.is_branch_owner()):
        messages.error(request, "Access denied. Customer Care or Owner role required.")
        return redirect('accounts:profile')
    
    from cashier.models import Payment
    from decimal import Decimal
    
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
        'is_customer_care_interface': True,
    }
    
    return render(request, 'orders/customer_care_receipt.html', context)


@login_required
def customer_care_receipt_management(request):
    """Manage receipts for Customer Care - search and reprint by order number or date"""
    if not (request.user.is_customer_care() or request.user.is_owner() or 
            request.user.is_main_owner() or request.user.is_branch_owner()):
        messages.error(request, "Access denied. Customer Care or Owner role required.")
        return redirect('accounts:profile')
    
    from cashier.models import Payment
    from restaurant.models import Product
    from django.db.models import Q
    
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
    
    context = {
        'payments': payments,
        'search_query': search_query,
        'date_from': date_from,
        'date_to': date_to,
        'user': request.user,
    }
    
    return render(request, 'orders/customer_care_receipt_management.html', context)

@login_required
def view_receipt(request, order_id):
    """View receipt for a paid order"""
    # Get the order - ensure user has permission to view it
    if request.user.is_customer():
        order = get_object_or_404(Order, id=order_id, ordered_by=request.user)
    elif request.user.is_customer_care():
        try:
            owner_filter = get_owner_filter(request.user)
            if owner_filter:
                order = get_object_or_404(Order, id=order_id, table_info__owner=owner_filter)
            else:
                order = get_object_or_404(Order, id=order_id)
        except PermissionDenied:
            messages.error(request, 'You are not associated with any restaurant.')
            return redirect('orders:my_orders')
    else:
        messages.error(request, 'Access denied.')
        return redirect('orders:my_orders')
    
    # Check if order is paid
    if order.payment_status != 'paid':
        messages.error(request, 'Receipt is only available for paid orders.')
        return redirect('orders:my_orders')
    
    # Get payment information
    payments = order.payments.filter(is_voided=False).select_related('processed_by').order_by('created_at')
    
    # Calculate totals
    subtotal = order.get_subtotal()
    tax_amount = order.get_tax_amount()
    discount_amount = order.get_total_discount()
    total_amount = order.total_amount
    
    # Get restaurant name - use main restaurant name for branch staff
    owner = order.table_info.owner
    if owner.role.name == 'branch_owner':
        # For branch owners, show the main restaurant name
        from restaurant.models import Restaurant
        branch_restaurant = Restaurant.objects.filter(
            branch_owner=owner, 
            is_main_restaurant=False
        ).first()
        if branch_restaurant and branch_restaurant.parent_restaurant:
            restaurant_name = branch_restaurant.parent_restaurant.name
        else:
            restaurant_name = owner.restaurant_name
    else:
        restaurant_name = owner.restaurant_name
    
    context = {
        'order': order,
        'payments': payments,
        'subtotal': subtotal,
        'tax_amount': tax_amount,
        'discount_amount': discount_amount,
        'total_amount': total_amount,
        'restaurant_name': restaurant_name,
        'restaurant_owner': owner,
    }
    
    return render(request, 'orders/receipt.html', context)


@login_required
def print_kot(request, order_id):
    """
    Generate Kitchen Order Ticket (KOT) for kitchen staff
    
    KOT is printed when:
    - Order is placed by customer or customer care
    - Kitchen staff needs to reprint order details
    - Order is confirmed and needs kitchen preparation
    
    Accessible by: Kitchen staff, Customer care, Cashier, Owner, Administrator
    """
    # Get the order
    order = get_object_or_404(Order, id=order_id)
    
    # Permission check - only staff can print KOT
    if not (request.user.is_kitchen_staff() or 
            request.user.is_customer_care() or 
            request.user.is_cashier() or
            request.user.is_owner() or 
            request.user.is_administrator()):
        messages.error(request, 'Access denied. Staff privileges required to print KOT.')
        return redirect('orders:my_orders')
    
    # Check owner permission (ensure user can access this restaurant's order)
    try:
        if not request.user.is_administrator():
            owner_filter = get_owner_filter(request.user)
            if owner_filter and order.table_info.owner != owner_filter:
                messages.error(request, 'Access denied. This order belongs to a different restaurant.')
                return redirect('orders:kitchen_dashboard')
    except Exception:
        messages.error(request, 'Permission error. Please contact administrator.')
        return redirect('orders:kitchen_dashboard')
    
    # Get restaurant name - use main restaurant name for branch staff
    owner = order.table_info.owner
    if owner.role.name == 'branch_owner':
        from restaurant.models import Restaurant
        branch_restaurant = Restaurant.objects.filter(
            branch_owner=owner, 
            is_main_restaurant=False
        ).first()
        if branch_restaurant and branch_restaurant.parent_restaurant:
            restaurant_name = branch_restaurant.parent_restaurant.name
        else:
            restaurant_name = owner.restaurant_name
    else:
        restaurant_name = owner.restaurant_name
    
    # Context for KOT template
    context = {
        'order': order,
        'now': timezone.now(),
        'restaurant_name': restaurant_name,
    }
    
    return render(request, 'orders/kot.html', context)


@login_required  
def reprint_kot(request, order_id):
    """
    Reprint Kitchen Order Ticket for existing order
    Same as print_kot but with a different message for tracking
    """
    # Permission check
    if not (request.user.is_kitchen_staff() or 
            request.user.is_customer_care() or 
            request.user.is_cashier() or
            request.user.is_owner() or 
            request.user.is_administrator()):
        messages.error(request, 'Access denied. Staff privileges required.')
        return redirect('orders:my_orders')
    
    # Get order with owner filtering to prevent cross-restaurant access
    if request.user.is_administrator():
        order = get_object_or_404(Order, id=order_id)
    else:
        owner_filter = get_owner_filter(request.user)
        if owner_filter:
            order = get_object_or_404(Order, id=order_id, table_info__owner=owner_filter)
        else:
            order = get_object_or_404(Order, id=order_id)
    
    # Get restaurant name - use main restaurant name for branch staff
    owner = order.table_info.owner
    if owner.role.name == 'branch_owner':
        from restaurant.models import Restaurant
        branch_restaurant = Restaurant.objects.filter(
            branch_owner=owner, 
            is_main_restaurant=False
        ).first()
        if branch_restaurant and branch_restaurant.parent_restaurant:
            restaurant_name = branch_restaurant.parent_restaurant.name
        else:
            restaurant_name = owner.restaurant_name
    else:
        restaurant_name = owner.restaurant_name
    
    # Add reprint message
    messages.info(request, f'Reprinting KOT for Order #{order.order_number}')
    
    context = {
        'order': order,
        'now': timezone.now(),
        'is_reprint': True,
        'restaurant_name': restaurant_name,
    }
    
    return render(request, 'orders/kot.html', context)


@login_required
def print_bot(request, order_id):
    """
    Generate Bar Order Ticket (BOT) for bar staff
    
    BOT is printed when:
    - Order contains bar items
    - Bar staff needs to prepare drinks
    - Order is confirmed and needs bar preparation
    
    Accessible by: Bar staff, Customer care, Cashier, Owner, Administrator
    """
    # Get the order
    order = get_object_or_404(Order, id=order_id)
    
    # Permission check - only staff can print BOT
    if not (hasattr(request.user, 'role') and request.user.role and request.user.role.name == 'bar') and not (
            request.user.is_customer_care() or 
            request.user.is_cashier() or
            request.user.is_owner() or 
            request.user.is_administrator()):
        messages.error(request, 'Access denied. Staff privileges required to print BOT.')
        return redirect('orders:my_orders')
    
    # Check owner permission (ensure user can access this restaurant's order)
    try:
        if not request.user.is_administrator():
            owner_filter = get_owner_filter(request.user)
            if owner_filter and order.table_info.owner != owner_filter:
                messages.error(request, 'Access denied. This order belongs to a different restaurant.')
                return redirect('orders:bar_dashboard')
    except Exception:
        messages.error(request, 'Permission error. Please contact administrator.')
        return redirect('orders:bar_dashboard')
    
    # Get restaurant name - use main restaurant name for branch staff
    owner = order.table_info.owner
    if owner.role.name == 'branch_owner':
        from restaurant.models import Restaurant
        branch_restaurant = Restaurant.objects.filter(
            branch_owner=owner, 
            is_main_restaurant=False
        ).first()
        if branch_restaurant and branch_restaurant.parent_restaurant:
            restaurant_name = branch_restaurant.parent_restaurant.name
        else:
            restaurant_name = owner.restaurant_name
    else:
        restaurant_name = owner.restaurant_name
    
    # Context for BOT template
    context = {
        'order': order,
        'now': timezone.now(),
        'restaurant_name': restaurant_name,
    }
    
    return render(request, 'orders/bot.html', context)


@login_required  
def reprint_bot(request, order_id):
    """
    Reprint Bar Order Ticket for existing order
    Same as print_bot but with a different message for tracking
    """
    # Permission check
    if not (hasattr(request.user, 'role') and request.user.role and request.user.role.name == 'bar') and not (
            request.user.is_customer_care() or 
            request.user.is_cashier() or
            request.user.is_owner() or 
            request.user.is_administrator()):
        messages.error(request, 'Access denied. Staff privileges required.')
        return redirect('orders:my_orders')
    
    # Get order with owner filtering to prevent cross-restaurant access
    if request.user.is_administrator():
        order = get_object_or_404(Order, id=order_id)
    else:
        owner_filter = get_owner_filter(request.user)
        if owner_filter:
            order = get_object_or_404(Order, id=order_id, table_info__owner=owner_filter)
        else:
            order = get_object_or_404(Order, id=order_id)
    
    # Get restaurant name - use main restaurant name for branch staff
    owner = order.table_info.owner
    if owner.role.name == 'branch_owner':
        from restaurant.models import Restaurant
        branch_restaurant = Restaurant.objects.filter(
            branch_owner=owner, 
            is_main_restaurant=False
        ).first()
        if branch_restaurant and branch_restaurant.parent_restaurant:
            restaurant_name = branch_restaurant.parent_restaurant.name
        else:
            restaurant_name = owner.restaurant_name
    else:
        restaurant_name = owner.restaurant_name
    
    # Add reprint message
    messages.info(request, f'Reprinting BOT for Order #{order.order_number}')
    
    context = {
        'order': order,
        'now': timezone.now(),
        'is_reprint': True,
        'restaurant_name': restaurant_name,
    }
    
    return render(request, 'orders/bot.html', context)


@login_required
def print_buffet(request, order_id):
    """
    Generate Buffet Order Ticket (BUFFET) for buffet staff
    
    BUFFET is printed when:
    - Order contains buffet items
    - Buffet staff needs to prepare food
    - Order is confirmed and needs buffet preparation
    
    Accessible by: Buffet staff, Customer care, Cashier, Owner, Administrator
    """
    # Get the order
    order = get_object_or_404(Order, id=order_id)
    
    # Permission check - only staff can print BUFFET
    if not (hasattr(request.user, 'role') and request.user.role and request.user.role.name == 'buffet') and not (
            request.user.is_customer_care() or 
            request.user.is_cashier() or
            request.user.is_owner() or 
            request.user.is_administrator()):
        messages.error(request, 'Access denied. Staff privileges required to print BUFFET.')
        return redirect('orders:my_orders')
    
    # Check owner permission (ensure user can access this restaurant's order)
    try:
        if not request.user.is_administrator():
            owner_filter = get_owner_filter(request.user)
            if owner_filter and order.table_info.owner != owner_filter:
                messages.error(request, 'Access denied. This order belongs to a different restaurant.')
                return redirect('orders:buffet_dashboard')
    except Exception:
        messages.error(request, 'Permission error. Please contact administrator.')
        return redirect('orders:buffet_dashboard')
    
    # Get restaurant name - use main restaurant name for branch staff
    owner = order.table_info.owner
    if owner.role.name == 'branch_owner':
        from restaurant.models import Restaurant
        branch_restaurant = Restaurant.objects.filter(
            branch_owner=owner, 
            is_main_restaurant=False
        ).first()
        if branch_restaurant and branch_restaurant.parent_restaurant:
            restaurant_name = branch_restaurant.parent_restaurant.name
        else:
            restaurant_name = owner.restaurant_name
    else:
        restaurant_name = owner.restaurant_name
    
    # Context for BUFFET template
    context = {
        'order': order,
        'now': timezone.now(),
        'restaurant_name': restaurant_name,
    }
    
    return render(request, 'orders/buffet.html', context)


@login_required  
def reprint_buffet(request, order_id):
    """
    Reprint Buffet Order Ticket for existing order
    Same as print_buffet but with a different message for tracking
    """
    # Permission check
    if not (hasattr(request.user, 'role') and request.user.role and request.user.role.name == 'buffet') and not (
            request.user.is_customer_care() or 
            request.user.is_cashier() or
            request.user.is_owner() or 
            request.user.is_administrator()):
        messages.error(request, 'Access denied. Staff privileges required.')
        return redirect('orders:my_orders')
    
    # Get order with owner filtering to prevent cross-restaurant access
    if request.user.is_administrator():
        order = get_object_or_404(Order, id=order_id)
    else:
        owner_filter = get_owner_filter(request.user)
        if owner_filter:
            order = get_object_or_404(Order, id=order_id, table_info__owner=owner_filter)
        else:
            order = get_object_or_404(Order, id=order_id)
    
    # Get restaurant name - use main restaurant name for branch staff
    owner = order.table_info.owner
    if owner.role.name == 'branch_owner':
        from restaurant.models import Restaurant
        branch_restaurant = Restaurant.objects.filter(
            branch_owner=owner, 
            is_main_restaurant=False
        ).first()
        if branch_restaurant and branch_restaurant.parent_restaurant:
            restaurant_name = branch_restaurant.parent_restaurant.name
        else:
            restaurant_name = owner.restaurant_name
    else:
        restaurant_name = owner.restaurant_name
    
    # Add reprint message
    messages.info(request, f'Reprinting BUFFET for Order #{order.order_number}')
    
    context = {
        'order': order,
        'now': timezone.now(),
        'is_reprint': True,
        'restaurant_name': restaurant_name,
    }
    
    return render(request, 'orders/buffet.html', context)


@login_required
def print_service(request, order_id):
    """
    Generate Service Order Ticket (SERVICE) for service staff
    
    SERVICE is printed when:
    - Order contains service items
    - Service staff needs to prepare items
    - Order is confirmed and needs service preparation
    
    Accessible by: Service staff, Customer care, Cashier, Owner, Administrator
    """
    # Get the order
    order = get_object_or_404(Order, id=order_id)
    
    # Permission check - only staff can print SERVICE
    if not (hasattr(request.user, 'role') and request.user.role and request.user.role.name == 'service') and not (
            request.user.is_customer_care() or 
            request.user.is_cashier() or
            request.user.is_owner() or 
            request.user.is_administrator()):
        messages.error(request, 'Access denied. Staff privileges required to print SERVICE.')
        return redirect('orders:my_orders')
    
    # Check owner permission (ensure user can access this restaurant's order)
    try:
        if not request.user.is_administrator():
            owner_filter = get_owner_filter(request.user)
            if owner_filter and order.table_info.owner != owner_filter:
                messages.error(request, 'Access denied. This order belongs to a different restaurant.')
                return redirect('orders:service_dashboard')
    except Exception:
        messages.error(request, 'Permission error. Please contact administrator.')
        return redirect('orders:service_dashboard')
    
    # Get restaurant name - use main restaurant name for branch staff
    owner = order.table_info.owner
    if owner.role.name == 'branch_owner':
        from restaurant.models import Restaurant
        branch_restaurant = Restaurant.objects.filter(
            branch_owner=owner, 
            is_main_restaurant=False
        ).first()
        if branch_restaurant and branch_restaurant.parent_restaurant:
            restaurant_name = branch_restaurant.parent_restaurant.name
        else:
            restaurant_name = owner.restaurant_name
    else:
        restaurant_name = owner.restaurant_name
    
    # Context for SERVICE template
    context = {
        'order': order,
        'now': timezone.now(),
        'restaurant_name': restaurant_name,
    }
    
    return render(request, 'orders/service.html', context)


@login_required  
def reprint_service(request, order_id):
    """
    Reprint Service Order Ticket for existing order
    Same as print_service but with a different message for tracking
    """
    # Permission check
    if not (hasattr(request.user, 'role') and request.user.role and request.user.role.name == 'service') and not (
            request.user.is_customer_care() or 
            request.user.is_cashier() or
            request.user.is_owner() or 
            request.user.is_administrator()):
        messages.error(request, 'Access denied. Staff privileges required.')
        return redirect('orders:my_orders')
    
    # Get order with owner filtering to prevent cross-restaurant access
    if request.user.is_administrator():
        order = get_object_or_404(Order, id=order_id)
    else:
        owner_filter = get_owner_filter(request.user)
        if owner_filter:
            order = get_object_or_404(Order, id=order_id, table_info__owner=owner_filter)
        else:
            order = get_object_or_404(Order, id=order_id)
    
    # Get restaurant name - use main restaurant name for branch staff
    owner = order.table_info.owner
    if owner.role.name == 'branch_owner':
        from restaurant.models import Restaurant
        branch_restaurant = Restaurant.objects.filter(
            branch_owner=owner, 
            is_main_restaurant=False
        ).first()
        if branch_restaurant and branch_restaurant.parent_restaurant:
            restaurant_name = branch_restaurant.parent_restaurant.name
        else:
            restaurant_name = owner.restaurant_name
    else:
        restaurant_name = owner.restaurant_name
    
    # Add reprint message
    messages.info(request, f'Reprinting SERVICE for Order #{order.order_number}')
    
    context = {
        'order': order,
        'now': timezone.now(),
        'is_reprint': True,
        'restaurant_name': restaurant_name,
    }
    
    return render(request, 'orders/service.html', context)



@login_required
@login_required
def request_bill(request, table_id):
    """Customer requests bill for their table"""
    if not request.user.is_customer():
        messages.error(request, 'Access denied. Customer privileges required.')
        return redirect('orders:my_orders')
    
    try:
        table = TableInfo.objects.get(id=table_id)
        
        # Get restaurant context from QR code session (not user ownership)
        selected_restaurant_id = request.session.get('selected_restaurant_id')
        
        if not selected_restaurant_id:
            messages.error(request, 'Restaurant context not found. Please scan QR code again.')
            return redirect('orders:my_orders')
        
        # Verify the table belongs to the restaurant from QR code session
        try:
            # Support all owner types: owner, main_owner, branch_owner
            current_restaurant = User.objects.get(
                id=selected_restaurant_id,
                role__name__in=['owner', 'main_owner', 'branch_owner']
            )
        except User.DoesNotExist:
            messages.error(request, 'Invalid restaurant context. Please scan QR code again.')
            return redirect('orders:my_orders')
        
        if table.owner != current_restaurant:
            messages.error(request, 'You can only request bill for tables in the current restaurant.')
            return redirect('orders:my_orders')
        
        # Check if there's already a pending bill request for this table
        existing_request = BillRequest.objects.filter(
            table_info=table,
            status='pending'
        ).first()
        
        if existing_request:
            messages.warning(request, f'Bill request already submitted for Table {table.tbl_no}. Staff will bring your bill shortly.')
        else:
            # Create new bill request
            bill_request = BillRequest.objects.create(
                table_info=table,
                requested_by=request.user,
                status='pending'
            )
            messages.success(request, f'Bill requested for Table {table.tbl_no}! Staff will bring your bill shortly.')
        
    except TableInfo.DoesNotExist:
        messages.error(request, 'Table not found.')
    except Exception as e:
        messages.error(request, f'An error occurred: {e}')
    
    return redirect('orders:my_orders')


@login_required
def mark_bill_request_completed(request, request_id):
    """Staff marks bill request as completed"""
    if not (request.user.is_customer_care() or request.user.is_owner() or 
            request.user.is_main_owner() or request.user.is_branch_owner() or request.user.is_cashier()):
        messages.error(request, 'Access denied. Staff privileges required.')
        return redirect('orders:my_orders')
    
    try:
        bill_request = BillRequest.objects.get(id=request_id)
        
        # Check ownership
        if request.user.get_owner() != bill_request.owner:
            messages.error(request, 'Access denied.')
            return redirect('orders:customer_care_dashboard')
        
        # Mark as completed
        bill_request.status = 'completed'
        bill_request.completed_by = request.user
        bill_request.completed_at = timezone.now()
        bill_request.save()
        
        messages.success(request, f'Bill request for Table {bill_request.table_info.tbl_no} marked as completed.')
        
    except BillRequest.DoesNotExist:
        messages.error(request, 'Bill request not found.')
    
    return redirect('orders:customer_care_dashboard')


# ============================================================================
# MULTI-CUSTOMER OCCUPIED TABLE ORDERING
# ============================================================================

@require_restaurant_context
@require_table_selection
def choose_order_action(request):
    """
    Let customer choose action when table is occupied:
    - Add to existing order (if they have one)
    - Create new order (always available)
    Works for all plans: SINGLE, PRO main, PRO branches
    """
    # Get table from session
    table_number = request.session.get('selected_table')
    table_id = request.session.get('selected_table_id')
    restaurant = validate_session_restaurant_id(request.session)
    
    if not table_number or not table_id:
        messages.error(request, 'Table selection lost. Please select a table again.')
        return redirect('orders:select_table')
    
    try:
        # Get table - works with both owner and restaurant fields (all plans)
        if restaurant:
            # Filter by owner (legacy) OR restaurant (new hierarchical)
            table = TableInfo.objects.filter(
                Q(id=table_id, owner=restaurant) |
                Q(id=table_id, restaurant__main_owner=restaurant) |
                Q(id=table_id, restaurant__branch_owner=restaurant)
            ).first()
        else:
            owner_filter = get_owner_filter(request.user)
            table = TableInfo.objects.filter(
                Q(id=table_id, owner=owner_filter) |
                Q(id=table_id, restaurant__main_owner=owner_filter) |
                Q(id=table_id, restaurant__branch_owner=owner_filter)
            ).first()
        
        if not table:
            messages.error(request, 'Table not found.')
            return redirect('orders:select_table')
        
        # Get all active orders at this table
        active_orders = table.get_active_orders()
        
        # Get current customer's active orders at this table
        customer_orders = active_orders.filter(ordered_by=request.user)
        
        # Get other customers' orders at this table
        other_orders_count = active_orders.exclude(ordered_by=request.user).count()
        
        if request.method == 'POST':
            action = request.POST.get('action')
            
            if action == 'new':
                # Create new order - clear any existing cart and go to menu
                request.session['cart'] = {}
                request.session['order_mode'] = 'new'
                messages.info(request, f'Creating new order at Table {table.tbl_no}')
                return redirect('restaurant:menu')
            
            elif action == 'add':
                # Add to existing order - redirect to order selection
                return redirect('orders:add_to_existing_order')
        
        context = {
            'table': table,
            'customer_orders': customer_orders,
            'other_orders_count': other_orders_count,
            'total_orders': active_orders.count(),
            'has_customer_orders': customer_orders.exists(),
            'restaurant_name': request.session.get('selected_restaurant_name', 'Restaurant')
        }
        
        return render(request, 'orders/choose_order_action.html', context)
        
    except Exception as e:
        logger.error(f"Error in choose_order_action: {e}")
        messages.error(request, 'An error occurred. Please try again.')
        return redirect('orders:select_table')


@require_restaurant_context
@require_table_selection
@require_restaurant_context
@require_table_selection
def add_to_existing_order(request):
    """
    Show order selection page for adding items to existing order
    Only handles GET - selection of which order to add to
    POST is handled by place_order
    """
    # Get table from session
    table_number = request.session.get('selected_table')
    table_id = request.session.get('selected_table_id')
    restaurant = validate_session_restaurant_id(request.session)
    
    if not table_number or not table_id:
        messages.error(request, 'Table selection lost. Please select a table again.')
        return redirect('orders:select_table')
    
    # Only handle GET - show order selection
    try:
        # Get table
        if restaurant:
            table = TableInfo.objects.filter(
                Q(id=table_id, owner=restaurant) |
                Q(id=table_id, restaurant__main_owner=restaurant) |
                Q(id=table_id, restaurant__branch_owner=restaurant)
            ).first()
        else:
            owner_filter = get_owner_filter(request.user)
            table = TableInfo.objects.filter(
                Q(id=table_id, owner=owner_filter) |
                Q(id=table_id, restaurant__main_owner=owner_filter) |
                Q(id=table_id, restaurant__branch_owner=owner_filter)
            ).first()
        
        if not table:
            messages.error(request, 'Table not found.')
            return redirect('orders:select_table')
        
        # Get customer's active orders at this table
        customer_orders = Order.objects.filter(
            ordered_by=request.user,
            table_info=table,
            status__in=['pending', 'confirmed', 'preparing', 'ready', 'served'],
            payment_status__in=['unpaid', 'partial']
        ).order_by('-created_at')
        
        if not customer_orders.exists():
            messages.error(request, 'You have no active orders at this table.')
            return redirect('orders:choose_order_action')
        
        # Handle POST - order selection
        if request.method == 'POST':
            order_id = request.POST.get('order_id')
            if not order_id:
                messages.error(request, 'Please select an order.')
                return redirect('orders:add_to_existing_order')
            
            # Store order ID for adding items
            request.session['add_to_order_id'] = order_id
            request.session['order_mode'] = 'add'
            messages.info(request, 'Select items to add to your order.')
            return redirect('restaurant:menu')
        
        # GET - show order selection
        context = {
            'table': table,
            'customer_orders': customer_orders,
            'restaurant': restaurant,
            'restaurant_name': request.session.get('selected_restaurant_name', 'Restaurant')
        }
        return render(request, 'orders/select_order_to_add.html', context)
        
    except Exception as e:
        logger.error(f"Error showing order selection: {str(e)}")
        messages.error(request, 'Error loading orders.')
        return redirect('orders:choose_order_action')


def handle_add_to_existing_order(request, order_id, cart):
    """
    Helper function to add cart items to an existing order
    Called from place_order when add_to_order_id is set
    Works for all plans: SINGLE, PRO main, PRO branches
    """
    new_items = []  # Store new items for printing after transaction
    order_number = None
    
    try:
        with transaction.atomic():
            # Get the order
            order = Order.objects.select_for_update().get(
                id=order_id,
                ordered_by=request.user,
                status__in=['pending', 'confirmed', 'preparing', 'ready', 'served'],
                payment_status__in=['unpaid', 'partial']
            )
            
            order_number = order.order_number  # Store for later use
            
            # Verify order belongs to correct restaurant (all plans)
            restaurant = validate_session_restaurant_id(request.session)
            table_owner = order.table_info.get_owner()
            
            if restaurant and table_owner.id != restaurant.id:
                messages.error(request, 'Order does not belong to this restaurant.')
                return redirect('orders:select_table')
            
            # Add new items to order
            total_added = Decimal('0.00')
            for product_id, item in cart.items():
                product = Product.objects.filter(
                    id=product_id,
                    main_category__owner=restaurant
                ).first()
                
                if not product:
                    raise Exception(f'Product not available')
                
                # Check stock
                if product.available_in_stock < item['quantity']:
                    raise Exception(f'Insufficient stock for {product.name}')
                
                # Create new order item
                order_item = OrderItem.objects.create(
                    order=order,
                    product=product,
                    quantity=item['quantity'],
                    unit_price=product.price
                )
                
                new_items.append(order_item)
                
                # Update stock
                product.available_in_stock -= item['quantity']
                product.save()
                
                total_added += Decimal(item['price']) * item['quantity']
            
            # Update order total
            order.total_amount += total_added
            order.save()
            
            # Log the action
            log_security_event(
                event_type='items_added_to_order',
                user=request.user,
                description=f"Added {len(cart)} items to Order {order.order_number}",
                ip_address=get_client_ip(request),
                extra_data={
                    'order_id': order.id,
                    'order_number': order.order_number,
                    'items_added': len(cart),
                    'amount_added': str(total_added)
                }
            )
            
            # Send real-time notifications (non-critical, wrapped in try-except)
            try:
                restaurant_id = restaurant.id
                async_to_sync(channel_layer.group_send)(
                    f'restaurant_{restaurant_id}',
                    {
                        'type': 'order_updated',
                        'order_id': str(order.id),
                        'order_number': order.order_number,
                        'message': f'Items added to Order #{order.order_number}',
                        'timestamp': timezone.now().isoformat()
                    }
                )
            except Exception as ws_error:
                logger.warning(f"WebSocket notification failed (non-critical): {ws_error}")
        
        # Transaction committed successfully - now safe to show success message and print
        
        # Clear cart and add_to_order mode
        if 'cart' in request.session:
            del request.session['cart']
        if 'add_to_order_id' in request.session:
            del request.session['add_to_order_id']
        if 'order_mode' in request.session:
            del request.session['order_mode']
        request.session.modified = True
        
        # Auto-print ONLY the newly added items (not the whole order)
        try:
            logger.info(f"Auto-printing {len(new_items)} new items for Order #{order_number}")
            # Re-fetch the order outside the transaction lock
            order = Order.objects.get(order_number=order_number)
            print_result = auto_print_new_items(order, new_items)
            if print_result.get('kot_printed'):
                messages.success(request, '🖨️ Additional KOT printed!')
            if print_result.get('bot_printed'):
                messages.success(request, '🖨️ Additional BOT printed!')
            if print_result.get('buffet_printed'):
                messages.success(request, '🖨️ Additional BUFFET ticket printed!')
            if print_result.get('service_printed'):
                messages.success(request, '🖨️ Additional SERVICE ticket printed!')
        except Exception as e:
            # Don't fail the whole operation if printing fails
            logger.warning(f"Auto-print of new items failed (non-critical): {e}")
        
        # Show success message AFTER transaction commits
        messages.success(request, f'✅ Added {len(new_items)} items to Order #{order_number}!')
        return redirect('orders:select_table')
            
    except Order.DoesNotExist:
        messages.error(request, 'Order not found or already completed.')
        # Clear the invalid order ID
        if 'add_to_order_id' in request.session:
            del request.session['add_to_order_id']
        if 'order_mode' in request.session:
            del request.session['order_mode']
        request.session.modified = True
        return redirect('orders:select_table')
    except Exception as e:
        logger.error(f'Error adding items to order: {str(e)}')
        messages.error(request, f'Error adding items: {str(e)}')
        return redirect('orders:view_cart')


@login_required
def customer_care_reports(request):
    """Customer Care Reports - showing only their own orders and sales"""
    if not request.user.is_customer_care():
        messages.error(request, "Access denied. Customer Care role required.")
        return redirect('accounts:profile')
    
    from django.utils import timezone
    from django.db.models import Sum, Count, Q
    from datetime import datetime, timedelta
    
    owner = get_owner_filter(request.user)
    
    # Get filter parameters
    period = request.GET.get('period', 'today')
    payment_status = request.GET.get('payment_status', 'all')
    category_id = request.GET.get('category_id', 'all')
    subcategory_id = request.GET.get('subcategory_id', 'all')
    station_filter = request.GET.get('station_filter', 'all')
    from_date = request.GET.get('from_date')
    to_date = request.GET.get('to_date')
    
    # Base queryset - customer care sees only their own orders
    orders = Order.objects.filter(
        table_info__owner=owner,
        ordered_by=request.user
    )
    
    # Apply period filter
    today = timezone.now().date()
    if period == 'today':
        orders = orders.filter(created_at__date=today)
    elif period == 'weekly':
        week_start = today - timedelta(days=today.weekday())
        orders = orders.filter(created_at__date__gte=week_start)
    elif period == 'monthly':
        month_start = today.replace(day=1)
        orders = orders.filter(created_at__date__gte=month_start)
    elif period == 'yearly':
        year_start = today.replace(month=1, day=1)
        orders = orders.filter(created_at__date__gte=year_start)
    
    # Apply custom date range if provided
    if from_date:
        try:
            from_date_obj = datetime.strptime(from_date, '%Y-%m-%d').date()
            orders = orders.filter(created_at__date__gte=from_date_obj)
        except ValueError:
            pass
    
    if to_date:
        try:
            to_date_obj = datetime.strptime(to_date, '%Y-%m-%d').date()
            orders = orders.filter(created_at__date__lte=to_date_obj)
        except ValueError:
            pass
    
    # Apply payment status filter (before related filters)
    if payment_status == 'paid':
        orders = orders.filter(payment_status='paid')
    elif payment_status == 'unpaid':
        orders = orders.filter(payment_status='unpaid')
    elif payment_status == 'partial':
        orders = orders.filter(payment_status='partial')
    
    # Store order IDs before applying related filters to avoid duplicates
    order_ids = list(orders.values_list('id', flat=True))
    
    # Apply category filter
    if category_id != 'all':
        filtered_order_ids = OrderItem.objects.filter(
            order_id__in=order_ids,
            product__main_category_id=category_id
        ).values_list('order_id', flat=True).distinct()
        order_ids = list(filtered_order_ids)
    
    # Apply subcategory filter
    if subcategory_id != 'all':
        filtered_order_ids = OrderItem.objects.filter(
            order_id__in=order_ids,
            product__sub_category_id=subcategory_id
        ).values_list('order_id', flat=True).distinct()
        order_ids = list(filtered_order_ids)
    
    # Apply station filter
    if station_filter != 'all':
        filtered_order_ids = OrderItem.objects.filter(
            order_id__in=order_ids,
            product__station=station_filter
        ).values_list('order_id', flat=True).distinct()
        order_ids = list(filtered_order_ids)
    
    # Get final filtered orders
    orders = Order.objects.filter(id__in=order_ids).select_related('table_info').prefetch_related(
        'order_items__product__main_category',
        'order_items__product__sub_category',
        'payments'
    ).order_by('-created_at')
    
    # Calculate statistics
    total_revenue = orders.aggregate(total=Sum('total_amount'))['total'] or 0
    total_orders = orders.count()
    total_items = orders.aggregate(total=Sum('order_items__quantity'))['total'] or 0
    avg_order_value = total_revenue / total_orders if total_orders > 0 else 0
    
    # Get currency symbol from owner's profile (customer care inherits from owner)
    currency_symbol = request.user.get_currency_symbol()
    
    # Payment status breakdown
    paid_orders = orders.filter(payment_status='paid').count()
    unpaid_orders = orders.filter(payment_status='unpaid').count()
    partial_orders = orders.filter(payment_status='partial').count()
    
    # Get categories and subcategories for dropdown
    from restaurant.models import MainCategory, SubCategory
    categories = MainCategory.objects.filter(owner=owner).order_by('name')
    subcategories = SubCategory.objects.filter(main_category__owner=owner).order_by('name')
    
    # Handle export requests
    export_format = request.GET.get('export')
    
    if export_format == 'csv':
        import csv
        from django.http import HttpResponse
        
        # Get currency symbol
        currency_symbol = request.user.get_currency_symbol()
        
        response = HttpResponse(content_type='text/csv')
        response['Content-Disposition'] = f'attachment; filename="customer_care_report_{timezone.now().strftime("%Y%m%d_%H%M%S")}.csv"'
        
        writer = csv.writer(response)
        writer.writerow(['Order #', 'Date', 'Time', 'Table', 'Items', 'Category', 'Sub Category', 'Station', 'Total Amount', 'Payment Status', 'Customer Care'])
        
        for order in orders:
            items_list = []
            categories_list = []
            subcategories_list = []
            stations_list = []
            
            for item in order.order_items.all():
                items_list.append(f"{item.product.name} x{item.quantity}")
                categories_list.append(item.product.main_category.name if item.product.main_category else '-')
                subcategories_list.append(item.product.sub_category.name if item.product.sub_category else '-')
                stations_list.append(item.product.station.upper() if item.product.station else '-')
            
            writer.writerow([
                order.order_number,
                order.created_at.strftime('%Y-%m-%d'),
                order.created_at.strftime('%H:%M:%S'),
                order.table_info.tbl_no,
                ', '.join(items_list),
                ', '.join(categories_list),
                ', '.join(subcategories_list),
                ', '.join(stations_list),
                f"{currency_symbol}{order.total_amount:.2f}",
                order.payment_status.upper(),
                request.user.get_full_name() or request.user.username
            ])
        
        return response
    
    elif export_format == 'pdf':
        from django.http import HttpResponse
        from reportlab.lib.pagesizes import letter, landscape
        from reportlab.lib import colors
        from reportlab.platypus import SimpleDocTemplate, Table, TableStyle, Paragraph, Spacer
        from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
        from reportlab.lib.units import inch
        from io import BytesIO
        
        # Get currency symbol
        currency_symbol = request.user.get_currency_symbol()
        
        buffer = BytesIO()
        doc = SimpleDocTemplate(buffer, pagesize=landscape(letter), rightMargin=30, leftMargin=30, topMargin=30, bottomMargin=18)
        
        elements = []
        styles = getSampleStyleSheet()
        
        # Title
        title_style = ParagraphStyle(
            'CustomTitle',
            parent=styles['Heading1'],
            fontSize=16,
            textColor=colors.HexColor('#2c5282'),
            spaceAfter=30,
            alignment=1
        )
        elements.append(Paragraph(f"Customer Care Sales Report - {request.user.get_full_name() or request.user.username}", title_style))
        elements.append(Paragraph(f"Generated: {timezone.now().strftime('%B %d, %Y at %H:%M')}", styles['Normal']))
        elements.append(Spacer(1, 0.3*inch))
        
        # Summary statistics
        summary_data = [
            ['Total Revenue', 'Total Orders', 'Items Sold'],
            [f"{currency_symbol}{total_revenue:.2f}", str(total_orders), str(total_items)]
        ]
        summary_table = Table(summary_data, colWidths=[2.5*inch, 2.5*inch, 2.5*inch])
        summary_table.setStyle(TableStyle([
            ('BACKGROUND', (0, 0), (-1, 0), colors.HexColor('#2c5282')),
            ('TEXTCOLOR', (0, 0), (-1, 0), colors.whitesmoke),
            ('ALIGN', (0, 0), (-1, -1), 'CENTER'),
            ('FONTNAME', (0, 0), (-1, 0), 'Helvetica-Bold'),
            ('FONTSIZE', (0, 0), (-1, 0), 12),
            ('BOTTOMPADDING', (0, 0), (-1, 0), 12),
            ('BACKGROUND', (0, 1), (-1, -1), colors.beige),
            ('GRID', (0, 0), (-1, -1), 1, colors.black)
        ]))
        elements.append(summary_table)
        elements.append(Spacer(1, 0.3*inch))
        
        # Orders table
        table_data = [['Order #', 'Date & Time', 'Table', 'Items', 'Total', 'Payment']]
        
        for order in orders:
            items_str = ', '.join([f"{item.product.name} x{item.quantity}" for item in order.order_items.all()[:3]])
            if order.order_items.count() > 3:
                items_str += '...'
            
            table_data.append([
                order.order_number,
                order.created_at.strftime('%m/%d/%y %H:%M'),
                order.table_info.tbl_no,
                Paragraph(items_str, styles['Normal']),
                f"{currency_symbol}{order.total_amount:.2f}",
                order.payment_status.upper()
            ])
        
        order_table = Table(table_data, colWidths=[1.3*inch, 1.5*inch, 0.8*inch, 3*inch, 1.2*inch, 1.2*inch])
        order_table.setStyle(TableStyle([
            ('BACKGROUND', (0, 0), (-1, 0), colors.HexColor('#2c5282')),
            ('TEXTCOLOR', (0, 0), (-1, 0), colors.whitesmoke),
            ('ALIGN', (0, 0), (-1, -1), 'CENTER'),
            ('FONTNAME', (0, 0), (-1, 0), 'Helvetica-Bold'),
            ('FONTSIZE', (0, 0), (-1, 0), 10),
            ('BOTTOMPADDING', (0, 0), (-1, 0), 12),
            ('BACKGROUND', (0, 1), (-1, -1), colors.white),
            ('GRID', (0, 0), (-1, -1), 1, colors.grey),
            ('FONTSIZE', (0, 1), (-1, -1), 8),
            ('VALIGN', (0, 0), (-1, -1), 'MIDDLE'),
        ]))
        elements.append(order_table)
        
        doc.build(elements)
        
        pdf = buffer.getvalue()
        buffer.close()
        
        response = HttpResponse(content_type='application/pdf')
        response['Content-Disposition'] = f'attachment; filename="customer_care_report_{timezone.now().strftime("%Y%m%d_%H%M%S")}.pdf"'
        response.write(pdf)
        
        return response
    
    context = {
        'orders': orders,
        'period': period,
        'payment_status': payment_status,
        'category_id': category_id,
        'subcategory_id': subcategory_id,
        'station_filter': station_filter,
        'from_date': from_date,
        'to_date': to_date,
        'total_revenue': total_revenue,
        'total_orders': total_orders,
        'total_items': total_items,
        'avg_order_value': avg_order_value,
        'paid_orders': paid_orders,
        'unpaid_orders': unpaid_orders,
        'partial_orders': partial_orders,
        'categories': categories,
        'subcategories': subcategories,
        'user': request.user,
        'currency_symbol': currency_symbol,
    }
    
    return render(request, 'orders/customer_care_reports.html', context)


@login_required
def cancel_order_item(request, item_id):
    """Cancel individual item from an order - works for all plans"""
    if request.method != 'POST':
        return JsonResponse({'error': 'Invalid request method'}, status=405)
    
    # Check permissions - customer care, cashier, or owners can cancel items
    if not (request.user.is_customer_care() or request.user.is_cashier() or 
            request.user.is_owner() or request.user.is_main_owner() or 
            request.user.is_branch_owner() or request.user.is_kitchen_staff()):
        return JsonResponse({'error': 'Access denied'}, status=403)
    
    try:
        # Get owner filter for multi-tenant support (SINGLE, PRO main, PRO branches)
        owner = get_owner_filter(request.user)
        
        # Get the order item with owner filtering
        item = get_object_or_404(OrderItem, id=item_id, order__table_info__owner=owner)
        order = item.order
        
        # Validations
        if order.status == 'cancelled':
            return JsonResponse({'error': 'Cannot cancel item from a cancelled order'}, status=400)
        
        if order.payment_status == 'paid':
            return JsonResponse({'error': 'Cannot cancel item from a fully paid order'}, status=400)
        
        # Check if this is the last item in the order
        if order.order_items.count() <= 1:
            return JsonResponse({
                'error': 'Cannot cancel the last item. Please cancel the entire order instead.'
            }, status=400)
        
        # Get cancellation reason
        import json
        data = json.loads(request.body) if request.body else {}
        reason = data.get('reason', 'Item cancelled by staff').strip()
        
        # Store item details before deletion
        item_name = item.product.name
        item_quantity = item.quantity
        item_price = item.unit_price
        item_total = item.get_subtotal()
        
        # Restore stock if product stock tracking is enabled
        if item.product:
            from restaurant.models import Product
            product = Product.objects.select_for_update().get(id=item.product.id)
            if hasattr(product, 'stock_quantity') and product.stock_quantity is not None:
                product.stock_quantity += item.quantity
                product.save(update_fields=['stock_quantity'])
                logger.info(f"Restored {item.quantity} units of {product.name} to stock")
        
        # Delete the item (this will trigger OrderItem's save method on Order)
        item.delete()
        
        # Recalculate order total
        order.total_amount = sum(oi.get_subtotal() for oi in order.order_items.all())
        order.save(update_fields=['total_amount'])
        
        # Log the cancellation
        logger.info(
            f"Item cancelled: {item_name} x{item_quantity} (${item_total}) "
            f"from Order #{order.order_number} by {request.user.username}. "
            f"Reason: {reason}"
        )
        
        return JsonResponse({
            'success': True,
            'message': f'Item "{item_name}" cancelled successfully',
            'new_total': float(order.total_amount),
            'remaining_items': order.order_items.count()
        })
        
    except OrderItem.DoesNotExist:
        return JsonResponse({'error': 'Order item not found'}, status=404)
    except Exception as e:
        logger.error(f'Error cancelling order item: {str(e)}', exc_info=True)
        return JsonResponse({'error': f'Error cancelling item: {str(e)}'}, status=500)

