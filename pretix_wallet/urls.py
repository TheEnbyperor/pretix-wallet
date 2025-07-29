from django.urls import include, path
from . import views


urlpatterns = [
    path("control/organizer/<organizer>/wallets/", views.WalletListView.as_view(), name='wallets'),
    path("control/organizer/<organizer>/wallets/settings/", views.SettingsView.as_view(), name='settings'),
]