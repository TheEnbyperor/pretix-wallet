import decimal
from typing import Dict, Any, Union
from django.db import transaction
from django.http import HttpRequest
from django.template.loader import get_template
from pretix.base.models import Order, Customer, OrderPayment, OrderRefund
from pretix.base.payment import BasePaymentProvider, cart_session, PaymentException
from pretix.base.services.cart import add_payment_to_cart_session
from . import models, signals


class Wallet(BasePaymentProvider):
    identifier = "wallet"
    verbose_name = "Wallet"
    public_name = "Wallet balance"
    abort_pending_allowed = True
    multi_use_supported = True
    execute_payment_needs_user = False

    @staticmethod
    def customer(request, order: Order = None):
        if order and order.customer:
            return order.customer
        try:
            return request.organizer.customers.get(pk=cart_session(request).get('customer', -1))
        except Customer.DoesNotExist:
            return request.customer

    def is_allowed(self, request: HttpRequest, total: decimal.Decimal=None) -> bool:
        if not super().is_allowed(request, total):
            return False

        if customer := self.customer(request):
            if hasattr(customer, "wallet"):
                return True

        return False

    def payment_is_valid_session(self, request: HttpRequest) -> bool:
        if customer := self.customer(request):
            if hasattr(customer, "wallet"):
                return True

        return False

    def payment_form_render(self, request: HttpRequest, total: decimal.Decimal, order: Order=None) -> str:
        customer = self.customer(request, order)
        if not customer:
            return ""
        return get_template("pretix_wallet/payment/method_form.html").render({
            "request": request,
            "wallet": customer.wallet
        })

    def checkout_confirm_render(self, request, order: Order=None, info_data: dict=None) -> str:
        return get_template("pretix_wallet/payment/checkout_confirm.html").render({
            "request": request,
            "wallet": models.Wallet.objects.get(pk=info_data["wallet"])
        })

    def checkout_prepare(self, request: HttpRequest, cart: Dict[str, Any]) -> Union[bool, str]:
        wallet = self.customer(request).wallet
        cs = cart_session(request)
        add_payment_to_cart_session(
            cs,
            self,
            max_value=wallet.balance - wallet.settings.get("wallet_minimum_balance", as_type=decimal.Decimal),
            info_data={
                'wallet': wallet.pk
            }
        )
        return True

    def payment_prepare(self, request: HttpRequest, payment: OrderPayment) -> Union[bool, str]:
        customer = (payment.order.customer or self.customer(request))
        if not customer:
            return False
        wallet = customer.wallet
        payment.info_data = {
            'wallet': wallet.pk,
        }
        payment.amount = min(payment.amount, wallet.balance - wallet.settings.get("wallet_minimum_balance", as_type=decimal.Decimal))
        payment.save()
        return True

    def execute_payment(self, request: HttpRequest, payment: OrderPayment) -> str:
        wallet = models.Wallet.objects.get(pk=payment.info_data['wallet'])
        try:
            with transaction.atomic():
                if wallet.currency != self.event.currency:
                    raise PaymentException("The wallet is in the wrong currency")
                if wallet.balance - payment.amount < wallet.settings.get("wallet_minimum_balance", as_type=decimal.Decimal):
                    raise PaymentException("Insufficient balance.")

                trans = wallet.transactions.create(
                    value=-payment.amount,
                    descriptor=f"Payment for order #{payment.order.full_code}",
                    order_payment=payment,
                )
                signals.update_ticket_output.apply_async(kwargs={"wallet_pk": wallet.pk})
                payment.info_data = {
                    'wallet': wallet.pk,
                    'transaction_id': trans.pk,
                }
                payment.confirm()
        except PaymentException as e:
            payment.fail(info={'error': str(e)})
            raise e

    def api_payment_details(self, payment: OrderPayment):
        wallet = models.Wallet.objects.get(pk=payment.info_data['wallet'])
        return {
            'wallet': {
                'pan': wallet.pan,
                'public_pan': wallet.public_pan,
            }
        }

    def api_refund_details(self, refund: OrderRefund):
        wallet = models.Wallet.objects.get(pk=refund.info_data['wallet'])
        return {
            'wallet': {
                'pan': wallet.pan,
                'public_pan': wallet.public_pan,
            }
        }

    def payment_control_render(self, request, payment: OrderPayment) -> str:
        wallet = models.Wallet.objects.get(pk=payment.info_data['wallet'])
        return get_template("pretix_wallet/payment/payment_control.html").render({
            "request": request,
            "wallet": wallet
        })

    def refund_control_render(self, request, refund: OrderRefund) -> str:
        wallet = models.Wallet.objects.get(pk=refund.info_data['wallet'])
        return get_template("pretix_wallet/payment/payment_control.html").render({
            "request": request,
            "wallet": wallet
        })

    def payment_control_render_short(self, payment: OrderPayment) -> str:
        wallet = models.Wallet.objects.get(pk=payment.info_data['wallet'])
        return wallet.pan

    def refund_control_render_short(self, refund: OrderRefund) -> str:
        wallet = models.Wallet.objects.get(pk=refund.info_data['wallet'])
        return wallet.pan

    def payment_partial_refund_supported(self, payment: OrderPayment) -> bool:
        return True

    def payment_refund_supported(self, payment: OrderPayment) -> bool:
        return True
    
    def execute_refund(self, refund: OrderRefund):
        with transaction.atomic():
            wallet = models.Wallet.objects.get(pk=refund.info_data.get('wallet') or refund.payment.info_data.get('wallet'))
            trans = wallet.transactions.create(
                value=refund.amount,
                descriptor=f"Refund for order #{refund.order.full_code}",
                order_refund=refund,
            )
            signals.update_ticket_output.apply_async(kwargs={"wallet_pk": wallet.pk})
            refund.info_data = {
                'wallet': wallet.pk,
                'transaction_id': trans.pk,
            }
            refund.done()