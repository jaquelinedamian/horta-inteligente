from django.urls import path

from . import views

app_name = "devices"

urlpatterns = [
    path("telemetry/", views.telemetry, name="telemetry"),
    path("heartbeat/", views.heartbeat, name="heartbeat"),
    path("commands/", views.commands, name="commands"),
    path("commands/<uuid:command_id>/ack/", views.acknowledge_command, name="acknowledge-command"),
]
