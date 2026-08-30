from rest_framework import serializers
from django.contrib.auth import get_user_model

from restaurant.models import TableInfo, Product, MainCategory, SubCategory
from restaurant.models_restaurant import Restaurant
from orders.models import Order, OrderItem, BillRequest
from cashier.models import Payment

User = get_user_model()


# ---------------------------------------------------------------------------
# Auth
# ---------------------------------------------------------------------------

class UserSerializer(serializers.ModelSerializer):
    role_name = serializers.SerializerMethodField()
    restaurant_name = serializers.SerializerMethodField()
    restaurant_logo_url = serializers.SerializerMethodField()
    currency_code = serializers.SerializerMethodField()
    currency_symbol = serializers.SerializerMethodField()
    tax_rate = serializers.SerializerMethodField()

    class Meta:
        model = User
        fields = [
            'id', 'username', 'email', 'first_name', 'last_name',
            'phone_number', 'address', 'date_joined', 'last_login',
            'role_name', 'restaurant_name', 'restaurant_logo_url', 'currency_code', 'currency_symbol', 'tax_rate',
        ]

    def _get_effective_owner(self, obj):
        """
        Resolve the owner for a user.
        For staff/owners, obj.get_owner() works directly.
        For customers without an owner link (registered independently),
        fall back to the restaurant owner indicated by X-Restaurant-ID header.
        """
        owner = obj.get_owner()
        if owner:
            return owner
        try:
            request = self.context.get('request')
            if request:
                rest_id = request.META.get('HTTP_X_RESTAURANT_ID')
                if rest_id:
                    restaurant = Restaurant.objects.select_related(
                        'branch_owner', 'main_owner'
                    ).get(id=int(rest_id))
                    return restaurant.branch_owner or restaurant.main_owner
        except Exception:
            pass
        return None

    def get_role_name(self, obj):
        return obj.role.name if obj.role else None

    def get_restaurant_name(self, obj):
        try:
            owner = self._get_effective_owner(obj)
            return owner.restaurant_name if owner else None
        except Exception:
            return None

    def get_restaurant_logo_url(self, obj):
        try:
            request = self.context.get('request')
            owner = self._get_effective_owner(obj)
            if not owner:
                return None
            restaurant = (
                Restaurant.objects
                .filter(branch_owner=owner)
                .filter(logo__isnull=False)
                .exclude(logo='')
                .first()
            )
            if not restaurant:
                restaurant = (
                    Restaurant.objects
                    .filter(main_owner=owner)
                    .filter(logo__isnull=False)
                    .exclude(logo='')
                    .first()
                )
            if restaurant and restaurant.logo and request:
                return request.build_absolute_uri(restaurant.logo.url)
        except Exception:
            pass
        return None

    def get_currency_code(self, obj):
        try:
            owner = self._get_effective_owner(obj)
            return owner.currency_code if owner else 'USD'
        except Exception:
            return 'USD'

    def get_currency_symbol(self, obj):
        try:
            owner = self._get_effective_owner(obj)
            if not owner:
                return '$'
            from accounts.models import User as _U
            return _U.CURRENCY_SYMBOLS.get(owner.currency_code, '$')
        except Exception:
            return '$'

    def get_tax_rate(self, obj):
        try:
            owner = self._get_effective_owner(obj)
            return float(owner.tax_rate) if owner else 0.0
        except Exception:
            return 0.0


# ---------------------------------------------------------------------------
# Menu
# ---------------------------------------------------------------------------

class ProductSerializer(serializers.ModelSerializer):
    current_price = serializers.SerializerMethodField()
    original_price = serializers.SerializerMethodField()
    has_promotion = serializers.SerializerMethodField()
    category_id = serializers.IntegerField(source='main_category_id', read_only=True)
    category_name = serializers.SerializerMethodField()
    subcategory_id = serializers.SerializerMethodField()
    subcategory_name = serializers.SerializerMethodField()
    image_url = serializers.SerializerMethodField()

    class Meta:
        model = Product
        fields = [
            'id', 'name', 'description', 'price', 'current_price',
            'original_price', 'has_promotion',
            'is_available', 'available_in_stock', 'preparation_time',
            'category_id', 'category_name',
            'subcategory_id', 'subcategory_name',
            'image_url', 'updated_at', 'station',
        ]

    def get_current_price(self, obj):
        try:
            fn = getattr(obj, 'get_current_price', None)
            return float(fn()) if fn else float(obj.price)
        except Exception:
            return float(obj.price)

    def get_original_price(self, obj):
        return float(obj.price)

    def get_has_promotion(self, obj):
        try:
            fn = getattr(obj, 'get_active_promotion', None)
            return fn() is not None if fn else False
        except Exception:
            return False

    def get_category_name(self, obj):
        return obj.main_category.name if obj.main_category else None

    def get_subcategory_id(self, obj):
        return obj.sub_category_id if hasattr(obj, 'sub_category_id') else None

    def get_subcategory_name(self, obj):
        return obj.sub_category.name if obj.sub_category else None

    def get_image_url(self, obj):
        request = self.context.get('request')
        try:
            # Product has no direct image; get_image() returns the category image
            img = obj.image if hasattr(obj, 'image') and obj.image else None
            if img is None:
                fn = getattr(obj, 'get_image', None)
                img = fn() if fn else None
            if img and request:
                return request.build_absolute_uri(img.url)
        except Exception:
            pass
        return None


