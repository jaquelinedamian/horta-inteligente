from django.contrib import admin
from .models import (Assignment, ChecklistExecution, Incident, InventoryCategory, InventoryItem,
                     MaintenancePlan, MaintenanceRecord, MaintenanceTask, StockLot, StockMovement,
                     Supplier, SupportTicket, Visit, VisitMaterialUsage, WorkOrder, WorkTask)

admin.site.register([MaintenancePlan, WorkOrder, Assignment, WorkTask, MaintenanceRecord,
                     Incident, Visit, ChecklistExecution, SupportTicket, InventoryCategory,
                     InventoryItem, StockLot, StockMovement, Supplier, VisitMaterialUsage,
                     MaintenanceTask])
