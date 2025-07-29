from pretix.base.payment import BasePaymentProvider


class Wallet(BasePaymentProvider):
    identifier = 'wallet'
    verbose_name = "Wallet"
    abort_pending_allowed = True