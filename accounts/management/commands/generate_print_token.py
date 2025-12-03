"""
Management command to generate API tokens for print clients

Usage:
    python manage.py generate_print_token <username>
    python manage.py generate_print_token owner1 --regenerate
"""

from django.core.management.base import BaseCommand, CommandError
from django.contrib.auth import get_user_model
from rest_framework.authtoken.models import Token

User = get_user_model()


class Command(BaseCommand):
    help = 'Generate API token for print client authentication'

    def add_arguments(self, parser):
        parser.add_argument(
            'username',
            type=str,
            help='Username of the restaurant owner'
        )
        parser.add_argument(
            '--regenerate',
            action='store_true',
            help='Regenerate token if it already exists (revokes old token)'
        )

    def handle(self, *args, **options):
        username = options['username']
        regenerate = options.get('regenerate', False)

        try:
            user = User.objects.get(username=username)
        except User.DoesNotExist:
            raise CommandError(f'User "{username}" does not exist')

        # Check if user is a restaurant owner
        if not hasattr(user, 'role') or user.role.name != 'Owner':
            self.stdout.write(
                self.style.WARNING(
                    f'Warning: User "{username}" is not a restaurant owner (Role: {user.role.name if hasattr(user, "role") else "None"})'
                )
            )

        # Get or create token
        if regenerate:
            # Delete old token and create new one
            Token.objects.filter(user=user).delete()
            token = Token.objects.create(user=user)
            self.stdout.write(
                self.style.SUCCESS(f'✓ Token regenerated for user "{username}"')
            )
        else:
            token, created = Token.objects.get_or_create(user=user)
            if created:
                self.stdout.write(
                    self.style.SUCCESS(f'✓ New token created for user "{username}"')
                )
            else:
                self.stdout.write(
                    self.style.SUCCESS(f'✓ Token already exists for user "{username}"')
                )

        # Display token and restaurant info
        self.stdout.write('')
        self.stdout.write('=' * 70)
        self.stdout.write(f'Restaurant: {user.restaurant_name}')
        self.stdout.write(f'Owner: {user.username} ({user.get_full_name() or user.email})')
        self.stdout.write('=' * 70)
        self.stdout.write(f'API Token: {token.key}')
        self.stdout.write('=' * 70)
        self.stdout.write('')
        self.stdout.write('Print Client Configuration:')
        self.stdout.write('-' * 70)
        self.stdout.write(f'1. Copy the token above')
        self.stdout.write(f'2. Edit print_client/config.json on restaurant computer')
        self.stdout.write(f'3. Set "api_token": "{token.key}"')
        self.stdout.write(f'4. Set "server_url": "https://your-server.com"')
        self.stdout.write(f'5. Run: python print_client.py')
        self.stdout.write('')

        if regenerate:
            self.stdout.write(
                self.style.WARNING(
                    '⚠ Old token has been revoked! Update config.json on all print clients.'
                )
            )
