from django.core.management.base import BaseCommand
from django.db.models import Q
from accounts.models import User, SubscriptionLog, RestaurantSubscription
from restaurant.models_restaurant import Restaurant


class Command(BaseCommand):
    help = 'Delete orphaned owner users whose Restaurant record no longer exists'

    def add_arguments(self, parser):
        parser.add_argument('--dry-run', action='store_true', help='Show what would be deleted without deleting')

    def handle(self, *args, **options):
        dry_run = options['dry_run']

        active_owner_ids = set(
            list(Restaurant.objects.values_list('main_owner_id', flat=True)) +
            list(Restaurant.objects.values_list('branch_owner_id', flat=True))
        )
        active_owner_ids.discard(None)

        orphaned_owners = User.objects.filter(
            role__name__in=['owner', 'main_owner', 'branch_owner'],
        ).exclude(id__in=active_owner_ids)

        if not orphaned_owners.exists():
            self.stdout.write(self.style.SUCCESS('No orphaned restaurant users found. Already clean.'))
            return

        self.stdout.write(f'Found {orphaned_owners.count()} orphaned owner account(s):')
        for owner in orphaned_owners:
            staff_count = User.objects.filter(owner=owner).count()
            self.stdout.write(f'  [{owner.role.name if owner.role else "?"}] {owner.username} '
                              f'("{owner.restaurant_name}") — {staff_count} staff')

        if dry_run:
            self.stdout.write(self.style.WARNING('DRY RUN — nothing deleted.'))
            return

        deleted_owners = 0
        deleted_staff = 0

        for owner in orphaned_owners:
            try:
                # 1. PrintJobs
                try:
                    from orders.models_printjob import PrintJob
                    PrintJob.objects.filter(restaurant=owner).delete()
                except Exception:
                    pass
                # 2. Events
                try:
                    from restaurant.models import Event
                    Event.objects.filter(owner=owner).delete()
                except Exception:
                    pass
                # 3. HappyHour promotions
                try:
                    from restaurant.models import HappyHour
                    HappyHour.objects.filter(owner=owner).delete()
                except Exception:
                    pass
                # 4. SalesReports
                try:
                    from reports.models import SalesReport
                    staff_qs = User.objects.filter(owner=owner)
                    SalesReport.objects.filter(generated_by__in=staff_qs).delete()
                    SalesReport.objects.filter(owner=owner).delete()
                    SalesReport.objects.filter(generated_by=owner).delete()
                except Exception:
                    pass
                # 5. WasteReportSummary
                try:
                    from waste_management.models import WasteReportSummary
                    WasteReportSummary.objects.filter(owner=owner).delete()
                except Exception:
                    pass
                # 6. Subscription
                try:
                    sub = owner.subscription
                    SubscriptionLog.objects.filter(subscription=sub).delete()
                    sub.delete()
                except Exception:
                    pass
                # 7. Staff/customer users
                n_staff = User.objects.filter(owner=owner).count()
                User.objects.filter(owner=owner).delete()
                deleted_staff += n_staff
                # 8. Owner user
                owner.delete()
                deleted_owners += 1
                self.stdout.write(f'  Deleted: {owner.username} + {n_staff} staff/customers')
            except Exception as e:
                self.stdout.write(self.style.ERROR(f'  Failed to delete {owner.username}: {e}'))

        self.stdout.write(self.style.SUCCESS(
            f'Done. Deleted {deleted_owners} owner account(s) and {deleted_staff} staff/customer account(s).'
        ))
