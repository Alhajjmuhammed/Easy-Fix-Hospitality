from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):

    dependencies = [
        ("restaurant", "0023_alter_event_owner"),
        ("orders", "0013_alter_orderitem_product"),
    ]

    operations = [
        migrations.AlterField(
            model_name="order",
            name="table_info",
            field=models.ForeignKey(
                blank=True,
                null=True,
                on_delete=django.db.models.deletion.SET_NULL,
                related_name="orders",
                to="restaurant.tableinfo",
            ),
        ),
    ]
