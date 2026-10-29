"""
Add the reservation permissions and grant them to the roles that get them by default.

Restaurants that already have saved role permission sets never fall back to
DEFAULT_ROLE_FEATURES, so the new features are attached to those existing sets
for manager / cashier / customer_care. Purely additive: nothing is removed.
"""
from django.db import migrations

FEATURES = [
    ('view_reservations', 'View Reservations', 'View table reservations (read-only)', 'orders'),
    ('manage_reservations', 'Manage Reservations',
     'Create, confirm, decline, assign tables and update reservations (includes view)', 'orders'),
]
ROLES = ('manager', 'cashier', 'customer_care')


def add_features(apps, schema_editor):
    Feature = apps.get_model('accounts', 'Feature')
    RolePermissionSet = apps.get_model('accounts', 'RolePermissionSet')
    features = []
    for slug, name, description, category in FEATURES:
        feature, _ = Feature.objects.get_or_create(
            slug=slug, defaults={'name': name, 'description': description, 'category': category})
        features.append(feature)
    for rps in RolePermissionSet.objects.filter(role_name__in=ROLES):
        rps.features.add(*features)


def remove_features(apps, schema_editor):
    Feature = apps.get_model('accounts', 'Feature')
    Feature.objects.filter(slug__in=[f[0] for f in FEATURES]).delete()


class Migration(migrations.Migration):

    dependencies = [
        ('accounts', '0028_restaurantsubscription_disabled_features'),
    ]

    operations = [
        migrations.RunPython(add_features, remove_features),
    ]
