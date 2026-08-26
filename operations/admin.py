from django.contrib import admin
from .models import (Assignment, ChecklistExecution, Incident, InventoryItem, MaintenancePlan,
                     MaintenanceRecord, SupportTicket, Visit, WorkOrder, WorkTask)

admin.site.register([MaintenancePlan, WorkOrder, Assignment, WorkTask, MaintenanceRecord,
                     Incident, Visit, ChecklistExecution, SupportTicket, InventoryItem])
