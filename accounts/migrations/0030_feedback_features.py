"""
Add the customer feedback permissions and grant them to the roles that get them by default.

Restaurants that already have saved role permission sets never fall back to
DEFAULT_ROLE_FEATURES, so the new features are attached to those existing sets
for manager / customer_care. Purely additive: nothing is removed.
"""
from django.db import migrations

FEATURES = [
    ('view_feedback', 'View Customer Feedback',
     'See customer ratings and comments, and get alerts for low ratings', 'reports'),
    ('reply_feedback', 'Reply to Feedback', 'Reply to customer ratings (includes view)', 'reports'),
]
ROLES = ('manager', 'customer_care')


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
        ('accounts', '0029_reservation_features'),
    ]

    operations = [
        migrations.RunPython(add_features, remove_features),
    ]
