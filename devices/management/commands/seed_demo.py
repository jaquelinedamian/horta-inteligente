import os
from datetime import time, timedelta

from django.core.management.base import BaseCommand, CommandError
from django.utils import timezone

from accounts.models import Membership, Organization, User
from crops.models import Crop, CropRequirement, Cultivar, PlantingCycle
from devices.models import Alert, AlertRule, Channel, Device, DeviceCredential, DeviceModel, LightingSchedule, TelemetryReading
from gardens.models import Garden, GardenModule, ModuleInstallation, ModuleType
from operations.models import Assignment, InventoryItem, MaintenancePlan, Visit, WorkOrder, WorkTask
from subscriptions.models import Payment, Plan, PlanFeature, PlanVersion, Subscription


class Command(BaseCommand):
    help = "Cria uma demonstração navegável e emite uma credencial para o simulador."

    def add_arguments(self, parser):
        parser.add_argument("--password", help="Senha dos usuários demo; prefira a variável DEMO_PASSWORD.")
        parser.add_argument("--show-device-token", action="store_true", help="Exibe o token recém-emitido somente no terminal local.")

    def set_password_if_new(self, user, created, password):
        if created or not user.has_usable_password():
            user.set_password(password)
            user.save(update_fields=["password"])

    def handle(self, *args, **options):
        demo_password = options.get("password") or os.environ.get("DEMO_PASSWORD")
        if not demo_password:
            raise CommandError("Defina DEMO_PASSWORD apenas no ambiente local para executar o seed.")
        now = timezone.now()
        customer, created = User.objects.get_or_create(email="cliente@hortaviva.local", defaults={"full_name": "Marina Oliveira", "phone": "11988887777"})
        self.set_password_if_new(customer, created, demo_password)
        technician, created = User.objects.get_or_create(email="tecnico@hortaviva.local", defaults={"full_name": "Carlos Mendes", "phone": "11999990000"})
        self.set_password_if_new(technician, created, demo_password)
        admin_user, created = User.objects.get_or_create(email="admin@hortaviva.local", defaults={"full_name": "Ana Gestora", "is_staff": True, "is_superuser": True})
        self.set_password_if_new(admin_user, created, demo_password)

        org, _ = Organization.objects.get_or_create(slug="horta-demo", defaults={"name": "Residência Oliveira"})
        Membership.objects.get_or_create(organization=org, user=customer, defaults={"role": Membership.Role.OWNER})
        Membership.objects.get_or_create(organization=org, user=technician, defaults={"role": Membership.Role.TECHNICIAN})

        plan, _ = Plan.objects.get_or_create(code="essencial", defaults={"name": "Essencial", "description": "Tudo para cultivar com tranquilidade."})
        version, _ = PlanVersion.objects.get_or_create(plan=plan, version=1, defaults={"price_cents": 9900, "effective_from": now})
        for key, limit in (("hortas", 1), ("módulos", 3), ("manutenção mensal", 1), ("retenção de telemetria", 90)):
            PlanFeature.objects.get_or_create(plan_version=version, key=key, defaults={"limit": limit})
        subscription, _ = Subscription.objects.get_or_create(organization=org, status=Subscription.Status.ACTIVE, defaults={"plan_version": version, "current_period_start": now, "current_period_end": now + timedelta(days=30)})
        Payment.objects.get_or_create(subscription=subscription, provider_reference="SIM-DEMO-001", defaults={"amount_cents": version.price_cents, "status": Payment.Status.PAID, "due_at": now, "paid_at": now})

        garden, _ = Garden.objects.get_or_create(organization=org, code="principal", defaults={"name": "Horta da Cozinha"})
        module_type, _ = ModuleType.objects.get_or_create(code="mvp-bed", defaults={"name": "Módulo HortaViva", "capabilities": ["environment", "water_level", "pump", "grow_light"]})
        module, _ = GardenModule.objects.get_or_create(organization=org, serial_number="MOD-DEMO-001", defaults={"name": "Módulo principal", "module_type": module_type, "status": GardenModule.Status.INSTALLED})
        ModuleInstallation.objects.get_or_create(module=module, removed_at=None, defaults={"garden": garden, "installed_at": now - timedelta(days=21)})

        crop_specs = [("basil", "Manjericão", "Ocimum basilicum", "Aromático e perfeito para molhos frescos.", 45), ("parsley", "Salsinha", "Petroselinum crispum", "Versátil, delicada e presente em toda cozinha.", 60), ("chives", "Cebolinha", "Allium schoenoprasum", "Crescimento vigoroso e colheitas frequentes.", 50)]
        cultivars = []
        for code, common, scientific, description, days in crop_specs:
            crop, _ = Crop.objects.get_or_create(code=code, defaults={"common_name": common, "scientific_name": scientific, "description": description, "difficulty": "Fácil", "light_requirement": "6–10 horas/dia", "uses": "Culinária fresca e temperos do dia a dia."})
            cultivar, _ = Cultivar.objects.get_or_create(crop=crop, name="Padrão", defaults={"days_to_harvest": days})
            cultivars.append(cultivar)
        CropRequirement.objects.get_or_create(cultivar=cultivars[0], metric="air_temperature", defaults={"unit": "°C", "minimum": 15, "maximum": 28})
        PlantingCycle.objects.get_or_create(module=module, cultivar=cultivars[0], status=PlantingCycle.Status.ACTIVE, defaults={"planted_at": now - timedelta(days=21), "expected_harvest_at": now + timedelta(days=24)})

        model, _ = DeviceModel.objects.get_or_create(code="wemos-d1-mini-esp8266", defaults={"manufacturer": "Wemos", "name": "D1 Mini", "hardware_platform": "ESP8266", "capabilities": ["i2c", "analog", "digital_output", "wifi"]})
        device, _ = Device.objects.get_or_create(organization=org, serial_number="ESP-DEMO-001", defaults={"name": "Controlador da cozinha", "model": model, "module": module, "status": Device.Status.ONLINE, "last_seen_at": now, "firmware_version": "1.0.0"})
        specs = [("air-temperature", "Temperatura do ar", "sensor", "air_temperature", "°C", "decimal", "I2C", {"component": "BME280"}), ("air-humidity", "Umidade do ar", "sensor", "air_humidity", "%RH", "decimal", "I2C", {"component": "BME280"}), ("air-pressure", "Pressão atmosférica", "sensor", "air_pressure", "hPa", "decimal", "I2C", {"component": "BME280"}), ("water-level", "Nível de água", "sensor", "water_level", "%", "decimal", "A0", {"component": "FD10", "adc_min": 0, "adc_max": 1023}), ("pump", "Bomba", "actuator", "pump_state", "", "boolean", "D5", {"component": "relay_1ch", "active_low": True}), ("grow-light", "Grow light", "actuator", "light_state", "", "boolean", "D6", {"component": "relay_1ch", "active_low": True})]
        channels = {}
        for key, name, kind, metric, unit, value_type, pin, configuration in specs:
            channels[key], _ = Channel.objects.get_or_create(device=device, key=key, defaults={"name": name, "kind": kind, "metric": metric, "unit": unit, "value_type": value_type, "pin": pin, "configuration": configuration})
        LightingSchedule.objects.get_or_create(actuator=channels["grow-light"], name="Fotoperíodo padrão", defaults={"days_of_week": [0, 1, 2, 3, 4, 5, 6], "start_time": time(6), "end_time": time(20)})
        rule, _ = AlertRule.objects.get_or_create(organization=org, channel=channels["water-level"], name="Reservatório baixo", defaults={"operator": AlertRule.Operator.LT, "threshold": 25, "severity": 3})
        for hour in range(48):
            recorded_at = now - timedelta(hours=47 - hour)
            for key, base in (("air-temperature", 24.2), ("air-humidity", 67), ("air-pressure", 1008.4), ("water-level", 78)):
                value = base + ((hour % 7) - 3) * (0.35 if key != "water-level" else 0.7)
                TelemetryReading.objects.get_or_create(channel=channels[key], idempotency_key=f"demo-{key}-{hour}", defaults={"recorded_at": recorded_at, "decimal_value": value})
        reading = TelemetryReading.objects.filter(channel=channels["water-level"]).order_by("-recorded_at").first()
        Alert.objects.get_or_create(rule=rule, reading=reading, defaults={"message": "Reservatório monitorado — abastecimento recomendado em breve.", "opened_at": now - timedelta(hours=2)})

        maintenance_plan, _ = MaintenancePlan.objects.get_or_create(organization=org, name="Inspeção mensal", defaults={"interval_days": 30, "checklist": ["Verificar bomba", "Limpar sensores"]})
        work_order, _ = WorkOrder.objects.get_or_create(organization=org, garden=garden, title="Revisão mensal da horta", defaults={"module": module, "device": device, "maintenance_plan": maintenance_plan, "kind": WorkOrder.Kind.PREVENTIVE, "status": WorkOrder.Status.SCHEDULED, "scheduled_for": now + timedelta(days=2)})
        WorkTask.objects.get_or_create(work_order=work_order, description="Validar leituras do BME280", defaults={"position": 1})
        WorkTask.objects.get_or_create(work_order=work_order, description="Testar relé da bomba", defaults={"position": 2})
        Assignment.objects.get_or_create(work_order=work_order, user=technician, defaults={"assigned_at": now})
        Visit.objects.get_or_create(organization=org, garden=garden, work_order=work_order, defaults={"technician": technician, "visit_type": "Manutenção preventiva", "scheduled_start": now + timedelta(days=2), "scheduled_end": now + timedelta(days=2, hours=1)})
        for sku, name, category, quantity in (("PUMP-5V", "Bomba compacta 5V", "pump", 8), ("BME280", "Sensor BME280", "sensor", 12), ("SUB-5L", "Substrato orgânico 5L", "substrate", 20)):
            InventoryItem.objects.get_or_create(sku=sku, defaults={"name": name, "category": category, "quantity": quantity, "minimum_quantity": 5})

        DeviceCredential.objects.filter(device=device, name="simulator").update(is_active=False)
        _, token = DeviceCredential.issue(device, name="simulator")
        self.stdout.write(self.style.SUCCESS("Demonstração criada."))
        self.stdout.write("Usuários demo criados. A senha não é exibida.")
        if options.get("show_device_token"):
            self.stdout.write(f"DEVICE_API_TOKEN={token}")
        else:
            self.stdout.write("Credencial do simulador emitida e ocultada. Use --show-device-token apenas localmente se necessário.")
