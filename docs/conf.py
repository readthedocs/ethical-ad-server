# -*- coding: utf-8 -*-
#
# Configuration file for the Sphinx documentation builder.
#
# This file does only contain a selection of the most common options. For a
# full list see the documentation:
# http://www.sphinx-doc.org/en/master/config
# -- Path setup --------------------------------------------------------------
# If extensions (or modules to document with autodoc) are in another directory,
# add these directories to sys.path here. If the directory is relative to the
# documentation root, use os.path.abspath to make it absolute, like shown here.
#
import os
import sys
from datetime import datetime

import django

os.environ["DJANGO_SETTINGS_MODULE"] = "config.settings.development"
BASE_DIR = os.path.join(os.path.dirname(__file__), "..")
sys.path.append(BASE_DIR)

django.setup()

from django.conf import settings


# -- Project information -----------------------------------------------------

project = "Ethical Ad Server"
copyright = "{}, Read the Docs, Inc".format(datetime.now().year)
author = "Read the Docs, Inc"

# The short X.Y version
version = settings.ADSERVER_VERSION
# The full version, including alpha/beta/rc tags
release = settings.ADSERVER_VERSION


# -- General configuration ---------------------------------------------------

# If your documentation needs a minimal Sphinx version, state it here.
#
# needs_sphinx = '1.0'

# Add any Sphinx extension module names here, as strings. They can be
# extensions coming with Sphinx (named 'sphinx.ext.*') or your custom
# ones.
extensions = [
    "sphinx.ext.autodoc",
    "sphinx.ext.intersphinx",
    "sphinx.ext.viewcode",
    "sphinx.ext.autosectionlabel",
    "sphinxcontrib.httpdomain",
]

# Add any paths that contain templates here, relative to this directory.
templates_path = ["_templates"]

# The suffix(es) of source filenames.
# You can specify multiple suffix as a list of string:
#
# source_suffix = ['.rst', '.md']
source_suffix = ".rst"

# The master toctree document.
master_doc = "index"

# The language for content autogenerated by Sphinx. Refer to documentation
# for a list of supported languages.
#
# This is also used if you do content translation via gettext catalogs.
# Usually you set "language" from the command line for these cases.
language = "en"

# List of patterns, relative to source directory, that match files and
# directories to ignore when looking for source files.
# This pattern also affects html_static_path and html_extra_path .
exclude_patterns = ["_build", "Thumbs.db", ".DS_Store"]

# The name of the Pygments (syntax highlighting) style to use.
pygments_style = "sphinx"

# Each header is prefixed with a ID for referencing (:ref:)
# And each reference must fully qualify the reference including the document
# http://www.sphinx-doc.org/en/1.7/ext/autosectionlabel.html
autosectionlabel_prefix_document = True

# Warn about all references where the target cannot be found
nitpicky = True

# Ignore missing targets for the http:obj <type>
# This is used for input/output fields in the API docs.
nitpick_ignore = [
    ("http:obj", "array"),
    ("http:obj", "boolean"),
    ("http:obj", "int"),
    ("http:obj", "float"),
    ("http:obj", "date"),
    ("http:obj", "object"),
    ("http:obj", "string"),
]

# -- Options for HTML output -------------------------------------------------

# The theme to use for HTML and HTML Help pages.  See the documentation for
# a list of builtin themes.
#
html_theme = "sphinx_rtd_theme"

# Theme options are theme-specific and customize the look and feel of a theme
# further.  For a list of options available for each theme, see the
# documentation.
#
html_theme_options = {
    "includehidden": False,
    "navigation_depth": 2,
    "prev_next_buttons_location": None,
    "style_external_links": True,
}

# Add any paths that contain custom static files (such as style sheets) here,
# relative to this directory. They are copied after the builtin static files,
# so a file named "default.css" will overwrite the builtin "default.css".
html_static_path = ["_static"]

# Custom sidebar templates, must be a dictionary that maps document names
# to template names.
#
# The default sidebars (for documents that don't match any pattern) are
# defined by theme itself.  Builtin themes are using these templates by
# default: ``['localtoc.html', 'relations.html', 'sourcelink.html',
# 'searchbox.html']``.
#
# html_sidebars = {}

html_css_files = [
    "_static/css/custom.css",
]

html_js_files = []

if not os.environ.get("READTHEDOCS", False):
    # The client is needed just for styling some of the sample ad blocks
    # Ads aren't loaded on these docs outside of RTD
    html_js_files.append(
        "https://media.ethicalads.io/media/client/beta/ethicalads.min.js"
    )


# -- Extension configuration -------------------------------------------------

# -- Options for intersphinx extension ---------------------------------------

intersphinx_mapping = {
    "django": (
        "https://docs.djangoproject.com/en/dev/",
        "https://docs.djangoproject.com/en/dev/_objects/",
    ),
    "python": ("https://docs.python.org/3.8/", None),
}
