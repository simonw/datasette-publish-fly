from click.testing import CliRunner
from datasette import cli
import json
from unittest import mock
from subprocess import PIPE
import pathlib
import pytest


class FakeCompletedProcess:
    def __init__(self, stdout, stderr, returncode=0):
        self.stdout = stdout
        self.stderr = stderr
        self.returncode = returncode


@pytest.fixture
def mock_graphql_region(mocker):
    m = mocker.patch("datasette_publish_fly.httpx")
    m.post.return_value = mocker.Mock()
    m.post.return_value.status_code = 200
    m.post.return_value.json.return_value = {"data": {"nearestRegion": {"code": "sjc"}}}


@mock.patch("shutil.which")
def test_publish_fly_requires_flyctl(mock_which):
    mock_which.return_value = False
    runner = CliRunner()
    with runner.isolated_filesystem():
        open("test.db", "w").write("data")
        result = runner.invoke(cli.cli, ["publish", "fly", "test.db", "-a", "app"])
        assert result.exit_code == 1
        assert "Publishing to Fly requires flyctl" in result.output


@mock.patch("shutil.which")
@mock.patch("datasette_publish_fly.run")
def test_publish_fly_app_name_not_available(mock_run, mock_which, mock_graphql_region):
    mock_which.return_value = True
    runner = CliRunner()

    def run_side_effect(*args, **kwargs):
        if args == (["flyctl", "apps", "list", "--json"],):
            return FakeCompletedProcess(b"[]", b"")
        elif args == (["flyctl", "auth", "token", "--json"],):
            return FakeCompletedProcess(b'{"token": "TOKEN"}', b"")
        elif args == (["flyctl", "volumes", "list", "-a", "app", "--json"],):
            return FakeCompletedProcess(b"[]", b"")
        else:
            print(args)
            return FakeCompletedProcess(b"", b"That app name is not available", 1)

    mock_run.side_effect = run_side_effect

    with runner.isolated_filesystem():
        open("test.db", "w").write("data")
        result = runner.invoke(
            cli.cli, ["publish", "fly", "test.db", "-a", "app"], catch_exceptions=False
        )
        assert 1 == result.exit_code
        assert "That app name is not available" in result.output
        (
            auth_token_call,
            apps_list_call,
            apps_create_call,
        ) = mock_run.call_args_list
        assert auth_token_call == mock.call(
            ["flyctl", "auth", "token", "--json"], stderr=PIPE, stdout=PIPE
        )
        assert apps_list_call == mock.call(
            ["flyctl", "apps", "list", "--json"], stdout=PIPE, stderr=PIPE
        )
        assert list(apps_create_call)[0][0] == [
            "flyctl",
            "apps",
            "create",
            "--name",
            "app",
            "--json",
        ]


@mock.patch("shutil.which")
@mock.patch("datasette_publish_fly.run")
def test_publish_fly(mock_run, mock_which, mock_graphql_region):
    mock_which.return_value = True
    runner = CliRunner()

    def run_side_effect(*args, **kwargs):
        if args == (["flyctl", "apps", "list", "--json"],):
            return FakeCompletedProcess(b"[]", b"")
        elif args == (["flyctl", "apps", "create", "--name", "app", "--json"],):
            return FakeCompletedProcess(b"[]", b"")
        elif args == (["flyctl", "auth", "token", "--json"],):
            return FakeCompletedProcess(b'{"token": "TOKEN"}', b"")
        elif args == (["flyctl", "volumes", "list", "-a", "app", "--json"],):
            return FakeCompletedProcess(b"", b"Could not resolve App", 1)
        else:
            print(args)
            return FakeCompletedProcess(b"", 0)

    mock_run.side_effect = run_side_effect

    with runner.isolated_filesystem():
        open("test.db", "w").write("data")
        result = runner.invoke(cli.cli, ["publish", "fly", "test.db", "-a", "app"])
        assert result.exit_code == 0, result.output

        (
            auth_token_call,
            apps_list_call,
            apps_create_call,
            volumes_list_call,
            apps_deploy_call,
        ) = mock_run.call_args_list
        assert auth_token_call == mock.call(
            ["flyctl", "auth", "token", "--json"], stderr=PIPE, stdout=PIPE
        )
        assert apps_list_call == mock.call(
            ["flyctl", "apps", "list", "--json"], stdout=PIPE, stderr=PIPE
        )
        assert list(apps_create_call)[0][0] == [
            "flyctl",
            "apps",
            "create",
            "--name",
            "app",
            "--json",
        ]
        assert volumes_list_call == mock.call(
            ["flyctl", "volumes", "list", "-a", "app", "--json"], stdout=-1, stderr=-1
        )
        assert apps_deploy_call == mock.call(
            [
                "flyctl",
                "deploy",
                ".",
                "--app",
                "app",
                "--config",
                "fly.toml",
                "--remote-only",
            ]
        )


