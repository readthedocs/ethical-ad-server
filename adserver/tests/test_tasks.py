import datetime

from django.contrib.auth.models import AnonymousUser

from ..models import Offer
from ..tasks import remove_old_client_ids
from .common import BaseAdModelsTestCase


class TasksTest(BaseAdModelsTestCase):
    def test_remove_client_ids(self):
        request = self.factory.get("/")
        request.user = AnonymousUser()

        offer_dict = self.ad1.offer_ad(
            request=request,
            publisher=self.publisher,
            ad_type_slug=self.text_ad_type.slug,
            div_id="foo",
            keywords=None,
        )
        offer = Offer.objects.filter(pk=offer_dict["nonce"]).first()
        self.assertIsNotNone(offer)
        self.assertIsNotNone(offer.client_id)

        remove_old_client_ids()

        # Shouldn't remove the offer's client_id since it is "recent"
        offer.refresh_from_db()
        self.assertIsNotNone(offer.client_id)

        # Set the time back on the offer and the client_id should be blanked out
        offer.date = offer.date - datetime.timedelta(days=100)
        offer.save()
        remove_old_client_ids()

        # Offer's client_id is nulled out
        offer.refresh_from_db()
        self.assertIsNone(offer.client_id)
