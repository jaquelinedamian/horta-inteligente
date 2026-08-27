from django.db import migrations


def migrate_categories(apps, schema_editor):
    Category = apps.get_model("operations", "InventoryCategory")
    Item = apps.get_model("operations", "InventoryItem")
    labels = {"module": "Módulos", "seedling": "Mudas", "substrate": "Substratos", "pump": "Bombas", "sensor": "Sensores", "part": "Peças"}
    for item in Item.objects.all().iterator():
        category, _ = Category.objects.get_or_create(name=labels.get(item.category, item.category.title()))
        item.inventory_category = category
        item.save(update_fields=["inventory_category"])


class Migration(migrations.Migration):
    dependencies = [("operations", "0004_inventorycategory_supplier_and_more")]
    operations = [migrations.RunPython(migrate_categories, migrations.RunPython.noop)]
