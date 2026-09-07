"""Browser automation for sites that have no API: build a configured driver,
then drive the page by element id.

Written for the download-a-report kind of job, so most of the configuration
is about making files land in a known directory without a dialog.

Needs the ``selenium`` extra: ``pip install fuchitools[selenium]``. Only
:func:`undetected_chrome_driver` needs ``undetected-chromedriver``; it is
imported on first use, so the Firefox side works with plain ``selenium``.
"""

import os
import random
import time

try:
    from selenium import webdriver
    from selenium.webdriver.common.by import By
    from selenium.webdriver.firefox.options import Options as FirefoxOptions
    from selenium.webdriver.firefox.service import Service as FirefoxService
    from selenium.webdriver.support import expected_conditions as EC
    from selenium.webdriver.support.ui import Select, WebDriverWait
except ImportError as exc:  # pragma: no cover - depends on the environment
    raise ImportError(
        "fuchitools.selenium needs the 'selenium' extra: pip install fuchitools[selenium]"
    ) from exc


def _uc():
    """Import ``undetected_chromedriver`` lazily: only the Chrome driver needs it."""
    try:
        import undetected_chromedriver as uc
    except ImportError as exc:  # pragma: no cover - depends on the environment
        raise ImportError(
            "undetected_chrome_driver needs undetected-chromedriver: "
            "pip install undetected-chromedriver (or fuchitools[selenium])"
        ) from exc
    return uc

__all__ = [
    "sleep",
    "firefox",
    "undetected_chrome_driver",
    "input_by_id",
    "click_by_id",
    "select_by_id",
    "submit_by_id",
    "click_by_class",
    "download_dir",
]

# MIME types saved to disk without asking (Firefox) / the kinds of files the
# scrapers download (Chrome relies on prompt_for_download=False instead).
DOWNLOAD_MIME_TYPES = (
    "application/pdf,"
    "application/octet-stream,"
    "application/zip,"
    "application/x-zip-compressed,"
    "application/msword,"
    "application/vnd.openxmlformats-officedocument.wordprocessingml.document,"
    "text/csv,"
    "application/vnd.ms-excel,"
    "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
)

HEADLESS_WINDOW = (1920, 1080)


def sleep(a, b=None):
    """Pause for ``a`` seconds, or for a random time between ``a`` and ``b``.

    The two-argument form is for looking less like a robot: a scraper that
    pauses exactly 3.000 s between requests is trivially recognisable.
    """
    if b is None:
        time.sleep(a)
    else:
        time.sleep(random.uniform(a, b))


# --------------------------------------------------------------------------
# Option builders (pure: no browser is started)
# --------------------------------------------------------------------------

def _firefox_options(download_dir=None, binary_path=None, headless=False) -> "FirefoxOptions":
    """Build the Firefox options :func:`firefox` uses."""
    options = FirefoxOptions()

    if headless:
        options.add_argument("-headless")
        options.add_argument(f"-width={HEADLESS_WINDOW[0]}")
        options.add_argument(f"-height={HEADLESS_WINDOW[1]}")
        options.add_argument("-disable-gpu")
        options.add_argument("-no-remote")   # never attach to a running instance

    if binary_path is not None:
        options.binary_location = binary_path

    if download_dir is not None:
        # folderList: 0 desktop, 1 Downloads folder, 2 the directory in browser.download.dir
        options.set_preference("browser.download.folderList", 2)
        options.set_preference("browser.download.dir", os.path.abspath(download_dir))
    else:
        options.set_preference("browser.download.folderList", 1)

    options.set_preference("browser.download.manager.showWhenStarting", False)
    options.set_preference("browser.helperApps.neverAsk.saveToDisk", DOWNLOAD_MIME_TYPES)
    options.set_preference("pdfjs.disabled", True)              # download PDFs, do not view them
    options.set_preference("devtools.jsonview.enabled", False)
    return options


def _chrome_prefs(download_dir=None) -> dict:
    """Chrome ``prefs`` for downloading into ``download_dir`` without a prompt."""
    if download_dir is None:
        return {}
    return {
        "download.default_directory": os.path.abspath(download_dir),
        "download.prompt_for_download": False,
        "download.directory_upgrade": True,
        "download.extensions_to_open": "",
        "profile.default_content_setting_values.automatic_downloads": 1,
        "safebrowsing.enabled": True,
    }


