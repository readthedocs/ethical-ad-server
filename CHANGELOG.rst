CHANGELOG
=========

.. The text for the changelog is generated with ``npm run changelog``
.. Then it is formatted and copied into this file.
.. This is included by docs/developer/changelog.rst


Version v0.6.0
--------------

:Date: August 3, 2020

This release had a few minor changes but the larger changes involved
adding the ability to rate limit ad views
and an admin action for processing advertiser refunds/credits.

 * @davidfischer: Admin action for processing refunds (#220)
 * @davidfischer: Default ad creation to live (#218)
 * @davidfischer: Ignore all known users (#217)
 * @davidfischer: Update the all publishers report to show our revenue (#216)
 * @davidfischer: Rate limit ad viewing (#212)


Version v0.5.0
--------------

:Date: July 29, 2020

 * @davidfischer: Evaluate IP based proxy detection solution (#213)


Version v0.4.2
--------------

:Date: July 29, 2020

 * @davidfischer: IP Geolocation and Proxy detection improvements (#210)


Version v0.4.1
--------------

:Date: July 28, 2020

This was purely a bugfix release.

 * @davidfischer: Fix a bug around clicking an add after 4 hours (#208)


Version v0.4.0
--------------

:Date: July 28, 2020

There's two main changes in this release related to blocking referrers and UAs:
Firstly, the setting ``ADSERVER_BLACKLISTED_USER_AGENTS`` became ``ADSERVER_BLOCKLISTED_USER_AGENTS``.
Also, we added a setting ``ADSERVER_BLOCKLISTED_REFERRERS``.

 * @davidfischer: Send warnings to Sentry (#206)
 * @davidfischer: Allow blocking referrers for ad impressions with a setting (#205)


Version v0.3.2
--------------

:Date: July 28, 2020

This is a minor release that just changes some cookie settings
to have shorter CSRF cookies and send them in fewer contexts.
It also allows the link for an advertiser's ad to contain variables.

 * @davidfischer: Allow simple variables in Advertisement.link (#201)
 * @davidfischer: CSRF Cookie tweaks (#196)


Version v0.3.1
--------------

:Date: July 23, 2020

This is mostly a bugfix release and contains some slight operations tweaks.
The biggest change is to allow mobile targeting or excluding mobile traffic.

 * @davidfischer: Fix a secondary check on geo-targeting (#199)
 * @davidfischer: Optimization to choose a flight with live ads (#198)
 * @davidfischer: Add a link to the privacy policy (#197)
 * @davidfischer: Remove request logging (#193)
 * @davidfischer: Allow targeting mobile or non-mobile traffic (#192)
 * @dependabot[bot]: Bump lodash from 4.17.15 to 4.17.19 (#190)
 * @davidfischer: Flight targeting to include/exclude mobile traffic (#188)


Version v0.3.0
--------------

:Date: July 15, 2020

The major change in this version is the Stripe integration which allows tying
advertisers to a Stripe customer ID and the automated creation of invoices
(they're created as drafts for now) through the admin interface.

 * @ericholscher: Order the Ad admin by created date, not slug (#187)
 * @davidfischer: Use Django dev for Intersphinx (#186)
 * @davidfischer: Stripe integration (#185)
 * @ericholscher: Update docs to explain auth on POST request (#184)
