from django.contrib import admin
from .models import Garden, GardenMember, GardenModule, ModuleInstallation, ModuleType

admin.site.register([Garden, GardenMember, GardenModule, ModuleInstallation, ModuleType])
