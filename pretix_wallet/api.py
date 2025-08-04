from django.http import Http404
from i18nfield.rest_framework import I18nAwareModelSerializer
from rest_framework import viewsets, serializers

from rest_framework.exceptions import MethodNotAllowed

from . import models


class WalletSerializer(I18nAwareModelSerializer):
    balance = serializers.DecimalField(max_digits=13, decimal_places=2, read_only=True)
    issuer = serializers.SlugRelatedField(slug_field='slug', read_only=True)
    customer = serializers.SlugRelatedField(slug_field='identifier', read_only=True)

    class Meta:
        model = models.Wallet
        fields = ('id', 'issuer', 'balance', 'customer', 'created_at', 'pan', 'currency')


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