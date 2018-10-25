Configuration
=============

The server is intended to be configured by setting **environment variables**.
Most web hosts that will run a Dockerized application,
such as Heroku, AWS Elastic Beanstalk, or Azure App Service,
have ways to set environment variables in line with the `Twelve Factor App`_.

.. _Twelve Factor App: https://12factor.net


Environment variables
---------------------

There are a few required environment variables and the server will not start without them:

* :ref:`install/configuration:DATABASE_URL`
* :ref:`install/configuration:SECRET_KEY`


ADSERVER_ADMIN_URL
~~~~~~~~~~~~~~~~~~

Set to a unique and secret path to enable the Django admin at that path.
For example, if this is set to ``admin-path``
then the Django admin will be available at the URL ``http://adserver.example.com/admin-path/``.
By default, the Django admin is disabled.


ADSERVER_DECISION_BACKEND
~~~~~~~~~~~~~~~~~~~~~~~~~

Set to a dotted Python path to a decision backend to use for the ad server.
Different publishers and ad networks may want different backends based on how different
ads should be prioritized. For example, you may want to prioritize
ads with the highest CPM/CPC or prioritize the most relevant.
Defaults to ``adserver.decisionengine.backends.ProbabilisticClicksNeededBackend``,
a backend that chooses ads based on how many more clicks and views are needed.

Set to ``None`` to disable all ads from serving. This can be useful during migrations.


ADSERVER_HTTPS
~~~~~~~~~~~~~~

Set to ``True`` to enforce some security precautions that are recommended when run over HTTPS:

* The session and CSRF cookie are marked "secure" (not transmitted over insecure HTTP)
* HSTS is enabled


ALLOWED_HOSTS
~~~~~~~~~~~~~

This setting will adjust Django's ``ALLOWED_HOSTS`` setting.
By default in production this is set to ``['*']`` which will allow any host header.
For improved security, set this to the host you are using (eg. ``['adserver.example.com']``).


DATABASE_URL
~~~~~~~~~~~~

This will set the address of the database used by the ad server.
While any database supported by Django will work, PostgreSQL is preferred
(eg. ``psql://username:password@127.0.0.1:5432/database``)


DEBUG
~~~~~

This setting will turn on Django's ``DEBUG`` mode.
It should be off in production (which is the default).
Set to ``True`` to enable it.


INTERNAL_IPS
~~~~~~~~~~~~

This setting will adjust Django's ``INTERNAL_IPS`` setting.
This setting has a few additional meanings for the ad server including:

* All ad impressions and clicks from ``INTERNAL_IPS`` are ignored for reporting purposes


SECRET_KEY
~~~~~~~~~~

This required setting will be your Django ``SECRET_KEY``.
Set this to something random like 50 random alphanumeric characters and keep it a secret.
The server will refuse to start without this.

There are a few implications to changing this setting in a production deployment including:

* All sessions will be invalidated (everyone gets logged out)
* Password reset tokens are invalidated


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
