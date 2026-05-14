"""The trivial test — exists so CI has something green to run on day one."""

from gridpulse import __version__


def test_package_imports_and_has_version() -> None:
    assert isinstance(__version__, str)
    assert __version__.count(".") == 2  # semver-ish
