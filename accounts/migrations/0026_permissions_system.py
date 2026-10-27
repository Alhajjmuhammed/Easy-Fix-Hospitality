from django.conf import settings
from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):

    dependencies = [
        ('accounts', '0025_user_route_receipt_by_station'),
    ]

    operations = [
        # 1. Feature lookup table
        migrations.CreateModel(
            name='Feature',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('slug', models.CharField(max_length=50, unique=True)),
                ('name', models.CharField(max_length=100)),
                ('description', models.CharField(blank=True, max_length=255)),
                ('category', models.CharField(
                    choices=[
                        ('orders', 'Orders'),
                        ('payments', 'Payments'),
                        ('station', 'Station Dashboards'),
                        ('menu', 'Menu Management'),
                        ('staff', 'Staff'),
                        ('reports', 'Reports'),
                        ('operations', 'Operations'),
                    ],
                    default='operations',
                    max_length=20,
                )),
            ],
            options={
                'verbose_name': 'Feature',
                'verbose_name_plural': 'Features',
                'ordering': ['category', 'name'],
            },
        ),

        # 2. CustomRole table (owner FK to User — User already exists)
        migrations.CreateModel(
            name='CustomRole',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('name', models.CharField(max_length=100)),
                ('description', models.CharField(blank=True, max_length=255)),
                ('created_at', models.DateTimeField(auto_now_add=True)),
                ('updated_at', models.DateTimeField(auto_now=True)),
                ('owner', models.ForeignKey(
                    limit_choices_to={'role__name__in': ['owner', 'main_owner', 'branch_owner']},
                    on_delete=django.db.models.deletion.CASCADE,
                    related_name='custom_roles',
                    to=settings.AUTH_USER_MODEL,
                )),
                ('features', models.ManyToManyField(
                    blank=True,
                    related_name='custom_roles',
                    to='accounts.feature',
                )),
            ],
            options={
                'verbose_name': 'Custom Role',
                'verbose_name_plural': 'Custom Roles',
                'ordering': ['owner', 'name'],
                'unique_together': {('owner', 'name')},
            },
        ),

        # 3. RolePermissionSet table
        migrations.CreateModel(
            name='RolePermissionSet',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('role_name', models.CharField(
                    choices=[
                        ('manager', 'Manager'),
                        ('customer_care', 'Customer Care'),
                        ('kitchen', 'Kitchen'),
                        ('bar', 'Bar'),
                        ('buffet', 'Buffet'),
                        ('service', 'Service'),
                        ('cashier', 'Cashier'),
                        ('delivery_rider', 'Delivery Rider'),
                    ],
                    max_length=20,
                )),
                ('updated_at', models.DateTimeField(auto_now=True)),
                ('owner', models.ForeignKey(
                    limit_choices_to={'role__name__in': ['owner', 'main_owner', 'branch_owner']},
                    on_delete=django.db.models.deletion.CASCADE,
                    related_name='role_permission_sets',
                    to=settings.AUTH_USER_MODEL,
                )),
                ('features', models.ManyToManyField(
                    blank=True,
                    related_name='role_sets',
                    to='accounts.feature',
                )),
                ('updated_by', models.ForeignKey(
                    blank=True,
                    null=True,
                    on_delete=django.db.models.deletion.SET_NULL,
                    related_name='permission_set_updates',
                    to=settings.AUTH_USER_MODEL,
                )),
            ],
            options={
                'verbose_name': 'Role Permission Set',
                'verbose_name_plural': 'Role Permission Sets',
                'ordering': ['owner', 'role_name'],
                'unique_together': {('owner', 'role_name')},
            },
        ),

        # 4. Add custom_role FK to User
        migrations.AddField(
            model_name='user',
            name='custom_role',
            field=models.ForeignKey(
                blank=True,
                null=True,
                on_delete=django.db.models.deletion.SET_NULL,
                related_name='assigned_users',
                to='accounts.customrole',
            ),
        ),
    ]
