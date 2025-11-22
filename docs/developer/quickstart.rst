Quickstart
==========

Developing with Docker compose
------------------------------

To build a local Docker compose environment:

.. code-block:: bash

    # Create an environment file based on the sample
    $ cp .envs/local/django.sample .envs/local/django

    # This command can take quite a while the first time
    $ make dockerbuild

Start a local multi-container application with Postgres, Redis, Celery, and Django:

.. code-block:: bash

    $ make dockerserve

To get a shell into the Django container where you can run ``./manage.py createsuperuser``,
get a Django shell, or run other commands:

.. code-block:: bash

    $ make dockershell
    ...
    /app # ./manage.py createsuperuser

After setting up your super user account on your local development instance,
you'll still need to set the :ref:`install/installation:Set the ad server URL`
to something like ``localhost:5000``.


Developing locally
------------------

Docker compose is the recommended way to do development consistently.
This section is more to document steps than to encourage you to develop outside of Docker.

Requirements
~~~~~~~~~~~~

- Python 3.12
- Nodejs (tested with v20)

Front-end assets
~~~~~~~~~~~~~~~~

To build the assets::

    $ npm clean-install
    $ npm run build

Install Python dependencies
~~~~~~~~~~~~~~~~~~~~~~~~~~~

First, install uv if you haven't already:

.. code-block:: bash

   $ curl -LsSf https://astral.sh/uv/install.sh | sh

Then install dependencies:

.. code-block:: bash

   $ uv sync --all-extras           # Install all dependencies including dev tools
   $ uv run pre-commit install      # Install a code style pre-commit hook

Run the server
~~~~~~~~~~~~~~

Run migrations:

.. code-block:: bash

   $ uv run ./manage.py migrate

Create a superuser:

.. code-block:: bash

   $ uv run ./manage.py createsuperuser

Run the server:

.. code-block:: bash

   $ uv run ./manage.py runserver

Running the tests
-----------------

To run the unit tests:

.. code-block:: bash

    $ uv tool install tox --with tox-uv
    $ tox

Run a specific test:

.. code-block:: bash

   $ tox -e py3 -- -k <test_name>
