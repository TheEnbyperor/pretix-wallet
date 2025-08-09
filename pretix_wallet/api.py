import decimal
from django.db import transaction
from django.http import Http404
from i18nfield.rest_framework import I18nAwareModelSerializer
from pretix.base.models import Device, TeamAPIToken
from pretix.helpers import OF_SELF
from rest_framework import viewsets, serializers, status
from rest_framework.decorators import action
from rest_framework.exceptions import MethodNotAllowed
from rest_framework.response import Response
from . import models, signals


class WalletSerializer(I18nAwareModelSerializer):
    balance = serializers.DecimalField(max_digits=13, decimal_places=2, read_only=True)
    issuer = serializers.SlugRelatedField(slug_field='slug', read_only=True)
    customer = serializers.SlugRelatedField(slug_field='identifier', read_only=True)

    class Meta:
        model = models.Wallet
        fields = ('id', 'issuer', 'balance', 'customer', 'created_at', 'pan',
                  'public_pan', 'currency')


class WalletViewSet(viewsets.ReadOnlyModelViewSet):
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