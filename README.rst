=================
Ethical Ad Server
=================

The Ethical Ad Server is an advertising server without all the tracking.
It is created by Read the Docs to serve the ads on Read the Docs.

.. image:: https://img.shields.io/badge/code%20style-black-000000.svg
    :target: https://github.com/ambv/black

.. image:: https://circleci.com/gh/rtfd/ethical-ad-server.svg?style=svg&circle-token=1a62029aff2165c86af383a1951509259136f0f3
    :target: https://circleci.com/gh/rtfd/ethical-ad-server

Features
--------

* Supports banners, banner+text, and text-only ads
* Extensive and extensible ad fraud prevention
* Reports based on campaign, flight, or individual ad
* DoNotTrack ready
* GDPR ready
* Geographical targeting by country and state/province
* Supports custom targeting parameters

The Ethical Ad Server uses GeoLite2 data created by MaxMind.


Developing
----------

To setup your environment and run a local development server::

    $ npm install
    $ npm run build
    $ pip install -r requirements/development.txt
    $ pre-commit install            # Install a code style pre-commit hook
    $ python3 manage.py runserver   # This server runs on Python 3.6+

To run the unit tests::

    $ make test

To build the production Docker container::

    $ make dockerbuild

