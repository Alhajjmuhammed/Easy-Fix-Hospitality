from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('accounts', '0027_admin_staff_permissions'),
    ]

    operations = [
        migrations.AddField(
            model_name='restaurantsubscription',
            name='disabled_features',
            field=models.ManyToManyField(
                blank=True,
                help_text='Features the system admin has disabled for this restaurant.',
                related_name='restricted_subscriptions',
                to='accounts.feature',
            ),
        ),
    ]
