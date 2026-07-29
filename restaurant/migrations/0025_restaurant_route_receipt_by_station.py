from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('restaurant', '0024_restaurant_allow_remote_orders'),
    ]

    operations = [
        migrations.AddField(
            model_name='restaurant',
            name='route_receipt_by_station',
            field=models.BooleanField(
                default=False,
                help_text=(
                    'When ON, bills and receipts for single-station orders print at '
                    'that station\'s printer (e.g. bar-only order → bar printer). '
                    'Leave OFF for restaurants with one cashier who handles all payments.'
                ),
            ),
        ),
    ]
