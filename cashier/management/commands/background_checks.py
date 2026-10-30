"""Run every few minutes from cron:

    */3 * * * * cd /var/www/restaurant && DJANGO_SETTINGS_MODULE=restaurant_system.production_settings venv/bin/python manage.py background_checks

• mobile money: settles payment requests whose confirmation was missed (closed screens, lost callbacks)
• SMS: sends texts left waiting when a web worker restarted mid-send
"""
from django.core.management.base import BaseCommand


class Command(BaseCommand):
    help = 'Mobile money re-checks and stuck SMS retries.'

    def handle(self, *args, **options):
        from cashier.mobile_money import sweep
        from orders.sms import retry_stuck
        for name, job in (('mobile money requests', sweep), ('stuck SMS', retry_stuck)):
            try:
                self.stdout.write(f'{name}: {job()}')
            except Exception as e:   # one failing part must not stop the other
                self.stderr.write(f'{name} failed: {e}')
