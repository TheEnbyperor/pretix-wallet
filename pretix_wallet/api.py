import decimal
from django.db import transaction
from django.http import Http404
from i18nfield.rest_framework import I18nAwareModelSerializer
from pretix.base.models import Device, TeamAPIToken, Customer, Order, OrderPosition
from pretix.helpers import OF_SELF
from rest_framework import viewsets, serializers, status
from rest_framework.decorators import action
from rest_framework.exceptions import MethodNotAllowed
from rest_framework.response import Response
from . import models, signals


class WalletSerializer(I18nAwareModelSerializer):
    balance = serializers.DecimalField(max_digits=13, decimal_places=2, read_only=True)
    pan = serializers.CharField(read_only=True)
    customer = serializers.SlugRelatedField(slug_field='identifier', queryset=Customer.objects.none(), required=False)
    order = serializers.SlugRelatedField(slug_field='code', queryset=Order.objects.none(), required=False)

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields['customer'].queryset = self.context['organizer'].customers.all()
        self.fields['order'].queryset = self.context['organizer'].orders.all()
        self.fields['order_position'] = serializers.PrimaryKeyRelatedField(
            required=False, allow_null=True,
            queryset=OrderPosition.all.filter(order__event__organizer=self.context['organizer']),
        )

    class Meta:
        model = models.Wallet
        fields = ('id', 'balance', 'customer', 'created_at', 'pan',
                  'public_pan', 'currency', 'order')

    def validate(self, attrs):
        if customer := attrs.get('customer'):
            if hasattr(customer, 'wallet') and customer.wallet != self.instance:
                raise serializers.ValidationError({
                    "customer": "Customer already has a Wallet",
                })
        if order := attrs.get('order'):
            if hasattr(order, 'wallet') and order.wallet != self.instance:
                raise serializers.ValidationError({
                    "order": "Order already has a Wallet",
                })
        if order_position := attrs.get('order_position'):
            if hasattr(order_position, 'wallet') and order_position.wallet != self.instance:
                raise serializers.ValidationError({
                    "order_position": "Order position already has a Wallet",
                })
        return attrs

    def create(self, validated_data):
        validated_data["issuer"] = self.context["organizer"]
        return super().create(validated_data)


class WalletViewSet(viewsets.ModelViewSet):
    serializer_class = WalletSerializer
    queryset = models.Wallet.objects.none()
    permission = 'can_change_orders'

    def get_queryset(self):
        return self.request.organizer.wallets.all()

    def get_object(self):
        try:
            return self.get_queryset().get(pan=self.kwargs['pk'])
        except models.Wallet.DoesNotExist:
            raise Http404

    def get_serializer_context(self):
        ctx = super().get_serializer_context()
        ctx['organizer'] = self.request.organizer
        return ctx

    def perform_destroy(self, instance):
        raise MethodNotAllowed("Wallets cannot be deleted.")

    @action(detail=True, methods=["POST"])
    @transaction.atomic
    def charge(self, request, **kwarg):
        wallet = models.Wallet.objects.select_for_update(of=OF_SELF).get(pk=self.get_object().pk)
        amount = serializers.DecimalField(max_digits=13, decimal_places=2).to_internal_value(request.data.get('amount'))
        descriptor = serializers.CharField(allow_blank=True, allow_null=True).to_internal_value(request.data.get('descriptor', ''))
        data = serializers.JSONField(required=False, allow_null=True).to_internal_value(request.data.get('data', {}))
        if isinstance(request.auth, Device):
            data["_device_id"] = request.auth.pk
        elif isinstance(request.auth, TeamAPIToken):
            data["_team_token_id"] = request.auth.pk
        else:
            data["_user_id"] = request.user.pk
        if wallet.balance - amount < wallet.settings.get("wallet_minimum_balance", as_type=decimal.Decimal):
            return Response({
                "amount": ["Insufficient balance"],
            }, status=status.HTTP_402_PAYMENT_REQUIRED)
        wallet.transactions.create(
            value=-amount,
            descriptor=descriptor or "Charge",
            data=data,
        )
        signals.update_ticket_output.apply_async(kwargs={"wallet_pk": wallet.pk})
        return Response(WalletSerializer(self.get_object(), context=self.get_serializer_context()).data, status=status.HTTP_200_OK)