# Generated by Django 2.2.17 on 2021-08-14 13:18

import django.db.models.deletion
from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("playlist", "0012_playlistentry_use_instrumental"),
    ]

    operations = [
        migrations.CreateModel(
            name="PlayerToken",
            fields=[
                (
                    "karaoke",
                    models.OneToOneField(
                        on_delete=django.db.models.deletion.CASCADE,
                        primary_key=True,
                        serialize=False,
                        to="playlist.Karaoke",
                    ),
                ),
                ("token", models.CharField(editable=False, max_length=40, unique=True)),
            ],
        ),
    ]
