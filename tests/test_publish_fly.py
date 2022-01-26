from click.testing import CliRunner
from datasette import cli
from unittest import mock
from subprocess import PIPE
import pytest


class FakeCompletedProcess:
    def __init__(self, stdout, stderr, returncode=0):
        self.stdout = stdout
        self.stderr = stderr
        self.returncode = returncode


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
def test_publish_fly_app_name_not_available(mock_run, mock_which):
    mock_which.return_value = True
    runner = CliRunner()

    def run_side_effect(*args, **kwargs):
        if args == (["flyctl", "apps", "list", "--json"],):
            return FakeCompletedProcess(b"[]", b"")
        else:
            print(args)
            return FakeCompletedProcess(b"", b"That app name is not available", 1)

    mock_run.side_effect = run_side_effect

    with runner.isolated_filesystem():
        open("test.db", "w").write("data")
        result = runner.invoke(cli.cli, ["publish", "fly", "test.db", "-a", "app"])
        assert 1 == result.exit_code
        assert "That app name is not available" in result.output
        apps_list_call, apps_create_call = mock_run.call_args_list
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
def test_publish_fly(mock_run, mock_which):
    mock_which.return_value = True
    runner = CliRunner()

    def run_side_effect(*args, **kwargs):
        if args == (["flyctl", "apps", "list", "--json"],):
            return FakeCompletedProcess(b"[]", b"")
        else:
            print(args)
            return FakeCompletedProcess(b"", 0)

    mock_run.side_effect = run_side_effect

    with runner.isolated_filesystem():
        open("test.db", "w").write("data")
        result = runner.invoke(cli.cli, ["publish", "fly", "test.db", "-a", "app"])
        assert result.exit_code == 0, result.output

        apps_list_call, apps_create_call, apps_deploy_call = mock_run.call_args_list
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
