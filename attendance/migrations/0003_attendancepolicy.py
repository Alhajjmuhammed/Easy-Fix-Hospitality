from django.conf import settings
from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):

    dependencies = [
        ('attendance', '0002_alter_attendancerecord_owner'),
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
    ]

    operations = [
        migrations.CreateModel(
            name='AttendancePolicy',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('require_checkin_before_work', models.BooleanField(
                    default=False,
                    help_text='Block staff from working until they scan the attendance QR code.',
                )),
                ('updated_at', models.DateTimeField(auto_now=True)),
                ('owner', models.OneToOneField(
                    on_delete=django.db.models.deletion.CASCADE,
                    related_name='attendance_policy',
                    to=settings.AUTH_USER_MODEL,
                )),
            ],
        ),
    ]