class SubCategorySerializer(serializers.ModelSerializer):
    products = serializers.SerializerMethodField()

    class Meta:
        model = SubCategory
        fields = ['id', 'name', 'products']

    def get_products(self, obj):
        # only available products; sub_category already known via traversal path
        qs = obj.products.filter(is_available=True)
        return ProductSerializer(qs, many=True, context=self.context).data


class CategorySerializer(serializers.ModelSerializer):
    subcategories = serializers.SerializerMethodField()

    class Meta:
        model = MainCategory
        fields = ['id', 'name', 'subcategories']

    def get_subcategories(self, obj):
        qs = obj.subcategories.filter(is_active=True)
        return SubCategorySerializer(qs, many=True, context=self.context).data


# ---------------------------------------------------------------------------
# Tables
# ---------------------------------------------------------------------------

class TableSerializer(serializers.ModelSerializer):
    display_name = serializers.SerializerMethodField()
    table_number = serializers.CharField(source='tbl_no')
    # Use is_truly_available() — same check as the web's select_table view,
    # which calls table.is_truly_available() (flag AND no active unpaid orders).
    # The raw is_available flag can diverge from reality in edge cases.
    is_available = serializers.SerializerMethodField()

    class Meta:
        model = TableInfo
        fields = ['id', 'tbl_no', 'table_number', 'is_available', 'capacity', 'display_name']

    def get_display_name(self, obj):
        return f"Table {obj.tbl_no}"

    def get_is_available(self, obj):
        return obj.is_truly_available()


# ---------------------------------------------------------------------------
# Orders
# ---------------------------------------------------------------------------

class OrderItemSerializer(serializers.ModelSerializer):
    product_id = serializers.SerializerMethodField()
    product_name = serializers.SerializerMethodField()
    total_price = serializers.SerializerMethodField()
    station = serializers.SerializerMethodField()

    class Meta:
        model = OrderItem
        fields = [
            'id', 'product_id', 'product_name',
            'quantity', 'unit_price', 'total_price',
            'special_notes', 'station',
        ]

    def get_product_id(self, obj):
        return obj.product.id if obj.product else None

    def get_product_name(self, obj):
        return obj.product.name if obj.product else ''

    def get_total_price(self, obj):
        try:
            return float(obj.get_subtotal())
        except Exception:
            return 0.0

    def get_station(self, obj):
        return obj.product.station if obj.product else None


