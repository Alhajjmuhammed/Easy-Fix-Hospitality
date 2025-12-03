import json
import logging
from channels.generic.websocket import AsyncWebsocketConsumer
from channels.db import database_sync_to_async
from django.contrib.auth.models import AnonymousUser
from orders.models import Order
from django.core.exceptions import ObjectDoesNotExist

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
            order = Order.objects.select_related('ordered_by', 'table_info__owner').get(id=order_id)
            
            # Order owner can view
            if order.ordered_by == user:
                return True
                
            # Staff from same restaurant can view
            if hasattr(user, 'owner') and user.owner:
                if hasattr(order, 'table_info') and order.table_info and hasattr(order.table_info, 'owner'):
                    if order.table_info.owner == user.owner:
                        return True
            
            # Restaurant owner can view their own orders
            if user.is_owner() or user.is_main_owner() or user.is_branch_owner():
                if hasattr(order, 'table_info') and order.table_info and hasattr(order.table_info, 'owner'):
                    if order.table_info.owner == user:
                        return True
            
            # System administrators can view all
            if user.is_administrator():
                return True
                
            return False
            
        except Order.DoesNotExist:
            logger.error(f"Order {order_id} not found")
            return False
        except Exception as e:
            logger.error(f"Error checking order permission: {str(e)}")
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
                'items_count': order.order_items.count(),
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
            
            # Only staff members can connect to restaurant updates
            if not (user.is_owner() or user.is_main_owner() or user.is_branch_owner() or user.is_kitchen_staff() or user.is_customer_care() or user.is_cashier()):
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
            
            # Check if the owner exists
            try:
                owner = User.objects.get(id=owner_id, role__name='owner')
            except User.DoesNotExist:
                logger.error(f"Owner with id {owner_id} not found")
                return False
            
            # System administrators can access all restaurants
            if user.is_administrator():
                return True
            
            # Owner can access their own restaurant
            if user.is_owner() and user.id == owner_id:
                return True
                
            # Staff can access their owner's restaurant
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
            if user.is_owner():
                return user.id
            elif hasattr(user, 'owner') and user.owner:
                return user.owner.id
            return None
        except Exception as e:
            logger.error(f"Error getting user restaurant ID: {str(e)}")
            return None