# datasette-publish-fly

[![PyPI](https://img.shields.io/pypi/v/datasette-publish-fly.svg)](https://pypi.org/project/datasette-publish-fly/)
[![Changelog](https://img.shields.io/github/v/release/simonw/datasette-publish-fly?include_prereleases&label=changelog)](https://github.com/simonw/datasette-publish-fly/releases)
[![Tests](https://github.com/simonw/datasette-publish-fly/workflows/Test/badge.svg)](https://github.com/simonw/datasette-publish-fly/actions?query=workflow%3ATest)
[![License](https://img.shields.io/badge/license-Apache%202.0-blue.svg)](https://github.com/simonw/datasette-publish-fly/blob/main/LICENSE)

Datasette plugin for publishing data using [Fly](https://fly.io/).

## Installation

Install this plugin in the same environment as Datasette.

    $ pip install datasette-publish-fly

## Usage

First, install the `flyctl` command-line tool by [following their instructions](https://fly.io/docs/getting-started/installing-flyctl/).

Run `flyctl auth signup` to create an account there, or `flyctl auth login` if you already have one.

Now you can use `datasette publish fly` to publish your data:

    datasette publish fly my-database.db --app="my-data-app"

The argument you pass to `--app` will be used for the URL of your application: `my-data-app.fly.dev`.

To update an application, run the publish command passing the same application name to the `--app` option.

Fly will charge you monthly for each application you have live. Details of their pricing can be [found on their site](https://fly.io/docs/pricing/).
