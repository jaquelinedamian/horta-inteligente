from django.core.management.base import BaseCommand

from devices.models import Channel, Device
from devices.selectors import garden_snapshot
from devices.services import CANONICAL_ACTUATOR_CHANNELS
from gardens.models import Garden


class Command(BaseCommand):
    help = "Audita controladores e canais de atuadores sem alterar dados."

    def add_arguments(self, parser):
        parser.add_argument(
            "--disable-invalid",
            action="store_true",
            help="Desabilita explicitamente canais canônicos com métrica, pino ou dispositivo incorreto.",
        )

    def handle(self, *args, **options):
        invalid = []
        expected_pins = {"pump": "D5", "grow-light": "D6"}
        for garden in Garden.objects.select_related("organization").order_by("organization__name", "name"):
            snapshot = garden_snapshot(garden)
            controllers = snapshot["devices"]
            controllers = [item for item in controllers if item.kind == Device.Kind.CONTROLLER]
            self.stdout.write(f"HORTA {garden.id} | {garden.organization.name} | {garden.name}")
            self.stdout.write(
                "SNAPSHOT controller=%s pump_channel=%s light_channel=%s"
                % (
                    snapshot["controller"].id if snapshot["controller"] else "NONE/AMBIGUOUS",
                    snapshot["pump_channel"].id if snapshot["pump_channel"] else "NONE",
                    snapshot["light_channel"].id if snapshot["light_channel"] else "NONE",
                )
            )
            for device in controllers:
                self.stdout.write(
                    f"  CONTROLADOR id={device.id} name={device.name} kind={device.kind} "
                    f"garden={device.garden_id} module={device.module_id} status={device.status}"
                )
                for channel in device.channels.order_by("created_at"):
                    active_low = (channel.configuration or {}).get("active_low")
                    self.stdout.write(
                        f"    CANAL id={channel.id} key={channel.key} metric={channel.metric} "
                        f"pin={channel.pin} kind={channel.kind} enabled={channel.is_enabled} "
                        f"device_id={channel.device_id} active_low={active_low}"
                    )
                    if channel.key in CANONICAL_ACTUATOR_CHANNELS and (
                        channel.kind != Channel.Kind.ACTUATOR
                        or channel.metric != CANONICAL_ACTUATOR_CHANNELS[channel.key]
                        or channel.pin != expected_pins[channel.key]
                        or device.kind != Device.Kind.CONTROLLER
                    ):
                        invalid.append(channel)

        if options["disable_invalid"]:
            for channel in invalid:
                channel.is_enabled = False
                channel.save(update_fields=["is_enabled", "updated_at"])
                self.stdout.write(self.style.WARNING(f"DESABILITADO canal inconsistente {channel.id}"))

        if invalid:
            self.stderr.write(self.style.ERROR(f"{len(invalid)} canal(is) canônico(s) inconsistente(s)."))
        else:
            self.stdout.write(self.style.SUCCESS("Nenhum canal canônico inconsistente encontrado."))
