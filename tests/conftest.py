import os


def pytest_configure() -> None:
    os.environ.setdefault("APPLICATION_ID", "1")
    os.environ.setdefault("GUILD_ID", "1")
