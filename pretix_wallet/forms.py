from django.conf import settings
from django.core.exceptions import ValidationError
from django.core.validators import MaxValueValidator
from django.db.models import F, Q
from django.urls import reverse
from django_scopes.forms import SafeModelChoiceField
from pretix.base.forms import SettingsForm
from pretix.control.forms.filter import FilterForm
from django import forms
from pretix.control.forms.widgets import Select2 as BaseSelect2

from . import models


class WalletItemForm(forms.ModelForm):
    title = "Wallet"

    class Meta:
        model = models.WalletItem
        fields = ('issue_wallet_balance',)


class WalletSettingsForm(SettingsForm):
    wallet_create_for_customers = forms.BooleanField(
        label="Create wallet on customer account creation - i.e. before an order is placed",
        required=False
    )
    wallet_default_currency = forms.ChoiceField(
        label="Default currency",
        choices=[(c.alpha_3, c.alpha_3 + " - " + c.name) for c in settings.CURRENCIES],
    )
    wallet_iin = forms.CharField(
        max_length=18,
        label="Issuer Identification Number"
    )
    wallet_pan_length = forms.IntegerField(
        label="PAN length",
        min_value=10,
        max_value=19,
        initial=16,
    )
    wallet_minimum_balance = forms.DecimalField(
        label="Default minimum balance",
        decimal_places=2,
        max_digits=13,
        initial=0,
        validators=[MaxValueValidator(0)],
    )

    def clean(self):
        if self.cleaned_data.get("wallet_create_for_customers") and not self.cleaned_data.get("wallet_default_currency"):
            raise ValidationError({
                "wallet_default_currency": "Default currency must be specified",
            })

        if self.cleaned_data.get("wallet_pan_length", 16) - len(self.cleaned_data.get("wallet_iin", "")) < 2:
            raise ValidationError({
                "wallet_iin": "IIN is too long for the chosen PAN length",
            })


class Select2(BaseSelect2):
    def build_attrs(self, base_attrs, extra_attrs=None):
        attrs = super().build_attrs(base_attrs, extra_attrs)
        if self.choices.field.empty_label:
            attrs["data-placeholder"] = self.choices.field.empty_label
        return attrs


class WalletIndividualSettingsForm(forms.ModelForm):
    wallet_minimum_balance = forms.DecimalField(
        label="Minimum balance",
        decimal_places=2,
        max_digits=13,
        initial=None,
        validators=[MaxValueValidator(0)],
        required=False,
        help_text="Set an empty value to use the organizer default",
    )

    class Meta:
        model = models.Wallet
        fields = ('customer',)
        field_classes = {
            'customer': SafeModelChoiceField,
        }

    def __init__(self, *args, **kwargs):
        customers = kwargs.pop('customers')
        super().__init__(*args, **kwargs)

        if customers:
            self.fields['customer'].queryset = self.instance.issuer.customers.all()
            self.fields['customer'].widget = Select2(
                attrs={
                    'data-model-select2': 'generic',
                    'data-select2-url': reverse('control:organizer.customers.select2', kwargs={
                        'organizer': self.instance.issuer.slug,
                    }),
                }
            )
            self.fields['customer'].widget.choices = self.fields['customer'].choices
            self.fields['customer'].required = False
        else:
            del self.fields['customer']


class WalletChargeForm(forms.Form):
    descriptor = forms.CharField(required=False)
    amount = forms.DecimalField(
        max_digits=13, decimal_places=2,
        help_text="Enter a negative amount for top-ups",
    )


class WalletFilterForm(FilterForm):
    orders = {
        'created_at': 'created_at',
        'customer': 'customer__name_cached',
        'last_tx': F('last_tx').asc(nulls_first=True),
        '-last_tx': F('last_tx').desc(nulls_last=True),
        'id': 'pan',
        'value': 'cached_value',
    }
    state = forms.ChoiceField(
        label="Status",
        choices=(
            ('', "All"),
            ('empty', "Empty"),
            ('with_value', "With value"),
        ),
        required=False
    )
    query = forms.CharField(
        label="Search query",
        widget=forms.TextInput(attrs={
            'placeholder': "Query"
        }),
        required=False
    )

    def __init__(self, *args, **kwargs):
        kwargs.pop('request')
        super().__init__(*args, **kwargs)

    def filter_qs(self, qs):
        fdata = self.cleaned_data

        if fdata.get('query'):
            query = fdata.get('query')

            qs = qs.filter(
                Q(pan__icontains=query)
                | Q(transactions__descriptor__icontains=query)
                | Q(customer__name_cached__icontains=query)
                | Q(transactions__order_payment__order__code__icontains=query)
                | Q(transactions__order_refund__order__code__icontains=query)
            )
        if fdata.get('state') == 'empty':
            qs = qs.filter(cached_balance=0)
        elif fdata.get('state') == 'with_value':
            qs = qs.exclude(cached_balance=0)

        if fdata.get('ordering'):
            qs = qs.order_by(self.get_order_by())
        else:
            qs = qs.order_by('-created_at')

        return qs.distinct()