from django.urls import path

from . import views

app_name = "device_api"

urlpatterns = [
    path("telemetry/", views.telemetry_v2, name="telemetry"),
    path("photo/", views.photo, name="photo"),
    path("config/", views.configuration, name="configuration"),
]
