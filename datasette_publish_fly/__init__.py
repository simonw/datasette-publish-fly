from sys import stdout
from datasette import hookimpl
from datasette.publish.common import (
    add_common_publish_arguments_and_options,
    fail_if_publish_binary_not_installed,
)
from datasette.utils import temporary_docker_directory
from subprocess import run, PIPE
import click
from click.types import CompositeParamType
import httpx
import json
import os
import pathlib
import shutil


FLY_TOML = """
app = "{app}"
{mounts}
[[services]]
  internal_port = 8080
  protocol = "tcp"

  [services.concurrency]
    hard_limit = 25
    soft_limit = 20

  [[services.ports]]
    handlers = ["http"]
    port = 80

  [[services.ports]]
    handlers = ["tls", "http"]
    port = 443

  [[services.tcp_checks]]
    interval = 10000
    timeout = 2000
"""


class Setting(CompositeParamType):
    name = "setting"
    arity = 2

    def convert(self, config, param, ctx):
        from datasette.app import DEFAULT_SETTINGS

        name, value = config
        if name not in DEFAULT_SETTINGS:
            self.fail(
                f"{name} is not a valid option (--help-config to see all)",
                param,
                ctx,
            )
            return
        # Type checking
        default = DEFAULT_SETTINGS[name]
        if isinstance(default, bool):
            try:
                return name, value_as_boolean(value)
            except ValueAsBooleanError:
                self.fail(f'"{name}" should be on/off/true/false/1/0', param, ctx)
                return
        elif isinstance(default, int):
            if not value.isdigit():
                self.fail(f'"{name}" should be an integer', param, ctx)
                return
            return name, int(value)
        elif isinstance(default, str):
            return name, value
        else:
            # Should never happen:
            self.fail("Invalid option")


