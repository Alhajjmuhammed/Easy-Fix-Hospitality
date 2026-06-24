from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('orders', '0014_alter_order_table_info_nullable'),
    ]

    operations = [
        migrations.AddField(
            model_name='order',
            name='order_type',
            field=models.CharField(
                choices=[('dine-in', 'Dine In'), ('delivery', 'Delivery'), ('pickup', 'Pickup')],
                default='dine-in',
                max_length=20,
            ),
        ),
        migrations.AddField(
            model_name='order',
            name='delivery_address',
            field=models.TextField(blank=True, default=''),
        ),
        migrations.AddField(
            model_name='order',
            name='delivery_phone',
            field=models.CharField(blank=True, default='', max_length=30),
        ),
    ]
