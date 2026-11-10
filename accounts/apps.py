from django.apps import AppConfig

class AccountsConfig(AppConfig):
    default_auto_field = 'django.db.models.BigAutoField'
    name = 'accounts'

    def ready(self):
        # Delete a user's API token when their password changes (accounts/signals.py).
        from .signals import connect_signals
        connect_signals()
