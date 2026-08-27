import uuid

from django.db import migrations


def populate_public_ids(apps, schema_editor):
    User = apps.get_model("accounts", "User")
    for user in User.objects.all().iterator():
        user.public_id = uuid.uuid4()
        user.save(update_fields=["public_id"])


class Migration(migrations.Migration):
    dependencies = [("accounts", "0002_address_access_instructions_address_access_notes_and_more")]
    operations = [migrations.RunPython(populate_public_ids, migrations.RunPython.noop)]
