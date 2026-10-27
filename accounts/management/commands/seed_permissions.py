"""
Management command: seed_permissions

Creates Feature rows for all 22 features and, for every existing restaurant
owner, creates default RolePermissionSets that mirror the current hardcoded
behavior (so existing restaurants are unaffected by the new system).

Safe to run multiple times (idempotent).
"""
from django.core.management.base import BaseCommand
from django.db import transaction

from accounts.models import Feature, RolePermissionSet, User
from accounts.permissions_defaults import ALL_FEATURES, DEFAULT_ROLE_FEATURES


class Command(BaseCommand):
    help = 'Seed Feature records and default RolePermissionSets for all existing restaurants'

    def add_arguments(self, parser):
        parser.add_argument(
            '--owner-id',
            type=int,
            default=None,
            help='Seed only for a specific owner user id (default: all owners)',
        )
        parser.add_argument(
            '--reset',
            action='store_true',
            default=False,
            help='Reset existing RolePermissionSets to their defaults (dangerous!)',
        )

    def handle(self, *args, **options):
        with transaction.atomic():
            self._seed_features()
            self._seed_role_permission_sets(
                owner_id=options['owner_id'],
                reset=options['reset'],
            )

    def _seed_features(self):
        created = 0
        for slug, name, description, category in ALL_FEATURES:
            _, was_created = Feature.objects.get_or_create(
                slug=slug,
                defaults={'name': name, 'description': description, 'category': category},
            )
            if was_created:
                created += 1
        self.stdout.write(self.style.SUCCESS(
            f'Features: {created} created, {len(ALL_FEATURES) - created} already existed'
        ))

    def _seed_role_permission_sets(self, owner_id=None, reset=False):
        qs = User.objects.filter(role__name__in=['owner', 'main_owner', 'branch_owner'])
        if owner_id:
            qs = qs.filter(pk=owner_id)

        feature_cache = {f.slug: f for f in Feature.objects.all()}
        created_total = 0
        skipped_total = 0

        for owner in qs:
            for role_name, defaults in DEFAULT_ROLE_FEATURES.items():
                rps, was_created = RolePermissionSet.objects.get_or_create(
                    owner=owner,
                    role_name=role_name,
                )
                if was_created or reset:
                    feature_objs = [feature_cache[s] for s in defaults if s in feature_cache]
                    rps.features.set(feature_objs)
                    if was_created:
                        created_total += 1
                    else:
                        self.stdout.write(f'  Reset {owner.username} / {role_name}')
                else:
                    skipped_total += 1

        self.stdout.write(self.style.SUCCESS(
            f'RolePermissionSets: {created_total} created, {skipped_total} already existed (use --reset to overwrite)'
        ))
