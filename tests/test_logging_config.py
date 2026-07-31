import io
import logging

from logging_config import configure_logging, parse_log_level


def _managed_handlers() -> list[logging.Handler]:
    return [
        handler
        for handler in logging.getLogger().handlers
        if getattr(handler, "_wankorobot_handler", False)
    ]


def test_configured_level_and_info_format() -> None:
    stdout = io.StringIO()
    stderr = io.StringIO()
    configure_logging("DEBUG", stdout=stdout, stderr=stderr)

    logging.getLogger("tests.logging").info("Bot started")

    output = stdout.getvalue()
    assert logging.getLogger().level == logging.DEBUG
    assert " INFO tests.logging Bot started" in output
    assert stderr.getvalue() == ""


def test_error_includes_exception_information() -> None:
    stderr = io.StringIO()
    configure_logging("INFO", stdout=io.StringIO(), stderr=stderr)

    try:
        raise RuntimeError("simulated failure")
    except RuntimeError:
        logging.getLogger("tests.logging").exception("Operation failed")

    output = stderr.getvalue()
    assert " ERROR tests.logging Operation failed" in output
    assert "Traceback (most recent call last)" in output
    assert "RuntimeError: simulated failure" in output


def test_secret_is_redacted() -> None:
    stdout = io.StringIO()
    token = "discord-secret-token"
    configure_logging("INFO", secrets=(token,), stdout=stdout, stderr=io.StringIO())

    logging.getLogger("tests.logging").info("Token was %s", token)

    assert token not in stdout.getvalue()
    assert "[REDACTED]" in stdout.getvalue()


def test_secret_is_redacted_from_exception_information() -> None:
    stderr = io.StringIO()
    token = "discord-secret-token"
    configure_logging("INFO", secrets=(token,), stdout=io.StringIO(), stderr=stderr)

    try:
        raise RuntimeError(f"request rejected for {token}")
    except RuntimeError:
        logging.getLogger("tests.logging").exception("Operation failed")

    assert token not in stderr.getvalue()
    assert "RuntimeError: request rejected for [REDACTED]" in stderr.getvalue()


def test_initialization_does_not_duplicate_handlers() -> None:
    configure_logging("INFO", stdout=io.StringIO(), stderr=io.StringIO())
    configure_logging("INFO", stdout=io.StringIO(), stderr=io.StringIO())

    assert len(_managed_handlers()) == 2


def test_invalid_level_falls_back_to_info() -> None:
    configure_logging("not-a-level", stdout=io.StringIO(), stderr=io.StringIO())

    assert parse_log_level("not-a-level") == logging.INFO
    assert logging.getLogger().level == logging.INFO
