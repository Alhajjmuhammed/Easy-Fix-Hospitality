"""
CRITICAL: Run this test while Django server is running
This will create a new order and trigger the print
"""
import os
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'restaurant_system.settings')
import django
django.setup()

from orders.models import Order, OrderItem
from restaurant.models import TableInfo, Product
from accounts.models import User
from django.db import transaction
import uuid

print("=" * 60)
print("CREATING A TEST ORDER TO TRIGGER PRINTING")
print("=" * 60)

# Find a table owned by tropicana
table = TableInfo.objects.filter(owner__username='tropicana').first()
if not table:
    print("No table found for tropicana!")
    exit(1)

print(f"\nUsing table: {table.tbl_no} (owner: {table.owner})")

# Find a kitchen product
product = Product.objects.filter(station='kitchen').first()
if not product:
    print("No kitchen product found!")
    exit(1)

print(f"Using product: {product.name} (station: {product.station})")

# Find the tropicana user
user = User.objects.get(username='tropicana')

# Create order
with transaction.atomic():
    order = Order.objects.create(
        order_number=f"TEST-{uuid.uuid4().hex[:6].upper()}",
        table_info=table,
        ordered_by=user,
        special_instructions="TEST ORDER - DELETE AFTER",
        status='pending'
    )
    
    OrderItem.objects.create(
        order=order,
        product=product,
        quantity=1,
        unit_price=product.price
    )

print(f"\nCreated Order: {order.order_number}")

# Now trigger auto_print_order
print("\n" + "=" * 60)
print("TRIGGERING AUTO-PRINT...")
print("=" * 60)

from orders.printing import auto_print_order

result = auto_print_order(order)

print("\n" + "=" * 60)
print("RESULT:")
print(f"  KOT Printed: {result['kot_printed']}")
print(f"  BOT Printed: {result['bot_printed']}")
print(f"  Errors: {result['errors']}")
print("=" * 60)

if result['kot_printed']:
    print("\n✅ SUCCESS! The print system is working!")
    print("If you don't see prints when ordering from browser,")
    print("the issue is with the Django server configuration.")
else:
    print("\n❌ FAILED to print. Check the errors above.")
