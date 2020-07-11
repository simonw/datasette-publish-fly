from datasette import hookimpl
from datasette.publish.common import (
    add_common_publish_arguments_and_options,
    fail_if_publish_binary_not_installed,
)
from datasette.utils import temporary_docker_directory
from subprocess import run, PIPE
import click

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
        "-a", "--app", help="Name of Fly app to deploy", required=True,
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
                result = run(["flyctl", "apps", "create", "--name", app])
                if result.returncode:
                    raise click.ClickException("That app name is not available")
            else:
                open("fly.toml", "w").write(FLY_TOML.format(app=app))
            # Now deploy it
            run(["flyctl", "deploy", "--remote-only"])


def existing_apps():
    process = run(["flyctl", "apps", "list"], stdout=PIPE, stderr=PIPE)
    output = process.stdout.decode("utf8")
    all_lines = [l.strip() for l in output.split("\n")]
    # Skip lines until we find the NAME line
    lines = []
    collect = False
    for line in all_lines:
        if collect:
            lines.append(line)
        elif line.startswith("NAME"):
            collect = True
    apps = [l.strip().split()[0] for l in lines if l.strip()]
    return apps
