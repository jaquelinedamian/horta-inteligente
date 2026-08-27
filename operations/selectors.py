from .models import Visit, WorkOrder


def get_customer_visits(organization):
    return Visit.objects.filter(organization=organization).select_related("technician", "garden", "work_order").order_by("-scheduled_start")


def get_technician_visits(user):
    return Visit.objects.filter(technician=user).select_related("organization", "garden", "work_order").order_by("scheduled_start")


def get_technician_orders(user):
    return WorkOrder.objects.filter(assignments__user=user).select_related("organization", "garden", "device").distinct()
