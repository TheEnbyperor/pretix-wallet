from django.db import migrations
from django.db.models import Exists, OuterRef


def activate_plugin(apps, schema_editor):
    Event = apps.get_model("pretixbase", "Event")
    Organizer = apps.get_model("pretixbase", "Organizer")
    qs_events = Event.objects.filter(plugins__contains="pretix_wallet")
    qs_organisers = Organizer.objects.filter(Exists(qs_events.filter(organizer_id=OuterRef("pk"))))
    for org in qs_organisers:
        if "pretix_wallet" not in org.plugins:
            org.plugins = ",".join(org.plugins.split(",") + ["pretix_wallet"])
            org.save(update_fields=["plugins"])
    for event in qs_events:
        plugins = event.plugins.split(",")
        plugins.remove("pretix_wallet")
        event.plugins = ",".join(plugins)
        event.save(update_fields=["plugins"])


class Migration(migrations.Migration):
    dependencies = [
        ("pretix_wallet", "0003_wallet_settingsstore"),
        ("pretixbase", "0287_organizer_plugins"),
    ]

    operations = [
        migrations.RunPython(
            activate_plugin,
            migrations.RunPython.noop,
        )
    ]