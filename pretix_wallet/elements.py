import typing
import asn1tools
import pathlib
from pretix_uic_barcode.elements import UICBarcodeElement, VASElement, BaseBarcodeElementGenerator, BaseVASElementGenerator
from pretix.base.templatetags.money import money_filter
from pretix.base.models import OrderPosition, Order
from pretix.multidomain.urlreverse import build_absolute_uri
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

class WalletVASElement(VASElement):
    def __init__(self, wallet_id: str):
        self.wallet_id = wallet_id

    @staticmethod
    def record_id():
        return "W"

    def record_content(self) -> bytes:
        return BARCODE_CONTENT.encode("VASPretixWallet", {
            "pan": self.wallet_id,
        })

def find_wallet(order_position: OrderPosition, order: Order) -> typing.Optional[models.Wallet]:
    if hasattr(order_position, "wallet"):
        return order_position.wallet
    elif hasattr(order.customer, "wallet"):
        return order.customer.wallet
    else:
        qs = models.Wallet.objects.filter(order_position__order=order).distinct()
        if qs.count() == 1:
            return qs.first()

    return None

class WalletBarcodeElementGenerator(BaseBarcodeElementGenerator):
    @staticmethod
    def generate_element(order_position: OrderPosition, order: Order) -> typing.Optional[WalletBarcodeElement]:
        wallet = find_wallet(order_position, order)
        if not wallet:
            return None

        return WalletBarcodeElement(
            wallet_id=wallet.pan,
            issuer=wallet.issuer.slug
        )

class WalletVASElementGenerator(BaseVASElementGenerator):
    @staticmethod
    def generate_vas_element(order_position: OrderPosition, order: Order) -> typing.Optional[WalletVASElement]:
        wallet = find_wallet(order_position, order)
        if not wallet:
            return None

        return WalletVASElement(
            wallet_id=wallet.pan,
        )


def generate_google_wallet_module(order_position: OrderPosition, order: Order):
    wallet = find_wallet(order_position, order)
    if not wallet:
        return []

    return [("valueAddedModule", {
        "header": {
            "defaultValue": {
                "language": "en",
                "value": f"Wallet {wallet.public_pan}",
            }
        },
        "body": {
            "defaultValue": {
                "language": "en",
                "value": f"Balance: {money_filter(wallet.balance, wallet.currency)}",
            }
        },
        "uri": build_absolute_uri(order.event, "presale:event.order", {
            "order": order.code, "secret": order.secret
        }),
    })]


def generate_apple_wallet_module(order_position: OrderPosition, order: Order):
    wallet = find_wallet(order_position, order)
    if not wallet:
        return []

    return [("backField", {
        "key": "wallet-number",
        "label": "Wallet number",
        "value": wallet.public_pan,
    }), ("backField", {
        "key": "wallet-balance",
        "label": "Wallet balance",
        "value": float(wallet.balance),
        "currencyCode": wallet.currency,
        "changeMessage": f"New balance for wallet {wallet.public_pan}: %@",
    })]