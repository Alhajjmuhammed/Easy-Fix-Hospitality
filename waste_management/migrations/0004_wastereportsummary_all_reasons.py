from django.db import migrations, models
from decimal import Decimal


class Migration(migrations.Migration):

    dependencies = [
        ('waste_management', '0003_alter_foodwastelog_order_item'),
    ]

    operations = [
        migrations.AddField(
            model_name='wastereportsummary',
            name='wrong_order_count',
            field=models.IntegerField(default=0),
        ),
        migrations.AddField(
            model_name='wastereportsummary',
            name='wrong_order_cost',
            field=models.DecimalField(decimal_places=2, default=Decimal('0.00'), max_digits=10),
        ),
        migrations.AddField(
            model_name='wastereportsummary',
            name='overcooking_count',
            field=models.IntegerField(default=0),
        ),
        migrations.AddField(
            model_name='wastereportsummary',
            name='overcooking_cost',
            field=models.DecimalField(decimal_places=2, default=Decimal('0.00'), max_digits=10),
        ),
        migrations.AddField(
            model_name='wastereportsummary',
            name='undercooking_count',
            field=models.IntegerField(default=0),
        ),
        migrations.AddField(
            model_name='wastereportsummary',
            name='undercooking_cost',
            field=models.DecimalField(decimal_places=2, default=Decimal('0.00'), max_digits=10),
        ),
        migrations.AddField(
            model_name='wastereportsummary',
            name='contamination_count',
            field=models.IntegerField(default=0),
        ),
        migrations.AddField(
            model_name='wastereportsummary',
            name='contamination_cost',
            field=models.DecimalField(decimal_places=2, default=Decimal('0.00'), max_digits=10),
        ),
        migrations.AddField(
            model_name='wastereportsummary',
            name='equipment_failure_count',
            field=models.IntegerField(default=0),
        ),
        migrations.AddField(
            model_name='wastereportsummary',
            name='equipment_failure_cost',
            field=models.DecimalField(decimal_places=2, default=Decimal('0.00'), max_digits=10),
        ),
        migrations.AddField(
            model_name='wastereportsummary',
            name='ingredient_expired_count',
            field=models.IntegerField(default=0),
        ),
        migrations.AddField(
            model_name='wastereportsummary',
            name='ingredient_expired_cost',
            field=models.DecimalField(decimal_places=2, default=Decimal('0.00'), max_digits=10),
        ),
        migrations.AddField(
            model_name='wastereportsummary',
            name='staff_error_count',
            field=models.IntegerField(default=0),
        ),
        migrations.AddField(
            model_name='wastereportsummary',
            name='staff_error_cost',
            field=models.DecimalField(decimal_places=2, default=Decimal('0.00'), max_digits=10),
        ),
        migrations.AddField(
            model_name='wastereportsummary',
            name='customer_complaint_count',
            field=models.IntegerField(default=0),
        ),
        migrations.AddField(
            model_name='wastereportsummary',
            name='customer_complaint_cost',
            field=models.DecimalField(decimal_places=2, default=Decimal('0.00'), max_digits=10),
        ),
        migrations.AddField(
            model_name='wastereportsummary',
            name='customer_left_count',
            field=models.IntegerField(default=0),
        ),
        migrations.AddField(
            model_name='wastereportsummary',
            name='customer_left_cost',
            field=models.DecimalField(decimal_places=2, default=Decimal('0.00'), max_digits=10),
        ),
    ]
