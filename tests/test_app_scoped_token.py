from click.testing import CliRunner
from datasette import cli
from subprocess import CompletedProcess
import pytest


@pytest.mark.parametrize(
    "status_code,status_error",
    [(0, b""), (1, b"Error: unauthorized"), (2, b"Error: network unavailable")],
)
def test_publish_with_app_scoped_token(mocker, tmp_path, status_code, status_error):
    mocker.patch("shutil.which", return_value="flyctl")
    database = tmp_path / "test.db"
    database.touch()

    def run(args, **kwargs):
        if args == ["flyctl", "auth", "token", "--json"]:
            return CompletedProcess(args, 0, b'{"token": "APP_TOKEN"}', b"")
        if args == ["flyctl", "apps", "list", "--json"]:
            # Valid app-scoped tokens cannot list all applications.
            return CompletedProcess(args, 1, b"", b"Error: unauthorized")
        if args == ["flyctl", "status", "--app", "app", "--json"]:
            return CompletedProcess(
                args,
                status_code,
                b'{"Name": "app"}' if not status_code else b"",
                status_error,
            )
        if args == ["flyctl", "volumes", "list", "-a", "app", "--json"]:
            return CompletedProcess(args, 0, b"[]", b"")
        if args[:2] == ["flyctl", "deploy"]:
            return CompletedProcess(args, 0, b"", b"")
        pytest.fail("Unexpected command: {}".format(args))

    mock_run = mocker.patch("datasette_publish_fly.run", side_effect=run)
    result = CliRunner().invoke(
        cli.cli, ["publish", "fly", str(database), "--app", "app", "--region", "sjc"]
    )
    commands = [call.args[0] for call in mock_run.call_args_list]
    if status_code:
        assert result.exit_code == 1
        assert "Error calling 'flyctl status'" in result.output
        assert status_error.decode() in result.output
        assert not any(command[:2] == ["flyctl", "deploy"] for command in commands)
    else:
        assert result.exit_code == 0, result.output
        assert any(command[:2] == ["flyctl", "deploy"] for command in commands)
    assert ["flyctl", "apps", "list", "--json"] not in commands
    assert not any(command[:3] == ["flyctl", "apps", "create"] for command in commands)
