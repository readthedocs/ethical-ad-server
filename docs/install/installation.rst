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

Building the Docker image is only necessary if you need to heavily customize the ad server.
To build this, you'll need to have Docker installed and you'll probably want the GeoIP database
command ``geoipupdate`` installed and configured so that the ad server
can convert IP addresses to cities and countries for ad targeting purposes.

.. code-block:: bash

    $ make geoip dockerprod
