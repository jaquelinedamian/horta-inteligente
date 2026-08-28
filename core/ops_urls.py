from django.urls import path

from . import ops_views

urlpatterns = [
    path("", ops_views.dashboard, name="ops-dashboard"),
    path("area/<slug:area>/", ops_views.area_dashboard, name="ops-area"),
    path("comercial/", ops_views.area_dashboard, {"area": "comercial"}),
    path("cultivo/", ops_views.area_dashboard, {"area": "cultivo"}),
    path("hortas/", ops_views.area_dashboard, {"area": "hortas"}),
    path("iot/", ops_views.area_dashboard, {"area": "iot"}),
    path("operacao/", ops_views.area_dashboard, {"area": "operacao"}),
    path("estoque/", ops_views.area_dashboard, {"area": "estoque"}),
    path("administracao/", ops_views.area_dashboard, {"area": "administracao"}),
    path("clientes/novo/", ops_views.client_create, name="ops-client-create"),
    path("clientes/<int:user_id>/editar/", ops_views.client_edit, name="ops-client-edit"),
    path("clientes/<int:user_id>/<slug:section>/novo/", ops_views.client_related_create, name="ops-client-related-create"),
    path("clientes/<int:user_id>/", ops_views.client_detail, name="ops-client-detail"),
    path("dispositivos/<uuid:device_id>/credencial/", ops_views.credential_issue, name="ops-credential-issue"),
    path("credenciais/<uuid:pk>/revogar/", ops_views.credential_revoke, name="ops-credential-revoke"),
    path("demonstracao/criar/", ops_views.create_demo, name="ops-create-demo"),
    path("qrcodes/<uuid:module_id>/", ops_views.module_qr, name="ops-module-qr"),
    path("ordens/nova/", ops_views.create, {"section": "orders"}, name="create-work-order"),
    path("<str:section>/novo/", ops_views.create, name="ops-create"),
    path("<str:section>/<str:pk>/editar/", ops_views.edit, name="ops-edit"),
    path("<str:section>/<str:pk>/", ops_views.detail, name="ops-detail"),
    path("<str:section>/", ops_views.collection, name="ops-collection"),
]
