# Generated by Django 4.2.6 on 2024-02-13 10:14

from django.db import migrations


class Migration(migrations.Migration):

    dependencies = [
        ('FRIEND', '0001_initial'),
    ]

    operations = [
        migrations.RemoveField(
            model_name='friendrequest',
            name='receiver',
        ),
        migrations.RemoveField(
            model_name='friendrequest',
            name='sender',
        ),
        migrations.DeleteModel(
            name='FriendList',
        ),
        migrations.DeleteModel(
            name='FriendRequest',
        ),
    ]