@mock.patch("shutil.which")
@mock.patch("datasette_publish_fly.run")
@pytest.mark.parametrize(
    "app_name,opts,expected_cmd,expected_mount,expected_files",
    (
        (
            "myapp1",
            [],
            "CMD datasette serve --host 0.0.0.0 --cors --inspect-file inspect-data.json --port $PORT",
            None,
            None,
        ),
        (
            "myapp2",
            ["database.db"],
            "CMD datasette serve --host 0.0.0.0 -i database.db --cors --inspect-file inspect-data.json --port $PORT",
            None,
            ["database.db"],
        ),
        (
            "myapp2",
            ["database.db", "-m", "metadata.json"],
            "CMD datasette serve --host 0.0.0.0 -i database.db --cors --inspect-file inspect-data.json --metadata metadata.json --port $PORT",
            None,
            ["database.db", "metadata.json"],
        ),
        (
            "myapp1",
            ["--create-volume", "1", "--create-db", "tiddlywiki"],
            "CMD datasette serve --host 0.0.0.0 --cors --inspect-file inspect-data.json /data/tiddlywiki.db --create --port $PORT /data/*.db",
            "datasette",
            None,
        ),
        (
            "myapp1_custom_volume",
            [
                "--create-volume",
                "1",
                "--create-db",
                "tiddlywiki",
                "--volume-name",
                "custom_volume",
            ],
            "CMD datasette serve --host 0.0.0.0 --cors --inspect-file inspect-data.json /data/tiddlywiki.db --create --port $PORT /data/*.db",
            "custom_volume",
            None,
        ),
    ),
)
def test_generate_directory(
    mock_run,
    mock_which,
    tmp_path_factory,
    app_name,
    opts,
    expected_cmd,
    expected_mount,
    expected_files,
):
    mock_which.return_value = True

    expected_files = expected_files or []
    expected_files += ["fly.toml", "Dockerfile"]

    input_directory = tmp_path_factory.mktemp("input")
    output_directory = tmp_path_factory.mktemp("output")

    # Rewrite options array with paths to input_directory
    new_opts = []
    if opts:
        for opt in opts:
            if opt in expected_files:
                new_opts.append(str(input_directory / opt))
            else:
                new_opts.append(opt)
    opts = new_opts

    runner = CliRunner()
    if "database.db" in expected_files:
        (input_directory / "database.db").write_text("", "utf-8")
    if "metadata.json" in expected_files:
        (input_directory / "metadata.json").write_text(
            '{"title": "Metadata title"}', "utf-8"
        )
    result = runner.invoke(
        cli.cli,
        ["publish", "fly", "-a", app_name, "--generate-dir", str(output_directory)]
        + opts,
        catch_exceptions=False,
    )
    assert result.exit_code == 0, result.output

    filenames = [p.name for p in pathlib.Path(output_directory).glob("*")]
    assert set(filenames) == set(expected_files)

    fly_toml = (output_directory / "fly.toml").read_text("utf-8")
    dockerfile = (output_directory / "Dockerfile").read_text("utf-8")
    dockerfile_cmd = dockerfile.strip().split("\n")[-1]
    expected_mounts = ""
    if expected_mount:
        expected_mounts = (
            "[[mounts]]\n"
            '  destination = "/data"\n' + '  source = "{}"\n\n'.format(expected_mount)
        )
    assert fly_toml == (
        "\n"
        'app = "{}"\n'.format(app_name) + "\n" + expected_mounts + "[[services]]\n"
        "  internal_port = 8080\n"
        '  protocol = "tcp"\n'
        "\n"
        "  [services.concurrency]\n"
        "    hard_limit = 25\n"
        "    soft_limit = 20\n"
        "\n"
        "  [[services.ports]]\n"
        '    handlers = ["http"]\n'
        '    port = "80"\n'
        "\n"
        "  [[services.ports]]\n"
        '    handlers = ["tls", "http"]\n'
        '    port = "443"\n'
        "\n"
        "  [[services.tcp_checks]]\n"
        "    interval = 10000\n"
        "    timeout = 2000\n"
    )
    assert dockerfile_cmd == expected_cmd

    assert not mock_run.called


@mock.patch("shutil.which")
def test_publish_fly_create_db_no_spaces(mock_which):
    mock_which.return_value = True
    runner = CliRunner()
    result = runner.invoke(
        cli.cli,
        [
            "publish",
            "fly",
            "-a",
            "app",
            "--create-volume",
            1,
            "--create-db",
            "tiddly wiki",
        ],
    )
    assert result.exit_code == 2
    assert "Database name cannot contain spaces" in result.output


