"""Dish stock never goes below 0 from now on (orders/stock.py). Dishes that were already oversold
(negative stock) start again at 0. Only rows below 0 are touched."""
from django.db import migrations


def clamp(apps, schema_editor):
    Product = apps.get_model('restaurant', 'Product')
    Product.objects.filter(available_in_stock__lt=0).update(available_in_stock=0)


class Migration(migrations.Migration):

    dependencies = [
        ('restaurant', '0029_table_number_per_restaurant'),
    ]

    operations = [
        migrations.RunPython(clamp, migrations.RunPython.noop),
    ]
