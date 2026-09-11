import json
from subprocess import CompletedProcess

import click
import pytest

from datasette_publish_fly import existing_volumes


def test_existing_volumes(mocker):
    volumes = [
        {"id": "vol_test", "name": "issue32", "region": "sjc"},
        {"id": "vol_other", "name": "other", "region": "sjc"},
    ]
    mocker.patch(
        "datasette_publish_fly.run",
        return_value=CompletedProcess([], 0, json.dumps(volumes).encode(), b""),
    )
    assert existing_volumes("app") == ["issue32", "other"]


@pytest.mark.parametrize("returncode", [1, 2])
def test_existing_volumes_reports_errors(returncode, mocker):
    mocker.patch(
        "datasette_publish_fly.run",
        return_value=CompletedProcess([], returncode, b"", b"Error: unauthorized"),
    )
    with pytest.raises(
        click.ClickException, match="(?s)flyctl volumes list.*unauthorized"
    ):
        existing_volumes("app")
