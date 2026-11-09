"""Re-check open mobile money requests (run every few minutes from cron).

Catches payments whose confirmation never reached us (screen closed, callback lost, provider slow).
"""
from django.core.management.base import BaseCommand

from cashier.mobile_money import sweep


class Command(BaseCommand):
    help = 'Re-check open mobile money payment requests with the providers.'

    def handle(self, *args, **options):
        n = sweep()
        self.stdout.write(f'checked {n} open mobile money request(s)')
