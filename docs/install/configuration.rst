Configuration
=============

The server is intended to be configured by setting **environment variables**.
Most web hosts that will run a Dockerized application,
such as Heroku, AWS Elastic Beanstalk, or Azure App Service,
have ways to set environment variables in line with the `Twelve Factor App`_.

.. _Twelve Factor App: https://12factor.net


Environment variables
---------------------

This lists the commonly configured environment variables.
For a complete list, please see ``config/settings/production.py`` for details.

There are a few required environment variables and the server will not start without them:

* :ref:`install/configuration:ALLOWED_HOSTS`
* :ref:`install/configuration:DATABASE_URL`
* :ref:`install/configuration:REDIS_URL`
* :ref:`install/configuration:SECRET_KEY`
* :ref:`install/configuration:SENDGRID_API_KEY`


ADSERVER_ADMIN_URL
~~~~~~~~~~~~~~~~~~

Set to a unique and secret path to enable the :doc:`administration interface </user-guide/administration>`
(a lightly customized Django admin) at that path.
For example, if this is set to ``admin-path``
then the admin interface will be available at the URL ``http://adserver.example.com/admin-path/``.
By default, this set to ``/admin``.


ADSERVER_BLOCKLISTED_USER_AGENTS
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

Set this to a comma separated list of strings that are looked for anywhere in the User Agent of an ad request.
Any user agents matching any of these will be completely ignored for counting clicks and views for billing purposes.


ADSERVER_BLOCKLISTED_REFERRERS
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

Set this to a comma separated list of strings that are looked for anywhere in the Referrer of an ad request.
Any referrer matching any of these will be completely ignored for counting clicks and views for billing purposes.


ADSERVER_CLICK_RATELIMITS
~~~~~~~~~~~~~~~~~~~~~~~~~

Set this to a comma separated list of formats to specify how quickly a single IP can click on multiple ads.
Clicks that happen faster than any of these rates will still click-through, but won't count toward billed clicks.
By default, this is set to ``"1/m,3/10m,10/h,25/d"`` which is:

* 1 click per minute
* 3 click per 10 minutes
* 10 clicks per hour
* 25 clicks per day


ADSERVER_DECISION_BACKEND
~~~~~~~~~~~~~~~~~~~~~~~~~

Set to a dotted Python path to a decision backend to use for the ad server.
Different publishers and ad networks may want different backends based on how different
ads should be prioritized. For example, you may want to prioritize
ads with the highest CPM/CPC or prioritize the most relevant.
Defaults to ``adserver.decisionengine.backends.ProbabilisticFlightBackend``,
a backend that chooses ads based on how many more clicks and views are needed.

Set to ``None`` to disable all ads from serving. This can be useful during migrations.


ADSERVER_HTTPS
~~~~~~~~~~~~~~

Set to ``True`` to enforce some security precautions that are recommended when run over HTTPS:

* The session and CSRF cookie are marked "secure" (not transmitted over insecure HTTP)
* HSTS is enabled

ADSERVER_RECORD_VIEWS
~~~~~~~~~~~~~~~~~~~~~

Whether to store metadata (a database record) each time an ad is viewed.
This is ``False`` by default and can result in a bloated database and poor performance.
It's ``True`` by default in development.
This can be overridden on a per publisher basis by setting the ``Publisher.record_views`` flag.


ALLOWED_HOSTS
~~~~~~~~~~~~~

This setting will adjust Django's ``ALLOWED_HOSTS`` setting.
Set this to the host you are using (eg. ``server.ethicalads.io,server2.ethicalads.io``).


DATABASE_URL
~~~~~~~~~~~~

This will set the address of the database used by the ad server.
While any database supported by Django will work, PostgreSQL is preferred
(eg. ``psql://username:password@127.0.0.1:5432/database``)
See Django's :doc:`database documentation <django:ref/databases>`
and the :ref:`DATABASES setting <django:ref/settings:database>` for details.


DEBUG
~~~~~

This setting will turn on Django's ``DEBUG`` mode.
It should be off in production (which is the default).
Set to ``True`` to enable it.


DEFAULT_FILE_STORAGE
~~~~~~~~~~~~~~~~~~~~

Adjusts Django's ``DEFAULT_FILE_STORAGE`` setting.
Defaults to ``storages.backends.azure_storage.AzureStorage`` which
can be used to storage uploaded ad images in Azure.
See Django's :doc:`storage documentation <django:ref/files/storage>` for details.


ENFORCE_HOST
~~~~~~~~~~~~

If set, all requests to hosts other than this one will be redirected to this host.
In production, this is typically ``server.ethicalads.io``.


INTERNAL_IPS
~~~~~~~~~~~~

This setting will adjust Django's ``INTERNAL_IPS`` setting.
This setting has a few additional meanings for the ad server including:

* All ad impressions and clicks from ``INTERNAL_IPS`` are ignored for reporting purposes


REDIS_URL
~~~~~~~~~

A Redis cache is required to operate the ad server.
The Redis connection is specified in URL format such as ``redis://redis:6379/0``.


SECRET_KEY
~~~~~~~~~~

This required setting will be your Django ``SECRET_KEY``.
Set this to something random like 50 random alphanumeric characters and keep it a secret.
The server will refuse to start without this.

There are a few implications to changing this setting in a production deployment including:

* All sessions will be invalidated (everyone gets logged out)
* Password reset tokens are invalidated


SENDGRID_API_KEY
~~~~~~~~~~~~~~~~

Set this to your Sendgrid API key to enable sending email through Sendgrid.


STRIPE_SECRET_KEY
~~~~~~~~~~~~~~~~~

Sets up the Stripe API where advertisers can be connected to a Stripe customer
and invoices created directly through the ad server.
Invoices are created in the :doc:`admin interface </user-guide/administration>`.


Overriding settings entirely
----------------------------

While most options can be set by tuning environment variables,
for a complex setup, you might consider completely overriding the settings.

To completely override the settings, create a new file ``config/settings/mysettings.py``
which should extend from ``config/settings/base.py``
and then you'll need to set the environment variable ``DJANGO_SETTINGS_MODULE``
to ``config.settings.mysettings``
(note that the path is separated by dots and there is no file extension).

Once this is done, other :ref:`install/configuration:Environment variables` will be configured
in your new ``mysettings.py`` rather than with environment variables.
