from django.contrib import admin
from .models import (Alert, AlertRule, Channel, Device, DeviceCommand, DeviceCredential,
                     DeviceHeartbeat, DeviceModel, LightingSchedule, SensorCalibration,
                     TelemetryMetric, TelemetryReading)

@admin.register(Device)
class DeviceAdmin(admin.ModelAdmin):
    list_display = ("name", "serial_number", "organization", "model", "status", "firmware_version", "last_seen_at")
    list_filter = ("status", "model")
    search_fields = ("name", "serial_number", "organization__name")
    readonly_fields = ("last_seen_at", "created_at", "updated_at")

@admin.register(Channel)
class ChannelAdmin(admin.ModelAdmin):
    list_display = ("name", "device", "kind", "metric", "unit", "is_enabled")
    list_filter = ("kind", "is_enabled", "value_type")
    search_fields = ("name", "key", "metric", "device__name")

@admin.register(TelemetryReading)
class TelemetryAdmin(admin.ModelAdmin):
    list_display = ("channel", "recorded_at", "decimal_value", "boolean_value", "quality")
    list_filter = ("quality", "channel__metric")
    search_fields = ("channel__device__name", "channel__name", "idempotency_key")
    readonly_fields = tuple(field.name for field in TelemetryReading._meta.fields)

@admin.register(DeviceCredential)
class DeviceCredentialAdmin(admin.ModelAdmin):
    list_display = ("device", "name", "key_prefix", "is_active", "last_used_at", "expires_at")
    list_filter = ("is_active",)
    search_fields = ("device__name", "key_prefix")
    readonly_fields = ("key_prefix", "secret_hash", "last_used_at", "created_at", "updated_at")

@admin.register(Alert)
class AlertAdmin(admin.ModelAdmin):
    list_display = ("rule", "status", "opened_at", "acknowledged_at", "resolved_at")
    list_filter = ("status", "rule__severity")
    search_fields = ("rule__name", "message", "rule__organization__name")

admin.site.register([DeviceModel, DeviceHeartbeat, DeviceCommand, AlertRule, LightingSchedule,
                     TelemetryMetric, SensorCalibration])