class OrderSerializer(serializers.ModelSerializer):
    table_number = serializers.SerializerMethodField()
    ordered_by_name = serializers.SerializerMethodField()
    ordered_by_id = serializers.SerializerMethodField()
    items = OrderItemSerializer(source='order_items', many=True, read_only=True)
    items_count = serializers.SerializerMethodField()
    subtotal = serializers.SerializerMethodField()
    tax_amount = serializers.SerializerMethodField()
    discount_amount = serializers.SerializerMethodField()
    total = serializers.SerializerMethodField()
    total_paid = serializers.SerializerMethodField()
    balance_due = serializers.SerializerMethodField()
    payments = serializers.SerializerMethodField()
    confirmed_by_name = serializers.SerializerMethodField()
    entered_by_name = serializers.SerializerMethodField()
    pending_bill_requested = serializers.SerializerMethodField()
    pending_bill_requested_at = serializers.SerializerMethodField()
    delivery_lat = serializers.SerializerMethodField()
    delivery_lng = serializers.SerializerMethodField()

    class Meta:
        model = Order
        fields = [
            'id', 'order_number', 'table_info', 'table_number',
            'ordered_by_name', 'ordered_by_id', 'confirmed_by_name', 'entered_by_name', 'status', 'payment_status',
            'order_type', 'delivery_address', 'delivery_phone', 'delivery_lat', 'delivery_lng',
            'total_amount', 'subtotal', 'tax_amount', 'discount_amount', 'total',
            'total_paid', 'balance_due', 'items_count',
            'special_instructions', 'reason_if_cancelled',
            'created_at', 'updated_at',
            'items', 'payments', 'pending_bill_requested', 'pending_bill_requested_at',
        ]

    def get_table_number(self, obj):
        return obj.table_info.tbl_no if obj.table_info else 'N/A'

    def get_delivery_lat(self, obj):
        return float(obj.delivery_lat) if obj.delivery_lat is not None else None

    def get_delivery_lng(self, obj):
        return float(obj.delivery_lng) if obj.delivery_lng is not None else None

    def get_items_count(self, obj):
        return len(obj.order_items.all())

    def get_ordered_by_name(self, obj):
        if not obj.ordered_by:
            return 'Unknown'
        return obj.ordered_by.get_full_name() or obj.ordered_by.username

    def get_ordered_by_id(self, obj):
        return obj.ordered_by.id if obj.ordered_by else None

    def get_subtotal(self, obj):
        try:
            return float(obj.get_subtotal())
        except Exception:
            return float(obj.total_amount)

    def get_tax_amount(self, obj):
        try:
            return float(obj.get_tax_amount())
        except Exception:
            return 0.0

    def get_total(self, obj):
        try:
            return float(obj.get_total())
        except Exception:
            return float(obj.total_amount)

    def get_discount_amount(self, obj):
        try:
            return float(obj.get_total_discount())
        except Exception:
            return 0.0

    def get_confirmed_by_name(self, obj):
        try:
            if obj.confirmed_by:
                return obj.confirmed_by.get_full_name() or obj.confirmed_by.username
            return None
        except Exception:
            return None

    def get_entered_by_name(self, obj):
        try:
            if obj.entered_by:
                return obj.entered_by.get_full_name() or obj.entered_by.username
            return None
        except Exception:
            return None

    def get_pending_bill_requested(self, obj):
        try:
            if obj.table_info:
                return any(br.status == 'pending' for br in obj.table_info.bill_requests.all())
            return False
        except Exception:
            return False

    def get_pending_bill_requested_at(self, obj):
        try:
            if obj.table_info:
                pending = sorted(
                    (br for br in obj.table_info.bill_requests.all() if br.status == 'pending'),
                    key=lambda br: br.created_at,
                )
                if pending:
                    return pending[0].created_at.isoformat()
            return None
        except Exception:
            return None

    def get_total_paid(self, obj):
        try:
            return round(sum(float(p.amount) for p in obj.payments.all() if not p.is_voided), 2)
        except Exception:
            return 0.0

    def get_balance_due(self, obj):
        try:
            total = self.get_total(obj)
            paid = self.get_total_paid(obj)
            return max(0.0, round(total - paid, 2))
        except Exception:
            return 0.0

    def get_payments(self, obj):
        try:
            payments = sorted(
                (p for p in obj.payments.all() if not p.is_voided),
                key=lambda p: p.created_at,
            )
            return [
                {
                    'id': p.id,
                    'amount': float(p.amount),
                    'payment_method': p.payment_method,
                    'processed_by_name': p.processed_by.get_full_name() or p.processed_by.username if p.processed_by else None,
                    'reference_number': p.reference_number or '',
                    'notes': p.notes or '',
                    'created_at': p.created_at.isoformat(),
                }
                for p in payments
            ]
        except Exception:
            return []


    def to_representation(self, instance):
        data = super().to_representation(instance)
        # Strip internal offline sync dedup tags that should never be visible to users.
        import re
        if data.get('special_instructions'):
            cleaned = re.sub(r'\[offline(?:-append)?:[^\]]*\]', '', data['special_instructions']).strip()
            data['special_instructions'] = cleaned or ''
        return data


