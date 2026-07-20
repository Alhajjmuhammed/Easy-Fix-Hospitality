from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('orders', '0017_delivery_rider_owner_nullable'),
    ]

    operations = [
        migrations.AddField(
            model_name='order',
            name='delivery_lat',
            field=models.DecimalField(blank=True, decimal_places=7, max_digits=10, null=True),
        ),
        migrations.AddField(
            model_name='order',
            name='delivery_lng',
            field=models.DecimalField(blank=True, decimal_places=7, max_digits=10, null=True),
        ),
    ]
