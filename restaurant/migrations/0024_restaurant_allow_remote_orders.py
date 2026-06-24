from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('restaurant', '0023_alter_event_owner'),
    ]

    operations = [
        migrations.AddField(
            model_name='restaurant',
            name='allow_remote_orders',
            field=models.BooleanField(
                default=False,
                help_text='Allow customers to place delivery/pickup orders from outside the restaurant (without scanning a QR code)',
            ),
        ),
    ]
