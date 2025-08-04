from django.urls import path
from pretix.api import urls
from . import views, api


urlpatterns = [
    path("control/organizer/<organizer>/wallets/", views.WalletListView.as_view(), name='wallets'),
    path("control/organizer/<organizer>/wallets/settings/", views.SettingsView.as_view(), name='settings'),
]

urls.orga_router.register('wallets', api.WalletViewSet, basename='wallets')