from django.urls import path
from pretix.api import urls
from . import views, api


urlpatterns = [
    path("control/organizer/<organizer>/wallets/", views.WalletListView.as_view(), name='wallets'),
    path("control/organizer/<organizer>/wallets/wallet/<str:pan>/", views.WalletView.as_view(), name='wallet'),
    path("control/organizer/<organizer>/wallets/wallet/<str:pan>/settings/", views.WalletSettingsView.as_view(), name='wallet_settings'),
    path("control/organizer/<organizer>/wallets/wallet/<str:pan>/manual_charge/", views.WalletManualChargeView.as_view(), name='wallet_manual_charge'),
    path("control/organizer/<organizer>/wallets/settings/", views.SettingsView.as_view(), name='settings'),
]

urls.orga_router.register('wallets', api.WalletViewSet, basename='wallets')