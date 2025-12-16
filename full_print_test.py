"""COMPLETE simulation of what happens when order is placed from web"""
import os
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'restaurant_system.settings')
import django
django.setup()

print("=" * 60)
print("SIMULATING ORDER PLACEMENT FROM WEB")
print("=" * 60)

# Check Windows printing availability
from orders.printing import WINDOWS_PRINTING_AVAILABLE
print(f"\n1. WINDOWS_PRINTING_AVAILABLE: {WINDOWS_PRINTING_AVAILABLE}")

if not WINDOWS_PRINTING_AVAILABLE:
    print("   ❌ PROBLEM: Windows printing module not loaded!")
    print("   This means win32print is not installed or not working")
    exit(1)

# Check settings
from django.conf import settings
use_queue = getattr(settings, 'USE_PRINT_QUEUE', False)
print(f"\n2. USE_PRINT_QUEUE: {use_queue}")
if use_queue:
    print("   ⚠ Queue mode is ON - printing goes to queue, not direct")

# Get the most recent order
from orders.models import Order
order = Order.objects.select_related(
    'table_info', 
    'table_info__owner', 
    'table_info__restaurant'
).order_by('-created_at').first()

if not order:
    print("\n❌ No orders found!")
    exit(1)

print(f"\n3. Using Order #{order.order_number}")
print(f"   Table: {order.table_info.tbl_no}")
print(f"   Created: {order.created_at}")

# Check order items
from orders.models import OrderItem
items = order.order_items.all()
kitchen_items = [i for i in items if i.product.station == 'kitchen']
bar_items = [i for i in items if i.product.station == 'bar']
print(f"\n4. Order Items:")
print(f"   Kitchen items: {len(kitchen_items)}")
print(f"   Bar items: {len(bar_items)}")

if len(kitchen_items) == 0 and len(bar_items) == 0:
    print("   ❌ PROBLEM: No kitchen or bar items - nothing to print!")
    exit(1)

# Get print settings
from orders.printing import get_restaurant_print_settings
print_settings = get_restaurant_print_settings(order)
print(f"\n5. Print Settings (from {print_settings['source']}: {print_settings['name']}):")
print(f"   auto_print_kot: {print_settings['auto_print_kot']}")
print(f"   auto_print_bot: {print_settings['auto_print_bot']}")
print(f"   kitchen_printer_name: {print_settings['kitchen_printer_name']}")
print(f"   bar_printer_name: {print_settings['bar_printer_name']}")

if not print_settings['auto_print_kot'] and not print_settings['auto_print_bot']:
    print("   ❌ PROBLEM: Auto-print is DISABLED for this restaurant!")
    exit(1)

# Now call auto_print_order EXACTLY as the web view does
print("\n6. Calling auto_print_order(order)...")
print("-" * 60)

from orders.printing import auto_print_order
try:
    print_result = auto_print_order(order)
    print("-" * 60)
    print("\n7. RESULT:")
    print(f"   kot_printed: {print_result['kot_printed']}")
    print(f"   bot_printed: {print_result['bot_printed']}")
    print(f"   errors: {print_result['errors']}")
    
    if print_result['kot_printed'] or print_result['bot_printed']:
        print("\n✅ SUCCESS! Printing worked!")
    else:
        print("\n❌ FAILED! Nothing was printed")
        if print_result['errors']:
            print("   Errors:", print_result['errors'])
            
except Exception as e:
    print("-" * 60)
    print(f"\n❌ EXCEPTION occurred: {e}")
    import traceback
    traceback.print_exc()
