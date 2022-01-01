from sys import stdout
from datasette import hookimpl
from datasette.publish.common import (
    add_common_publish_arguments_and_options,
    fail_if_publish_binary_not_installed,
)
from datasette.utils import temporary_docker_directory
from subprocess import run, PIPE
import tempfile
import click
import json

FLY_TOML = """
app = "{app}"

[[services]]
  internal_port = 8080
  protocol = "tcp"

  [services.concurrency]
    hard_limit = 25
    soft_limit = 20

  [[services.ports]]
    handlers = ["http"]
    port = "80"

  [[services.ports]]
    handlers = ["tls", "http"]
    port = "443"

  [[services.tcp_checks]]
    interval = 10000
    timeout = 2000
"""


@hookimpl
def publish_subcommand(publish):
    @publish.command()
    @add_common_publish_arguments_and_options
    @click.option("--spatialite", is_flag=True, help="Enable SpatialLite extension")
    @click.option(
        "-a",
        "--app",
        help="Name of Fly app to deploy",
        required=True,
    )
    def fly(
        files,
        metadata,
        extra_options,
        branch,
        template_dir,
        plugins_dir,
        static,
        install,
        plugin_secret,
        version_note,
        secret,
        title,
        license,
        license_url,
        source,
        source_url,
        about,
        about_url,
        spatialite,
        app,
    ):
        fail_if_publish_binary_not_installed(
            "flyctl", "Fly", "https://fly.io/docs/getting-started/installing-flyctl/"
        )
        extra_metadata = {
            "title": title,
            "license": license,
            "license_url": license_url,
            "source": source,
            "source_url": source_url,
            "about": about,
            "about_url": about_url,
        }

        environment_variables = {}
        if plugin_secret:
            extra_metadata["plugins"] = {}
            for plugin_name, plugin_setting, setting_value in plugin_secret:
                environment_variable = (
                    "{}_{}".format(plugin_name, plugin_setting)
                    .upper()
                    .replace("-", "_")
                )
                environment_variables[environment_variable] = setting_value
                extra_metadata["plugins"].setdefault(plugin_name, {})[
                    plugin_setting
                ] = {"$env": environment_variable}
        with temporary_docker_directory(
            files,
            app,
            metadata,
            extra_options,
            branch,
            template_dir,
            plugins_dir,
            static,
            install,
            spatialite,
            version_note,
            secret,
            extra_metadata,
            environment_variables,
            port=8080,
        ):
            apps = existing_apps()
            if app not in apps:
                # Attempt to create the app
                with tempfile.TemporaryDirectory() as tmpdirname:
                    result = run(
                        [
                            "flyctl",
                            "apps",
                            "create",
                            "--name",
                            app,
                        ],
                        cwd=tmpdirname,
                        stderr=PIPE,
                        stdout=PIPE,
                    )
                if result.returncode:
                    raise click.ClickException(
                        "Error calling 'flyctl apps create':\n\n{}".format(
                            # Don't include Usage: - could be confused for usage
                            # instructions for datasette publish fly
                            result.stderr.decode("utf-8")
                            .split("Usage:")[0]
                            .strip()
                        )
                    )

            open("fly.toml", "w").write(FLY_TOML.format(app=app))
            # Now deploy it
            run(
                [
                    "flyctl",
                    "deploy",
                    ".",
                    "--app",
                    app,
                    "--config",
                    "fly.toml",
                    "--remote-only",
                ]
            )


def existing_apps():
    process = run(["flyctl", "apps", "list", "--json"], stdout=PIPE, stderr=PIPE)
    output = process.stdout.decode("utf8")
    return [app["Name"] for app in json.loads(output)]
