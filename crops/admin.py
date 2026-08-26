from django.contrib import admin
from .models import Crop, CropObservation, CropRequirement, Cultivar, Harvest, PlantingCycle

admin.site.register([Crop, Cultivar, CropRequirement, PlantingCycle, CropObservation, Harvest])
