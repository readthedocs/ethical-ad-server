CHANGELOG
=========

.. The text for the changelog is generated with ``npm run changelog``
.. Then it is formatted and copied into this file.
.. This is included by docs/developer/changelog.rst


Version v0.24.0
---------------

In our reporting interface, we added some more summary and high level data
on ad and flight performance from a CTR perspective.
The other big change was a tweak to ad prioritization to prioritize
higher eCPM ads when making an ad decision.

:date: April 15, 2021

 * @davidfischer: Mute the disallowed host logger in prod (#362)
 * @dependabot[bot]: Bump django from 2.2.18 to 2.2.20 in /requirements (#361)
 * @ericholscher: Add naive attempt at price targeting (#360)
 * @davidfischer: Show CTR in summaries for ads and flights (#358)
 * @davidfischer: Create security policy (#356)
 * @davidfischer: Tweaks to the archive management command (#355)
 * @davidfischer: Update JS dependencies (#347)


Version v0.23.0
---------------

The big change in this release was to add overview screens for advertisers and publishers.
Another change was to include a ``ea-publisher`` query parameter with ad clicks.
This release also had some minor UX improvements to the reporting interface
and a few other minor changes.

:date: April 1, 2021

 * @davidfischer: Reporting UX improvements (#351)
 * @davidfischer: Advertiser/publisher overview screens (#350)
 * @dependabot[bot]: Bump y18n from 4.0.0 to 4.0.1 (#349)
 * @davidfischer: Add publisher query parameter to ad clicks (#348)
 * @davidfischer: Changes needed now that cryptography requires rust (#346)
 * @ericholscher: Tweaks payouts more (#345)
 * @davidfischer: Advertiser overview page (#174)
 * @davidfischer: Publisher overview page (#173)


Version v0.22.1
---------------

This was a tweak to the stickiness feature that rolled out earlier today.

:date: March 19, 2021

 * @davidfischer: Tweaks to the new stickiness factor (#342)


Version v0.22.0
---------------

The main feature in this release was to make sticky ad decisions.
This will make the same ad appear for the same user for a certain amount of time
(default 15s) even if they load new pages.

:date: March 19, 2021

 * @dependabot[bot]: Bump pillow from 7.1.2 to 8.1.1 in /requirements (#340)
 * @dependabot[bot]: Bump django from 2.2.13 to 2.2.18 in /requirements (#339)
 * @davidfischer: Enable sticky ad decisions (#338)
 * @davidfischer: Fix the geo report (#337)


Version v0.21.0
---------------

This release fixes a bug in report sorting and adds a management command to archive offers

:date: March 15, 2021

* @ericholscher: Sort indexes based on raw data vs. display (#333)
* @davidfischer: Archive offers management command (#332)
* @dependabot[bot]: Bump elliptic from 6.5.3 to 6.5.4 (#331)


Version v0.20.0
---------------

This release made some small reporting updates primarily for performance reasons.

:date: March 8, 2021

 * @davidfischer: Remove refunded offers from aggregate reports (#329)
 * @davidfischer: Total revenue report improvements (#328)
 * @ericholscher: Make the Geo report a bit faster (#326)
 * @ericholscher: Calculate Fill Rate against only paid offers (#325)
 * @ericholscher: Add debug flag to payout command (#324)
 * @ericholscher: Publisher report cleanup (#323)
 * @davidfischer: Uplift report updates (#319)


Version v0.19.1
---------------

This release is primarily bug fixes and minor changes to when scheduled tasks are run.

:date: March 3, 2021

 * @davidfischer: Remove hourly report updates. (#321)
 * @davidfischer: Fix off by 1 (actually 2) error in ad text size (#320)
 * @davidfischer: Run previous days reports automatically (#318)
 * @davidfischer: Fix a bug in the uplift report (#317)


Version v0.19.0
---------------

Most of these changes were minor quality of life improvements for managing the ad server.
It did involve a small dependency bump so it is a minor version increase.

:date: February 4, 2021

 * @davidfischer: Minor testing changes (#315)
 * @davidfischer: Don't count ad display when a particular ad is forced (#314)
 * @dependabot[bot]: Bump bleach from 3.1.4 to 3.3.0 in /requirements (#313)
 * @davidfischer: Show whats left on a flight always (#312)
 * @davidfischer: Add a management command for creating advertisers (#311)
 * @davidfischer: Fix a typo in the help text (#310)
 * @davidfischer: Small admin improvements (#309)
 * @davidfischer: Remove the link to DockerHub in the docs (#307)
 * @davidfischer: Show top publishers for an ad flight (#172)

Version v0.18.1
---------------

This change included just a new constraint to prevent a DB race condition.
Depending on your database, you may need to remove some records to apply the constraint.
See the migration file for a query to get the records that need to be removed.

:date: January 19, 2021

 * @davidfischer: Add a null offer constraint (#306)


Version v0.18.0
---------------

We made a change to make it a little easier for advertisers to have compelling ads.
Advertisers can now declare a headline for an ad, a body, and a call to action
and our default styles bold the headline and CTA.
These fields are broken out in our JSON API as well for ads if publishers
do custom integrations.
No changes were made to existing ads in our system.

:date: December 17, 2020

 * @davidfischer: Break the ad headline and CTA from the body (#302)


Version v0.17.0
---------------

The big user-facing change on this is to enable the publisher and geo reports for advertisers.
There's also an easy option to exclude a publisher for an advertiser if requested.

:date: December 15, 2020

 * @davidfischer: Add a backend option to exclude publishers for an advertiser (#300)
 * @davidfischer: Enable the geo and publisher report for advertisers (#299)
 * @davidfischer: Fix a few issues with refunding (#298)


Version v0.16.0
---------------

:date: December 1, 2020

This release contained some minor reporting changes and some admin-specific reports.
We are testing some new advertiser reports (showing top geos, top publishers)
but those are staff-only now but will likely roll out to all advertisers
in the next release.

 * @davidfischer: Advertiser reporting breakdowns (#295)
 * @ericholscher: Add uplift reporting (#294)
 * @ericholscher: Additional payout automation (#285)

Version v0.15.0
---------------

:date: November 24, 2020

There were a few minor fixes and refactors in this release.
We are defaulting new publishers to use viewport tracking (#292),
and we found a slight bug which was hotfixed related to Acceptable Ads uplift.
There were significant internal changes to reporting to make
creating new reports easier but these should not have significant user-facing changes.

 * @ericholscher: Update a few model method defaults (#292)
 * @davidfischer: Report refactor (#291)
 * @ericholscher: Don't overwrite Offer on uplift (#290)


Version v0.14.0
---------------

:date: November 17, 2020

This version adds additional reporting around keywords and offer rate.
Both of these are behind admin-only flags until we do more testing,
but will likely be enabled in the next release.

 * @ericholscher: Add keyword reporting for publishers (#286)
 * @ericholscher: Add Decision modeling to our indexes (#274)


Version v0.13.0
---------------

:date: November 10, 2020

This version ships two new publisher reports: Geos and Advertisers.
It also adds uplift tracking for Acceptable Ads tracking,
allowing the server to be used for AA-approved ad networks.

 * @ericholscher: Add uplift to Offers (#279)
 * @ericholscher: Ship Geo & Advertiser reports to publishers (#278)
 * @ericholscher: Don’t pass `advertiser` to the all publishers reports. (#277)
 * @dependabot[bot]: Bump dot-prop from 4.2.0 to 4.2.1 (#276)


Version v0.12.0
---------------

:date: November 3, 2020

None of the changes in this release are user facing.
There are improvements to track and understand the fill rate for publishers
(why some requests don't result in a paid ad) and another change
to prepare to show publishers details of the advertisers advertising on their site.

 * @ericholscher: Make Offers nullable to track fill rate (#272)
 * @ericholscher: Add a new report for Publishers showing their advertisers (#271)
 * @ericholscher: Add ability to sort All Publishers report by all metrics (#273)


Version v0.11.1
---------------

:date: October 29, 2020

This release adds the ability do to viewport tracking on publisher sites.
It is managed on the backend via an admin setting,
and we'll be slowly rolling it out to publishers.

 * @ericholscher: Add a render_pixel option to the publisher. (#269)
 * @davidfischer: Performance workaround for the offer admin (#267)


Version v0.11.0
---------------

:Date: October 27, 2020

This release adds Celery tasks for indexing of all our generated reporting indexes.
We also added a Geo index in beta for this release,
along with a few performance improvements.

 * @davidfischer: Add an estimated count paginator (#265)
 * @davidfischer: Add get_absolute_url methods to flight and advertiser models (#264)
 * @ericholscher: Show breakdown report on the Geo/Placement reports by default (#263)
 * @ericholscher: Remove unused entrypoint from dockerfile (#262)
 * @ericholscher: Properly sort Countries in Geo report by most views (#261)
 * @ericholscher: Migrate PlacementImpressions to a Celery task (#260)
 * @ericholscher: Clean up Publisher settings (#259)
 * @ericholscher: Cleanup celery config to work with beat (#258)
 * @davidfischer: Index the date fields on ad impressions, clicks, views, and offers (#257)
 * @ericholscher: Callout to EA (#256)
 * @ericholscher: Add an initial Geo report for publishers (#244)


Version v0.10.2
---------------

:Date: October 1, 2020

v0.10.2 finally fixed the slow migration issues.

 * @ericholscher: Make ad_type a slug on the AdBase & PlacementImpression (#248)


Version v0.10.1
---------------

:Date: October 1, 2020

v0.10.0 caused a very long migration which we resolved in v0.10.1

 * @ericholscher: Don’t index `ad_type` on the AdBase (#246)


Version v0.10.0
---------------

:Date: October 1, 2020

The major change in this release was to allow publishers to individually
track the performance of ads on certain pages/sections separately
by adding an ``id`` attribute to the ad ``<div>``.
Behind the scenes, there was a rework in how we track when an ad is
offered and viewed but those are not user facing.

 * @ericholscher: Store placements and keywords and add reporting (#239)


Version v0.9.1
--------------

:Date: September 22, 2020

 * @ericholscher: Update precommit deps to match latest (#240)
 * @ericholscher: Improve automation around payouts (#237)
 * @ericholscher: Add a management command to add a publisher (#236)
 * @ericholscher: Allow sorting All Publishers list by revenue (#235)

Version v0.9.0
--------------

:Date: August 25, 2020

The largest change in this release was to store publisher payout settings
and allow publishers to connect via Stripe to attach a bank account for payouts.

 * @davidfischer: Turn down the rate limiting logging (#232)
 * @davidfischer: Use Django2 style URLs everywhere (#231)
 * @davidfischer: Refactor publisher tests (#230)
 * @davidfischer: Store publisher payout settings (#229)
 * @davidfischer: Refactor flight metadata view (#180)
 * @davidfischer: Store publisher payout settings (#177)


Version v0.8.0
--------------

:Date: August 18, 2020

The two changes in this release were to add branding to the ad server
which is only enabled in production and shouldn't be used by third-parties
and to add the ability to group publishers into groups for targeting purposes.

 * @davidfischer: Group publishers (#227)
 * @davidfischer: Add EthicalAds branding to the adserver (#226)


Version v0.7.0
--------------

:Date: August 5, 2020

The main change in this version is to add a database model for storing publisher payouts
and making that data visible to publishers.

 * @davidfischer: Change some log levels around impressions blocking (#224)
 * @davidfischer: Save publisher payouts (#223)
 * @ericholscher: Make Publisher defaults line up with Ad Network defaults (#222)


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
