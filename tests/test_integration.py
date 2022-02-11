# These integration tests only run with "pytest --integration" -
# they execute live calls against Fly and clean up after themselves
from click.testing import CliRunner
from datasette import cli
import httpx
import json
import pytest
import secrets
import sqlite3
import subprocess

# Mark all tests in this module with "integration":
pytestmark = pytest.mark.integration

APP_PREFIX = "publish-fly-temp-"


@pytest.fixture(autouse=True)
def cleanup():
    cleanup_any_resources()
    yield
    cleanup_any_resources()


def test_basic():
    runner = CliRunner()
    app_name = APP_PREFIX + secrets.token_hex(4)
    with runner.isolated_filesystem():
        sqlite3.connect("test.db").execute("create table foo (id integer primary key)")
        result = runner.invoke(
            cli.cli,
            ["publish", "fly", "test.db", "-a", app_name],
            catch_exceptions=False,
        )
        assert result.exit_code == 0, result.output
    # It should have been deployed - but Fly takes a while to start responding to https://...
    # url = "https://{}.fly.dev/.json".format(app_name)
    # So instead we us flyctl apps list to see if it's there
    apps = get_apps()
    matches = [a for a in apps if a["Name"] == app_name]
    assert matches, "No app found with expected name: " + app_name
    app = matches[0]
    assert app["Status"] == "running"
    assert app["Deployed"] is True


def test_with_volume():
    runner = CliRunner()
    app_name = APP_PREFIX + "v-" + secrets.token_hex(4)
    with runner.isolated_filesystem():
        sqlite3.connect("test.db").execute("create table foo (id integer primary key)")
        result = runner.invoke(
            cli.cli,
            [
                "publish",
                "fly",
                "test.db",
                "-a",
                app_name,
                "--create-volume",
                "1",
                "--create-db",
                "writeme",
                "--install",
                "datasette-graphql",
                "--plugin-secret",
                "foo",
                "bar",
                "baz",
                "--show-files",
            ],
            catch_exceptions=False,
        )
        assert result.exit_code == 0, result.output
    # These fragments are expected in Dockerfile or fly.toml or metadata.json
    fragments = (
        "CMD datasette serve --host 0.0.0.0 -i test.db",
        "/data/writeme.db --create --port $PORT /data/*.db",
        'destination = "/data"\n  source = "datasette"',
        '"$env": "FOO_BAR"',
    )
    for fragment in fragments:
        assert fragment in result.output
    # Confirm app has deployed
    apps = get_apps()
    matches = [a for a in apps if a["Name"] == app_name]
    assert matches, "No app found with expected name: " + app_name
    app = matches[0]
    assert app["Status"] == "running"
    assert app["Deployed"] is True
    # That app should also have a volume
    volumes = get_volumes(app_name)
    assert len(volumes) == 1
    assert volumes[0]["Name"] == "datasette"
    # Check secrets - there's no --json for that yet
    app_secrets = get_secrets(app_name)
    assert "FOO_BAR" in app_secrets


def cleanup_any_resources():
    app_names = [app["Name"] for app in get_apps()]
    # Delete any starting with publish-fly-temp-
    to_delete = [app_name for app_name in app_names if app_name.startswith(APP_PREFIX)]
    for app_name in to_delete:
        subprocess.run(["flyctl", "apps", "destroy", app_name, "--yes", "--json"])


def get_apps():
    process = subprocess.run(
        ["flyctl", "apps", "list", "--json"],
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )
    return json.loads(process.stdout)


def get_volumes(app_name):
    process = subprocess.run(
        ["flyctl", "volumes", "list", "-a", app_name, "--json"],
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )
    return json.loads(process.stdout)


def get_secrets(app_name):
    # No --json for this yet, so just returns a big ugly string
    process = subprocess.run(
        ["flyctl", "secrets", "list", "-a", app_name],
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )
    return process.stdout.decode("utf-8")
