from django.conf import settings
from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):

    dependencies = [
        ('accounts', '0026_permissions_system'),
    ]

    operations = [
        migrations.CreateModel(
            name='AdminSectionPermission',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('section', models.CharField(choices=[
                    ('dashboard',   'Dashboard'),
                    ('restaurants', 'Restaurants'),
                    ('users',       'User Management'),
                    ('statistics',  'Statistics'),
                    ('orders',      'Orders'),
                    ('categories',  'Categories'),
                    ('products',    'Products'),
                    ('tables',      'Tables'),
                    ('riders',      'Delivery Riders'),
                ], max_length=30)),
                ('can_view',   models.BooleanField(default=False)),
                ('can_create', models.BooleanField(default=False)),
                ('can_edit',   models.BooleanField(default=False)),
                ('can_delete', models.BooleanField(default=False)),
                ('staff', models.ForeignKey(
                    limit_choices_to={'role__name': 'admin_staff'},
                    on_delete=django.db.models.deletion.CASCADE,
                    related_name='admin_section_permissions',
                    to=settings.AUTH_USER_MODEL,
                )),
            ],
            options={
                'verbose_name': 'Admin Section Permission',
                'unique_together': {('staff', 'section')},
            },
        ),
    ]
