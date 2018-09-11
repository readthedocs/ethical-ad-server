Quickstart
==========

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

