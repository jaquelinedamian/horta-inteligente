"""Transactional application services used by guided backoffice journeys.

Forms own input validation; these entry points own the transaction boundary.
They intentionally orchestrate existing domain models instead of introducing a
second set of "wizard" models.
"""

from django.db import transaction


@transaction.atomic
def _save_validated_form(form):
    if not form.is_valid():
        raise ValueError("The workflow service requires a validated form.")
    return form.save()


def create_commercial_plan(form):
    return _save_validated_form(form)


def create_customer(form):
    return _save_validated_form(form)


def create_crop_setup(form):
    return _save_validated_form(form)


def create_garden_installation(form):
    return _save_validated_form(form)


def create_physical_module(form):
    return _save_validated_form(form)


def create_employee(form):
    return _save_validated_form(form)


def create_inventory_supply(form):
    return _save_validated_form(form)


def create_device_setup(form):
    return _save_validated_form(form)


def schedule_visit(form):
    return _save_validated_form(form)


def create_work_order(form):
    return _save_validated_form(form)


SERVICES = {
    "plans": create_commercial_plan,
    "crops": create_crop_setup,
    "gardens": create_garden_installation,
    "modules": create_physical_module,
    "employees": create_employee,
    "inventory": create_inventory_supply,
    "devices": create_device_setup,
    "visits": schedule_visit,
    "orders": create_work_order,
}


def run_guided_workflow(section, form):
    return SERVICES.get(section, _save_validated_form)(form)
