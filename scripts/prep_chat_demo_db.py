"""
Prep local database for the AI chat demo.

Usage:
    python manage.py shell < scripts/prep_chat_demo_db.py

This script uses the first existing object for each model where possible,
creating only what's missing. It wires everything together so that the
chat demo at /chat/ can successfully request and display ads.
"""

import datetime

from django.utils import timezone

from adserver.constants import HOUSE_CAMPAIGN
from adserver.models import (
    AdType,
    Advertisement,
    Advertiser,
    Campaign,
    Flight,
    Publisher,
    PublisherGroup,
)


def run():
    print("=" * 60)
    print("Prepping database for AI chat demo")
    print("=" * 60)

    # --- Publisher Group ---
    pub_group = PublisherGroup.objects.first()
    if not pub_group:
        pub_group = PublisherGroup.objects.create(
            name="Chat Demo Group",
            slug="chat-demo-group",
            default_enabled=True,
        )
        print(f"  Created PublisherGroup: {pub_group}")
    else:
        print(f"  Using existing PublisherGroup: {pub_group} (slug={pub_group.slug})")

    # --- Publisher ---
    publisher = Publisher.objects.first()
    if not publisher:
        publisher = Publisher.objects.create(
            name="Chat Demo Publisher",
            slug="chat-demo",
        )
        print(f"  Created Publisher: {publisher}")
    else:
        print(f"  Using existing Publisher: {publisher} (slug={publisher.slug})")

    # Ensure publisher is configured for the demo
    changed_fields = []
    if not publisher.unauthed_ad_decisions:
        publisher.unauthed_ad_decisions = True
        changed_fields.append("unauthed_ad_decisions")
    if not publisher.allow_paid_campaigns:
        publisher.allow_paid_campaigns = True
        changed_fields.append("allow_paid_campaigns")
    if not publisher.allow_house_campaigns:
        publisher.allow_house_campaigns = True
        changed_fields.append("allow_house_campaigns")
    if not publisher.allow_community_campaigns:
        publisher.allow_community_campaigns = True
        changed_fields.append("allow_community_campaigns")
    if not publisher.allow_api_keywords:
        publisher.allow_api_keywords = True
        changed_fields.append("allow_api_keywords")
    if publisher.disabled:
        publisher.disabled = False
        changed_fields.append("disabled")
    if changed_fields:
        publisher.save(update_fields=changed_fields)
        print(f"  Updated Publisher fields: {changed_fields}")

    # Link publisher to publisher group
    if not publisher.publisher_groups.filter(pk=pub_group.pk).exists():
        pub_group.publishers.add(publisher)
        print(f"  Added Publisher to PublisherGroup")

    # --- AdType ---
    ad_type = AdType.objects.filter(slug="readthedocs-sidebar").first()
    if not ad_type:
        ad_type = AdType.objects.first()
    if not ad_type:
        ad_type = AdType.objects.create(
            name="Sidebar Image",
            slug="image-v1",
            has_image=True,
            image_width=240,
            image_height=180,
            has_text=True,
            max_text_length=150,
            default_enabled=True,
        )
        print(f"  Created AdType: {ad_type}")
    else:
        print(f"  Using existing AdType: {ad_type} (slug={ad_type.slug})")

    # --- Advertiser ---
    advertiser = Advertiser.objects.first()
    if not advertiser:
        advertiser = Advertiser.objects.create(
            name="Demo Advertiser",
            slug="demo-advertiser",
        )
        print(f"  Created Advertiser: {advertiser}")
    else:
        print(f"  Using existing Advertiser: {advertiser} (slug={advertiser.slug})")

    # --- Campaign ---
    campaign = Campaign.objects.first()
    if not campaign:
        campaign = Campaign.objects.create(
            name="Demo Campaign",
            slug="demo-campaign",
            advertiser=advertiser,
            campaign_type=HOUSE_CAMPAIGN,
        )
        print(f"  Created Campaign: {campaign}")
    else:
        print(f"  Using existing Campaign: {campaign} (slug={campaign.slug})")

    # Ensure the campaign's publisher groups include ours
    if not campaign.publisher_groups.filter(pk=pub_group.pk).exists():
        campaign.publisher_groups.add(pub_group)
        print(f"  Added PublisherGroup to Campaign")

    # --- Flight ---
    flight = Flight.objects.first()
    if not flight:
        flight = Flight.objects.create(
            name="Demo Flight",
            slug="demo-flight",
            campaign=campaign,
            live=True,
            cpc=0,
            cpm=0,
            sold_clicks=10000,
            start_date=datetime.date.today() - datetime.timedelta(days=1),
            end_date=datetime.date.today() + datetime.timedelta(days=365),
        )
        print(f"  Created Flight: {flight}")
    else:
        print(f"  Using existing Flight: {flight} (slug={flight.slug})")

    # Ensure flight is live and has a valid date range
    changed_fields = []
    if not flight.live:
        flight.live = True
        changed_fields.append("live")
    if flight.start_date > datetime.date.today():
        flight.start_date = datetime.date.today() - datetime.timedelta(days=1)
        changed_fields.append("start_date")
    if flight.end_date < datetime.date.today():
        flight.end_date = datetime.date.today() + datetime.timedelta(days=365)
        changed_fields.append("end_date")
    if flight.sold_clicks == 0 and flight.sold_impressions == 0:
        flight.sold_clicks = 10000
        changed_fields.append("sold_clicks")
    if changed_fields:
        flight.save(update_fields=changed_fields)
        print(f"  Updated Flight fields: {changed_fields}")

    # --- Advertisement ---
    ad = Advertisement.objects.first()
    if not ad:
        ad = Advertisement.objects.create(
            name="Demo Ad",
            slug="demo-ad",
            flight=flight,
            headline="Try Our Developer Tools",
            content="Build faster with our modern dev platform.",
            cta="Learn More",
            link="https://example.com/?utm_source=ethicalads",
            live=True,
        )
        print(f"  Created Advertisement: {ad}")
    else:
        print(f"  Using existing Advertisement: {ad} (slug={ad.slug})")

    # Ensure ad is live
    if not ad.live:
        ad.live = True
        ad.save(update_fields=["live"])
        print(f"  Set Advertisement live=True")

    # Ensure ad has the ad type
    if not ad.ad_types.filter(pk=ad_type.pk).exists():
        ad.ad_types.add(ad_type)
        print(f"  Added AdType '{ad_type.slug}' to Advertisement")

    # --- Summary ---
    print()
    print("=" * 60)
    print("Setup complete! Here's your configuration:")
    print("=" * 60)
    print()
    print(f"  Publisher slug:  {publisher.slug}")
    print(f"  AdType slug:     {ad_type.slug}")
    print(f"  Advertiser:      {advertiser.name}")
    print(f"  Campaign:        {campaign.name} (type={campaign.campaign_type})")
    print(f"  Flight:          {flight.name} (live={flight.live})")
    print(f"  Advertisement:   {ad.name} (live={ad.live})")
    print()
    print("Environment variables to set:")
    print(f'  export ADSERVER_CHAT_DEMO_PUBLISHER="{publisher.slug}"')
    print(f'  export OPENAI_API_KEY="sk-your-key-here"')
    print()
    print("Then run:")
    print("  python manage.py runserver")
    print()
    print("And open: http://localhost:8000/chat/")
    print()
    print(f"Test the ad API directly:")
    print(
        f"  curl 'http://localhost:8000/api/v1/decision/"
        f"?publisher={publisher.slug}"
        f"&div_ids=ad1"
        f"&ad_types={ad_type.slug}"
        f"&keywords=python'"
    )
    print()


run()
