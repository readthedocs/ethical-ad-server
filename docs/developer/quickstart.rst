Quickstart
==========

Developing with Docker compose
------------------------------

To build a local Docker compose environment:

.. code-block:: bash

    # This command can take quite a while the first time
    $ make dockerbuild

Start a local multi-container application with Postgres, Redis, Celery, and Django:

.. code-block:: bash

    $ make dockerserve

To get a shell into the Django container where you can run ``createsuperuser``,
get a Django shell, or run other commands:

.. code-block:: bash

    $ make dockershell


Developing locally
------------------

Docker compose is the recommended way to do development consistently.
This section is more to document steps than to encourage you to develop outside of Docker.

Requirements
~~~~~~~~~~~~

- Python 3.6
- Nodejs (tested with v12.3)

Front-end assets
~~~~~~~~~~~~~~~~

To build the assets::

    $ npm install
    $ npm run build

Install Python dependencies
~~~~~~~~~~~~~~~~~~~~~~~~~~~

.. code-block:: bash

   $ pip install -r requirements/development.txt
   $ pre-commit install            # Install a code style pre-commit hook

Run the server
~~~~~~~~~~~~~~

Run migrations:

.. code-block:: bash

   $ python manage.py migrate

Create a superuser:

.. code-block:: bash

   $ python manage.py createsuperuser

Run the server:

.. code-block:: bash

   $ python manage.py runserver

Running the tests
-----------------

To run the unit tests:

.. code-block:: bash

    $ pip install -r requirements/testing.txt
    $ make test