class PlaceOrderSerializer(serializers.Serializer):
    table_id = serializers.IntegerField(required=False, allow_null=True)
    items = serializers.ListField(child=serializers.DictField(), min_length=1)
    special_instructions = serializers.CharField(allow_blank=True, allow_null=True, required=False, default='', max_length=1000)
    offline_id = serializers.CharField(allow_blank=True, allow_null=True, required=False, default='', max_length=64)
    restaurant_id = serializers.IntegerField(required=False, allow_null=True)
    order_type = serializers.ChoiceField(
        choices=['dine-in', 'delivery', 'pickup'],
        required=False,
        default='dine-in',
        allow_null=True,
    )
    delivery_address = serializers.CharField(allow_blank=True, allow_null=True, required=False, default='', max_length=500)
    delivery_phone = serializers.CharField(allow_blank=True, allow_null=True, required=False, default='', max_length=30)
    delivery_lat = serializers.FloatField(required=False, allow_null=True, default=None)
    delivery_lng = serializers.FloatField(required=False, allow_null=True, default=None)

    def validate_order_type(self, value):
        if value is None:
            return 'dine-in'
        return value

    def validate_special_instructions(self, value):
        return value or ''

    def validate_delivery_address(self, value):
        return value or ''

    def validate_delivery_lat(self, value):
        if value is not None and not (-90 <= value <= 90):
            raise serializers.ValidationError('lat must be between -90 and 90.')
        return value

    def validate_delivery_lng(self, value):
        if value is not None and not (-180 <= value <= 180):
            raise serializers.ValidationError('lng must be between -180 and 180.')
        return value

    def validate_delivery_phone(self, value):
        if value is None:
            return ''
        return value[:30]  # truncate silently if somehow > 30 chars

    def validate_items(self, value):
        for i, item in enumerate(value):
            product_id = item.get('product_id')
            quantity = item.get('quantity', 1)
            if not isinstance(product_id, int) or product_id <= 0:
                raise serializers.ValidationError(
                    f'Item {i+1}: product_id must be a positive integer.'
                )
            if not isinstance(quantity, int) or quantity <= 0 or quantity > 100:
                raise serializers.ValidationError(
                    f'Item {i+1}: quantity must be an integer between 1 and 100.'
                )
        return value


# ---------------------------------------------------------------------------
# Payments
# ---------------------------------------------------------------------------

class PaymentSerializer(serializers.ModelSerializer):
    order_number = serializers.SerializerMethodField()
    processed_by_name = serializers.SerializerMethodField()
    table_number = serializers.SerializerMethodField()

    class Meta:
        model = Payment
        fields = [
            'id', 'order_id', 'order_number', 'amount',
            'payment_method', 'processed_by_name',
            'reference_number', 'notes',
            'is_voided', 'void_reason', 'created_at',
            'table_number',
        ]

    def get_order_number(self, obj):
        return obj.order.order_number if obj.order else ''

    def get_processed_by_name(self, obj):
        if obj.processed_by:
            return obj.processed_by.get_full_name() or obj.processed_by.username
        return ''

    def get_table_number(self, obj):
        if obj.order and obj.order.table_info:
            return obj.order.table_info.tbl_no
        return None


class ProcessPaymentSerializer(serializers.Serializer):
    order_id = serializers.IntegerField()
    amount = serializers.DecimalField(max_digits=10, decimal_places=2, min_value=0.01)
    payment_method = serializers.ChoiceField(choices=['cash', 'card', 'digital', 'voucher'])
    reference_number = serializers.CharField(allow_blank=True, required=False, default='', max_length=100)
    notes = serializers.CharField(allow_blank=True, required=False, default='', max_length=500)
    offline_id = serializers.CharField(allow_blank=True, required=False, default='', max_length=64)


# ---------------------------------------------------------------------------
# Bill Requests
# ---------------------------------------------------------------------------

class BillRequestSerializer(serializers.ModelSerializer):
    table_number = serializers.SerializerMethodField()
    requested_by_name = serializers.SerializerMethodField()

    class Meta:
        model = BillRequest
        fields = [
            'id', 'table_info', 'table_number',
            'requested_by_name', 'status', 'created_at',
        ]

    def get_table_number(self, obj):
        return obj.table_info.tbl_no if obj.table_info else 'N/A'

    def get_requested_by_name(self, obj):
        if obj.requested_by:
            return obj.requested_by.get_full_name() or obj.requested_by.username
        return ''


# ---------------------------------------------------------------------------
# Offline Sync
# ---------------------------------------------------------------------------

class SyncPushSerializer(serializers.Serializer):
    # DictField with no child constraint — each dict can contain mixed types
    # (strings, ints, lists for 'items').  Size limits are enforced at the list
    # level (max_length) and in the view logic.
    orders        = serializers.ListField(child=serializers.DictField(), required=False, default=list, max_length=50)
    payments      = serializers.ListField(child=serializers.DictField(), required=False, default=list, max_length=100)
    bill_requests = serializers.ListField(child=serializers.DictField(), required=False, default=list, max_length=20)
