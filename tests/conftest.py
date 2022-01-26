import pytest


def pytest_addoption(parser):
    parser.addoption(
        "--integration",
        action="store_true",
        default=False,
        help="run integration tests",
    )


def pytest_configure(config):
    config.addinivalue_line(
        "markers",
        "integration: mark test as integration test, only run with --integration",
    )


def pytest_collection_modifyitems(config, items):
    if config.getoption("--integration"):
        # Also run integration tests
        return
    skip_integration = pytest.mark.skip(reason="use --integration option to run")
    for item in items:
        if "integration" in item.keywords:
            item.add_marker(skip_integration)
