from django.urls import re_path
from . import consumers

websocket_urlpatterns = [
    re_path(r'ws/order/(?P<order_id>\w+)/$', consumers.OrderConsumer.as_asgi()),
    re_path(r'ws/restaurant/(?P<owner_id>\w+)/$', consumers.RestaurantConsumer.as_asgi()),
    re_path(r'ws/delivery/(?P<order_id>\w+)/$', consumers.DeliveryConsumer.as_asgi()),
]
