import math
import os
from datetime import time, timedelta

from django.core.management.base import BaseCommand, CommandError
from django.utils import timezone

from accounts.models import Membership, Organization, User
from crops.models import Crop, CropRequirement, Cultivar, PlantingCycle
from devices.models import Alert, AlertRule, Channel, Device, DeviceCommand, DeviceCredential, DeviceModel, LightingSchedule, TelemetryMetric, TelemetryReading
from gardens.models import Garden, GardenModule, ModuleInstallation, ModuleType
from operations.models import Assignment, InventoryCategory, InventoryItem, MaintenancePlan, Supplier, SupportTicket, Visit, WorkOrder, WorkTask
from subscriptions.models import Payment, Plan, PlanEntitlement, PlanFeature, PlanVersion, Subscription


class Command(BaseCommand):
    help = "Cria dados fictícios idempotentes para desenvolvimento e demonstração."

    def add_arguments(self, parser):
        parser.add_argument("--password", help="Senha dos usuários demo; prefira DEMO_PASSWORD.")
        parser.add_argument("--show-device-token", action="store_true", help="Rotaciona e exibe um token somente no terminal local.")

    def demo_user(self, email, name, password, **flags):
        user, _ = User.objects.update_or_create(email=email, defaults={"full_name": name, "is_active": True, **flags})
        user.set_password(password)
        user.save(update_fields=["password"])
        return user

    def membership(self, user, organization, role):
        Membership.objects.update_or_create(user=user, organization=organization, defaults={"role": role, "is_active": True})

    def plan(self, code, name, description, price_cents, module_limit, maintenance_days):
        plan, _ = Plan.objects.update_or_create(code=code, defaults={"name": name, "description": description, "is_active": True})
        version, _ = PlanVersion.objects.update_or_create(plan=plan, version=1, defaults={"price_cents": price_cents, "currency": "BRL", "billing_interval_months": 1, "effective_from": timezone.now(), "retired_at": None})
        features = {"modules": module_limit, "maintenance_interval_days": maintenance_days, "remote_monitoring": None, "periodic_visits": None}
        for key, limit in features.items():
            PlanFeature.objects.update_or_create(plan_version=version, key=key, defaults={"limit": limit, "enabled": True})
            label, unit = {"modules": ("Módulos simultâneos", "módulos"), "maintenance_interval_days": ("Manutenção preventiva", "dias"), "remote_monitoring": ("Monitoramento remoto", ""), "periodic_visits": ("Visitas periódicas", "visitas")}[key]
            PlanEntitlement.objects.update_or_create(plan_version=version, benefit_type=key, defaults={"name": label, "quantity": limit, "unit": unit, "unlimited": limit is None, "is_featured": True})
        return version

    def active_subscription(self, organization, plan_version, now):
        subscription = Subscription.objects.filter(organization=organization, status__in=[Subscription.Status.ACTIVE, Subscription.Status.TRIALING]).order_by("created_at").first()
        defaults = {"plan_version": plan_version, "status": Subscription.Status.ACTIVE, "current_period_start": now - timedelta(days=15), "current_period_end": now + timedelta(days=15), "canceled_at": None, "provider": "demo", "provider_reference": f"DEMO-{organization.slug}"}
        if subscription:
            for field, value in defaults.items(): setattr(subscription, field, value)
            subscription.save()
        else:
            subscription = Subscription.objects.create(organization=organization, **defaults)
        return subscription

    def garden(self, organization, code, name):
        return Garden.objects.update_or_create(organization=organization, code=code, defaults={"name": name, "is_active": True})[0]

    def device_channels(self, device):
        specs = [
            ("air-temperature", "Temperatura do ar", Channel.Kind.SENSOR, "air_temperature", "°C", Channel.ValueType.DECIMAL, "I2C", {"component": "BME280"}),
            ("air-humidity", "Umidade do ar", Channel.Kind.SENSOR, "air_humidity", "%RH", Channel.ValueType.DECIMAL, "I2C", {"component": "BME280"}),
            ("air-pressure", "Pressão atmosférica", Channel.Kind.SENSOR, "air_pressure", "hPa", Channel.ValueType.DECIMAL, "I2C", {"component": "BME280"}),
            ("water-level", "Nível do reservatório", Channel.Kind.SENSOR, "water_level", "%", Channel.ValueType.DECIMAL, "A0", {"component": "FD10", "adc_min": 0, "adc_max": 1023}),
            ("pump", "Bomba", Channel.Kind.ACTUATOR, "pump_state", "", Channel.ValueType.BOOLEAN, "D5", {"component": "relay_1ch", "active_low": True}),
            ("grow-light", "Grow light", Channel.Kind.ACTUATOR, "light_state", "", Channel.ValueType.BOOLEAN, "D6", {"component": "relay_1ch", "active_low": True}),
        ]
        channels = {}
        for key, name, kind, metric, unit, value_type, pin, configuration in specs:
            metric_definition, _ = TelemetryMetric.objects.update_or_create(code=metric, defaults={"name": name, "default_unit": unit, "data_type": value_type, "is_active": True})
            channels[key], _ = Channel.objects.update_or_create(device=device, key=key, defaults={"name": name, "kind": kind, "metric": metric, "metric_definition": metric_definition, "unit": unit, "value_type": value_type, "pin": pin, "configuration": configuration, "is_enabled": True})
        return channels

    def handle(self, *args, **options):
        password = options.get("password") or os.environ.get("DEMO_PASSWORD")
        if not password:
            raise CommandError("Defina DEMO_PASSWORD somente no ambiente de demonstração.")
        now = timezone.now()

        marina = self.demo_user("cliente@hortaviva.local", "Marina Oliveira", password)
        technician = self.demo_user("tecnico@hortaviva.local", "Carlos Mendes", password)
        self.demo_user("admin@hortaviva.local", "Ana Costa", password, is_staff=True, is_superuser=True)
        organization, _ = Organization.objects.update_or_create(slug="horta-viva-marina", defaults={"name": "Horta Viva — Marina Oliveira", "is_active": True})
        self.membership(marina, organization, Membership.Role.OWNER)
        self.membership(technician, organization, Membership.Role.TECHNICIAN)

        essential = self.plan("essencial", "Essencial", "Automação e cuidado para até três módulos.", 14990, 3, 30)
        family = self.plan("familia", "Família", "Mais variedade para toda a casa.", 22990, 6, 21)
        complete = self.plan("completo", "Completo", "Máxima variedade e acompanhamento prioritário.", 32990, 10, 15)
        subscription = self.active_subscription(organization, essential, now)

        crop_specs = [
            ("basil", "Manjericão", "Ocimum basilicum", "Aromático, vigoroso e perfeito para molhos frescos.", 45, 20, 29),
            ("parsley", "Salsinha", "Petroselinum crispum", "Versátil e delicada para a cozinha do dia a dia.", 60, 18, 27),
            ("chives", "Cebolinha", "Allium schoenoprasum", "Rebrota rápida e colheitas frequentes.", 50, 18, 28),
            ("coriander", "Coentro", "Coriandrum sativum", "Folhas perfumadas para receitas marcantes.", 45, 18, 28),
            ("oregano", "Orégano", "Origanum vulgare", "Erva mediterrânea compacta e aromática.", 70, 18, 27),
            ("thyme", "Tomilho", "Thymus vulgaris", "Aroma intenso e ótima adaptação indoor.", 75, 18, 27),
        ]
        cultivars = {}
        for code, common, scientific, description, days, minimum, maximum in crop_specs:
            crop, _ = Crop.objects.update_or_create(code=code, defaults={"common_name": common, "scientific_name": scientific, "description": description, "difficulty": "Fácil", "light_requirement": "6–10 horas/dia", "uses": "Culinária fresca e temperos cotidianos.", "is_available": True})
            cultivar, _ = Cultivar.objects.update_or_create(crop=crop, name="Padrão", defaults={"days_to_harvest": days})
            cultivars[code] = cultivar
            CropRequirement.objects.update_or_create(cultivar=cultivar, metric="air_temperature", defaults={"unit": "°C", "minimum": minimum, "maximum": maximum, "target": (minimum + maximum) / 2})
            CropRequirement.objects.update_or_create(cultivar=cultivar, metric="light_hours", defaults={"unit": "h/dia", "minimum": 6, "maximum": 10, "target": 8})

        garden = self.garden(organization, "principal", "Minha Horta")
        module_type, _ = ModuleType.objects.update_or_create(code="mvp-bed", defaults={"name": "Módulo HortaViva", "capabilities": ["environment", "water_level", "pump", "grow_light"]})
        modules = []
        for index in range(1, 4):
            status = GardenModule.Status.INSTALLED if index < 3 else GardenModule.Status.STOCK
            module, _ = GardenModule.objects.update_or_create(organization=organization, serial_number=f"MOD-DEMO-{index:03d}", defaults={"name": f"Módulo {index}", "module_type": module_type, "status": status})
            modules.append(module)
            if index < 3:
                ModuleInstallation.objects.get_or_create(module=module, removed_at=None, defaults={"garden": garden, "installed_at": now - timedelta(days=30 - index * 4), "position_label": f"Posição {index}"})
        PlantingCycle.objects.update_or_create(module=modules[0], cultivar=cultivars["basil"], status=PlantingCycle.Status.ACTIVE, defaults={"planted_at": now - timedelta(days=21), "expected_harvest_at": now + timedelta(days=24), "finished_at": None})
        PlantingCycle.objects.update_or_create(module=modules[1], cultivar=cultivars["chives"], status=PlantingCycle.Status.ACTIVE, defaults={"planted_at": now - timedelta(days=14), "expected_harvest_at": now + timedelta(days=36), "finished_at": None})

        model, _ = DeviceModel.objects.update_or_create(code="wemos-d1-mini-esp8266", defaults={"manufacturer": "Wemos", "name": "D1 Mini", "hardware_platform": "ESP8266", "capabilities": ["i2c", "analog", "digital_output", "wifi"]})
        device, _ = Device.objects.update_or_create(organization=organization, serial_number="HORTA-DEMO-001", defaults={"name": "Controlador principal", "model": model, "module": modules[0], "status": Device.Status.ONLINE, "last_seen_at": now, "firmware_version": "1.0.0"})
        channels = self.device_channels(device)
        LightingSchedule.objects.update_or_create(actuator=channels["grow-light"], name="Fotoperíodo padrão", defaults={"days_of_week": [0, 1, 2, 3, 4, 5, 6], "start_time": time(6), "end_time": time(20), "enabled": True})

        points = 84
        for point in range(points):
            recorded_at = now - timedelta(hours=(points - 1 - point) * 2)
            day_fraction = (point % 12) / 12
            temperature = 24.5 + 3.5 * math.sin(day_fraction * math.tau)
            humidity = 62 - 8 * math.sin(day_fraction * math.tau)
            pressure = 1010 + 8 * math.sin(point / 10)
            water = 100 - (point % 36) * 0.9
            values = {"air-temperature": temperature, "air-humidity": humidity, "air-pressure": pressure, "water-level": water}
            for key, value in values.items():
                TelemetryReading.objects.update_or_create(channel=channels[key], idempotency_key=f"demo-7d-{key}-{point}", defaults={"recorded_at": recorded_at, "decimal_value": round(value, 2), "quality": "good"})

        for offset in (6, 3, 1):
            command, _ = DeviceCommand.objects.update_or_create(device=device, idempotency_key=f"demo-irrigation-{offset}", defaults={"channel": channels["pump"], "command_type": "set_state", "payload": {"on": True, "mode": "safe_preset"}, "status": DeviceCommand.Status.SUCCEEDED, "delivered_at": now - timedelta(days=offset, minutes=2), "acknowledged_at": now - timedelta(days=offset), "result": {"completed": True}})
        DeviceCommand.objects.update_or_create(device=device, idempotency_key="demo-pump-current-off", defaults={"channel": channels["pump"], "command_type": "set_state", "payload": {"on": False}, "status": DeviceCommand.Status.SUCCEEDED, "delivered_at": now - timedelta(hours=1), "acknowledged_at": now - timedelta(hours=1), "result": {"relay": False}})

        maintenance_plan, _ = MaintenancePlan.objects.update_or_create(organization=organization, name="Inspeção mensal", defaults={"interval_days": 30, "checklist": ["Estrutura", "Bomba", "Iluminação", "Sensores", "Culturas"], "is_active": True})
        order_specs = [("demo-completed", "Revisão anterior", WorkOrder.Status.COMPLETED, now - timedelta(days=22)), ("demo-scheduled", "Manutenção preventiva + troca de cultura", WorkOrder.Status.SCHEDULED, now + timedelta(days=8)), ("demo-open", "Avaliar reposição do reservatório", WorkOrder.Status.OPEN, now + timedelta(days=20))]
        orders = {}
        for code, title, status, scheduled in order_specs:
            order, _ = WorkOrder.objects.update_or_create(organization=organization, garden=garden, title=title, defaults={"module": modules[0], "device": device, "maintenance_plan": maintenance_plan, "kind": WorkOrder.Kind.PREVENTIVE, "status": status, "scheduled_for": scheduled, "completed_at": scheduled if status == WorkOrder.Status.COMPLETED else None, "description": code})
            orders[code] = order
            Assignment.objects.update_or_create(work_order=order, user=technician, defaults={"assigned_at": now - timedelta(days=30)})
            WorkTask.objects.get_or_create(work_order=order, description="Verificar sensores", defaults={"position": 1})
        visit_specs = [("Visita concluída", orders["demo-completed"], now - timedelta(days=22), Visit.Status.COMPLETED), ("Manutenção preventiva + troca de cultura", orders["demo-scheduled"], now + timedelta(days=8), Visit.Status.SCHEDULED), ("Acompanhamento futuro", orders["demo-open"], now + timedelta(days=20), Visit.Status.SCHEDULED)]
        for visit_type, order, start, status in visit_specs:
            Visit.objects.update_or_create(organization=organization, garden=garden, work_order=order, defaults={"technician": technician, "visit_type": visit_type, "scheduled_start": start.replace(hour=9, minute=0, second=0, microsecond=0), "scheduled_end": start.replace(hour=10, minute=0, second=0, microsecond=0), "status": status})

        alert_specs = [("Irrigação concluída", channels["pump"], 1, "Irrigação concluída com sucesso."), ("Reservatório em 68%", channels["water-level"], 2, "Nível suficiente; acompanhe a próxima reposição."), ("Próxima visita agendada", channels["air-temperature"], 1, "Manutenção preventiva confirmada com Carlos Mendes.")]
        for name, channel, severity, message in alert_specs:
            rule, _ = AlertRule.objects.update_or_create(organization=organization, channel=channel, name=name, defaults={"operator": AlertRule.Operator.LT, "threshold": 0, "severity": severity, "cooldown_seconds": 86400, "is_active": False})
            Alert.objects.update_or_create(rule=rule, message=message, defaults={"status": Alert.Status.OPEN, "opened_at": now - timedelta(hours=severity)})

        for reference, due_at, status in [("DEMO-PAID-01", now - timedelta(days=60), Payment.Status.PAID), ("DEMO-PAID-02", now - timedelta(days=30), Payment.Status.PAID), ("DEMO-NEXT-01", now + timedelta(days=15), Payment.Status.PENDING)]:
            Payment.objects.update_or_create(subscription=subscription, provider_reference=reference, defaults={"amount_cents": 14990, "currency": "BRL", "status": status, "due_at": due_at, "paid_at": due_at if status == Payment.Status.PAID else None})
        SupportTicket.objects.update_or_create(organization=organization, opened_by=marina, subject="Dúvida sobre iluminação", defaults={"category": "Iluminação", "description": "Como funciona o modo automático da grow light?", "status": SupportTicket.Status.RESOLVED})
        SupportTicket.objects.update_or_create(organization=organization, opened_by=marina, subject="Acompanhar próxima visita", defaults={"category": "Solicitar visita", "description": "Gostaria de confirmar a próxima manutenção.", "status": SupportTicket.Status.OPEN})

        supplier, _ = Supplier.objects.update_or_create(name="Fornecedor Verde Demo", defaults={"email": "fornecedor@demo.local", "is_active": True})
        for sku, name, category, category_name, quantity in (("PUMP-5V", "Bomba compacta 5V", "pump", "Bombas", 8), ("BME280", "Sensor BME280", "sensor", "Sensores", 12), ("SUB-5L", "Substrato orgânico 5L", "substrate", "Substratos", 20)):
            inventory_category, _ = InventoryCategory.objects.get_or_create(name=category_name)
            InventoryItem.objects.update_or_create(sku=sku, defaults={"name": name, "category": category, "inventory_category": inventory_category, "primary_supplier": supplier, "quantity": quantity, "minimum_quantity": 5})
        for index in range(1, 5):
            extra_org, _ = Organization.objects.update_or_create(slug=f"cliente-demo-{index}", defaults={"name": f"Cliente Demonstração {index}", "is_active": True})
            self.active_subscription(extra_org, family if index % 2 else complete, now)
            self.garden(extra_org, "principal", f"Horta Demo {index}")

        scenarios = [
            ("semassinatura@hortaviva.local", "Cliente Sem Assinatura", "sem-assinatura", False, False, False),
            ("semhorta@hortaviva.local", "Cliente Sem Horta", "sem-horta", True, False, False),
            ("semdispositivo@hortaviva.local", "Cliente Sem Dispositivo", "sem-dispositivo", True, True, False),
            ("semtelemetria@hortaviva.local", "Cliente Sem Telemetria", "sem-telemetria", True, True, True),
        ]
        for email, name, slug, with_subscription, with_garden, with_device in scenarios:
            user = self.demo_user(email, name, password)
            org, _ = Organization.objects.update_or_create(slug=slug, defaults={"name": name, "is_active": True})
            self.membership(user, org, Membership.Role.OWNER)
            if with_subscription: self.active_subscription(org, essential, now)
            scenario_garden = self.garden(org, "principal", "Minha Horta") if with_garden else None
            if with_device:
                scenario_device, _ = Device.objects.update_or_create(organization=org, serial_number=f"DEVICE-{slug.upper()}", defaults={"name": "Controlador sem leituras", "model": model, "status": Device.Status.ONLINE, "last_seen_at": now})
                self.device_channels(scenario_device)

        active_credential = DeviceCredential.objects.filter(device=device, name="simulator", is_active=True).first()
        token = None
        if options.get("show_device_token"):
            DeviceCredential.objects.filter(device=device, name="simulator", is_active=True).update(is_active=False)
            _, token = DeviceCredential.issue(device, name="simulator")
        elif not active_credential:
            DeviceCredential.issue(device, name="simulator")

        self.stdout.write(self.style.SUCCESS("Demonstração criada/atualizada sem apagar dados existentes."))
        self.stdout.write("Usuários demo usam DEMO_PASSWORD; a senha não é exibida.")
        if token: self.stdout.write(f"DEVICE_API_TOKEN={token}")
        else: self.stdout.write("Token do simulador oculto. Use --show-device-token somente em ambiente local.")
