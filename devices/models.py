import hashlib
import secrets

from django.db import models
from django.db.models import Q

from accounts.models import Organization
from core.models import BaseModel
from gardens.models import GardenModule


class DeviceModel(BaseModel):
    manufacturer = models.CharField(max_length=100, blank=True)
    name = models.CharField(max_length=120)
    code = models.SlugField(unique=True)
    hardware_platform = models.CharField(max_length=80, blank=True)
    capabilities = models.JSONField(default=list, blank=True)

    def __str__(self):
        return self.name


class Device(BaseModel):
    class Status(models.TextChoices):
        PROVISIONING = "provisioning", "Em provisionamento"
        ONLINE = "online", "Online"
        OFFLINE = "offline", "Offline"
        MAINTENANCE = "maintenance", "Em manutenção"
        RETIRED = "retired", "Desativado"

    organization = models.ForeignKey(Organization, on_delete=models.CASCADE, related_name="devices")
    model = models.ForeignKey(DeviceModel, on_delete=models.PROTECT, related_name="devices")
    module = models.ForeignKey(GardenModule, on_delete=models.SET_NULL, null=True, blank=True, related_name="devices")
    serial_number = models.CharField(max_length=100)
    name = models.CharField(max_length=120)
    status = models.CharField(max_length=20, choices=Status.choices, default=Status.PROVISIONING)
    firmware_version = models.CharField(max_length=50, blank=True)
    last_seen_at = models.DateTimeField(null=True, blank=True)
    metadata = models.JSONField(default=dict, blank=True)

    class Meta:
        constraints = [models.UniqueConstraint(fields=["organization", "serial_number"], name="uniq_org_device_serial")]
        indexes = [models.Index(fields=["organization", "status"])]

    def __str__(self):
        return self.name


class TelemetryMetric(BaseModel):
    code = models.SlugField(max_length=80, unique=True)
    name = models.CharField(max_length=120)
    description = models.TextField(blank=True)
    default_unit = models.CharField(max_length=24, blank=True)
    data_type = models.CharField(max_length=16, choices=(("decimal", "Decimal"), ("boolean", "Booleano"), ("integer", "Inteiro"), ("text", "Texto")), default="decimal")
    minimum_expected = models.DecimalField(max_digits=18, decimal_places=6, null=True, blank=True)
    maximum_expected = models.DecimalField(max_digits=18, decimal_places=6, null=True, blank=True)
    is_active = models.BooleanField(default=True)

    def __str__(self):
        return f"{self.name} ({self.default_unit})" if self.default_unit else self.name


class DeviceCredential(BaseModel):
    device = models.ForeignKey(Device, on_delete=models.CASCADE, related_name="credentials")
    name = models.CharField(max_length=80, default="principal")
    key_prefix = models.CharField(max_length=16, db_index=True)
    secret_hash = models.CharField(max_length=64)
    is_active = models.BooleanField(default=True)
    last_used_at = models.DateTimeField(null=True, blank=True)
    expires_at = models.DateTimeField(null=True, blank=True)

    @staticmethod
    def hash_secret(secret):
        return hashlib.sha256(secret.encode("utf-8")).hexdigest()

    @classmethod
    def issue(cls, device, name="principal"):
        secret = secrets.token_urlsafe(32)
        prefix = secrets.token_hex(6)
        credential = cls.objects.create(
            device=device, name=name, key_prefix=prefix, secret_hash=cls.hash_secret(secret)
        )
        return credential, f"{prefix}.{secret}"


class Channel(BaseModel):
    class Kind(models.TextChoices):
        SENSOR = "sensor", "Sensor"
        ACTUATOR = "actuator", "Atuador"
    class ValueType(models.TextChoices):
        DECIMAL = "decimal", "Decimal"
        BOOLEAN = "boolean", "Booleano"
        INTEGER = "integer", "Inteiro"
        TEXT = "text", "Texto"

    device = models.ForeignKey(Device, on_delete=models.CASCADE, related_name="channels")
    key = models.SlugField(max_length=80)
    name = models.CharField(max_length=120)
    kind = models.CharField(max_length=16, choices=Kind.choices)
    metric = models.CharField(max_length=50)
    metric_definition = models.ForeignKey(TelemetryMetric, on_delete=models.SET_NULL, null=True, blank=True, related_name="channels")
    unit = models.CharField(max_length=24, blank=True)
    value_type = models.CharField(max_length=16, choices=ValueType.choices, default=ValueType.DECIMAL)
    pin = models.CharField(max_length=20, blank=True)
    configuration = models.JSONField(default=dict, blank=True)
    is_enabled = models.BooleanField(default=True)

    class Meta:
        constraints = [models.UniqueConstraint(fields=["device", "key"], name="uniq_device_channel")]

    def __str__(self):
        return f"{self.device.name} — {self.name}"


class TelemetryReading(BaseModel):
    channel = models.ForeignKey(Channel, on_delete=models.PROTECT, related_name="readings")
    recorded_at = models.DateTimeField()
    received_at = models.DateTimeField(auto_now_add=True)
    decimal_value = models.DecimalField(max_digits=18, decimal_places=6, null=True, blank=True)
    boolean_value = models.BooleanField(null=True, blank=True)
    text_value = models.TextField(blank=True)
    quality = models.CharField(max_length=30, default="good")
    idempotency_key = models.CharField(max_length=120)
    raw = models.JSONField(default=dict, blank=True)
    source = models.CharField(max_length=20, choices=(("device", "Dispositivo"), ("simulator", "Simulador"), ("manual", "Manual/teste"), ("import", "Importação")), default="device")
    notes = models.TextField(blank=True)

    class Meta:
        constraints = [models.UniqueConstraint(fields=["channel", "idempotency_key"], name="uniq_channel_ingestion")]
        indexes = [models.Index(fields=["channel", "recorded_at"])]


