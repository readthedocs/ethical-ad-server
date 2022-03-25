"""Dump or load data from Metabase."""
import argparse
import getpass
import json

import requests
from django.conf import settings
from django.core.management import CommandError
from django.core.management.base import BaseCommand
from django.utils.translation import gettext_lazy as _


class Command(BaseCommand):

    """Management command to dump/load data from Metabase."""

    help = "Dump or load questions from metabase."

    def __init__(self, stdout=None, stderr=None, no_color=False, force_color=False):
        """Override to store the metabase session."""
        super().__init__(stdout, stderr, no_color, force_color)
        self.metabase_session = None

    def add_arguments(self, parser):
        """Add command line args for this command."""
        parser.add_argument(
            "-d",
            "--dump-questions",
            type=argparse.FileType("w"),
            help=_("Dump questions to file"),
        )
        parser.add_argument(
            "-l",
            "--load-questions",
            type=argparse.FileType("r"),
            help=_("Load questions from a file"),
        )

    def handle(self, *args, **kwargs):
        """Entrypoint to the command."""
        self.authenticate_metabase()

        if kwargs["dump_questions"]:
            # Dump questions to a file
            self.handle_dump_questions(kwargs["dump_questions"])
        elif kwargs["load_questions"]:
            # Load questions from a file
            self.handle_load_questions(kwargs["load_questions"])

    def authenticate_metabase(self):
        """Authenticate with metabase and store the session token temporarily."""
        self.stdout.write(
            _("Authenticating with Metabase (%s)...") % settings.METABASE_SITE_URL
        )

        metabase_user = input("Metabase username: ")
        metabase_password = getpass.getpass("Metabase password: ")

        resp = requests.post(
            settings.METABASE_SITE_URL + "/api/session",
            json={"username": metabase_user, "password": metabase_password},
        )
        if not resp.ok:
            self.stdout.write(resp.text)
            raise CommandError(
                _("Could not authenticate with those credentials to Metabase")
            )

        self.stdout.write(
            self.style.SUCCESS(_("Successfully authenticated to Metabase."))
        )
        data = resp.json()
        self.metabase_session = data["id"]

    def handle_dump_questions(self, outfile):
        """Dump questions from metabase to a file."""
        self.stdout.write(_("Dumping questions from Metabase..."))

        resp = requests.get(
            settings.METABASE_SITE_URL + "/api/card/embeddable",
            headers={"X-Metabase-Session": self.metabase_session},
        )

        if not resp.ok:
            self.stdout.write(resp.text)
            raise CommandError(_("Error getting questions"))

        questions = []
        for question in resp.json():
            # https://www.metabase.com/docs/latest/api-documentation.html#post-apicard
            card_resp = requests.get(
                settings.METABASE_SITE_URL + "/api/card/" + str(question["id"]),
                headers={"X-Metabase-Session": self.metabase_session},
            )
            card = card_resp.json()
            questions.append(
                {
                    "id": card["id"],
                    "name": card["name"],
                    "description": card["description"],
                    "result_metadata": card["result_metadata"],
                    "dataset_query": card["dataset_query"],
                    "display": card["display"],
                    "visualization_settings": card["visualization_settings"],
                }
            )

        questions.sort(key=lambda q: q["id"])
        outfile.write(json.dumps(questions, indent=2))
        outfile.close()

        self.stdout.write(
            self.style.SUCCESS(_("Successfully dumped questions from Metabase."))
        )

    def handle_load_questions(self, infile):
        """Load questions from a file into metabase."""
        self.stdout.write(_("Loading questions to Metabase..."))

        # Check if there are existing cards in Metabase (warn if so)
        resp = requests.get(
            settings.METABASE_SITE_URL + "/api/card",
            headers={"X-Metabase-Session": self.metabase_session},
        )
        if resp.json():
            self.stdout.write(
                self.style.WARNING(_("There are existing questions in this Metabase!!"))
            )
            proceed = input("Proceed? (y/N): ")
            if not proceed.lower().startswith("y"):
                return

        errors = 0
        for question in json.load(infile):
            # https://www.metabase.com/docs/latest/api-documentation.html#post-apicard
            del question["id"]
            self.stdout.write(_(" - Loaded %s") % question["name"])
            resp = requests.post(
                settings.METABASE_SITE_URL + "/api/card",
                headers={"X-Metabase-Session": self.metabase_session},
                json=question,
            )

            if not resp.ok:
                self.stdout.write(resp.text)
                self.stdout.write(self.style.ERROR(_("Error loading question")))
                errors += 1

        if errors == 0:
            self.stdout.write(
                self.style.SUCCESS(_("Successfully loaded questions into Metabase."))
            )
