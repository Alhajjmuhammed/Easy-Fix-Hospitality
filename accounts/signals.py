"""
Account signals.

Password change => the user's DRF API token is deleted, so a mobile app (or anyone
holding a copied token) is signed out and must log in again with the new password.

One central place covers every way a password is changed: set_password() + save(),
`user.password = make_password(...)` + save() (system admin), the admin site, the
web password-change page, management commands, etc.

How it decides "the password changed": before an existing user is saved, the stored
hash is read from the database and compared with the hash being saved. Saves that
cannot touch the password are skipped without any query:
  - save(update_fields=[...]) without 'password' in the list
    (Django's login updates only last_login; push-token / language saves, etc.)
  - new users (nothing to revoke yet) and fixture loading (raw=True).

Not covered (bypasses model signals): QuerySet.update(password=...). Nothing in this
project does that.

Note: Django re-hashes a password on login when its hasher settings change (e.g. after
a Django upgrade raises the PBKDF2 iteration count). That save changes the stored hash,
so it also revokes the token: a one-off re-login in the mobile app, never a lockout.
The web session is unaffected (sessions are separate; the password-change views call
update_session_auth_hash), and mobile login creates a fresh token right after
authenticating, so mobile login keeps working.
"""
from django.db.models.signals import post_save, pre_save

_FLAG = '_revoke_api_tokens_after_save'


def _password_may_change(kwargs):
    if kwargs.get('raw'):
        return False
    update_fields = kwargs.get('update_fields')
    return update_fields is None or 'password' in update_fields


def mark_password_change(sender, instance, **kwargs):
    setattr(instance, _FLAG, False)
    if instance.pk is None or instance._state.adding or not _password_may_change(kwargs):
        return
    old_hash = (sender._default_manager.using(kwargs.get('using') or 'default')
                .filter(pk=instance.pk).values_list('password', flat=True).first())
    if old_hash is not None and old_hash != instance.password:
        setattr(instance, _FLAG, True)


def revoke_tokens_on_password_change(sender, instance, created=False, **kwargs):
    if created or not getattr(instance, _FLAG, False):
        return
    setattr(instance, _FLAG, False)
    from rest_framework.authtoken.models import Token
    Token.objects.using(kwargs.get('using') or 'default').filter(user_id=instance.pk).delete()


def connect_signals():
    from .models import User
    pre_save.connect(mark_password_change, sender=User,
                     dispatch_uid='accounts.mark_password_change')
    post_save.connect(revoke_tokens_on_password_change, sender=User,
                      dispatch_uid='accounts.revoke_tokens_on_password_change')
