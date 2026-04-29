from django.urls import path
from . import views

urlpatterns = [
    path("health/",                views.HealthView.as_view()),
    path("orders/",                views.OrderListView.as_view()),
    path("orders/<int:order_id>/", views.OrderDetailView.as_view()),
]
