API
===


Authentication
--------------

We require authentication on some requests,
but JSONP requests don't require them.
Authentication works in one of two ways:

 * For requests made in your web browser,
   your authenticated session will be used
 * For all other requests, you need to use the ``Authorization`` HTTP header::

       Authorization: Token 0000000000000000000000000000000000000000

   Where the value of the header is the string "Token"
   followed by a space and your 40 character API key.

.. note::

    Creating an API token can be done under :guilabel:`Username Dropdown > API Token`.


Ad decision
-----------

.. autoclass:: adserver.api.views.AdDecisionView


Publisher APIs
--------------

.. autoclass:: adserver.api.views.PublisherViewSet


Advertiser APIs
---------------

.. autoclass:: adserver.api.views.AdvertiserViewSet
