"""
Management command to create hierarchical roles for branch management
"""

from django.core.management.base import BaseCommand
from accounts.models import Role


class Command(BaseCommand):
    help = 'Create hierarchical roles for branch management'

    def handle(self, *args, **options):
        roles_to_create = [
            {
                'name': 'main_owner',
                'description': 'Main restaurant owner who can manage multiple branches and view consolidated reports'
            },
            {
                'name': 'branch_owner', 
                'description': 'Branch owner who manages a specific restaurant branch under a main owner'
            }
        ]
        
        created_count = 0
        
        for role_data in roles_to_create:
            role, created = Role.objects.get_or_create(
                name=role_data['name'],
                defaults={'description': role_data['description']}
            )
            
            if created:
                created_count += 1
                self.stdout.write(
                    self.style.SUCCESS(f'✓ Created role: {role.get_name_display()}')
                )
            else:
                self.stdout.write(
                    self.style.WARNING(f'• Role already exists: {role.get_name_display()}')
                )
        
        self.stdout.write('')
        self.stdout.write(
            self.style.SUCCESS(f'✓ Process complete. Created {created_count} new roles.')
        )
        self.stdout.write('')
        self.stdout.write('Available roles:')
        for role in Role.objects.all().order_by('name'):
            self.stdout.write(f'  • {role.get_name_display()} - {role.description}')