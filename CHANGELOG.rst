CHANGELOG
=========

.. The text for the changelog is generated with ``npm run changelog``
.. Then it is formatted and copied into this file.
.. This is included by docs/developer/changelog.rst


Version v0.55.0
---------------

The large change in this release is to add a machine learning
topic classifier that uses a custom trained model.
This release also contained minor dependency updates and bugfixes.

:date: July 18, 2022

 * @ericholscher: Fix archive_offers db code (#611)
 * @davidfischer: Add the topic classifier backend (#609)
 * @dependabot[bot]: Bump django from 3.2.13 to 3.2.14 in /requirements (#607)
 * @davidfischer: Downgrade mismatched client log to debug (#606)
 * @davidfischer: Fix multi topic targeting bug (#605)
 * @ericholscher: Fix email going to advertisers (#604)
 * @ericholscher: Add a comment that explains what to do when swapping the offers table (#603)
 * @ericholscher: Add initial ML experimentation (#597)


Version v0.54.1
---------------

This release has a few small advertiser management updates.

:date: June 28, 2022

 * @ericholscher: Show budget in manage ads flight list (#601)
 * @ericholscher: Add ability to create invoices for exact view amounts (#600)
 * @ericholscher: Cleanup copy in end of flight email a little (#599)
 * @dependabot[bot]: Bump ansi-regex from 4.1.0 to 4.1.1 (#594)

Version v0.54.0
---------------

The topic analyzer now uses a very basic machine learning model
to determine the topic and keywords for a page.

:date: June 20, 2022

 * @davidfischer: Mention publisher-house campaign type in docs (#593)
 * @davidfischer: Add a textacy/spacy-based analyzer model (#591)
 * @agjohnson: Add admin search for payout pk (#590)


Version v0.53.0
---------------

Outside of dependency fixes, this release had two major features.
Firstly, region and topic modeling are moved into the DB.
Flights can target by region or topic.
Secondly, we allow publishers to setup their own house ads.

:date: June 3, 2022

 * @davidfischer: Some dependency fixes (#588)
 * @davidfischer: Puts the notification settings on the same line (#587)
 * @ericholscher: Fix flight list URL (#586)
 * @davidfischer: Docs fix for the DATABASES setting (#585)
 * @dependabot[bot]: Bump pyjwt from 2.1.0 to 2.4.0 in /requirements (#584)
 * @davidfischer: Region & topic modeling (#583)
 * @dependabot[bot]: Bump moment from 2.29.1 to 2.29.2 (#563)
 * @dependabot[bot]: Bump minimist from 1.2.5 to 1.2.6 (#555)
 * @dependabot[bot]: Bump ajv from 6.10.2 to 6.12.6 (#528)
 * @dependabot[bot]: Bump node-sass from 4.14.1 to 7.0.0 (#523)


Version v0.52.0
---------------

The main change this release is turn on the daily analysis tasks.
These will scan websites where we server ads to try to understand them
and target better.

:date: May 20, 2022

 * @davidfischer: Add a daily cap for publishers (#579)
 * @davidfischer: Enable URL analyzer tasks (#578)
 * @davidfischer: Add an advertiser keyword report (#577)
 * @davidfischer: Handle invalid URLs in analysis (#576)
 * @davidfischer: Remove the left nav when printing (#575)

Version v0.51.0
---------------

The largest changes in this release were to add helpful screens during
onboarding of advertisers and publishers.
Other than that, we are continuing to iterate on the offline keyword
analysis.

:date: May 4, 2022

 * @davidfischer: Rework the analysis tasks (#573)
 * @davidfischer: Tips to help with advertiser onboarding (#572)
 * @davidfischer: Improved publisher onboarding (#571)
 * @davidfischer: Show ad CTR on the ad detail screen (#570)
 * @dependabot[bot]: Bump django from 3.2.12 to 3.2.13 in /requirements (#569)


Version v0.50.0
---------------

There were a few small tweaks and bug fixes in this release.
The big change was some new tasks to test offline keyword analysis
which is not yet integrated in when deciding which ad to show.

:date: April 20, 2022

 * @davidfischer: Guide advertisers on upcoming flights (#567)
 * @davidfischer: Refunds handle null offers (#566)
 * @davidfischer: Offline keyword and topic analysis (#564)
 * @davidfischer: Ensure ads are live after renewing (#562)
 * @davidfischer: Small tweaks to the wrapup email (#561)
 * @davidfischer: Log mismatched clients between offer and impression (#560)


Version v0.49.0
---------------

Add a Front email backend, and a couple small dependency upgrades.
This release also starts displaying the time an add is viewed (view time)
to staff users. Once vetted, this will be shown to advertisers and publishers.

:date: March 30, 2022

 * @davidfischer: Fix a pre-commit versioning issue (#557)
 * @davidfischer: Send a flight wrapup email (#556)
 * @davidfischer: Fix a number of test warnings (#554)
 * @davidfischer: Add a form for controlling user notifications (#553)
 * @davidfischer: Adds a Front (front.com) email backend (#552)
 * @davidfischer: Fix an awkward space (#551)
 * @davidfischer: Remove the redirect on the staging server (#550)
 * @ericholscher: Add view_time to AdImpression model (#546)
 * @ericholscher: Add a Python data import script (#520)


Version v0.48.2
---------------

Fixed more issues that weren't seen until staging.
Notably, a New Relic upgrade was required.

:date: March 17, 2022

 * @davidfischer: Still more Django 3.2 upgrade fixes (#548)


Version v0.48.1
---------------

This release fixed some issues not seen in development related to v0.48.0.
That release shouldn't be used.

:date: March 17, 2022

 * @davidfischer: Additional Django 3.2 fixes (#545)


Version v0.48.0
---------------

This release was purely to update dependencies.

:date: March 16, 2022

 * @dependabot[bot]: Bump pillow from 9.0.0 to 9.0.1 in /requirements (#543)
 * @davidfischer: Use pytest for testing (#541)
 * @davidfischer: Django 3.2 upgrade (#539)


Version v0.47.0
---------------

This version contained a number of small improvements to performance
and some additional notifications.
The larger change was a new staff-only (for now) form
for renewing an advertising flight.

:date: March 9, 2022

 * @davidfischer: Close flights when complete (#540)
 * @davidfischer: Post to Slack when an invoice is paid (#537)
 * @davidfischer: Flight renewal form (#536)
 * @davidfischer: Performance improvement to offer recording (#533)
 * @davidfischer: Aggregation task performance improvements (#532)
 * @ericholscher: Fix payout url for invalid methods (#531)
 * @ericholscher: Record data for forced ads if they are unpaid. (#530)


Version v0.46.1
---------------

We had a bug in the previous release that affected server-to-server ad clients.
These clients pass an IP address for geolocating and we weren't re-running
GeoIP for them properly.

:date: February 21, 2022

 * @davidfischer: Force IP Geolocation if there's a passed userip (#534)
 * @ericholscher: Don't show paid ads warning on saas account (#527)


Version v0.46.0
---------------

The big change here is added middleware for getting IP addresses
and for geolocating them. This gives options instead of just relying on
``X-Forwarded-For`` or using the MaxMind GeoIP databases.
For production, we will be using Cloudflare for GeoIP and IP normalization.

See the `docs <https://ethical-ad-server.readthedocs.io/en/latest/install/configuration.html#adserver-geoip-middleware>`_.

:date: February 14, 2022

 * @davidfischer: Put the priority multiplier in the flight form (#526)
 * @davidfischer: Add an existing user to an advertiser (#525)
 * @dependabot[bot]: Bump django from 2.2.26 to 2.2.27 in /requirements (#524)
 * @davidfischer: Use Cloudflare GeoIP and IP canonicalization (#512)


Version v0.45.1
---------------

This is purely a bugfix release.
The main fix is a fix for keyword aggregation that fixes a bug introduced in v0.44.0.
All keyword aggregations done since v0.44.0 need to be re-run.

:date: February 9, 2022

 * @davidfischer: Fix typo with keyword aggregation (#521)
 * @davidfischer: Handle a bug with a forced ad but mismatched ad type (#519)


Version v0.45.0
---------------

Other than a few quality of life improvements and bug fixes,
the main change in this release is a many-to-many relation between Flights to Invoices.

:date: February 8, 2022

 * @davidfischer: Disable a publisher completely (#517)
 * @davidfischer: Add a campaign inline to the advertiser admin (#516)
 * @davidfischer: Connect flights to invoices (#515)
 * @davidfischer: Change the default flight size and price (#514)
 * @davidfischer: Fix for incorrectly creating new advertisers (#513)
 * @ericholscher: Decisions aren't currency :) (#511)


Version v0.44.0
---------------

**NOTE:** This release requires Python 3.8

The largest change in this release was an upgrade to Python 3.8.
Other than that, there were a few migrations to support tighter Stripe integration
and some changes that will allow a set of publishers who pay us (instead of get paid)
to run their house ads or sponsorship.

:date: January 26, 2022

 * @ericholscher: Start modeling SaaS publishers to show them billing data (#509)
 * @davidfischer: Optimize the keyword aggregation (#508)
 * @davidfischer: Handle an extra long div-id (#507)
 * @ericholscher: Expose View Rate to publishers. (#505)
 * @davidfischer: Upgrade to Python 3.8 (#503)
 * @davidfischer: Stripe foreign key fields migrations (#498)
 * @dependabot[bot]: Bump pillow from 8.3.2 to 9.0.0 in /requirements (#496)


Version v0.43.1
---------------

The only changes in this release were minor bug fixes
and slight tweaks on some checks when updating ads and flights.

:date: January 20, 2022

 * @davidfischer: Tone down the link error message. (#504)
 * @davidfischer: Use iterators in daily aggregations (#502)
 * @davidfischer: Ensure the start date comes before the end date (#501)
 * @davidfischer: Distinct away duplicate ad types (#500)


Version v0.43.0
---------------

The big change in this PR was the beginnings of tighter Stripe integration.
This PR merely sets the groundwork by adding django-stripe which syncs
data from Stripe to our local database.

:date: January 18, 2022

 * @dependabot[bot]: Bump django from 2.2.24 to 2.2.26 in /requirements (#497)
 * @ericholscher: Disable metabase restart (#495)
 * @davidfischer: Initial DJStripe integration (#494)
 * @davidfischer: Make disabled ads more obvious (#493)
 * @davidfischer: Update exclude list (#492)
 * @davidfischer: Tweak to progress bar formatting (#490)
 * @davidfischer: Make the user name optional on the advertiser form (#489)
 * @davidfischer: Fix a bug with an invalid view time (#488)
 * @ericholscher: Fix another silly month/year date bug (#484)
 * @decaffeinatedio: Update GeoIP Links (#427)


Version v0.42.0
---------------

This release adds the ability for advertisers to view old invoices,
and does a few small operations changes.
The most important is being able to rename the Offers database table,
which we plan to do in production to improve database performance.

:date: November 15, 2021

 * @ericholscher: These ports were used for me locally, let them be overridden. (#486)
 * @ericholscher: Change the offers db_table to give us more space (#485)
 * @davidfischer: Enable Stripe billing portal for advertisers (#483)

Version v0.41.0
---------------

We added Plausible Analytics to see which parts of the dashboard get the most use.
We also added a lot more charts for staff and made a couple charts available
to advertisers and publishers.

:date: October 28, 2021

 * @davidfischer: Make metabase charts public (#480)
 * @davidfischer: Add Plausible Analytics to the dashboard (#479)
 * @ericholscher: Remove analytical import from settings (#478)
 * @davidfischer: Add additional charts (#477)


Version v0.40.0
---------------

The big change in this release was that we're trying out some graphs.
However, for this release, they are staff-only.
Other than that, there was nothing user facing in this release.

:date: October 21, 2021

 * @davidfischer: Charting/graphing with metabase (#475)
 * @davidfischer: Remove the CTR publisher change alert (#473)
 * @ericholscher: Show publisher name instead of slug in payout (#472)
 * @davidfischer: Tweaks to the daily aggregation task (#471)
 * @ericholscher: Make azure logging quiet (#470)
 * @ericholscher: Fix a bug where existing AdType was excluded (#455)


Version v0.39.0
---------------

Most of this release were small bug fixes and tweaks to staff notifications.

:date: October 6, 2021

 * @ericholscher: Force using the default DB during ad serving incr call (#467)
 * @davidfischer: Small tweak to flight ordering (#466)
 * @davidfischer: Fail silently on slack failures (#464)
 * @davidfischer: Increase aggregation task time limit (#463)
 * @davidfischer: Notify when daily reports are aggregated (#462)
 * @ericholscher: Fix silly where bug data wasn't defined if we weren't caching. (#461)



Version v0.38.0
---------------

This release had a number of changes to support custom publishers and support for a read replica on our reporting.

:date: September 24, 2021

 * @davidfischer: Fixes a bug with old-style ads (#458)
 * @ericholscher: Add a read replica DB router & settings (#457)
 * @ericholscher: Fix mailing list link. (#456)
 * @ericholscher: Add ability to export region data (#454)
 * @ericholscher: Update the link we're pointing to for CTR low messages (#452)
 * @ericholscher: Add ability to uncache publisher ads (#451)
 * @ericholscher: Fix payout filtering & show status in admin (#450)
 * @davidfischer: When copying ads, put newest ads first (#448)
 * @dependabot[bot]: Bump pillow from 8.2.0 to 8.3.2 in /requirements (#447)
 * @davidfischer: Flight form improvements (#443)


Version v0.37.0
---------------

This release had a minor change to topic-based reporting only.

:date: September 13, 2021

 * @ericholscher: Add `other` to the list of topics when none other apply. (#446)


Version v0.36.0
---------------

The big change in this release was to revamp our reporting
to be more focused on topic and region rather than
individual keywords and countries/regions.
This should make be much faster than the previous geo and keyword
reports which will be phased out.

:date: August 31, 2021

 * @davidfischer: More tweaks to publisher notifications (#444)
 * @ericholscher: Add "Stay updated" to the top of the payout email (#442)
 * @ericholscher: Tweaks payouts with issues that we've found (#441)
 * @ericholscher: Make advertiser flight ads linkable (#440)
 * @ericholscher: Add StaffRegionReport (#431)
 * @ericholscher: Make report queries faster (#376)


Version v0.35.0
---------------

The main change in this release involved the server side changes
to store how long an ad is viewed.
We believe this is a cool metric to show to advertisers
and may separate us from competition and generate higher revenues for publishers.

:date: August 13, 2021

 * @ericholscher: Fix silly bug with Payouts (#438)
 * @davidfischer: Minor tweaks around view time (#437)
 * @dependabot[bot]: Bump path-parse from 1.0.6 to 1.0.7 (#436)
 * @davidfischer: Remove server side analytics which we weren't using (#435)
 * @davidfischer: Fix the build (#434)
 * @decaffeinatedio: No results from decision API despite valid(?) configuration (#432)


Version v0.34.0
---------------

This release had no significant user-facing changes.
All the changes involved staff interfaces, staff notifications,
or documentation.

:date: August 4, 2021

 * @davidfischer: Fix form submission for flights with no targeting (#429)
 * @davidfischer: Note that the prod dockerfile is unmaintained (#428)
 * @decaffeinatedio: Update GeoIP Links (#427)
 * @decaffeinatedio: Error when running `make dockerprod` (#426)
 * @davidfischer: Interface to create a new flight (#425)
 * @davidfischer: Improve difference notifications (#422)
 * @ericholscher: Add option of `created` sort on Staff publisher report (#421)


Version v0.33.0
---------------

We added ``noopener`` to our ad links as a security precaution.
The other big change was to allow ad types to be publisher (group) specific.
We already have publisher specific ad types as Read the Docs
has a compatible but slightly different ad format from EthicalAds.
Some possible new publishers also expressed interest.

:date: July 22, 2021

 * @davidfischer: Add permissions to see staff-only report fields (#419)
 * @ericholscher: Use the right payout objects when finishing (#417)
 * @davidfischer: Add noopener to external links (#416)
 * @davidfischer: Raise a warning after validating landing pages (#415)
 * @davidfischer: Publisher (group) specific ad types (#412)
 * @davidfischer: Validate ad landing page gives a 200 (#175)


Version v0.32.0
---------------

Mostly we added some new staff additions to help with payouts and help manage targeting.
We also added some callouts to help refer publishers.
Lastly, we did add a task to send Slack notifications to staff
when publisher metrics change significantly week to week.

:date: July 15, 2021

 * @ericholscher: Add a more obvious callout for the publisher referral in payouts (#413)
 * @ericholscher: Add some payout optimizations to make it faster (#411)
 * @davidfischer: Notify when publisher metrics change (#410)
 * @davidfischer: Initial staff interface for flight targeting and size updates (#409)

Version v0.31.0
---------------

This release adds a new staff-only interface to manage publishers.
It also adds the ability to notify via Slack when a campaign completes.
Currently, these notifications are just for staff but in the future
we could allow notifications for advertisers as well.

:date: June 30, 2021

 * @davidfischer: Send Slack notifications on completed flights (#407)
 * @dependabot[bot]: Bump color-string from 1.5.3 to 1.5.5 (#406)
 * @ericholscher: Add Staff Add Publisher View (#405)
 * @ericholscher: Fix float data in payout form (#404)
 * @dependabot[bot]: Bump set-getter from 0.1.0 to 0.1.1 (#403)
 * @dependabot[bot]: Bump striptags from 3.1.1 to 3.2.0 (#402)


Version v0.30.0
---------------

This release added change tracking to most models
and minor payout workflow improvements.

:date: June 17, 2021

 * @ericholscher: Clean up a number of payout workflow issues (#400)
 * @davidfischer: Track historical changes to select models (#399)
 * @dependabot[bot]: Bump postcss from 7.0.17 to 7.0.36 (#398)


Version v0.29.0
---------------

This release improves payouts in the adserver,
adds a RegionTopic index for improved reporting,
and starts weighting CPC ads to publishers with higher CTR.

:date: June 15, 2021

 * @davidfischer: This process is consuming the server (#396)
 * @davidfischer: Updates the weighting algorithm (#395)
 * @ericholscher: Add initial Staff Payouts view (#394)
 * @davidfischer: Release v0.28.0 (#393)
 * @dependabot[bot]: Bump django from 2.2.20 to 2.2.24 in /requirements (#392)
 * @dependabot[bot]: Bump django from 2.2.20 to 2.2.22 in /requirements (#391)
 * @dependabot[bot]: Bump pillow from 8.1.1 to 8.2.0 in /requirements (#390)
 * @ericholscher: Add RegionTopic index modeling (#388)

Version v0.28.0
---------------

The biggest new changes here are a task to null out some old data periodically
and a staff actions interface.

:date: June 10, 2021

 * @dependabot[bot]: Bump django from 2.2.20 to 2.2.24 in /requirements (#392)
 * @dependabot[bot]: Bump django from 2.2.20 to 2.2.22 in /requirements (#391)
 * @dependabot[bot]: Bump pillow from 8.1.1 to 8.2.0 in /requirements (#390)
 * @dependabot[bot]: Bump django from 2.2.20 to 2.2.21 in /requirements (#389)
 * @davidfischer: Move the add advertiser interface to a staff action (#387)
 * @davidfischer: Null out old client IDs (#386)
 * @dependabot[bot]: Bump browserslist from 4.6.6 to 4.16.6 (#385)
 * @davidfischer: Front form tweaks (#384)


Version v0.27.0
---------------

This release added some additional staff-only reports to understand advertising data.
It also included a support form for advertisers and publishers to get in touch.

:date: May 17, 2021

 * @davidfischer: The reports sometimes wrap the date ranges awkwardly (#382)
 * @davidfischer: Setup a support form (#381)
 * @davidfischer: I missed this when adding CTR to advertiser reports (#380)
 * @dependabot[bot]: Bump hosted-git-info from 2.8.8 to 2.8.9 (#379)
 * @dependabot[bot]: Bump lodash from 4.17.19 to 4.17.21 (#378)
 * @ericholscher: Add geo & keyword staff reports (#375)

Version v0.26.0
---------------

This release included advertiser dashboard improvements.
Advertisers can invite other users at their company to work with them on advertising.
We also added some minor filtering and reporting improvements.
There is also a migration to ensure certain fields are unique.

:date: May 5, 2021

 * @davidfischer: Allow filtering advertiser reports by flight (#374)
 * @davidfischer: Allow advertisers to control their authorized users (#373)
 * @davidfischer: Ensure slugs are unique (#372)
 * @davidfischer: Copy/Re-use an existing ad (#371)
 * @davidfischer: Show upcoming flights on the overview screen (#370)
 * @davidfischer: Silence the disallowed host logger again (#369)
 * @davidfischer: Don't reject invalid values in the URL field (#368)

Version v0.25.0
---------------

The big change here is that the ad decision API now supports
sending the URL where the ad will appear.
In the future, we can use this for some additional targeting
and automated fraud checking.

:date: April 20, 2021

 * @dependabot[bot]: Bump ssri from 6.0.1 to 6.0.2 (#366)
 * @davidfischer: Add an optional URL to the decision API (#365)
 * @ericholscher: Add link to FAQ in CTR callout in payout email (#364)
 * @davidfischer: Send URL with the ad request (#354)


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
