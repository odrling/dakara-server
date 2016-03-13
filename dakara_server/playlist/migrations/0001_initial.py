# -*- coding: utf-8 -*-
from __future__ import unicode_literals

from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('library', '0003_auto_20160313_1822'),
    ]

    operations = [
        migrations.CreateModel(
            name='PlaylistEntry',
            fields=[
                ('id', models.AutoField(verbose_name='ID', primary_key=True, serialize=False, auto_created=True)),
                ('date_created', models.DateTimeField(auto_now_add=True)),
                ('song', models.ForeignKey(to='library.Song')),
            ],
        ),
    ]
