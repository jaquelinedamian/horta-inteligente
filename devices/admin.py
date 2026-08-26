from django.contrib import admin
from .models import (
    Alert, AlertRule, Channel, Device, DeviceCommand, DeviceCredential,
    DeviceHeartbeat, DeviceModel, LightingSchedule, TelemetryReading,
)

admin.site.register([
    DeviceModel, Device, DeviceCredential, Channel, TelemetryReading,
    DeviceHeartbeat, DeviceCommand, AlertRule, Alert, LightingSchedule,
])