@mock.patch("shutil.which")
@mock.patch("datasette_publish_fly.run")
def test_publish_fly_create_plugin_secret(mock_run, mock_which):
    mock_which.return_value = True

    def run_side_effect(*args, **kwargs):
        if args == (["flyctl", "apps", "list", "--json"],):
            return FakeCompletedProcess(b"[]", b"")
        elif args == (["flyctl", "apps", "create", "--name", "app", "--json"],):
            return FakeCompletedProcess(b"", b"")
        elif args == (["flyctl", "volumes", "list", "-a", "app", "--json"],):
            return FakeCompletedProcess(b"[]", b"")
        elif args == (["flyctl", "auth", "token", "--json"],):
            return FakeCompletedProcess(b'{"token": "TOKEN"}', b"")
        elif args == (
            [
                "flyctl",
                "secrets",
                "set",
                "DATASETTE_AUTH_PASSWORDS_ROOT_PASSWORD_HASH=root",
                "-a",
                "app",
                "--json",
            ],
        ):
            return FakeCompletedProcess(
                b"", b"No change detected to secrets", returncode=1
            )
        else:
            print(args)
            return FakeCompletedProcess(b"", b"That app name is not available", 1)

    mock_run.side_effect = run_side_effect

    runner = CliRunner()
    result = runner.invoke(
        cli.cli,
        [
            "publish",
            "fly",
            "-a",
            "app",
            "--region",
            "sjc",
            "--plugin-secret",
            "datasette-auth-passwords",
            "ROOT_PASSWORD_HASH",
            "root",
        ],
        catch_exceptions=False,
    )
    assert result.exit_code == 0
    assert mock_run.call_args_list == [
        mock.call(["flyctl", "auth", "token", "--json"], stderr=-1, stdout=-1),
        mock.call(["flyctl", "apps", "list", "--json"], stdout=-1, stderr=-1),
        mock.call(
            ["flyctl", "apps", "create", "--name", "app", "--json"],
            stderr=-1,
            stdout=-1,
        ),
        mock.call(
            ["flyctl", "volumes", "list", "-a", "app", "--json"], stdout=-1, stderr=-1
        ),
        mock.call(
            [
                "flyctl",
                "secrets",
                "set",
                "DATASETTE_AUTH_PASSWORDS_ROOT_PASSWORD_HASH=root",
                "-a",
                "app",
                "--json",
            ],
            stderr=-1,
            stdout=-1,
        ),
        mock.call(
            [
                "flyctl",
                "deploy",
                ".",
                "--app",
                "app",
                "--config",
                "fly.toml",
                "--remote-only",
            ]
        ),
    ]


@mock.patch("shutil.which")
@mock.patch("datasette_publish_fly.run")
@pytest.mark.parametrize("volume_exists", (False, True))
def test_publish_fly_create_volume_ignored_if_volume_exists(
    mock_run, mock_which, volume_exists
):
    mock_which.return_value = True

    def run_side_effect(*args, **kwargs):
        print(args, kwargs)
        if args == (["flyctl", "auth", "token", "--json"],):
            return FakeCompletedProcess(b'{"token": "TOKEN"}', b"")
        elif args == (["flyctl", "apps", "list", "--json"],):
            return FakeCompletedProcess(b"[]", b"")
        elif args == (["flyctl", "apps", "create", "--name", "app", "--json"],):
            return FakeCompletedProcess(b"", b"")
        elif args == (["flyctl", "volumes", "list", "-a", "app", "--json"],):
            if volume_exists:
                return FakeCompletedProcess(
                    json.dumps(
                        [
                            {
                                "id": "vol_wod56vj56dm4ny30",
                                "Name": "datasette",
                            }
                        ]
                    ).encode("utf-8"),
                    b"",
                )
            else:
                return FakeCompletedProcess(b"[]", b"")
        elif args == (
            [
                "flyctl",
                "volumes",
                "create",
                "datasette",
                "--region",
                "sjc",
                "--size",
                "1",
                "-a",
                "app",
                "--json",
            ],
        ):
            return FakeCompletedProcess(b"", b"")
        return FakeCompletedProcess(b"", b"That app name is not available", 1)

    mock_run.side_effect = run_side_effect

    runner = CliRunner()
    result = runner.invoke(
        cli.cli,
        [
            "publish",
            "fly",
            "-a",
            "app",
            "--create-volume",
            1,
            "--region",
            "sjc",
            "--create-db",
            "tiddlywiki",
        ],
    )
    assert result.exit_code == 0, result.output

    expected = [
        mock.call(["flyctl", "auth", "token", "--json"], stderr=-1, stdout=-1),
        mock.call(["flyctl", "apps", "list", "--json"], stdout=-1, stderr=-1),
        mock.call(
            ["flyctl", "apps", "create", "--name", "app", "--json"],
            stderr=-1,
            stdout=-1,
        ),
        mock.call(
            ["flyctl", "volumes", "list", "-a", "app", "--json"], stdout=-1, stderr=-1
        ),
    ]
    if not volume_exists:
        expected.append(
            mock.call(
                [
                    "flyctl",
                    "volumes",
                    "create",
                    "datasette",
                    "--region",
                    "sjc",
                    "--size",
                    "1",
                    "-a",
                    "app",
                    "--json",
                ],
                stderr=-1,
                stdout=-1,
            )
        )
    expected.extend(
        [
            mock.call(
                [
                    "flyctl",
                    "deploy",
                    ".",
                    "--app",
                    "app",
                    "--config",
                    "fly.toml",
                    "--remote-only",
                ]
            ),
        ]
    )
    assert mock_run.call_args_list == expected
