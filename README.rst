=================
Ethical Ad Server
=================

The Ethical Ad Server is an advertising server without all the tracking.
It is created by Read the Docs to serve the ads on Read the Docs.


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
    $ python3 manage.py runserver     # This server runs on Python 3.6+

To run the unit tests::

    $ make test

To build the production Docker container::

    $ make dockerbuild

