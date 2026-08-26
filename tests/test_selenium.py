"""Tests for fuchitools.selenium that start no browser: option builders,
sleep, download_dir. Skipped when the 'selenium' extra is not installed."""

import os

import pytest

pytest.importorskip("selenium")
pytest.importorskip("undetected_chromedriver")

from fuchitools import selenium as fsel  # noqa: E402
from fuchitools.selenium import (  # noqa: E402
    DOWNLOAD_MIME_TYPES,
    _chrome_options,
    _chrome_prefs,
    _firefox_options,
    download_dir,
    sleep,
)


# --- sleep --------------------------------------------------------------

def test_sleep_fixed_and_random(monkeypatch):
    slept = []
    monkeypatch.setattr(fsel.time, "sleep", slept.append)
    monkeypatch.setattr(fsel.random, "uniform", lambda a, b: (a + b) / 2)
    sleep(3)
    sleep(2, 4)
    assert slept == [3, 3.0]


# --- Firefox options ----------------------------------------------------

def test_firefox_options_download_dir_is_absolute():
    opts = _firefox_options(download_dir="descargas")
    prefs = opts.preferences
    assert prefs["browser.download.folderList"] == 2
    assert prefs["browser.download.dir"] == os.path.abspath("descargas")
    assert prefs["browser.helperApps.neverAsk.saveToDisk"] == DOWNLOAD_MIME_TYPES
    assert prefs["pdfjs.disabled"] is True
    assert "-headless" not in opts.arguments


def test_firefox_options_without_download_dir_uses_downloads_folder():
    prefs = _firefox_options().preferences
    assert prefs["browser.download.folderList"] == 1
    assert "browser.download.dir" not in prefs


def test_firefox_options_headless_and_binary():
    opts = _firefox_options(binary_path="C:/ff/firefox.exe", headless=True)
    assert opts.binary_location == "C:/ff/firefox.exe"
    for arg in ("-headless", "-width=1920", "-height=1080", "-disable-gpu", "-no-remote"):
        assert arg in opts.arguments


# --- Chrome options -----------------------------------------------------

def test_chrome_prefs():
    assert _chrome_prefs(None) == {}
    prefs = _chrome_prefs("descargas")
    assert prefs["download.default_directory"] == os.path.abspath("descargas")
    assert prefs["download.prompt_for_download"] is False


def test_chrome_options_download_dir_headless_binary():
    opts = _chrome_options(download_dir="descargas", binary_path="C:/chrome.exe", headless=True)
    assert opts.experimental_options["prefs"]["download.default_directory"] == os.path.abspath("descargas")
    assert opts.binary_location == "C:/chrome.exe"
    for arg in ("--disable-gpu", "--window-size=1920,1080", "--disable-notifications", "--disable-popup-blocking"):
        assert arg in opts.arguments
    # the headless flag itself is uc.Chrome(headless=True)'s job
    assert not any(a.startswith("--headless") for a in opts.arguments)


def test_chrome_options_plain():
    opts = _chrome_options()
    assert "prefs" not in opts.experimental_options
    assert "--disable-gpu" not in opts.arguments


# --- download_dir -------------------------------------------------------

class _Browser:
    def __init__(self, options=None):
        if options is not None:
            self.options = options


def test_download_dir_firefox():
    browser = _Browser(_firefox_options(download_dir="descargas"))
    assert download_dir(browser) == os.path.abspath("descargas")


def test_download_dir_chrome():
    browser = _Browser(_chrome_options(download_dir="descargas"))
    assert download_dir(browser) == os.path.abspath("descargas")


def test_download_dir_unconfigured_is_none():
    assert download_dir(_Browser(_firefox_options())) is None
    assert download_dir(_Browser(_chrome_options())) is None
    assert download_dir(_Browser()) is None
