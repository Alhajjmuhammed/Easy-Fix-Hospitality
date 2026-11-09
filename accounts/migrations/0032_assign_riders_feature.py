"""
Add the "Assign Riders" permission: give delivery orders to a rider (managers and cashiers by default).

Restaurants that already saved role permission sets never fall back to DEFAULT_ROLE_FEATURES, so the
feature is attached to their existing manager / cashier sets, and to custom roles that could already
assign riders through "Manage Delivery". Purely additive: nothing is removed.
"""
from django.db import migrations

FEATURE = ('assign_riders', 'Assign Riders', 'Give delivery orders to a rider (own restaurant riders only)', 'orders')
ROLES = ('manager', 'cashier')


def add_feature(apps, schema_editor):
    Feature = apps.get_model('accounts', 'Feature')
    RolePermissionSet = apps.get_model('accounts', 'RolePermissionSet')
    CustomRole = apps.get_model('accounts', 'CustomRole')
    slug, name, description, category = FEATURE
    feature, _ = Feature.objects.get_or_create(
        slug=slug, defaults={'name': name, 'description': description, 'category': category})
    for rps in RolePermissionSet.objects.filter(role_name__in=ROLES):
        rps.features.add(feature)
    for role in CustomRole.objects.filter(features__slug='manage_delivery').distinct():
        role.features.add(feature)


def remove_feature(apps, schema_editor):
    Feature = apps.get_model('accounts', 'Feature')
    Feature.objects.filter(slug=FEATURE[0]).delete()


class Migration(migrations.Migration):

    dependencies = [
        ('accounts', '0031_user_language'),
    ]

    operations = [
        migrations.RunPython(add_feature, remove_feature),
    ]
