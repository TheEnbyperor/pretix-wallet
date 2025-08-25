from django.core import validators
from django.core.exceptions import ValidationError
from pretix.base.models import LoggedModel, Device
from django.conf import settings
from django.db import models
import decimal
import random
import string

from pretix.base.settings import settings_hierarkey


def luhn_checksum(n: str):
    m = [0, 2, 4, 6, 8, 1, 3, 5, 7, 9]
    digits = list(n)
    odd_digits = [*map(int, digits[1:][::2])]
    even_digits = [m[int(d)] for d in digits[0:][::2]]
    x = sum(odd_digits) + sum(even_digits)

    x = (10 - x % 10)
    return 0 if x == 10 else x

def gen_wallet_pan(issuer):
    pan_len = issuer.settings.get("wallet_pan_length", 16, as_type=int)
    iin = issuer.settings.get("wallet_iin", "")
    while True:
        random_len = pan_len - 1 - len(iin)
        ian = "".join(random.choices(string.digits, k=random_len))
        pan = f"{iin}{ian}"
        pan = f"{pan}{luhn_checksum(pan)}"
        if not Wallet.objects.filter(pan=pan).exists():
            return pan


@settings_hierarkey.add(parent_field='issuer', cache_namespace='pretix_wallet')
class Wallet(LoggedModel):
    settings_namespace = 'pretix_wallet'

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
    pan = models.CharField(max_length=19, validators=[validators.RegexValidator(regex=r"^[0-9]{10-19}$")], db_index=True)
    CURRENCY_CHOICES = [(c.alpha_3, c.alpha_3 + " - " + c.name) for c in settings.CURRENCIES]
    currency = models.CharField(max_length=10, choices=CURRENCY_CHOICES, validators=[
        validators.MinLengthValidator(3),
    ])

    def save(self, *args, **kwargs):
        if not self.pan:
            self.pan = gen_wallet_pan(self.issuer)

        super().save(*args, **kwargs)

    @property
    def public_pan(self):
        redacted_len = len(self.pan) - 8
        iin = self.pan[:4]
        last4 = self.pan[-4:]
        return f"{iin}{'*' * redacted_len}{last4}"

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
        on_delete=models.CASCADE
    )
    order_payment = models.ForeignKey(
        'pretixbase.OrderPayment',
        related_name="wallet_transactions",
        null=True,
        blank=True,
        on_delete=models.CASCADE
    )
    order_refund = models.ForeignKey(
        'pretixbase.OrderRefund',
        related_name="wallet_transactions",
        null=True,
        blank=True,
        on_delete=models.CASCADE
    )
    descriptor = models.TextField(blank=True, null=False, default="")
    data = models.JSONField(default=dict)

    class Meta:
        ordering = ('-timestamp',)

    def device(self):
        if "_device_id" not in self.data:
            return None
        return Device.objects.get(pk=self.data["_device_id"])


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