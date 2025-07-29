from django.core import validators
from django.core.exceptions import ValidationError
from pretix.base.models import LoggedModel
from django.conf import settings
from django.db import models
import decimal
import secrets
import base64

def gen_wallet_secret(length=16):
    while True:
        code = secrets.token_bytes(length)
        if not Wallet.objects.filter(secret=code).exists():
            return code

class Wallet(LoggedModel):
    issuer = models.ForeignKey(
        "pretixbase.Organizer",
        related_name="wallets",
        on_delete=models.PROTECT,
    )
    customer = models.OneToOneField(
        "pretixbase.Customer",
        related_name="wallet",
        null=True, blank=True,
        on_delete=models.SET_NULL
    )
    order_position = models.OneToOneField(
        "pretixbase.OrderPosition",
        related_name="wallet",
        null=True, blank=True,
        on_delete=models.SET_NULL
    )
    created_at = models.DateTimeField(auto_now_add=True)
    secret = models.BinaryField(max_length=64)
    CURRENCY_CHOICES = [(c.alpha_3, c.alpha_3 + " - " + c.name) for c in settings.CURRENCIES]
    currency = models.CharField(max_length=10, choices=CURRENCY_CHOICES, validators=[
        validators.MinLengthValidator(3),
    ])

    def save(self, *args, **kwargs):
        if not self.secret:
            self.secret = gen_wallet_secret()

        super().save(*args, **kwargs)

    @property
    def display_id(self):
        return base64.b32hexencode(self.secret).decode().replace("=", "")

    @property
    def public_id(self):
        return self.display_id[:6]

    @property
    def balance(self):
        if hasattr(self, 'cached_balance'):
            return self.cached_balance or decimal.Decimal('0.00')
        balance = self.transactions.aggregate(s=models.Sum('value'))['s'] or decimal.Decimal('0.00')
        self.cached_balance = balance
        return balance


class WalletTransaction(models.Model):
    wallet = models.ForeignKey(
        'Wallet',
        related_name='transactions',
        on_delete=models.PROTECT
    )
    timestamp = models.DateTimeField(auto_now_add=True)
    value = models.DecimalField(decimal_places=2, max_digits=13)
    order_position = models.ForeignKey(
        'pretixbase.OrderPosition',
        related_name="wallet_transactions",
        null=True,
        blank=True,
        on_delete=models.SET_NULL
    )
    order_payment = models.ForeignKey(
        'pretixbase.OrderPayment',
        related_name="wallet_transactions",
        null=True,
        blank=True,
        on_delete=models.SET_NULL
    )
    order_refund = models.ForeignKey(
        'pretixbase.OrderRefund',
        related_name="wallet_transactions",
        null=True,
        blank=True,
        on_delete=models.SET_NULL
    )
    descriptor = models.TextField(blank=True, null=False, default="")
    data = models.JSONField(default=dict)


class WalletItem(models.Model):
    item = models.OneToOneField('pretixbase.Item', on_delete=models.CASCADE, related_name="wallet")
    issue_wallet_balance = models.BooleanField(
        default=False, blank=True,
        help_text="Issue a wallet balance equivalent to this item's price"
    )

    def clean(self):
        if self.issue_wallet_balance:
            if self.item.admission:
                raise ValidationError("An item cannot both be an admission item and issue a balance")
            if self.item.issue_giftcard:
                raise ValidationError("An item cannot both issue a gift card and a balance")