@hookimpl
def publish_subcommand(publish):
    @publish.command()
    @add_common_publish_arguments_and_options
    @click.option("--spatialite", is_flag=True, help="Enable SpatialLite extension")
    @click.option(
        "--region",
        help="Fly region to deploy to, e.g sjc - see https://fly.io/docs/reference/regions/",
    )
    @click.option(
        "--create-volume",
        type=click.IntRange(min=1),
        help="Create and attach volume of this size in GB",
    )
    @click.option(
        "--create-db",
        multiple=True,
        callback=validate_database_name,
        help="Names of read-write database files to create",
    )
    @click.option("--volume-name", default="datasette", help="Volume name to use")
    @click.option(
        "-a",
        "--app",
        help="Name of Fly app to deploy",
        required=True,
    )
    @click.option(
        "-o",
        "--org",
        help="Name of Fly org to deploy to",
        default="personal",
    )
    @click.option(
        "--generate-dir",
        type=click.Path(dir_okay=True, file_okay=False),
        help="Output generated application files and stop without deploying",
    )
    @click.option(
        "--show-files",
        is_flag=True,
        help="Output the generated Dockerfile, metadata.json and fly.toml",
    )
    @click.option(
        "--setting",
        "settings",
        type=Setting(),
        help="Setting, see docs.datasette.io/en/stable/settings.html",
        multiple=True,
    )
    @click.option("--crossdb", is_flag=True, help="Enable cross-database SQL queries")
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
        region,
        create_volume,
        create_db,
        volume_name,
        app,
        org,
        generate_dir,
        show_files,
        settings,
        crossdb,
    ):
        """
        Deploy an application to Fly that runs Datasette against the provided database files.

        Usage example:

            datasette publish fly my-database.db --app="my-data-app"

        Full documentation: https://datasette.io/plugins/datasette-publish-fly
        """
        fly_token = None

        # Ensure generate_dir is an absolute, not relative path
        if generate_dir:
            generate_dir = str(pathlib.Path(generate_dir).absolute())

        if not generate_dir:
            # They must have flyctl installed
            fail_if_publish_binary_not_installed(
                "flyctl",
                "Fly",
                "https://fly.io/docs/getting-started/installing-flyctl/",
            )
            # And they need to be logged in
            token_result = run(
                [
                    "flyctl",
                    "auth",
                    "token",
                    "--json",
                ],
                stderr=PIPE,
                stdout=PIPE,
            )
            if token_result.returncode:
                raise click.ClickException(
                    "Error calling 'flyctl auth token':\n\n{}".format(
                        token_result.stderr.decode("utf-8").strip()
                    )
                )
            else:
                fly_token = json.loads(token_result.stdout)["token"]

            # If they didn't specify a region, use fly_token to find the nearest
            if not region:
                response = httpx.post(
                    "https://api.fly.io/graphql",
                    json={"query": "{ nearestRegion { code } }"},
                    headers={
                        "accept": "application/json",
                        "Authorization": "Bearer {}".format(fly_token),
                    },
                )
                if response.status_code == 200 and "errors" not in response.json():
                    # {'data': {'nearestRegion': {'code': 'sjc'}}}
                    region = response.json()["data"]["nearestRegion"]["code"]
                else:
                    raise click.ClickException(
                        "Could not resolve nearest region, specify --region"
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

        if not generate_dir:
            apps = existing_apps()
            if app not in apps:
                # Attempt to create the app
                args = [
                    "flyctl",
                    "apps",
                    "create",
                    "--name",
                    app,
                    "--json",
                ]
                if org:
                    args.extend(["--org", org])
                result = run(args, stderr=PIPE, stdout=PIPE)
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

        volume_to_mount = None

        if create_volume and not generate_dir:
            # Ensure the volume has not been previousy created
            if volume_name not in existing_volumes(app):
                create_volume_result = run(
                    [
                        "flyctl",
                        "volumes",
                        "create",
                        volume_name,
                        "--region",
                        region,
                        "--size",
                        str(create_volume),
                        "-a",
                        app,
                        "--json",
                    ],
                    stderr=PIPE,
                    stdout=PIPE,
                )
                if create_volume_result.returncode:
                    raise click.ClickException(
                        "Error calling 'flyctl volumes create':\n\n{}".format(
                            create_volume_result.stderr.decode("utf-8")
                            .split("Usage:")[0]
                            .strip()
                        )
                    )

        if create_volume:
            volume_to_mount = volume_name

        if not create_volume and not generate_dir:
            # Does the previous app have mounted volumes?
            volumes = existing_volumes(app)
            if volumes:
                volume_to_mount = volumes[0]

        extra_options = extra_options or ""
        if settings:
            extra_options += " ".join(
                "--setting {} {}".format(*setting) for setting in settings
            )
        if crossdb:
            extra_options += " --crossdb"
        if volume_to_mount:
            for database_name in create_db:
                if not database_name.endswith(".db"):
                    database_name += ".db"
                extra_options += " /data/{}".format(database_name)
            extra_options += " --create"

        environment_variables = {}
        secrets_to_set = {}
        if plugin_secret:
            extra_metadata["plugins"] = {}
            for plugin_name, plugin_setting, setting_value in plugin_secret:
                environment_variable = (
                    "{}_{}".format(plugin_name, plugin_setting)
                    .upper()
                    .replace("-", "_")
                )
                secrets_to_set[environment_variable] = setting_value
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
            if volume_to_mount:
                # Modify CMD line of Dockerfile to use bash and add /data/*.db to end of it
                dockerfile_content = open("Dockerfile").read().strip()
                lines = dockerfile_content.split("\n")
                assert lines[-1].startswith("CMD ")
                new_line = lines[-1][len("CMD ") :] + " /data/*.db"
                # Convert that to CMD ["/bin/bash","-c","shopt -s nullglob &&
                # See https://github.com/simonw/datasette-publish-fly/issues/17
                new_line = (
                    'CMD ["/bin/bash", "-c", "shopt -s nullglob && ' + new_line + '"]\n'
                )
                lines[-1] = new_line
                open("Dockerfile", "w").write("\n".join(lines))

            if secrets_to_set and not generate_dir:
                secrets_args = ["flyctl", "secrets", "set"]
                for pair in secrets_to_set.items():
                    secrets_args.append("{}={}".format(*pair))
                secrets_args.extend(["-a", app, "--json"])
                secrets_result = run(
                    secrets_args,
                    stderr=PIPE,
                    stdout=PIPE,
                )
                if secrets_result.returncode:
                    # Ignore "No change detected to secrets" but raise anything else
                    error_message = secrets_result.stderr.decode("utf-8").strip()
                    if "No change detected to secrets" not in error_message:
                        raise click.ClickException(
                            "Error calling 'flyctl secrets set':\n\n{}".format(
                                error_message
                            )
                        )

            mounts = ""
            if volume_to_mount:
                mounts = (
                    "\n[[mounts]]\n"
                    '  destination = "/data"\n'
                    '  source = "{}"\n'.format(volume_to_mount)
                )

            fly_toml = FLY_TOML.format(app=app, mounts=mounts)

            if generate_dir:
                dir = pathlib.Path(generate_dir)
                if not dir.exists():
                    dir.mkdir()

                # Copy files from current directory to dir
                for file in pathlib.Path(".").glob("*"):
                    if file.is_dir():
                        shutil.copytree(str(file), str(dir / file.name))
                    else:
                        shutil.copy(str(file), str(dir / file.name))
                (dir / "fly.toml").write_text(fly_toml, "utf-8")
                return

            elif show_files:
                click.echo("fly.toml")
                click.echo("----")
                click.echo(fly_toml)
                click.echo("----")
                click.echo("Dockerfile")
                click.echo("----")
                click.echo(open("Dockerfile").read())
                if os.path.exists("metadata.json"):
                    click.echo("----")
                    click.echo("metadata.json")
                    click.echo("----")
                    click.echo(open("metadata.json").read())
                    click.echo("----")

            open("fly.toml", "w").write(fly_toml)
            # Now deploy it
            deploy_result = run(
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
            if deploy_result.returncode:
                raise click.ClickException("Error calling 'flyctl deploy'")


def existing_apps():
    process = run(["flyctl", "apps", "list", "--json"], stdout=PIPE, stderr=PIPE)
    return [app["Name"] for app in json.loads(process.stdout)]


def existing_volumes(app):
    process = run(
        ["flyctl", "volumes", "list", "-a", app, "--json"], stdout=PIPE, stderr=PIPE
    )
    if process.returncode == 1:
        if b"Could not resolve App" in process.stderr:
            return []
        else:
            assert False, "flyctl volumes list error: {}".format(
                process.stderr.decode("utf-8")
            )
    return [volume["Name"] for volume in json.loads(process.stdout)]


def validate_database_name(ctx, param, value):
    for name in value:
        if " " in name:
            raise click.BadParameter("Database name cannot contain spaces")
    return value
