Quickstart
==========

Requirements
------------

- Python 3.6
- Nodejs (tested with v12.3)

Front-end assets
----------------

To build the assets::

    $ npm install
    $ npm run build

Install Python dependencies
---------------------------

.. code-block:: bash

   $ pip install -r requirements/development.txt
   $ pre-commit install            # Install a code style pre-commit hook

Run the server
--------------

Run migrations:

.. code-block:: bash

   $ python manage.py migrate

Create a superuser:

.. code-block:: bash

   $ python manage.py createsuperuser

Run the server:

.. code-block:: bash

   $ python manage.py runserver

Tests
-----

To run the unit tests::

    $ make test

Production
----------

To build the production Docker container::

    $ make dockerbuild
