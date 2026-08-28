from django.db import migrations, models


def copy_cultivars_to_crops(apps, schema_editor):
    CheckoutRequest = apps.get_model("subscriptions", "CheckoutRequest")
    through = CheckoutRequest.selected_crops.through
    for checkout in CheckoutRequest.objects.prefetch_related("selected_cultures__crop").iterator(chunk_size=500):
        crop_ids = {cultivar.crop_id for cultivar in checkout.selected_cultures.all()}
        through.objects.bulk_create(
            [through(checkoutrequest_id=checkout.pk, crop_id=crop_id) for crop_id in crop_ids],
            ignore_conflicts=True,
        )


class Migration(migrations.Migration):
    dependencies = [("subscriptions", "0004_migrate_plan_features")]
    operations = [
        migrations.AddField(
            model_name="checkoutrequest",
            name="selected_crops",
            field=models.ManyToManyField(blank=True, related_name="checkout_crop_requests", to="crops.crop"),
        ),
        migrations.RunPython(copy_cultivars_to_crops, migrations.RunPython.noop),
    ]
