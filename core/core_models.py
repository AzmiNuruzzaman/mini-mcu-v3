# core/core_models.py
from django.db import models

# -------------------------
# Users
# -------------------------
class User(models.Model):
    id = models.AutoField(primary_key=True)
    username = models.CharField(max_length=100, unique=True)  # varchar
    password = models.TextField(blank=True, null=True)
    role = models.CharField(max_length=50)
    created_at = models.DateTimeField(blank=True, null=True)

    class Meta:
        db_table = "users"
        managed = False

    def __str__(self):
        return f"{self.username} ({self.role})"


# -------------------------
# Lokasi
# -------------------------
class Lokasi(models.Model):
    nama = models.TextField(primary_key=True)  # "nama" is the only column

    class Meta:
        db_table = "lokasi"
        managed = False

    def __str__(self):
        return self.nama


# -------------------------
# Karyawan
# -------------------------
class Karyawan(models.Model):
    uid = models.CharField(primary_key=True, max_length=64)
    nama = models.CharField(max_length=255, blank=True, null=True)
    jabatan = models.CharField(max_length=255, blank=True, null=True)
    lokasi = models.CharField(max_length=255, blank=True, null=True)
    tanggal_lahir = models.DateField(blank=True, null=True)
    # Add XLS-provided age (umur) to master data; do not auto-compute
    umur = models.IntegerField(blank=True, null=True)
    tanggal_MCU = models.DateField(blank=True, null=True)
    expired_MCU = models.DateField(blank=True, null=True)
    uploaded_at = models.DateTimeField(blank=True, null=True)
    upload_batch_id = models.CharField(max_length=64, blank=True, null=True)
    derajat_kesehatan = models.CharField(max_length=64, blank=True, null=True)
    tinggi = models.DecimalField(max_digits=5, decimal_places=2, blank=True, null=True)
    berat = models.DecimalField(max_digits=5, decimal_places=2, blank=True, null=True)
    bmi = models.DecimalField(max_digits=5, decimal_places=2, blank=True, null=True)
    bmi_category = models.CharField(max_length=64, blank=True, null=True)

    class Meta:
        managed = False
        db_table = 'karyawan'

    def __str__(self):
        return f"{self.nama} - {self.jabatan}"


# -------------------------
# Checkups
# -------------------------
class Checkup(models.Model):
    checkup_id = models.AutoField(primary_key=True)
    uid = models.ForeignKey(Karyawan, on_delete=models.CASCADE, db_column="uid")
    tanggal_checkup = models.DateField()
    tanggal_lahir = models.DateField(blank=True, null=True)
    umur = models.IntegerField(blank=True, null=True)
    tinggi = models.DecimalField(max_digits=6, decimal_places=2, blank=True, null=True)
    berat = models.DecimalField(max_digits=6, decimal_places=2, blank=True, null=True)
    lingkar_perut = models.DecimalField(max_digits=6, decimal_places=2, blank=True, null=True)
    bmi = models.DecimalField(max_digits=6, decimal_places=2, blank=True, null=True)
    gestational_diabetes = models.DecimalField(max_digits=6, decimal_places=2, blank=True, null=True)
    gula_darah_puasa = models.DecimalField(max_digits=6, decimal_places=2, blank=True, null=True)
    gula_darah_sewaktu = models.DecimalField(max_digits=6, decimal_places=2, blank=True, null=True)
    cholesterol = models.DecimalField(max_digits=6, decimal_places=2, blank=True, null=True)
    asam_urat = models.DecimalField(max_digits=6, decimal_places=2, blank=True, null=True)
    tekanan_darah = models.CharField(max_length=20, blank=True, null=True)
    status = models.CharField(max_length=50, blank=True, null=True)
    lokasi = models.CharField(max_length=100, blank=True, null=True)

    # 🟢 NEW FIELD (manual fill by manager/nurse)
    derajat_kesehatan = models.CharField(max_length=10, blank=True, null=True)

    class Meta:
        db_table = "checkups"
        managed = False

    def __str__(self):
        return f"Checkup {self.checkup_id} - {self.uid_id}"
