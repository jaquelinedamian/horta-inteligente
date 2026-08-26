from django.conf import settings
from django.db import models

from accounts.models import Organization
from core.models import BaseModel
from gardens.models import Garden, GardenModule


class MaintenancePlan(BaseModel):
    organization = models.ForeignKey(Organization, on_delete=models.CASCADE, related_name="maintenance_plans")
    name = models.CharField(max_length=120)
    interval_days = models.PositiveIntegerField()
    is_active = models.BooleanField(default=True)
    checklist = models.JSONField(default=list, blank=True)


class WorkOrder(BaseModel):
    class Kind(models.TextChoices):
        PREVENTIVE = "preventive", "Preventiva"
        CORRECTIVE = "corrective", "Corretiva"
        INSTALLATION = "installation", "Instalação"
    class Status(models.TextChoices):
        OPEN = "open", "Aberta"
        SCHEDULED = "scheduled", "Agendada"
        IN_PROGRESS = "in_progress", "Em andamento"
        COMPLETED = "completed", "Concluída"
        CANCELED = "canceled", "Cancelada"

    organization = models.ForeignKey(Organization, on_delete=models.CASCADE, related_name="work_orders")
    garden = models.ForeignKey(Garden, on_delete=models.PROTECT, related_name="work_orders")
    module = models.ForeignKey(GardenModule, on_delete=models.PROTECT, null=True, blank=True, related_name="work_orders")
    device = models.ForeignKey("devices.Device", on_delete=models.PROTECT, null=True, blank=True, related_name="work_orders")
    maintenance_plan = models.ForeignKey(MaintenancePlan, on_delete=models.SET_NULL, null=True, blank=True, related_name="work_orders")
    kind = models.CharField(max_length=20, choices=Kind.choices)
    status = models.CharField(max_length=20, choices=Status.choices, default=Status.OPEN)
    title = models.CharField(max_length=180)
    description = models.TextField(blank=True)
    priority = models.PositiveSmallIntegerField(default=3)
    scheduled_for = models.DateTimeField(null=True, blank=True)
    completed_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        indexes = [models.Index(fields=["organization", "status", "scheduled_for"])]

    def __str__(self):
        return self.title


class Assignment(BaseModel):
    work_order = models.ForeignKey(WorkOrder, on_delete=models.CASCADE, related_name="assignments")
    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name="work_assignments")
    assigned_at = models.DateTimeField()

    class Meta:
        constraints = [models.UniqueConstraint(fields=["work_order", "user"], name="uniq_work_order_assignee")]


class WorkTask(BaseModel):
    work_order = models.ForeignKey(WorkOrder, on_delete=models.CASCADE, related_name="tasks")
    description = models.CharField(max_length=255)
    position = models.PositiveSmallIntegerField(default=0)
    is_completed = models.BooleanField(default=False)
    completed_at = models.DateTimeField(null=True, blank=True)


class MaintenanceRecord(BaseModel):
    work_order = models.OneToOneField(WorkOrder, on_delete=models.PROTECT, related_name="record")
    performed_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name="maintenance_records")
    started_at = models.DateTimeField()
    finished_at = models.DateTimeField()
    notes = models.TextField(blank=True)
    parts_used = models.JSONField(default=list, blank=True)
    cost_cents = models.PositiveIntegerField(default=0)


class Incident(BaseModel):
    organization = models.ForeignKey(Organization, on_delete=models.CASCADE, related_name="incidents")
    garden = models.ForeignKey(Garden, on_delete=models.PROTECT, related_name="incidents")
    module = models.ForeignKey(GardenModule, on_delete=models.PROTECT, null=True, blank=True, related_name="incidents")
    device = models.ForeignKey("devices.Device", on_delete=models.PROTECT, null=True, blank=True, related_name="incidents")
    work_order = models.ForeignKey(WorkOrder, on_delete=models.SET_NULL, null=True, blank=True, related_name="incidents")
    title = models.CharField(max_length=180)
    description = models.TextField()
    severity = models.PositiveSmallIntegerField(default=2)
    occurred_at = models.DateTimeField()
    resolved_at = models.DateTimeField(null=True, blank=True)


class Visit(BaseModel):
    class Status(models.TextChoices):
        SCHEDULED = "scheduled", "Agendada"
        IN_PROGRESS = "in_progress", "Em andamento"
        COMPLETED = "completed", "Concluída"
        CANCELED = "canceled", "Cancelada"

    organization = models.ForeignKey(Organization, on_delete=models.CASCADE, related_name="visits")
    garden = models.ForeignKey(Garden, on_delete=models.PROTECT, related_name="visits")
    work_order = models.ForeignKey(WorkOrder, on_delete=models.SET_NULL, null=True, blank=True, related_name="visits")
    technician = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True, related_name="visits")
    visit_type = models.CharField(max_length=80)
    scheduled_start = models.DateTimeField()
    scheduled_end = models.DateTimeField()
    status = models.CharField(max_length=20, choices=Status.choices, default=Status.SCHEDULED)
    notes = models.TextField(blank=True)

    class Meta:
        indexes = [models.Index(fields=["technician", "scheduled_start", "status"])]

    def __str__(self):
        return f"{self.organization.name} — {self.scheduled_start:%d/%m/%Y %H:%M}"


class ChecklistExecution(BaseModel):
    visit = models.OneToOneField(Visit, on_delete=models.CASCADE, related_name="checklist_execution")
    items = models.JSONField(default=list)
    completed_at = models.DateTimeField(null=True, blank=True)


class SupportTicket(BaseModel):
    class Status(models.TextChoices):
        OPEN = "open", "Aberto"
        IN_PROGRESS = "in_progress", "Em atendimento"
        RESOLVED = "resolved", "Resolvido"

    organization = models.ForeignKey(Organization, on_delete=models.CASCADE, related_name="support_tickets")
    opened_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name="support_tickets")
    category = models.CharField(max_length=40)
    subject = models.CharField(max_length=180)
    description = models.TextField()
    status = models.CharField(max_length=20, choices=Status.choices, default=Status.OPEN)


class InventoryItem(BaseModel):
    class Category(models.TextChoices):
        MODULE = "module", "Módulo"
        SEEDLING = "seedling", "Muda"
        SUBSTRATE = "substrate", "Substrato"
        PUMP = "pump", "Bomba"
        SENSOR = "sensor", "Sensor"
        PART = "part", "Peça"

    name = models.CharField(max_length=120)
    sku = models.CharField(max_length=60, unique=True)
    category = models.CharField(max_length=20, choices=Category.choices)
    quantity = models.DecimalField(max_digits=12, decimal_places=2, default=0)
    minimum_quantity = models.DecimalField(max_digits=12, decimal_places=2, default=0)
    unit = models.CharField(max_length=20, default="un")
