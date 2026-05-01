from django.urls import path

from . import views

app_name = "google_integration"

urlpatterns = [
    path("", views.connect, name="connect"),
    path("auth/start/", views.auth_start, name="auth_start"),
    path("auth/callback/", views.auth_callback, name="callback"),
    path("auth/disconnect/", views.disconnect, name="disconnect"),
    path("sheets/", views.sheets_list, name="sheets_list"),
    path("sheets/create/", views.sheets_create, name="sheets_create"),
    path("sheets/<str:spreadsheet_id>/", views.sheet_view, name="sheet_view"),
    path("sheets/<str:spreadsheet_id>/save/", views.sheet_save, name="sheet_save"),
    path("sheets/<str:spreadsheet_id>/append/", views.sheet_append, name="sheet_append"),
]
