from django.contrib import messages
from django.db import transaction
from django.db.models import OuterRef, Sum, Max, Subquery
from django.db.models.functions import Coalesce
from django.http import HttpResponseNotAllowed
from django.shortcuts import redirect
from django.urls import reverse
from django.utils.functional import cached_property
from pretix.control.views.organizer import OrganizerDetailViewMixin, Organizer
from pretix.control.permissions import OrganizerPermissionRequiredMixin
from django.views.generic import ListView, FormView, DetailView
from . import models, forms, signals
import decimal


class SettingsView(OrganizerDetailViewMixin, OrganizerPermissionRequiredMixin, FormView):
    model = Organizer
    form_class = forms.WalletSettingsForm
    template_name = 'pretix_wallet/organizers/settings.html'
    permission = 'can_change_organizer_settings'

    def get_form_kwargs(self):
        kwargs = super().get_form_kwargs()
        kwargs['obj'] = self.request.organizer
        return kwargs

    def get_success_url(self):
        return reverse('plugins:pretix_wallet:settings', kwargs={
            'organizer': self.request.organizer.slug,
        })

    @transaction.atomic
    def post(self, request, *args, **kwargs):
        form = self.get_form()
        if form.is_valid():
            form.save()
            if form.has_changed():
                self.request.organizer.log_action(
                    'pretix.organizer.settings', user=self.request.user, data={
                        k: form.cleaned_data.get(k) for k in form.changed_data
                    }
                )
                messages.success(self.request, "Your changes have been saved.")
            return redirect(self.get_success_url())
        else:
            messages.error(self.request, "We could not save your changes. See below for details.")
            return self.get(request)


class WalletListView(OrganizerDetailViewMixin, OrganizerPermissionRequiredMixin, ListView):
    model = models.Wallet
    template_name = 'pretix_wallet/organizers/wallets.html'
    permission = 'can_change_orders'
    context_object_name = 'wallets'
    paginate_by = 50

    def get_queryset(self):
        s = models.WalletTransaction.objects.filter(
            wallet=OuterRef('pk')
        ).order_by().values('wallet').annotate(s=Sum('value')).values('s')
        s_last_tx = models.WalletTransaction.objects.filter(
            wallet=OuterRef('pk')
        ).order_by().values('wallet').annotate(m=Max('timestamp')).values('m')
        qs = self.request.organizer.wallets.annotate(
            cached_balance=Coalesce(Subquery(s), decimal.Decimal('0.00')),
            last_tx=Subquery(s_last_tx),
        ).order_by('-created_at')
        if self.filter_form.is_valid():
            qs = self.filter_form.filter_qs(qs)
        return qs

    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)
        ctx['filter_form'] = self.filter_form
        return ctx

    @cached_property
    def filter_form(self):
        return forms.WalletFilterForm(data=self.request.GET, request=self.request)


class WalletView(OrganizerPermissionRequiredMixin, DetailView):
    model = models.Wallet
    template_name = 'pretix_wallet/organizers/wallet.html'
    permission = 'can_change_orders'
    context_object_name = 'wallet'
    slug_url_kwarg = "pan"
    slug_field = "pan"

    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)
        ctx['organizer'] = self.request.organizer
        ctx['charge_form'] = forms.WalletChargeForm()
        return ctx

    def get_queryset(self):
        return self.request.organizer.wallets.all()


class WalletSettingsView(OrganizerPermissionRequiredMixin, DetailView):
    model = models.Wallet
    template_name = 'pretix_wallet/organizers/wallet_settings.html'
    permission = 'can_change_organizer_settings'
    slug_url_kwarg = "pan"
    slug_field = "pan"

    def get_context_data(self, **kwargs):
        ctx = super().get_context_data()
        ctx['form'] = self.form
        ctx['organizer'] = self.request.organizer
        return ctx

    @cached_property
    def form(self):
        self.object = self.get_object()
        return forms.WalletIndividualSettingsForm(
            instance=self.object,
            data=self.request.POST if self.request.method == "POST" else None,
            customers=self.request.organizer.settings.customer_accounts and (
                self.request.user.has_organizer_permission(
                    self.request.organizer, 'can_manage_customers', request=self.request
                )
            ),
            initial={
                "wallet_minimum_balance": self.object.settings._cache().get("wallet_minimum_balance", None),
            }
        )

    def get_success_url(self):
        return reverse('plugins:pretix_wallet:wallet', kwargs={
            'organizer': self.request.organizer.slug,
            'pan': self.object.pan,
        })

    @transaction.atomic
    def post(self, request, *args, **kwargs):
        if self.form.is_valid():
            self.form.save()

            if self.form.cleaned_data["wallet_minimum_balance"]:
                self.object.settings.set("wallet_minimum_balance", self.form.cleaned_data["wallet_minimum_balance"])
            else:
                self.object.settings.delete("wallet_minimum_balance")

            messages.success(self.request, "Your changes have been saved.")
            return redirect(self.get_success_url())
        else:
            messages.error(self.request, "We could not save your changes. See below for details.")
            return self.get(request)


class WalletManualChargeView(OrganizerPermissionRequiredMixin, DetailView):
    model = models.Wallet
    permission = 'can_change_orders'
    slug_url_kwarg = "pan"
    slug_field = "pan"

    def post(self, *args, **kwargs):
        wallet = self.get_object()
        form = forms.WalletChargeForm(self.request.POST)
        if form.is_valid():
            charged = False
            with transaction.atomic():
                if wallet.balance - form.cleaned_data["amount"] < wallet.settings.get("wallet_minimum_balance", as_type=decimal.Decimal):
                    messages.error(self.request, "Insufficient balance.")
                wallet.transactions.create(
                    value=-form.cleaned_data["amount"],
                    descriptor=form.cleaned_data["descriptor"] or "Charge",
                )
                charged = True

            if charged:
                signals.update_ticket_output.apply_async(kwargs={"wallet_pk": wallet.pk})
                messages.success(self.request, "The wallet has been charged.")
        else:
            messages.error(self.request, "The wallet could not be charged.")

        return redirect('plugins:pretix_wallet:wallet', organizer=self.request.organizer.slug, pan=wallet.pan)

    def get(self, *args, **kwargs):
        return HttpResponseNotAllowed(['POST'])
