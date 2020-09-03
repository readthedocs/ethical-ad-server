"""
Add a publisher to the DB and setup appropriate publisher groups.

Example::

   ./manage.py add_publisher -e foo@gmail.com -s docs.example.com -k foo,bar -g test
"""
from django.core.management.base import BaseCommand
from django.utils.text import slugify

from ...models import Publisher
from ...models import PublisherGroup
from adserver.auth.models import User


class Command(BaseCommand):

    """Add a publisher from the command line."""

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
            self.stdout.write("User creation failed: %s" % e)
            user_obj = User.objects.get(email=email)

        success = user_obj.invite_user()
        if success:
            self.stdout.write("User creation: %s" % success)

        publisher_obj = Publisher.objects.create(name=site, slug=pub_slug)
        publisher_obj.default_keywords = keywords or ""
        publisher_obj.save()

        user_obj.publishers.add(publisher_obj)

        group_obj = PublisherGroup.objects.filter(slug=group).first()
        if group_obj:
            group_obj.publishers.add(publisher_obj)
        else:
            self.stdout.write("No Publisher Group Found")
