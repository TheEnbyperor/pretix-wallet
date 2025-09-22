from collections import OrderedDict
from django.utils import timezone
from pretix.base.exporters import OrganizerLevelExportMixin, ListExporter
from pretix.base.timeframes import DateFrameField, resolve_timeframe_to_dates_inclusive

from . import models


class WalletExporter(OrganizerLevelExportMixin, ListExporter):
    identifier = "wallet-transactions"
    verbose_name = "Wallet Transactions"
    category = "Wallets"

    @property
    def additional_form_fields(self):
        return OrderedDict(
            [('date_range',
              DateFrameField(
                  label="Date range",
                  include_future_frames=True,
                  required=False,
                  help_text="Only include transactions within this date rane"
              ))]
        )

    def get_filename(self):
        return f"wallet-transactions-{self.organizer.slug}"

    def iterate_list(self, form_data):
        qs = models.WalletTransaction.objects.all()
        if dr := form_data.get("date_range"):
            d_start, d_end = resolve_timeframe_to_dates_inclusive(timezone.now(), dr, self.timezone)
            if d_start:
                qs = qs.filter(date__gte=d_start)
            if d_end:
                qs = qs.filter(date__lte=d_end)
        yield self.ProgressSetTotal(total=qs.count())
        yield [
            "timestamp",
            "wallet",
            "wallet_currency",
            "wallet_customer",
            "value",
            "descriptor",
            "issued_from_order_position",
            "payment_for_order",
            "refund_for_order",
            "device_serial",
            "data"
        ]
        for t in qs:
            device = t.device()
            if "_device_id" in t.data:
                del t.data["_device_id"]
            yield [
                t.timestamp.isoformat(),
                t.wallet.pan,
                t.wallet.currency,
                t.wallet.customer.identifier if t.wallet.customer else None,
                t.value,
                t.descriptor,
                t.order_position.code if t.order_position else None,
                t.order_payment.full_id if t.order_payment else None,
                t.order_refund.full_id if t.order_refund else None,
                device.unique_serial if device else None,
                t.data,
            ]
