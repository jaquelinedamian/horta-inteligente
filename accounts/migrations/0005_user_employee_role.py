from django.db import migrations, models


def migrate_employee_roles(apps, schema_editor):
    User = apps.get_model("accounts", "User")
    Membership = apps.get_model("accounts", "Membership")
    User.objects.filter(is_staff=True, employee_role__isnull=True).update(employee_role="admin")
    technician_ids = Membership.objects.filter(role="technician", is_active=True).values_list("user_id", flat=True)
    User.objects.filter(id__in=technician_ids, employee_role__isnull=True).update(employee_role="technician")


class Migration(migrations.Migration):
    dependencies = [("accounts", "0004_alter_user_public_id")]
    operations = [
        migrations.AddField(
            model_name="user", name="employee_role",
            field=models.CharField(blank=True, choices=[("admin", "Administrador"), ("technician", "Técnico"), ("stock", "Estoque")], max_length=20, null=True),
        ),
        migrations.RunPython(migrate_employee_roles, migrations.RunPython.noop),
    ]
