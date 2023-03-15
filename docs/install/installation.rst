Installation
============

The Ethical Ad Server is intended to be run on any host that can run a Dockerized application,
such as Heroku, AWS Elastic Beanstalk, Azure App Service, or on your own infrastructure.
It can also be run directly on virtual machines. It is intended to be run with:

* PostgreSQL
* Redis


Configuring the ad server
-------------------------

The ad server is configured by environment variables.
See the :doc:`document outlining them </install/configuration>`.


Set the ad server URL
---------------------

After configuring the ad server and setting up the database, you'll need to set the URL for the ad server.
This URL is used to create links to the ad server when clicking or viewing ads.

* Login to the :doc:`administration interface </user-guide/administration>`.
* Under :guilabel:`Sites`, click on the first and only Site
* Set the domain to be a domain without scheme (eg. ``server.ethicalads.io`` not ``http://...``)

.. figure:: /_static/img/install/configuring-server-url.png
    :alt: Configuring the ad server URL
    :width: 100%

    Configuring the ad server URL


Building the Docker image
-------------------------

.. admonition:: Production Docker support

    The process of setting up your own production installation is not supported by us.

To run the ad server in production on your own infrastructure,
you'll need to build a VM image or a Docker image to run the application.
The Dockerfile in ``docker-compose/django/Dockerfile`` should be a good reference,
but your own setup may vary a little bit.

Depending on your setup, you may also need the GeoIP databases from Maxmind or from DB-IP.
If you have a Maxmind license key, you can use the command ``make geoip`` to get the databases.
You can instead rely on a CDN like Cloudflare to match IPs to regions.
See our ``adserver/middleware.py`` for details.

For our own production setup, we build a VM image in a similar manner to our Dockerfile.
This image is run on a major cloud provider using managed Redis and managed PostgreSQL.
