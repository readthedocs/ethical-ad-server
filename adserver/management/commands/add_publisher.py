"""
Add a publisher to the DB

Example::

   ./manage.py add_publisher -e foo@gmail.com -s docs.example.com -k foo,bar -g test
"""
from django.core.management.base import BaseCommand
from django.test.client import RequestFactory
from django.utils.text import slugify

from ...models import Publisher
from ...models import PublisherGroup
from adserver.auth.models import User
from adserver.auth.utils import invite_user


class Command(BaseCommand):
    help = "Add a publisher"

    def add_arguments(self, parser):
        parser.add_argument("-e", "--email", type=str, help="Email", required=True)
        parser.add_argument("-s", "--site", type=str, help="Site URL", required=True)
        parser.add_argument("-k", "--keywords", type=str, help="Keywords")
        parser.add_argument(
            "-g",
            "--group",
            type=str,
            help="Publisher group",
            default="ethicalads-network",
        )

    def handle(self, *args, **kwargs):
        email = kwargs["email"]
        site = kwargs["site"]
        group = kwargs["group"]
        keywords = kwargs["keywords"]

        pub_slug = slugify(site.replace(".", "-"))

        try:
            user_obj = User.objects.create_user(email=email, password="")
        except Exception as e:
            print("User creation failed: %s" % e)
            user_obj = User.objects.get(email=email)

        request = RequestFactory().get("/", HTTP_HOST="ethicalads.io", secure=True)
        success = invite_user(
            User.objects.filter(pk=user_obj.pk), request=request, message=False
        )
        if success:
            print("User creation: %s" % success)

        publisher_obj = Publisher.objects.create(name=site, slug=pub_slug)
        publisher_obj.default_keywords = keywords
        publisher_obj.save()

        user_obj.publishers.add(publisher_obj)

        group_obj = PublisherGroup.objects.filter(slug=group).first()
        if group_obj:
            group_obj.publishers.add(publisher_obj)
        else:
            print("No Publisher Group Found")