def _chrome_options(download_dir=None, binary_path=None, headless=False):
    """Build the Chrome options :func:`undetected_chrome_driver` uses.

    The ``--headless=new`` flag itself is added by ``uc.Chrome(headless=True)``;
    here only the companions (window size, GPU) are set.
    """
    options = _uc().ChromeOptions()
    if binary_path:
        options.binary_location = binary_path
    prefs = _chrome_prefs(download_dir)
    if prefs:
        options.add_experimental_option("prefs", prefs)
    if headless:
        options.add_argument("--disable-gpu")
        options.add_argument(f"--window-size={HEADLESS_WINDOW[0]},{HEADLESS_WINDOW[1]}")
    options.add_argument("--disable-notifications")
    options.add_argument("--disable-popup-blocking")
    return options


# --------------------------------------------------------------------------
# Drivers
# --------------------------------------------------------------------------

def firefox(download_dir=None, binary_path=None, firefox_driver_path=None, headless=False):
    """Start Firefox configured to download into ``download_dir`` without dialogs.

    Parameters
    ----------
    download_dir : str, optional
        Directory for downloads (made absolute). ``None`` means the browser's
        own Downloads folder.
    binary_path : str, optional
        Path to the Firefox executable, for a portable or pinned install.
    firefox_driver_path : str, optional
        Path to geckodriver. ``None`` lets Selenium Manager find or download it.
    headless : bool, default False
        Run without a window, at 1920x1080 with GPU acceleration off.

    Returns
    -------
    selenium.webdriver.Firefox
    """
    options = _firefox_options(download_dir, binary_path, headless)
    service = FirefoxService(executable_path=firefox_driver_path) if firefox_driver_path else FirefoxService()
    return webdriver.Firefox(service=service, options=options)


def undetected_chrome_driver(download_dir=None, binary_path=None, chrome_driver_path=None, headless=False):
    """Start Chrome through ``undetected_chromedriver``, for sites that block
    obvious automation.

    Parameters
    ----------
    download_dir : str, optional
        Directory for downloads (made absolute), with the download prompt off.
        Chrome has no equivalent of Firefox's save-without-asking MIME list,
        so this is less airtight than :func:`firefox`.
    binary_path : str, optional
        Path to the Chrome executable.
    chrome_driver_path : str, optional
        Path to a chromedriver to patch and use. ``None`` lets
        undetected_chromedriver download the matching one.
    headless : bool, default False
        Run without a window (``--headless=new``), at 1920x1080.

    Returns
    -------
    undetected_chromedriver.Chrome
    """
    options = _chrome_options(download_dir, binary_path, headless)
    return _uc().Chrome(
        options=options,
        browser_executable_path=binary_path,
        driver_executable_path=chrome_driver_path,
        headless=headless,
    )


# --------------------------------------------------------------------------
# Driving the page
# --------------------------------------------------------------------------

def input_by_id(browser, element_id, value):
    """Type ``str(value)`` into the element with id ``element_id``."""
    browser.find_element(By.ID, element_id).send_keys(str(value))


def click_by_id(browser, element_id):
    """Click the element with id ``element_id``."""
    browser.find_element(By.ID, element_id).click()


def select_by_id(browser, element_id, value, timeout=20):
    """Choose the ``<option>`` whose ``value`` attribute is ``value`` in the
    ``<select>`` with id ``element_id``.

    Waits up to ``timeout`` seconds for the element and forces
    ``display: block`` on it first: custom dropdown widgets hide the real
    ``<select>``, and Selenium refuses to interact with a hidden element.
    """
    wait = WebDriverWait(browser, timeout)
    select_element = wait.until(EC.presence_of_element_located((By.ID, element_id)))
    browser.execute_script("arguments[0].style.display = 'block';", select_element)
    Select(select_element).select_by_value(value)


def submit_by_id(browser, element_id):
    """Submit the form with id ``element_id``."""
    browser.find_element(By.ID, element_id).submit()


def click_by_class(browser, class_name):
    """Click the first element with class ``class_name``."""
    browser.find_element(By.CLASS_NAME, class_name).click()


def download_dir(browser):
    """The download directory the driver was configured with, or ``None``.

    Works for drivers built by :func:`firefox` (reads the
    ``browser.download.dir`` preference) and :func:`undetected_chrome_driver`
    (reads the ``download.default_directory`` pref). Returns ``None`` when no
    directory was configured or the driver exposes no options.
    """
    options = getattr(browser, "options", None)
    prefs = getattr(options, "preferences", None)
    if isinstance(prefs, dict) and prefs.get("browser.download.dir"):
        return prefs["browser.download.dir"]
    experimental = getattr(options, "experimental_options", None)
    if isinstance(experimental, dict):
        return (experimental.get("prefs") or {}).get("download.default_directory")
    return None