class DeviceHeartbeat(BaseModel):
    device = models.ForeignKey(Device, on_delete=models.CASCADE, related_name="heartbeats")
    recorded_at = models.DateTimeField()
    received_at = models.DateTimeField(auto_now_add=True)
    uptime_seconds = models.PositiveBigIntegerField(null=True, blank=True)
    signal_strength = models.SmallIntegerField(null=True, blank=True)
    free_heap_bytes = models.PositiveIntegerField(null=True, blank=True)
    firmware_version = models.CharField(max_length=50, blank=True)
    diagnostics = models.JSONField(default=dict, blank=True)

    class Meta:
        indexes = [models.Index(fields=["device", "recorded_at"])]


class SensorCalibration(BaseModel):
    channel = models.ForeignKey(Channel, on_delete=models.PROTECT, related_name="calibrations")
    calibrated_at = models.DateTimeField()
    reference_value = models.DecimalField(max_digits=18, decimal_places=6)
    measured_value = models.DecimalField(max_digits=18, decimal_places=6)
    offset = models.DecimalField(max_digits=18, decimal_places=6, default=0)
    scale_factor = models.DecimalField(max_digits=18, decimal_places=6, default=1)
    responsible = models.ForeignKey("accounts.User", on_delete=models.PROTECT, related_name="sensor_calibrations")
    next_calibration_at = models.DateTimeField(null=True, blank=True)
    notes = models.TextField(blank=True)

    def __str__(self):
        return f"{self.channel} — {self.calibrated_at:%d/%m/%Y}"


class DeviceCommand(BaseModel):
    class Status(models.TextChoices):
        PENDING = "pending", "Pendente"
        DELIVERED = "delivered", "Entregue"
        SUCCEEDED = "succeeded", "Executado"
        FAILED = "failed", "Falhou"
        EXPIRED = "expired", "Expirado"
        CANCELED = "canceled", "Cancelado"

    device = models.ForeignKey(Device, on_delete=models.CASCADE, related_name="commands")
    channel = models.ForeignKey(Channel, on_delete=models.PROTECT, null=True, blank=True, related_name="commands")
    command_type = models.CharField(max_length=60)
    payload = models.JSONField(default=dict, blank=True)
    status = models.CharField(max_length=20, choices=Status.choices, default=Status.PENDING)
    idempotency_key = models.CharField(max_length=120)
    not_before = models.DateTimeField(null=True, blank=True)
    expires_at = models.DateTimeField(null=True, blank=True)
    delivered_at = models.DateTimeField(null=True, blank=True)
    acknowledged_at = models.DateTimeField(null=True, blank=True)
    result = models.JSONField(default=dict, blank=True)

    class Meta:
        constraints = [models.UniqueConstraint(fields=["device", "idempotency_key"], name="uniq_device_command")]
        indexes = [models.Index(fields=["device", "status", "not_before"])]


class AlertRule(BaseModel):
    class Operator(models.TextChoices):
        LT = "lt", "Menor que"
        LTE = "lte", "Menor ou igual"
        GT = "gt", "Maior que"
        GTE = "gte", "Maior ou igual"
        EQ = "eq", "Igual"

    organization = models.ForeignKey(Organization, on_delete=models.CASCADE, related_name="alert_rules")
    channel = models.ForeignKey(Channel, on_delete=models.CASCADE, related_name="alert_rules")
    name = models.CharField(max_length=120)
    operator = models.CharField(max_length=4, choices=Operator.choices)
    threshold = models.DecimalField(max_digits=18, decimal_places=6)
    severity = models.PositiveSmallIntegerField(default=2)
    cooldown_seconds = models.PositiveIntegerField(default=900)
    is_active = models.BooleanField(default=True)


class Alert(BaseModel):
    class Status(models.TextChoices):
        OPEN = "open", "Aberto"
        ACKNOWLEDGED = "acknowledged", "Reconhecido"
        RESOLVED = "resolved", "Resolvido"

    rule = models.ForeignKey(AlertRule, on_delete=models.PROTECT, related_name="alerts")
    reading = models.ForeignKey(TelemetryReading, on_delete=models.PROTECT, null=True, blank=True, related_name="alerts")
    status = models.CharField(max_length=20, choices=Status.choices, default=Status.OPEN)
    message = models.CharField(max_length=255)
    opened_at = models.DateTimeField()
    acknowledged_at = models.DateTimeField(null=True, blank=True)
    resolved_at = models.DateTimeField(null=True, blank=True)


class LightingSchedule(BaseModel):
    actuator = models.ForeignKey(Channel, on_delete=models.CASCADE, related_name="lighting_schedules")
    name = models.CharField(max_length=100)
    timezone = models.CharField(max_length=64, default="America/Sao_Paulo")
    days_of_week = models.JSONField(default=list, help_text="0=segunda-feira, 6=domingo")
    start_time = models.TimeField()
    end_time = models.TimeField()
    enabled = models.BooleanField(default=True)
