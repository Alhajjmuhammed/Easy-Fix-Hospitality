import attendance.models
from django.conf import settings
from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):

    initial = True

    dependencies = [
        ('restaurant', '0025_restaurant_route_receipt_by_station'),
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
    ]

    operations = [
        migrations.CreateModel(
            name='AttendanceQRToken',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('token', models.CharField(default=attendance.models._generate_token, max_length=64, unique=True)),
                ('created_at', models.DateTimeField(auto_now_add=True)),
                ('regenerated_at', models.DateTimeField(auto_now=True)),
                ('owner', models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name='attendance_qr_tokens', to=settings.AUTH_USER_MODEL)),
                ('restaurant', models.OneToOneField(blank=True, null=True, on_delete=django.db.models.deletion.CASCADE, related_name='attendance_qr_token', to='restaurant.restaurant')),
            ],
        ),
        migrations.CreateModel(
            name='Shift',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('name', models.CharField(max_length=100)),
                ('shift_type', models.CharField(choices=[('day', 'Day Shift'), ('night', 'Night Shift'), ('custom', 'Custom')], default='custom', max_length=20)),
                ('start_time', models.TimeField(help_text='Expected check-in time')),
                ('end_time', models.TimeField(help_text='Expected check-out time')),
                ('grace_minutes', models.PositiveIntegerField(default=15, help_text='Minutes after start_time before staff is marked late')),
                ('is_active', models.BooleanField(default=True)),
                ('created_at', models.DateTimeField(auto_now_add=True)),
                ('owner', models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name='shifts', to=settings.AUTH_USER_MODEL)),
                ('restaurant', models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.CASCADE, related_name='shifts', to='restaurant.restaurant')),
            ],
            options={
                'ordering': ['start_time'],
            },
        ),
        migrations.CreateModel(
            name='AttendanceRecord',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('date', models.DateField()),
                ('check_in', models.DateTimeField(blank=True, null=True)),
                ('check_out', models.DateTimeField(blank=True, null=True)),
                ('work_minutes', models.IntegerField(blank=True, null=True)),
                ('is_late', models.BooleanField(default=False)),
                ('late_minutes', models.IntegerField(default=0)),
                ('is_overtime', models.BooleanField(default=False)),
                ('overtime_minutes', models.IntegerField(default=0)),
                ('check_in_via', models.CharField(choices=[('mobile', 'Mobile'), ('web', 'Web')], default='mobile', max_length=10)),
                ('check_out_via', models.CharField(blank=True, choices=[('mobile', 'Mobile'), ('web', 'Web')], max_length=10, null=True)),
                ('notes', models.TextField(blank=True)),
                ('created_at', models.DateTimeField(auto_now_add=True)),
                ('updated_at', models.DateTimeField(auto_now=True)),
                ('staff', models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name='attendance_records', to=settings.AUTH_USER_MODEL)),
                ('owner', models.ForeignKey(null=True, on_delete=django.db.models.deletion.CASCADE, related_name='managed_attendance', to=settings.AUTH_USER_MODEL)),
                ('restaurant', models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, related_name='attendance_records', to='restaurant.restaurant')),
                ('shift', models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, related_name='attendance_records', to='attendance.shift')),
            ],
            options={
                'ordering': ['-date', '-check_in'],
                'unique_together': {('staff', 'date')},
            },
        ),
    ]
