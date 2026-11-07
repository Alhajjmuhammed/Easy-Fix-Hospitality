"""Stock records entered by hand stored the TOTAL paid in unit_price (the form asked for the total),
while purchase-order deliveries stored a real per-unit price. unit_price now always means per unit
(totals are |quantity| x unit_price), so the hand-entered ones are converted once:
unit_price = total / |quantity|, rounded half-up to the cent.

Only rows with no purchase-order line and no linked customer order are touched (those two kinds
always stored per-unit prices). Rows without a price or with a zero quantity are left alone."""
from decimal import Decimal, ROUND_HALF_UP

from django.db import migrations

CENT = Decimal('0.01')


def to_per_unit(apps, schema_editor):
    Record = apps.get_model('inventory', 'InventoryRecord')
    rows = Record.objects.filter(purchase_line__isnull=True, source_order__isnull=True,
                                 unit_price__isnull=False).exclude(quantity_change=0)
    for r in rows.iterator():
        per_unit = (Decimal(r.unit_price) / abs(Decimal(r.quantity_change))).quantize(CENT, ROUND_HALF_UP)
        Record.objects.filter(pk=r.pk).update(unit_price=per_unit)


def to_total(apps, schema_editor):
    Record = apps.get_model('inventory', 'InventoryRecord')
    rows = Record.objects.filter(purchase_line__isnull=True, source_order__isnull=True,
                                 unit_price__isnull=False).exclude(quantity_change=0)
    for r in rows.iterator():
        total = (Decimal(r.unit_price) * abs(Decimal(r.quantity_change))).quantize(CENT, ROUND_HALF_UP)
        Record.objects.filter(pk=r.pk).update(unit_price=total)


class Migration(migrations.Migration):

    dependencies = [
        ('inventory', '0007_recipes'),
    ]

    operations = [
        migrations.RunPython(to_per_unit, to_total),
    ]
