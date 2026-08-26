from django.db import models

from accounts.models import Organization
from core.models import BaseModel


class Plan(BaseModel):
    name = models.CharField(max_length=100)
    code = models.SlugField(unique=True)
    description = models.TextField(blank=True)
    is_active = models.BooleanField(default=True)

    def __str__(self):
        return self.name


class PlanVersion(BaseModel):
    plan = models.ForeignKey(Plan, on_delete=models.PROTECT, related_name="versions")
    version = models.PositiveIntegerField()
    price_cents = models.PositiveIntegerField()
    currency = models.CharField(max_length=3, default="BRL")
    billing_interval_months = models.PositiveSmallIntegerField(default=1)
    effective_from = models.DateTimeField()
    retired_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        constraints = [models.UniqueConstraint(fields=["plan", "version"], name="uniq_plan_version")]

    def __str__(self):
        return f"{self.plan.name} v{self.version}"


class PlanFeature(BaseModel):
    plan_version = models.ForeignKey(PlanVersion, on_delete=models.CASCADE, related_name="features")
    key = models.SlugField(max_length=80)
    enabled = models.BooleanField(default=True)
    limit = models.PositiveIntegerField(null=True, blank=True)

    class Meta:
        constraints = [models.UniqueConstraint(fields=["plan_version", "key"], name="uniq_plan_feature")]


class Subscription(BaseModel):
    class Status(models.TextChoices):
        TRIALING = "trialing", "Em teste"
        ACTIVE = "active", "Ativa"
        PAST_DUE = "past_due", "Pagamento atrasado"
        SUSPENDED = "suspended", "Suspensa"
        CANCELED = "canceled", "Cancelada"

    organization = models.ForeignKey(Organization, on_delete=models.PROTECT, related_name="subscriptions")
    plan_version = models.ForeignKey(PlanVersion, on_delete=models.PROTECT, related_name="subscriptions")
    status = models.CharField(max_length=20, choices=Status.choices, default=Status.TRIALING)
    current_period_start = models.DateTimeField()
    current_period_end = models.DateTimeField()
    canceled_at = models.DateTimeField(null=True, blank=True)
    provider = models.CharField(max_length=40, blank=True)
    provider_reference = models.CharField(max_length=120, blank=True)

    class Meta:
        indexes = [models.Index(fields=["organization", "status"])]


class SubscriptionEvent(BaseModel):
    subscription = models.ForeignKey(Subscription, on_delete=models.CASCADE, related_name="events")
    event_type = models.CharField(max_length=60)
    payload = models.JSONField(default=dict, blank=True)
    occurred_at = models.DateTimeField()
    idempotency_key = models.CharField(max_length=120, unique=True, null=True, blank=True)


class Payment(BaseModel):
    class Status(models.TextChoices):
        PENDING = "pending", "Pendente"
        PAID = "paid", "Pago"
        FAILED = "failed", "Falhou"
        REFUNDED = "refunded", "Estornado"

    subscription = models.ForeignKey(Subscription, on_delete=models.PROTECT, related_name="payments")
    amount_cents = models.PositiveIntegerField()
    currency = models.CharField(max_length=3, default="BRL")
    status = models.CharField(max_length=20, choices=Status.choices, default=Status.PENDING)
    due_at = models.DateTimeField()
    paid_at = models.DateTimeField(null=True, blank=True)
    provider_reference = models.CharField(max_length=120, blank=True)


class CheckoutRequest(BaseModel):
    class Status(models.TextChoices):
        DRAFT = "draft", "Rascunho"
        CONFIRMED = "confirmed", "Confirmado"
        CANCELED = "canceled", "Cancelado"

    user = models.ForeignKey("accounts.User", on_delete=models.CASCADE, related_name="checkout_requests")
    plan_version = models.ForeignKey(PlanVersion, on_delete=models.PROTECT, related_name="checkout_requests")
    selected_cultures = models.ManyToManyField("crops.Cultivar", blank=True, related_name="checkout_requests")
    installation_data = models.JSONField(default=dict, blank=True)
    scheduled_for = models.DateTimeField(null=True, blank=True)
    status = models.CharField(max_length=20, choices=Status.choices, default=Status.DRAFT)
