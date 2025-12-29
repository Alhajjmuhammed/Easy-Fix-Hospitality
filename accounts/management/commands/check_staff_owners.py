from django.core.management.base import BaseCommand
from accounts.models import User, Role


class Command(BaseCommand):
    help = 'Check and fix staff user owner assignments'

    def handle(self, *args, **options):
        self.stdout.write('=== CURRENT USER SITUATION ===')
        
        # Show all users with their roles and owners
        all_users = User.objects.select_related('role', 'owner').all()
        for user in all_users:
            role_name = user.role.name if user.role else 'No Role'
            owner_name = user.owner.username if user.owner else 'No Owner'
            self.stdout.write(f'{user.username} - Role: {role_name} - Owner: {owner_name}')
        
        self.stdout.write('\n=== STAFF WITHOUT OWNERS ===')
        staff_roles = ['customer_care', 'kitchen', 'bar', 'buffet', 'service', 'cashier']
        orphaned_staff = []
        
        for role_name in staff_roles:
            staff_users = User.objects.filter(role__name=role_name, owner__isnull=True)
            if staff_users.exists():
                self.stdout.write(f'\nOrphaned {role_name} staff:')
                for staff in staff_users:
                    self.stdout.write(f'  - {staff.username}')
                    orphaned_staff.append(staff)
        
        if not orphaned_staff:
            self.stdout.write('✅ All staff users have owners assigned!')
            return
            
        self.stdout.write(f'\n⚠️  Found {len(orphaned_staff)} staff users without owners')
        
        # Get all restaurant owners
        owners = User.objects.filter(role__name='owner')
        if not owners.exists():
            self.stdout.write('❌ No restaurant owners found!')
            return
            
        self.stdout.write('\n=== AVAILABLE RESTAURANT OWNERS ===')
        for i, owner in enumerate(owners, 1):
            self.stdout.write(f'{i}. {owner.username} ({owner.restaurant_name or "No Restaurant Name"})')
        
        # For now, just report the issue
        self.stdout.write('\n=== RECOMMENDATION ===')
        self.stdout.write('Some staff users don\'t have owners assigned.')
        self.stdout.write('This means the subscription middleware won\'t block them when restaurants are blocked.')
        self.stdout.write('You should manually assign these staff users to their respective restaurant owners.')