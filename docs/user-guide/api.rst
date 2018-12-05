API
===


Authentication
--------------

All API requests require a user to authenticate.
Authentication works in one of two ways:

 * For requests made in your web browser,
   your authenticated session will be used
 * For all other requests, you need to use the ``Authorization`` HTTP header::

       Authorization: Token 0000000000000000000000000000000000000000

   Where the value of the header is the string "Token"
   followed by a space and your 40 character API key.

Ad decision
-----------

.. autoclass:: adserver.api.views.AdDecisionView


Impression tracking
-------------------

.. autoclass:: adserver.api.views.ViewTrackingView
.. autoclass:: adserver.api.views.ClickTrackingView
