from django.db import migrations


class Migration(migrations.Migration):
    """
    Adds a partial unique index on AttendanceQRToken(owner_id) WHERE restaurant_id IS NULL.
    PostgreSQL allows multiple NULLs under a regular UNIQUE constraint, so without this index
    a race condition can create duplicate QR tokens for single-restaurant owners.
    """

    dependencies = [
        ('attendance', '0003_attendancepolicy'),
    ]

    operations = [
        migrations.RunSQL(
            sql=(
                "CREATE UNIQUE INDEX IF NOT EXISTS att_qr_owner_null_restaurant "
                "ON attendance_attendanceqrtoken (owner_id) "
                "WHERE restaurant_id IS NULL;"
            ),
            reverse_sql="DROP INDEX IF EXISTS att_qr_owner_null_restaurant;",
        ),
    ]
