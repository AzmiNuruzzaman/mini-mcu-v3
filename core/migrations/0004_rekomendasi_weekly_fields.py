from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('core', '0003_update_rekomendasi_global'),
    ]

    operations = [
        migrations.AddField(
            model_name='rekomendasikesehatan',
            name='senin_text',
            field=models.TextField(blank=True, null=True),
        ),
        migrations.AddField(
            model_name='rekomendasikesehatan',
            name='selasa_text',
            field=models.TextField(blank=True, null=True),
        ),
        migrations.AddField(
            model_name='rekomendasikesehatan',
            name='rabu_text',
            field=models.TextField(blank=True, null=True),
        ),
        migrations.AddField(
            model_name='rekomendasikesehatan',
            name='kamis_text',
            field=models.TextField(blank=True, null=True),
        ),
        migrations.AddField(
            model_name='rekomendasikesehatan',
            name='jumat_text',
            field=models.TextField(blank=True, null=True),
        ),
        migrations.AddField(
            model_name='rekomendasikesehatan',
            name='sabtu_text',
            field=models.TextField(blank=True, null=True),
        ),
        migrations.AddField(
            model_name='rekomendasikesehatan',
            name='minggu_text',
            field=models.TextField(blank=True, null=True),
        ),
    ]