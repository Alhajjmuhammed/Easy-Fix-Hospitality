import json
import logging
from channels.generic.websocket import AsyncWebsocketConsumer
from channels.db import database_sync_to_async
from django.contrib.auth.models import AnonymousUser
from orders.models import Order, DeliveryAssignment, DeliveryRider
from django.core.exceptions import ObjectDoesNotExist
from django.utils import timezone

logger = logging.getLogger(__name__)

class OrderConsumer(AsyncWebsocketConsumer):
    async def connect(self):
        """Connect to WebSocket and join order group"""
        try:
            self.order_id = self.scope['url_route']['kwargs']['order_id']
            self.order_group_name = f'order_{self.order_id}'
            
            # Check if user is authenticated and has permission to view this order
            user = self.scope.get("user")
            if not user or user == AnonymousUser() or not user.is_authenticated:
                logger.warning(f"Unauthenticated user attempted to connect to WebSocket for order {self.order_id}")
                await self.close(code=4001)
                return
            
            # Verify user has access to this order
            has_permission = await self.check_order_permission(user, self.order_id)
            if not has_permission:
                logger.warning(f"User {user.username} does not have permission to access order {self.order_id}")
                await self.close(code=4003)
                return
            
            # Join order group
            await self.channel_layer.group_add(
                self.order_group_name,
                self.channel_name
            )
            
            await self.accept()
            
            # Send current order status
            order_data = await self.get_order_data(self.order_id)
            if order_data:
                await self.send(text_data=json.dumps({
                    'type': 'order_status',
                    'order': order_data
                }))
            
            logger.info(f"WebSocket connected for order {self.order_id} by user {user.username}")
            
        except KeyError as e:
            logger.error(f"Missing URL parameter: {str(e)}")
            await self.close(code=4000)
        except Exception as e:
            logger.error(f"Error connecting WebSocket: {str(e)}")
            await self.close(code=4002)

    async def disconnect(self, close_code):
        """Disconnect from WebSocket"""
        try:
            if hasattr(self, 'order_group_name'):
                await self.channel_layer.group_discard(
                    self.order_group_name,
                    self.channel_name
                )
            logger.info(f"WebSocket disconnected for order {getattr(self, 'order_id', 'unknown')} with code {close_code}")
        except Exception as e:
            logger.error(f"Error during WebSocket disconnect: {str(e)}")

    async def receive(self, text_data):
        """Receive message from WebSocket"""
        try:
            text_data_json = json.loads(text_data)
            message_type = text_data_json.get('type')
            
            if message_type == 'ping':
                # Respond to ping with pong for connection health check
                await self.send(text_data=json.dumps({
                    'type': 'pong',
                    'timestamp': text_data_json.get('timestamp')
                }))
            else:
                logger.warning(f"Unknown message type received: {message_type}")
                
        except json.JSONDecodeError as e:
            logger.error(f"Invalid JSON received: {str(e)}")
        except Exception as e:
            logger.error(f"Error receiving WebSocket message: {str(e)}")

    async def order_status_update(self, event):
        """Send order status update to WebSocket"""
        try:
            await self.send(text_data=json.dumps({
                'type': 'status_update',
                'order_id': event['order_id'],
                'status': event['status'],
                'status_display': event['status_display'],
                'message': event['message'],
                'updated_by': event.get('updated_by'),
                'timestamp': event.get('timestamp')
            }))
        except Exception as e:
            logger.error(f"Error sending status update: {str(e)}")

    async def order_item_update(self, event):
        """Send order item update to WebSocket"""
        try:
            await self.send(text_data=json.dumps({
                'type': 'item_update',
                'order_id': event['order_id'],
                'message': event['message'],
                'timestamp': event.get('timestamp')
            }))
        except Exception as e:
            logger.error(f"Error sending item update: {str(e)}")

    @database_sync_to_async
    def check_order_permission(self, user, order_id):
        """Check if user has permission to view this order"""
        try:
            order = Order.objects.select_related(
                'ordered_by',
                'table_info__owner',
                'table_info__restaurant__main_owner',
                'table_info__restaurant__branch_owner',
            ).get(id=order_id)

            # System administrators can view all
            if user.is_administrator():
                return True

            # The customer who placed the order can view it
            if order.ordered_by == user:
                return True

            # Get the restaurant this table belongs to
            table = order.table_info
            if not table:
                order_owner = getattr(order.ordered_by, 'owner', None) if order.ordered_by else None
                if order_owner:
                    if order_owner == user:
                        return True
                    if getattr(user, 'owner', None) and user.owner == order_owner:
                        return True
                return False

            # Check via restaurant FK (new system)
            if table.restaurant:
                rest = table.restaurant
                if (rest.main_owner == user or
                        rest.branch_owner == user or
                        (hasattr(user, 'owner') and user.owner and
                         (rest.main_owner == user.owner or rest.branch_owner == user.owner))):
                    return True

            # Check via legacy owner FK (old system)
            if table.owner:
                if table.owner == user:
                    return True
                # Staff assigned to this owner
                if hasattr(user, 'owner') and user.owner and user.owner == table.owner:
                    return True

            logger.warning(
                f"User {user.username} (role={getattr(user.role, 'name', 'unknown')}) "
                f"denied access to order {order_id} WebSocket"
            )
            return False

        except Order.DoesNotExist:
            logger.error(f"Order {order_id} not found during WebSocket permission check")
            return False
        except Exception as e:
            logger.error(f"Error checking order permission for order {order_id}: {str(e)}")
            return False

    @database_sync_to_async
    def get_order_data(self, order_id):
        """Get current order data"""
        try:
            order = Order.objects.select_related(
                'table_info__owner', 'ordered_by', 'confirmed_by'
            ).prefetch_related('order_items__product').get(id=order_id)
            
            return {
                'id': order.id,
                'order_number': getattr(order, 'order_number', f"ORD-{order.id}"),
                'status': order.status,
                'status_display': order.get_status_display(),
                'table_number': order.table_info.tbl_no if order.table_info else None,
                'restaurant_name': (order.table_info.owner.restaurant_name 
                                  if order.table_info and order.table_info.owner 
                                  else 'Unknown Restaurant'),
                'total_amount': str(order.total_amount),
                'created_at': order.created_at.isoformat() if order.created_at else None,
                'updated_at': order.updated_at.isoformat() if order.updated_at else None,
                'items_count': len(order.order_items.all()),  # Uses prefetch cache
                'confirmed_by': (order.confirmed_by.get_full_name() 
                               if order.confirmed_by else None),
            }
            
        except Order.DoesNotExist:
            logger.error(f"Order {order_id} not found in get_order_data")
            return None
        except Exception as e:
            logger.error(f"Error getting order data: {str(e)}")
            return None


