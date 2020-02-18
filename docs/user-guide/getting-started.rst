Getting Started
===============

After the ad server is installed and you've :ref:`install/installation:Set the ad server URL`,
you can begin to create new user accounts and setup ad campaigns.

Unlike setting up something like Google Ad Words or many other ad platforms,
you don't just copy a JavaScript blob into your pages.
Instead, this ad server is run "server-to-server" meaning that the publisher's server (where the ads are shown)
connects to the ad server to get an ad. This allows features like server-side rendering of ads
rather than rendering them with JavaScript.

In the future, we may include a way to get ads with pure JavaScript but that isn't a high priority feature right now.


Understanding the ad server modeling
------------------------------------

There's a few models and terminology to understand that will help understand how the ad server is set up:

Advertisers
    These are individual companies that are advertising on the server.
    This could include a house advertiser run by the ad server.

Publishers
    These are various sites where ads are shown.
    When an ad is requested, it is requested by a publisher.
    Advertisers can limit which publishers can show their ads.
    Revenue is tracked individually per publisher.

Campaigns
    Campaigns generally represents a group of ad flights from an advertiser.
    No ad targeting is done at the campaign level.
    While most campaigns are "paid", ad server admins can configure "affiliate", "house" or "community" campaigns
    which have a lower priority than paid (Paid > Affiliate > Community > House).
    Most advertisers will only have 1 campaign (but multiple Flights) although sometimes multiple are needed
    if the advertiser has both "paid" and "community" ads or if they want to have
    different campaigns for different Publishers.

Flights
    Flights handle the budgeting and targeting for an individual ad buy from an Advertiser.
    For example, an advertiser might buy $500 worth of ads at $1 CPM with certain keyword or geographic targeting.
    The flight is a group of ads that are all part of the same ad buy and have the same targeting.
    This allows an advertiser to easily run multiple ads and find the best performing subset.

Advertisements
    This is an individual ad that can have an image, text, and a destination URL associated with it.

Ad types
    These are different ad types (and custom types) that the ad server supports.
    Ad types specify the parameters for an ad like whether it has an image or how long the text can be.

Ad Impressions
    Ad impressions store quantity of views and clicks for each ad on each publisher each day.

Clicks
    Each time an ad is clicked and the click is "billed", a Click record is written to the database
    with the page where the click occurred, the publisher, datetime, the specific ad, and some metadata about the user
    such as an anonymized IP and anonymized user agent.
    A click is considered "billed" regardless of whether the click cost money for a CPC flight or not
    as long as the following conditions are met:

    * This isn't a duplicate click
    * The user isn't rate limited
    * The user agent isn't banned or a known "bot"
    * The flight targeting (which is rechecked) matches
    * The user is not logged in as a staff account
    * The IP doesn't come from an :ref:`install/configuration:INTERNAL_IPS`

Views
    Just like clicks are stored each time an ad is clicked, it is possible to do the same each time an ad is viewed.
    By default, this is off in production and there should be no metadata on individual views.
    However, it can be enabled by toggling :ref:`install/configuration:ADSERVER_RECORD_VIEWS`.


Creating more users
-------------------

Additional login accounts for staff, advertisers, and publishers are created in the
:doc:`administration interface </user-guide/administration>` under :guilabel:`Ad Server Auth` > :guilabel:`Users`.
Users can be associated with specific advertisers or publishers.
This will reduce the actions and reports that a specific user can see.

Staff users can see reports for all advertisers and publishers.


Setting up advertisements
-------------------------

Advertisers, campaigns, flights, and individual ads are created in the
:doc:`administration interface </user-guide/administration>` under :guilabel:`Ad Server Core`.

For the very first time, you'll need to create a record for an advertiser and a campaign.
Then you can create a flight. Flights are where the details of the ad buy are stored
such as how many clicks (CPC) or impressions (CPM) were purchased at a specific price.
This is also where the targeting for a set of ads is configured.

.. figure:: /_static/img/user-guide/edit-flights.png
    :alt: Configuring an ad flight
    :width: 100%

    Configuring an ad flight

Once an ad flight is configured, one or more ads can be setup for that flight.
These are configured in the same interface.

Once the ads are setup, requests for an :ref:`ad decision <user-guide/api:Ad decision>`
will pick up your new ads assuming the targeting matches.


Reporting
---------

Reporting tables are available immediately upon logging in.
Access to publisher or advertiser reports are restricted to users who have access to them.
