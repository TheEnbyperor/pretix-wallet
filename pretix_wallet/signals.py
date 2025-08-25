import decimal

from django.db import transaction
from django.dispatch import receiver
from django.template.loader import get_template
from django.urls import resolve, reverse
from pretix.base.models.orders import Order, OrderPosition
from pretix.base.services import tickets
from pretix.base.signals import register_payment_providers, customer_created, order_paid, order_changed
from pretix.control.signals import nav_organizer, item_forms
from pretix.presale.signals import order_info_top
from pretix.celery_app import app
from pretix_uic_barcode.signals import register_barcode_element_generators, register_vas_element_generators, generate_google_wallet_module, generate_apple_wallet_module
from pretix_uic_barcode import ticket_output

from . import payment, models, elements, forms


@receiver(register_payment_providers, dispatch_uid="payment_wallet")
def register_payment_provider(sender, **kwargs):
    return payment.Wallet


@receiver(nav_organizer, dispatch_uid="wallet_organav")
def control_nav_orga_import(sender, request=None, **kwargs):
    url = resolve(request.path_info)
    if not request.user.has_organizer_permission(request.organizer, "can_change_orders", request=request):
        return []
    if not request.organizer.events.filter(plugins__icontains="pretix_wallet"):
        return []
    return [
        {
            'label': "Wallets",
            'url': reverse('plugins:pretix_wallet:wallets', kwargs={
                'organizer': request.organizer.slug,
            }),
            'icon': 'university',
            'children': [{
                'label': "Wallets",
                'url': reverse('plugins:pretix_wallet:wallets', kwargs={
                    'organizer': request.organizer.slug
                }),
                'active': url.url_name == "wallets",
            }, {
                'label': "Settings",
                'url': reverse('plugins:pretix_wallet:settings', kwargs={
                    'organizer': request.organizer.slug
                }),
                'active': url.url_name == "settings",
            }]
        }
    ]


@receiver(customer_created, dispatch_uid="wallet_customer_created")
def customer_created(sender, customer, **kwargs):
    if sender.settings.wallet_create_for_customers and not hasattr(customer, "wallet"):
        models.Wallet.objects.create(
            issuer=sender,
            customer=customer,
            currency=sender.settings.wallet_default_currency,
        )


@receiver(order_info_top, dispatch_uid="wallet_show_balance")
def order_info_balance(sender, request, order, **kwargs):
    template = get_template("pretix_wallet/order/balance.html")

    wallets = []
    if hasattr(order.customer, "wallet"):
        wallets.append(order.customer.wallet)

    ctx = {
        'order': order,
        'request': request,
        'event': sender,
        'wallets': wallets,
    }
    return template.render(ctx, request=request)


@receiver(item_forms, dispatch_uid="wallet_item_issue_balance")
def item_issue_balance(sender, item, request, **kwargs):
    try:
        inst = models.WalletItem.objects.get(item=item)
    except  models.WalletItem.DoesNotExist:
        inst = models.WalletItem(item=item)
    return forms.WalletItemForm(
        instance=inst,
        data=(request.POST if request.method == "POST" else None),
        prefix="wallet"
    )


@receiver(order_paid, dispatch_uid="wallet_order_paid_issue_balance")
@receiver(order_changed, dispatch_uid="wallet_order_changed_issue_balance")
@transaction.atomic()
def order_issue_balance(sender, order, **kwargs):
    any_wallets = False
    for p in OrderPosition.all.filter(order=order):
        if order.status == Order.STATUS_PAID:
            if not p.canceled and hasattr(p.item, "wallet") and p.item.wallet.issue_wallet_balance:
                issued = decimal.Decimal('0.00')
                for wt in p.wallet_transactions.all().distinct():
                    issued += wt.value
                tbi = p.price - issued
                if tbi > 0:
                    any_wallets = True

                    if order.customer:
                        if hasattr(order.customer, "wallet"):
                            wallet = order.customer.wallet
                        else:
                            wallet = models.Wallet.objects.create(
                                issuer=sender.organizer,
                                customer=order.customer,
                                currency=sender.settings.wallet_default_currency,
                            )
                            wallet.save()
                    else:
                        if hasattr(order, "wallet"):
                            wallet = order.wallet
                        else:
                            wallet = models.Wallet.objects.create(
                                issuer=sender.organizer,
                                order_position=p,
                                currency=sender.settings.wallet_default_currency,
                            )
                            wallet.save()

                    wallet.transactions.create(value=tbi, order_position=p, descriptor=f"Order #{order.full_code}")
                    update_ticket_output.apply_async(kwargs={"wallet_pk": wallet.pk})

        if p.wallet_transactions.count() > 0 and (p.canceled or order.status == Order.STATUS_CANCELED or order.status == Order.STATUS_REFUNDED):
            any_wallets = True
            wallets = list(set([w["wallet"] for w in p.wallet_transactions.values("wallet").distinct()]))
            wallets = models.Wallet.objects.filter(pk__in=wallets)
            p.wallet_transactions.all().delete()
            for wallet in wallets:
                update_ticket_output.apply_async(kwargs={"wallet_pk": wallet.pk})


    if any_wallets:
        tickets.invalidate_cache.apply_async(kwargs={'event': sender.pk, 'order': order.pk})


@receiver(register_barcode_element_generators, dispatch_uid="wallet_barcode_element_generator")
def barcode_element_generator(sender, **kwargs):
    return [elements.WalletBarcodeElementGenerator]


@receiver(register_vas_element_generators, dispatch_uid="wallet_vas_element_generator")
def vas_element_generator(sender, **kwargs):
    return [elements.WalletVASElementGenerator]


@receiver(generate_google_wallet_module, dispatch_uid="wallet_google_module_generator")
def google_module_generator(sender, **kwargs):
    return [elements.generate_google_wallet_module]


@receiver(generate_apple_wallet_module, dispatch_uid="wallet_apple_module_generator")
def apple_module_generator(sender, **kwargs):
    return [elements.generate_apple_wallet_module]


@app.task(acks_late=True)
def update_ticket_output(wallet_pk):
    wallet = models.Wallet.objects.get(pk=wallet_pk)
    if wallet.order_position:
        ticket_output.update_ticket_output.apply_async(kwargs={"event": wallet.order_position.event.pk, "position_pk": wallet.order_position.pk})
    
    if wallet.customer:
        for order in wallet.customer.orders.all():
            ticket_output.update_ticket_output_all.apply_async(kwargs={"event": order.event.pk, "order_pk": order.pk})
        