class RestaurantConsumer(AsyncWebsocketConsumer):
    """WebSocket consumer for restaurant-wide updates"""
    
    async def connect(self):
        """Connect to restaurant group for kitchen/staff notifications"""
        try:
            user = self.scope.get("user")
            if not user or user == AnonymousUser() or not user.is_authenticated:
                logger.warning("Unauthenticated user attempted to connect to restaurant WebSocket")
                await self.close(code=4001)
                return
            
            # Only staff members and managers can connect to restaurant updates
            if not (user.is_owner() or user.is_main_owner() or user.is_branch_owner() or user.is_manager() or
                    user.is_kitchen_staff() or user.is_bar_staff() or user.is_buffet_staff() or 
                    user.is_service_staff() or user.is_customer_care() or user.is_cashier()):
                logger.warning(f"User {user.username} with role {user.role} attempted unauthorized restaurant WebSocket connection")
                await self.close(code=4003)
                return
            
            # Get owner_id from URL parameters
            self.owner_id = self.scope['url_route']['kwargs'].get('owner_id')
            if not self.owner_id:
                logger.error("No owner_id provided in WebSocket URL")
                await self.close(code=4000)
                return
            
            # Verify user has access to this restaurant
            has_access = await self.check_restaurant_access(user, self.owner_id)
            if not has_access:
                logger.warning(f"User {user.username} does not have access to restaurant {self.owner_id}")
                await self.close(code=4003)
                return
            
            self.restaurant_group_name = f'restaurant_{self.owner_id}'
            
            # Join restaurant group
            await self.channel_layer.group_add(
                self.restaurant_group_name,
                self.channel_name
            )
            
            await self.accept()
            logger.info(f"Restaurant WebSocket connected for user {user.username} to restaurant {self.owner_id}")
            
        except KeyError as e:
            logger.error(f"Missing URL parameter: {str(e)}")
            await self.close(code=4000)
        except Exception as e:
            logger.error(f"Error connecting to restaurant WebSocket: {str(e)}")
            await self.close(code=4002)

    async def disconnect(self, close_code):
        """Disconnect from restaurant group"""
        try:
            if hasattr(self, 'restaurant_group_name'):
                await self.channel_layer.group_discard(
                    self.restaurant_group_name,
                    self.channel_name
                )
            logger.info(f"Restaurant WebSocket disconnected for restaurant {getattr(self, 'owner_id', 'unknown')} with code {close_code}")
        except Exception as e:
            logger.error(f"Error during restaurant WebSocket disconnect: {str(e)}")

    async def new_order(self, event):
        """Send new order notification to restaurant staff"""
        try:
            await self.send(text_data=json.dumps({
                'type': 'new_order',
                'order_id': event['order_id'],
                'order_number': event['order_number'],
                'table_number': event['table_number'],
                'customer_name': event['customer_name'],
                'items_count': event['items_count'],
                'total_amount': event['total_amount'],
                'message': event['message'],
                'timestamp': event.get('timestamp')
            }))
        except Exception as e:
            logger.error(f"Error sending new order notification: {str(e)}")

    async def order_cancelled(self, event):
        """Send order cancellation notification"""
        try:
            await self.send(text_data=json.dumps({
                'type': 'order_cancelled',
                'order_id': event['order_id'],
                'order_number': event['order_number'],
                'reason': event.get('reason', 'Customer cancelled'),
                'message': event['message'],
                'timestamp': event.get('timestamp')
            }))
        except Exception as e:
            logger.error(f"Error sending cancellation notification: {str(e)}")

    async def order_status_update(self, event):
        try:
            await self.send(text_data=json.dumps({
                'type': 'order_status_update',
                'order_id': event.get('order_id'),
                'order_number': event.get('order_number'),
                'status': event.get('status'),
                'status_display': event.get('status_display'),
                'updated_by': event.get('updated_by'),
                'timestamp': event.get('timestamp'),
            }))
        except Exception as e:
            logger.error(f"Error sending order_status_update to restaurant group: {e}")

    @database_sync_to_async
    def check_restaurant_access(self, user, owner_id):
        """Check if user has access to this restaurant"""
        try:
            from accounts.models import User
            
            # Convert owner_id to int if it's a string
            try:
                owner_id = int(owner_id)
            except (ValueError, TypeError):
                logger.error(f"Invalid owner_id format: {owner_id}")
                return False
            
            # Check if the owner exists (support all owner types)
            try:
                owner = User.objects.get(
                    id=owner_id, 
                    role__name__in=['owner', 'main_owner', 'branch_owner']
                )
            except User.DoesNotExist:
                logger.error(f"Owner with id {owner_id} not found")
                return False
            
            # System administrators can access all restaurants
            if user.is_administrator():
                return True
            
            # Owner/main_owner/branch_owner can access their own restaurant directly
            if (user.is_owner() or user.is_main_owner() or user.is_branch_owner()) and user.id == owner_id:
                return True

            # Staff (cashier, customer_care, manager, etc.) access via their owner FK
            if hasattr(user, 'owner') and user.owner and user.owner.id == owner_id:
                return True
                
            return False
            
        except Exception as e:
            logger.error(f"Error checking restaurant access: {str(e)}")
            return False

    @database_sync_to_async
    def get_user_restaurant_id(self, user):
        """Get the restaurant ID for the user (deprecated - kept for compatibility)"""
        try:
            if user.is_owner() or user.is_main_owner() or user.is_branch_owner() or user.is_manager():
                return user.id
            elif hasattr(user, 'owner') and user.owner:
                return user.owner.id
            return None
        except Exception as e:
            logger.error(f"Error getting user restaurant ID: {str(e)}")
            return None


