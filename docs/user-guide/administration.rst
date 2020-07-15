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


Invoicing advertisers
---------------------

Assuming an advertiser has a connected Stripe Customer ID,
invoices can be created for an advertiser directly from the ad server.
In the advertiser admin section or in flight administration (for admins, not advertisers),
select "Create draft invoice" from the actions dropdown,
select an advertiser or the flights to invoice for, and click Go.
This will create a draft invoice for the advertiser in Stripe which can customized further and sent.
