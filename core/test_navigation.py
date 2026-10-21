from django.test import TestCase
from django.urls import reverse

from accounts.models import Membership, Organization, User
from devices.models import Device, DeviceModel
from gardens.models import Garden


class PortalNavigationTests(TestCase):
    def setUp(self):
        self.organization = Organization.objects.create(name="Navegação", slug="navegacao")
        self.admin = User.objects.create_user(
            email="nav-admin@test.local", password="test", full_name="Admin",
            employee_role=User.EmployeeRole.ADMIN,
        )
        self.technician = User.objects.create_user(
            email="nav-tech@test.local", password="test", full_name="Técnico",
            employee_role=User.EmployeeRole.TECHNICIAN,
        )
        self.owner = User.objects.create_user(email="nav-owner@test.local", password="test", full_name="Owner")
        self.viewer = User.objects.create_user(email="nav-viewer@test.local", password="test", full_name="Viewer")
        Membership.objects.create(user=self.owner, organization=self.organization, role=Membership.Role.OWNER)
        Membership.objects.create(user=self.viewer, organization=self.organization, role=Membership.Role.VIEWER)
        self.garden = Garden.objects.create(
            organization=self.organization, name="Horta navegável", code="horta-navegavel",
            primary_technician=self.technician,
        )
        model = DeviceModel.objects.create(name="ESP8266", code="nav-esp8266")
        self.device = Device.objects.create(
            organization=self.organization, garden=self.garden, model=model,
            serial_number="NAV-ESP-1", name="Controlador",
        )

    def assert_accessible(self, route_name, *args):
        response = self.client.get(reverse(route_name, args=args))
        self.assertNotIn(response.status_code, {403, 404}, (route_name, response.status_code))
        return response

    def test_admin_keeps_admin_sidebar_on_shared_garden_pages(self):
        self.client.force_login(self.admin)
        for route_name in ("garden-detail", "garden-gallery", "garden-reports", "garden-configuration"):
            response = self.assert_accessible(route_name, self.garden.pk)
            self.assertContains(response, reverse("ops-dashboard"))
            self.assertContains(response, reverse("ops-collection", args=["clients"]))
            self.assertNotContains(response, reverse("customer-section", args=["garden"]))

        for route_name, args in (
            ("ops-dashboard", ()), ("ops-collection", ("clients",)),
            ("ops-collection", ("gardens",)), ("ops-collection", ("devices",)),
        ):
            self.assert_accessible(route_name, *args)

    def test_owner_menu_destinations_are_distinct_and_accessible(self):
        self.client.force_login(self.owner)
        dashboard = self.assert_accessible("customer-dashboard")
        garden_url = reverse("customer-section", args=["garden"])
        devices_url = reverse("customer-section", args=["devices"])
        self.assertNotEqual(garden_url, devices_url)
        self.assertContains(dashboard, f'href="{garden_url}"')
        self.assertContains(dashboard, f'href="{devices_url}"')
        self.assertContains(dashboard, f'href="{reverse("customer-dashboard")}#automacao"')
        for route_name, args in (
            ("customer-section", ("garden",)), ("customer-section", ("devices",)),
            ("customer-development", ()), ("customer-history", ()),
            ("customer-section", ("subscription",)), ("customer-support", ()),
            ("customer-profile", ()),
        ):
            self.assert_accessible(route_name, *args)

    def test_customer_devices_are_scoped_to_membership_organization(self):
        other = Organization.objects.create(name="Outra", slug="outra-nav")
        other_garden = Garden.objects.create(organization=other, name="Horta alheia", code="alheia-nav")
        Device.objects.create(
            organization=other, garden=other_garden, model=self.device.model,
            serial_number="OTHER-ESP", name="Controlador secreto",
        )
        self.client.force_login(self.owner)
        response = self.assert_accessible("customer-section", "devices")
        self.assertContains(response, "Controlador")
        self.assertNotContains(response, "Controlador secreto")
        self.assertNotContains(response, "DEVICE_API_TOKEN")

    def test_viewer_sees_customer_navigation_without_manual_controls(self):
        self.client.force_login(self.viewer)
        response = self.assert_accessible("customer-dashboard")
        self.assertContains(response, reverse("customer-section", args=["devices"]))
        self.assertContains(response, "acesso somente para consulta")
        self.assertNotContains(response, reverse("device-action"))
        self.assertNotContains(response, reverse("ops-dashboard"))

    def test_technician_keeps_technician_sidebar_on_shared_pages(self):
        self.client.force_login(self.technician)
        response = self.assert_accessible("garden-gallery", self.garden.pk)
        self.assertContains(response, reverse("tech-dashboard"))
        self.assertContains(response, reverse("tech-visits"))
        self.assertNotContains(response, reverse("customer-section", args=["garden"]))
        self.assertNotContains(response, reverse("ops-dashboard"))
        self.assert_accessible("tech-dashboard")
        self.assert_accessible("tech-visits")