class DeliveryConsumer(AsyncWebsocketConsumer):
    """
    Real-time delivery tracking WebSocket.

    Group: delivery_{order_id}
    - Rider connects and pushes GPS pings every ~5 s.
    - Customer connects and receives live location updates.
    - Both see delivery-status changes (picked_up / delivered).
    """

    async def connect(self):
        try:
            self.order_id = self.scope['url_route']['kwargs']['order_id']
            self.group_name = f'delivery_{self.order_id}'

            user = self.scope.get('user')
            if not user or user == AnonymousUser() or not user.is_authenticated:
                await self.close(code=4001)
                return

            allowed = await self.check_permission(user, self.order_id)
            if not allowed:
                await self.close(code=4003)
                return

            await self.channel_layer.group_add(self.group_name, self.channel_name)
            await self.accept()

            # Send current tracking snapshot so the client can render immediately
            snapshot = await self.get_tracking_snapshot(self.order_id)
            if snapshot:
                await self.send(text_data=json.dumps({'type': 'snapshot', **snapshot}))

            logger.info(f"Delivery WS connected: order {self.order_id} user {user.username}")
        except Exception as e:
            logger.error(f"DeliveryConsumer connect error: {e}")
            await self.close(code=4002)

    async def disconnect(self, close_code):
        try:
            if hasattr(self, 'group_name'):
                await self.channel_layer.group_discard(self.group_name, self.channel_name)
        except Exception as e:
            logger.error(f"DeliveryConsumer disconnect error: {e}")

    async def receive(self, text_data):
        """
        Accepts messages from the rider's phone:
          { type: 'location_update', lat: float, lng: float }
          { type: 'ping' }
        """
        try:
            data = json.loads(text_data)
            msg_type = data.get('type')

            if msg_type == 'location_update':
                try:
                    lat = float(data.get('lat'))
                    lng = float(data.get('lng'))
                except (TypeError, ValueError):
                    return
                if not (-90 <= lat <= 90) or not (-180 <= lng <= 180):
                    return

                user = self.scope.get('user')
                is_rider = await self.is_assigned_rider(user, self.order_id)
                if not is_rider:
                    return

                # Persist location to DB so REST GET /track/ always has fresh data
                await self.save_rider_location(user, self.order_id, lat, lng)

                # Broadcast to everyone in the group (customer + any monitors)
                await self.channel_layer.group_send(
                    self.group_name,
                    {
                        'type': 'location_broadcast',
                        'lat': lat,
                        'lng': lng,
                        'timestamp': timezone.now().isoformat(),
                    }
                )

            elif msg_type == 'ping':
                await self.send(text_data=json.dumps({'type': 'pong'}))

        except json.JSONDecodeError:
            pass
        except Exception as e:
            logger.error(f"DeliveryConsumer receive error: {e}")

    # ── Channel layer event handlers ──────────────────────────────────────────

    async def location_broadcast(self, event):
        await self.send(text_data=json.dumps({
            'type': 'location_update',
            'lat': event['lat'],
            'lng': event['lng'],
            'timestamp': event['timestamp'],
        }))

    async def delivery_status_update(self, event):
        await self.send(text_data=json.dumps({
            'type': 'delivery_status',
            'status': event['status'],
            'status_display': event['status_display'],
            'timestamp': event['timestamp'],
        }))

    # ── DB helpers ────────────────────────────────────────────────────────────

    @database_sync_to_async
    def check_permission(self, user, order_id):
        try:
            order = Order.objects.select_related(
                'ordered_by', 'table_info__owner'
            ).get(id=order_id)

            if user.is_administrator():
                return True
            if order.ordered_by == user:
                return True
            # Restaurant staff (dine-in orders have table_info)
            owner = order.table_info.owner if order.table_info else None
            if owner:
                if owner == user:
                    return True
                if hasattr(user, 'owner') and user.owner == owner:
                    return True
            # Delivery/pickup orders have no table_info — check via ordered_by.owner
            if not owner and order.order_type in ('delivery', 'pickup'):
                order_owner = getattr(order.ordered_by, 'owner', None) if order.ordered_by else None
                if order_owner:
                    if order_owner == user:
                        return True
                    if hasattr(user, 'owner') and user.owner == order_owner:
                        return True
            # The assigned rider
            try:
                assignment = order.delivery_assignment
                if assignment.rider.user == user:
                    return True
            except DeliveryAssignment.DoesNotExist:
                pass
            return False
        except Order.DoesNotExist:
            return False
        except Exception as e:
            logger.error(f"DeliveryConsumer permission check error: {e}")
            return False

    @database_sync_to_async
    def is_assigned_rider(self, user, order_id):
        try:
            assignment = DeliveryAssignment.objects.select_related('rider__user').get(
                order_id=order_id
            )
            return assignment.rider.user == user
        except DeliveryAssignment.DoesNotExist:
            return False

    @database_sync_to_async
    def save_rider_location(self, user, order_id, lat, lng):
        try:
            rider = user.rider_profile
            rider.current_lat = lat
            rider.current_lng = lng
            rider.last_location_at = timezone.now()
            rider.save(update_fields=['current_lat', 'current_lng', 'last_location_at'])
        except Exception as e:
            logger.error(f"save_rider_location error: {e}")

    @database_sync_to_async
    def get_tracking_snapshot(self, order_id):
        try:
            assignment = DeliveryAssignment.objects.select_related(
                'rider__user', 'order'
            ).get(order_id=order_id)
            rider = assignment.rider
            return {
                'status': assignment.status,
                'rider_name': rider.user.get_full_name() or rider.user.username,
                'vehicle': rider.get_vehicle_type_display(),
                'lat': float(rider.current_lat) if rider.current_lat is not None else None,
                'lng': float(rider.current_lng) if rider.current_lng is not None else None,
                'delivery_address': assignment.order.delivery_address,
            }
        except DeliveryAssignment.DoesNotExist:
            return None
        except Exception as e:
            logger.error(f"get_tracking_snapshot error: {e}")
            return None