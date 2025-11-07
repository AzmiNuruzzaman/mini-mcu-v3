from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ('core', '0002_rekomendasikesehatan'),
    ]

    operations = [
        # Drop karyawan_uid FK column (global recommendations are no longer tied to an employee)
        migrations.RemoveField(
            model_name='rekomendasikesehatan',
            name='karyawan_uid',
        ),
        # Drop created_at, keep updated_at
        migrations.RemoveField(
            model_name='rekomendasikesehatan',
            name='created_at',
        ),
        # Enforce unique per-parameter recommendations
        migrations.AlterField(
            model_name='rekomendasikesehatan',
            name='parameter',
            field=models.CharField(max_length=100, unique=True),
        ),
    ]