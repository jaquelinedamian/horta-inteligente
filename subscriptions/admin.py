from django.contrib import admin
from .models import (CheckoutRequest, Coupon, CouponRedemption, Payment, Plan, PlanEntitlement,
                     PlanFeature, PlanVersion, Subscription, SubscriptionEvent)

admin.site.register([Plan, PlanVersion, PlanFeature, PlanEntitlement, Coupon, CouponRedemption,
                     Subscription, SubscriptionEvent, Payment, CheckoutRequest])
