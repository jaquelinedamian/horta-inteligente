from django.db import migrations


def migrate_features(apps, schema_editor):
    Feature = apps.get_model("subscriptions", "PlanFeature")
    Entitlement = apps.get_model("subscriptions", "PlanEntitlement")
    labels = {
        "modules": ("Módulos simultâneos", "módulos"),
        "maintenance_interval_days": ("Intervalo de manutenção", "dias"),
        "remote_monitoring": ("Monitoramento remoto", ""),
        "periodic_visits": ("Visitas periódicas", "visitas"),
    }
    for feature in Feature.objects.filter(enabled=True).iterator():
        name, unit = labels.get(feature.key, (feature.key.replace("_", " ").title(), "unidades"))
        Entitlement.objects.get_or_create(
            plan_version=feature.plan_version,
            benefit_type=feature.key,
            defaults={"name": name, "quantity": feature.limit, "unit": unit, "unlimited": feature.limit is None},
        )


class Migration(migrations.Migration):
    dependencies = [("subscriptions", "0003_payment_competence_payment_discount_cents_and_more")]
    operations = [migrations.RunPython(migrate_features, migrations.RunPython.noop)]
