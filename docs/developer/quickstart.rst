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

To get a shell into the Django container where you can run ``uv run ./manage.py createsuperuser``,
get a Django shell, or run other commands:

.. code-block:: bash

    $ make dockershell
    ...
    /app    # uv run ./manage.py createsuperuser

After setting up your super user account on your local development instance,
you'll still need to set the :ref:`install/installation:Set the ad server URL`
to something like ``localhost:5000``.


Development tips
----------------

Docker compose is the recommended way to do development consistently.
This step documents commands for code style, building static assets, and more.
These commands can be run inside Docker (``make dockershell``).

Requirements
~~~~~~~~~~~~

- `uv <https://docs.astral.sh/uv/getting-started/installation/>`_
- Nodejs (tested with v20)


Managing the ad server and setup
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

Run migrations:

.. code-block:: bash

    $ uv run ./manage.py migrate

Create a superuser:

.. code-block:: bash

    $ uv run ./manage.py createsuperuser

Front-end assets
~~~~~~~~~~~~~~~~

To build the assets::

.. code-block:: bash

    $ npm clean-install
    $ npm run build

Pre-commit and code style
~~~~~~~~~~~~~~~~~~~~~~~~~

Setup pre-commit:

.. code-block:: bash

    $ uv tool install pre-commit --with pre-commit-uv
    $ uvx pre-commit install         # Install a code style pre-commit hook

You can run all code style checks with teh following:

.. code-block:: bash

    $ uvx pre-commit run --all-files


Running the tests
-----------------

To run the unit tests:

.. code-block:: bash

    $ uv tool install tox --with tox-uv
    $ tox

Run a specific test:

.. code-block:: bash

    $ tox -e py3 -- adserver/auth/tests.py
