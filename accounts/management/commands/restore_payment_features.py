"""
One-time command: ensure all cashier and customer_care RolePermissionSets
include the core operational features enabled by default.
Additive only — never removes existing features.
"""
from django.core.management.base import BaseCommand
from accounts.models import RolePermissionSet
from accounts.models import Feature


# Core features each role must have to function correctly
REQUIRED = {
    'cashier': [
        'place_orders', 'manage_orders', 'process_payments',
        'void_payments', 'view_receipts', 'manage_waste', 'view_reports',
    ],
    'customer_care': [
        'place_orders', 'manage_orders', 'process_payments',
        'view_receipts', 'manage_waste', 'view_reports', 'view_attendance',
    ],
}

ALL_SLUGS = list({s for slugs in REQUIRED.values() for s in slugs})


class Command(BaseCommand):
    help = 'Restore missing core features to cashier/customer_care role permission sets'

    def handle(self, *args, **options):
        feature_cache = {f.slug: f for f in Feature.objects.filter(slug__in=ALL_SLUGS)}

        total_fixed = 0
        for role_name, slugs in REQUIRED.items():
            rpsets = RolePermissionSet.objects.filter(role_name=role_name)
            for rps in rpsets:
                missing = [feature_cache[s] for s in slugs
                           if s in feature_cache and not rps.features.filter(slug=s).exists()]
                if missing:
                    rps.features.add(*missing)
                    total_fixed += 1
                    self.stdout.write(
                        f'  Fixed {role_name} for owner {rps.owner_id}: '
                        f'added {[f.slug for f in missing]}'
                    )

        if total_fixed:
            self.stdout.write(self.style.SUCCESS(
                f'\nFixed {total_fixed} role permission set(s).'
            ))
        else:
            self.stdout.write(self.style.SUCCESS('All role permission sets already have the required features.'))
