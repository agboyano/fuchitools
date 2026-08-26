"""Tests for fuchitools.misc.stream_logger."""

import io
import logging
import uuid

import pytest

from fuchitools.misc import stream_logger


@pytest.fixture
def name():
    """A fresh logger name per test, so the logging registry does not leak."""
    return "fuchitools.test." + uuid.uuid4().hex


def test_returns_logger_with_one_handler_at_level(name):
    log = stream_logger(name, "INFO")
    assert isinstance(log, logging.Logger) and log.name == name
    assert log.level == logging.INFO
    assert len(log.handlers) == 1 and log.handlers[0].level == logging.INFO


def test_second_call_does_not_duplicate_output(name):
    out = io.StringIO()
    stream_logger(name, "INFO", stream=out)
    log = stream_logger(name, "DEBUG", stream=out)          # again, different level
    assert len(log.handlers) == 1
    assert log.level == logging.DEBUG
    log.info("hola")
    assert out.getvalue() == "hola\n"                        # once, bare message


def test_level_as_int_and_lowercase_name(name):
    assert stream_logger(name, logging.WARNING).level == logging.WARNING
    assert stream_logger(name, "debug").level == logging.DEBUG


def test_default_level_is_error(name):
    out = io.StringIO()
    log = stream_logger(name, stream=out)
    log.warning("no"); log.error("si")
    assert out.getvalue() == "si\n"


def test_format_string(name):
    out = io.StringIO()
    log = stream_logger(name, "INFO", fmt="%(levelname)s|%(message)s", stream=out)
    log.info("x")
    assert out.getvalue() == "INFO|x\n"


@pytest.mark.parametrize("bad", ["LOUD", "", True])
def test_unknown_level_raises(name, bad):
    with pytest.raises(ValueError):
        stream_logger(name, bad)


def test_does_not_touch_foreign_handlers(name):
    log = logging.getLogger(name)
    foreign = logging.StreamHandler(io.StringIO())
    log.addHandler(foreign)
    stream_logger(name, "INFO")
    stream_logger(name, "INFO")
    assert foreign in log.handlers and len(log.handlers) == 2
