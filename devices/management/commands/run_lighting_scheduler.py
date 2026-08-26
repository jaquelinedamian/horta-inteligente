from django.core.management.base import BaseCommand

from devices.services import schedule_lighting


class Command(BaseCommand):
    help = "Materializa comandos de iluminação para o minuto atual. Execute periodicamente."

    def handle(self, *args, **options):
        self.stdout.write(f"{schedule_lighting()} comando(s) criado(s)")
