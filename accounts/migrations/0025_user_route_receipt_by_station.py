from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('accounts', '0024_add_delivery_rider_role'),
    ]

    operations = [
        migrations.AddField(
            model_name='user',
            name='route_receipt_by_station',
            field=models.BooleanField(
                default=False,
                help_text=(
                    'When ON, bills and receipts for single-station orders print at '
                    'that station\'s printer. Leave OFF for restaurants with one cashier.'
                ),
            ),
        ),
    ]
