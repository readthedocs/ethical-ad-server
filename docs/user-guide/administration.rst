Administering
=============

More interfaces are actively being built, but most data is currently entered in this administration interface.
Staff users get a link to the admin interface in the usual dashboard that shows reports (in the upper right menu).
The URL is ``/admin`` by default but this can be customized by setting :ref:`install/configuration:ADSERVER_ADMIN_URL`

.. figure:: /_static/img/user-guide/admin-interface.png
    :alt: The admin interface
    :width: 100%

    The admin interface


Deleting data
-------------

Most advertising records in the ad server such as clicks, impressions, advertisers, advertisements
cannot be deleted through the administration interface after they are created.
This is by design so that billing data is never deleted in the system.
Ads and flights can be deactivated so they aren't used, but advertiser data is not deleted.

If you absolutely must delete data, you'll have to go to the database directly.


Managing flight targeting
-------------------------

Most common flight targeting options can be managed by a staff user through the "Edit Flight" view.
However, certain uncommonly used options may need to be managed in the Django admin
by setting the appropriate flight targeting JSON.

The valid options here are:

``include_countries``
    A list of two digit country codes where this flight may be shown.
``exclude_countries``
    A list of two digit country codes where this flight may not be shown.
``include_regions``
    A list of region slugs that map to the region data in the database.
    The flight may be shown only in these regions.
    Regions and countries **should not** be combined.
``exclude_regions``
    Similar to the above except the flight will not be shown in these regions
``include_topics``
    A list of topic slugs that map to topic data in the database.
    The flight will only be shown on pages that match any of these topics.
``include_keywords``
    A list of keywords. The flight will only be shown on pages that match
    any of these keywords.
``exclude_keywords``
    A list of keywords except the flight will not be shown on matching pages.
``include_publishers``
    An allowlist of publisher slugs and the flight will only be shown on these publishers.
``exclude_publishers``
    A denylist of publishers where the flight will not be shown on these publishers.
``include_domains``
    An allowlist of domains where the flight will only be shown on these domains.
``exclude_domains``
    A denylist of domains where the flight will not be shown on these domains.
``mobile_traffic``
    Can be used to only show a flight to mobile traffic or to exclude mobile users from flights.
    Possible values: ``exclude`` and ``only``.
``include_state_provinces``
    An allowlist of state/province codes that can be combined with ``include_countries``.
    Not all of our geo targeting middlewares support targeting by state.
``include_metro_codes``
    An allowlist of 3 digit DMA codes that can be combined with ``include_countries``.
    Not all of our geo targeting middlewares support targeting by metro.
``days``
    A lowercase list of days of the week where the flight should be shown. Generally used for weekdays or weekends.

For a campaign that targets data science pages visited by users in the US & Canada not on mobile,
an example targeting JSON would be::

    {
        "include_regions": [
            "us-ca"
        ],
        "include_topics": [
            "data-science"
        ],
        "mobile_traffic": "exclude"
    }





Flight traffic caps
-------------------

Another advanced feature is to create a traffic cap that enforces
a limit on how a flight is fulfilled.
For example, we can specify a cap where a flight be fulfilled
no more than a specified percent on a particular publisher or in a country.
This is done by setting a traffic cap JSON in the Django admin.

The valid options are:

``publishers``
    Set a maximum percentage (maximum of 1.0) for particular publishers.
``countries``
    Set a maximum percentage for particular countries.
``regions``
    Set a maximum percentage for particular regions.

For a flight that enforces that no more than 25% of the campaign will be fulfilled in the US,
and no more than 5% in Canada,
the following JSON would be used::

    {
        "countries": {"US": 0.25, "CA": 0.05},
    }


Invoicing advertisers
---------------------

Assuming an advertiser has a connected Stripe Customer ID,
invoices can be created for an advertiser directly from the ad server.
In the advertiser admin section or in flight administration (for admins, not advertisers),
select "Create draft invoice" from the actions dropdown,
select an advertiser or the flights to invoice for, and click Go.
This will create a draft invoice for the advertiser in Stripe which can customized further and sent.


Processing refunds
------------------

For billed clicks and views that need to be refunded or credited back to the advertiser,
there is an administration action which will correctly update all the relevant models
and mark the impression as refunded so it can't be refunded again.

Go to :guilabel:`Ad Server Core` > :guilabel:`Views` or :guilabel:`Clicks`,
select the impressions to refund, choose the refund action from the dropdown, and hit "Go".
