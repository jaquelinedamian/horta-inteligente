from django.contrib import admin
from .models import CheckoutRequest, Payment, Plan, PlanFeature, PlanVersion, Subscription, SubscriptionEvent

admin.site.register([Plan, PlanVersion, PlanFeature, Subscription, SubscriptionEvent, Payment, CheckoutRequest])
