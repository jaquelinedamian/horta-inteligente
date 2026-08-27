from django.contrib import admin
from .models import (Crop, CropCultivationProfile, CropNutritionPlan, CropObservation, CropRequirement,
                     CropStageProfile, Cultivar, Fertilizer, Harvest, HarvestEvent, PlantingCycle,
                     SubstrateMaterial, SubstrateRecipe, SubstrateRecipeComponent)

admin.site.register([Crop, Cultivar, CropRequirement, PlantingCycle, CropObservation, Harvest,
                     CropCultivationProfile, CropStageProfile, SubstrateMaterial, SubstrateRecipe,
                     SubstrateRecipeComponent, Fertilizer, CropNutritionPlan, HarvestEvent])
