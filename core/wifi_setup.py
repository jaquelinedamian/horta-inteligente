from accounts.models import Membership, User
from devices.models import Device


def can_configure_wifi(user, garden):
    return bool(
        user.is_authenticated
        and (
            user.is_hortaviva_admin
            or user.employee_role == User.EmployeeRole.TECHNICIAN
            or user.memberships.filter(
                organization=garden.organization,
                is_active=True,
                role__in=[Membership.Role.OWNER, Membership.Role.MANAGER],
            ).exists()
        )
    )


def _signal_label(rssi):
    if rssi is None:
        return "Não informado"
    if rssi >= -55:
        return "Excelente"
    if rssi >= -67:
        return "Bom"
    return "Fraco"


def wifi_device_status(device):
    if not device:
        return None
    heartbeat = device.heartbeats.order_by("-recorded_at").first()
    diagnostics = heartbeat.diagnostics if heartbeat and isinstance(heartbeat.diagnostics, dict) else {}
    default_prefix = "HortaCam" if device.kind == Device.Kind.CAMERA else "Horta"
    fallback_suffix = (device.serial_number or str(device.id)).replace("-", "")[-4:].upper()
    return {
        "device": device,
        "online": device.is_online,
        "ssid": diagnostics.get("ssid") or "Não informado",
        "setup_ap": diagnostics.get("setup_ap") or f"{default_prefix}-{fallback_suffix}",
        "local_ip": device.local_ip,
        "last_seen_at": device.last_seen_at,
        "rssi": heartbeat.signal_strength if heartbeat else None,
        "signal_label": _signal_label(heartbeat.signal_strength if heartbeat else None),
    }


def garden_wifi_context(user, garden, snapshot):
    controller = wifi_device_status(snapshot.get("controller"))
    camera = wifi_device_status(snapshot.get("camera"))
    return {
        "garden": garden,
        "controller": controller,
        "camera": camera,
        "devices": [item for item in (controller, camera) if item],
        "can_configure": can_configure_wifi(user, garden),
    }
