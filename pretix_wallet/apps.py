from django.utils.translation import gettext_lazy

from . import __version__

try:
    from pretix.base.plugins import PluginConfig, PLUGIN_LEVEL_ORGANIZER
except ImportError:
    raise RuntimeError("Please use pretix 2.7 or above to run this plugin!")


class PluginApp(PluginConfig):
    default = True
    name = "pretix_wallet"
    verbose_name = "Wallet"

    class PretixPluginMeta:
        name = gettext_lazy("Wallet")
        author = "AS207960 Cyfyngedig"
        description = gettext_lazy("Allows users to pre-buy wallet balances at order time e.g. for an event bar.")
        visible = True
        experimental = True
        version = __version__
        category = "FEATURE"
        compatibility = "pretix>=2.7.1"
        level = PLUGIN_LEVEL_ORGANIZER
        settings_links = []
        navigation_links = []

    def ready(self):
        from django.conf import settings
        settings.MIDDLEWARE.append("pretix_wallet.middleware.CorsMiddleware")

        from . import signals  # NOQA
