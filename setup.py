from setuptools import setup
import os

VERSION = "1.1.1"


def get_long_description():
    with open(
        os.path.join(os.path.dirname(os.path.abspath(__file__)), "README.md"),
        encoding="utf8",
    ) as fp:
        return fp.read()


setup(
    name="datasette-publish-fly",
    description="Datasette plugin for publishing data using Fly",
    long_description=get_long_description(),
    long_description_content_type="text/markdown",
    author="Simon Willison",
    url="https://github.com/simonw/datasette-publish-fly",
    project_urls={
        "Issues": "https://github.com/simonw/datasette-publish-fly/issues",
        "CI": "https://github.com/simonw/datasette-publish-fly/actions",
        "Changelog": "https://github.com/simonw/datasette-publish-fly/releases",
    },
    license="Apache License, Version 2.0",
    version=VERSION,
    packages=["datasette_publish_fly"],
    entry_points={"datasette": ["publish_fly = datasette_publish_fly"]},
    install_requires=["datasette>=0.60.2"],
    extras_require={"test": ["pytest", "pytest-mock", "cogapp"]},
    tests_require=["datasette-publish-fly[test]"],
)
