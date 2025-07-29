import typing
import asn1tools
import pathlib
from pretix_uic_barcode.elements import UICBarcodeElement, BaseBarcodeElementGenerator
from pretix.base.models import OrderPosition, Order
from . import models

ROOT = pathlib.Path(__file__).parent
BARCODE_CONTENT = asn1tools.compile_files([ROOT / "asn1" / "pretixWallet.asn"], codec="uper")

class WalletBarcodeElement(UICBarcodeElement):
    def __init__(self, wallet_id: str, issuer: str):
        self.wallet_id = wallet_id
        self.issuer = issuer

    @staticmethod
    def tlb_record_id():
        return "5101PW"

    @staticmethod
    def dosipas_record_id():
        return "_5101PXW"

    def record_content(self) -> bytes:
        return BARCODE_CONTENT.encode("PretixWallet", {
            "pan": self.wallet_id,
            "issuer": self.issuer,
        })


class WalletBarcodeElementGenerator(BaseBarcodeElementGenerator):
    @staticmethod
    def generate_element(
            order_position: OrderPosition,
            order: Order,
    ) -> typing.Optional[WalletBarcodeElement]:
        wallet = None
        if hasattr(order_position, "wallet"):
            wallet = order_position.wallet
        elif hasattr(order.customer, "wallet"):
            wallet = order.customer.wallet
        else:
            qs = models.Wallet.objects.filter(order_position__order=order)
            if qs.count() == 1:
                wallet = qs.first()

        if not wallet:
            return None

        return WalletBarcodeElement(
            wallet_id=wallet.pan,
            issuer=wallet.issuer.slug
        )
