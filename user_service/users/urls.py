from django.urls import path
from . import views

urlpatterns = [
    path("health/",              views.HealthView.as_view()),
    path("users/",               views.UserListView.as_view()),
    path("users/register/",      views.RegisterView.as_view()),
    path("users/<int:user_id>/", views.UserDetailView.as_view()),
]
