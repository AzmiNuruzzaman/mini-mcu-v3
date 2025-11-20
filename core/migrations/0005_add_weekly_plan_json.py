from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('core', '0004_rekomendasi_weekly_fields'),
    ]

    operations = [
        migrations.AddField(
            model_name='rekomendasikesehatan',
            name='weekly_plan',
            field=models.JSONField(blank=True, null=True),
        ),
    ]