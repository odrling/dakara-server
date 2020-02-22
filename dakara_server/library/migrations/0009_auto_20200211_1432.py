# -*- coding: utf-8 -*-
# Generated by Django 1.11.23 on 2020-02-11 14:32
from __future__ import unicode_literals

from django.db import migrations
import library.fields


class Migration(migrations.Migration):

    dependencies = [("library", "0008_auto_20190609_0705")]

    operations = [
        migrations.AlterField(
            model_name="songtag",
            name="name",
            field=library.fields.UpperCaseCharField(max_length=255, unique=True),
        )
    ]
