"""Every message type the server sends to a WebSocket group must have a handler on the consumer
of that group. Channels raises "No handler for message type" otherwise and drops the socket."""
import re
from pathlib import Path

from django.conf import settings
from django.test import SimpleTestCase

from orders.consumers import DeliveryConsumer, OrderConsumer, RestaurantConsumer

GROUP_CONSUMERS = {
    'restaurant_': RestaurantConsumer,
    'order_': OrderConsumer,
    'delivery_': DeliveryConsumer,
}
SEND_RE = re.compile(
    r"group_send\)?\(\s*f?['\"](?P<group>restaurant_|order_|delivery_)[^'\"]*['\"]\s*,\s*\{\s*['\"]type['\"]\s*:\s*['\"](?P<type>\w+)['\"]",
    re.S)
HELPER_RE = re.compile(
    r"_ws_send_on_commit\(\s*f?['\"](?P<group>restaurant_|order_|delivery_)[^'\"]*['\"]\s*,\s*\{\s*['\"]type['\"]\s*:\s*['\"](?P<type>\w+)['\"]",
    re.S)


class WebSocketHandlerTests(SimpleTestCase):
    def test_every_sent_type_has_a_handler(self):
        base = Path(settings.BASE_DIR)
        found = []
        for path in base.rglob('*.py'):
            parts = set(path.parts)
            if parts & {'venv', 'node_modules', 'migrations', '.git', 'dev_tools'} or path.name.startswith('tests'):
                continue
            text = path.read_text(encoding='utf-8', errors='ignore')
            for m in list(SEND_RE.finditer(text)) + list(HELPER_RE.finditer(text)):
                found.append((path.relative_to(base), m['group'], m['type']))
        self.assertTrue(found, 'no group sends found: the scan is broken')
        missing = [f'{p}: {t} -> {GROUP_CONSUMERS[g].__name__}'
                   for p, g, t in found if not callable(getattr(GROUP_CONSUMERS[g], t, None))]
        self.assertEqual(missing, [])

    def test_known_restaurant_types(self):
        for t in ('new_order', 'order_cancelled', 'order_status_update', 'order_updated', 'bill_request'):
            self.assertTrue(callable(getattr(RestaurantConsumer, t, None)), t)
