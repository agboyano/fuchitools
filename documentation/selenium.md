# `fuchitools.selenium`

Browser automation for scraping sites that have no API: build a configured
driver, then drive the page by element id. Written for the download-a-report
kind of job, so most of the configuration is about making files land in a
known directory without a dialog.

Needs the `selenium` extra — `pip install fuchitools[selenium]` — which brings
`selenium` and `undetected-chromedriver`. Importing the module without them
raises an `ImportError` that says so. This is also why
[`__init__.py`](../fuchitools/__init__.py) does not import it automatically.

## Building a driver

```python
firefox(download_dir=None, binary_path=None, firefox_driver_path=None, headless=False)
undetected_chrome_driver(download_dir=None, binary_path=None, chrome_driver_path=None, headless=False)
```

```python
from fuchitools.selenium import firefox

browser = firefox(download_dir="g:/descargas", headless=True)
try:
    browser.get("https://example.com/informes")
    ...
finally:
    browser.quit()
```

Both return a normal Selenium driver — everything the Selenium API offers
still works. What they set up for you:

- **Downloads go to `download_dir`** (made absolute) with no prompt. In Firefox
  a long list of MIME types (pdf, zip, csv, doc, xls, xlsx, octet-stream) is
  marked save-without-asking and the built-in PDF viewer is disabled so PDFs
  download instead of opening. Without `download_dir` they go to the browser's
  Downloads folder.
- **`headless=True`** also sets a 1920x1080 window and disables GPU
  acceleration. Sites that lay out by viewport width behave very differently
  at the default headless size, so the explicit dimensions matter. Chrome uses
  the modern `--headless=new` mode.
- **The driver binary is found for you.** Leave `firefox_driver_path` /
  `chrome_driver_path` as None: Selenium Manager resolves geckodriver, and
  undetected-chromedriver downloads and patches the matching chromedriver.
  Pass a path only to pin a specific one. (`chrome_driver_path` used to be
  accepted and ignored; it is honoured now.)
- `binary_path` points at the browser itself, for a portable install or a
  version pinned away from the system one.

`undetected_chrome_driver` uses `undetected_chromedriver` rather than plain
Selenium Chrome: it is for sites that block obvious automation. Note that
Chrome has no equivalent of Firefox's `neverAsk.saveToDisk`, so its downloads
rely on `download.prompt_for_download = False` and are less airtight.

The option objects are built by `_firefox_options(...)` and
`_chrome_options(...)`, pure functions that start nothing; that is what the
tests exercise, and what to call if you want the same configuration on a
driver you construct yourself.

## Driving the page

Every helper takes the browser first and finds elements by id, which is the
common case in the old form-based sites this was written for.

```python
input_by_id(browser, element_id, value)          # type str(value) into a field
click_by_id(browser, element_id)                 # click
select_by_id(browser, element_id, value, timeout=20)   # choose an <option> by value
submit_by_id(browser, element_id)                # submit a form
click_by_class(browser, class_name)              # click, by class name instead
```

```python
from fuchitools.selenium import input_by_id, select_by_id, click_by_id, sleep

input_by_id(browser, "usuario", "agarcia")
input_by_id(browser, "clave", password)
click_by_id(browser, "btnEntrar")

sleep(2, 5)                          # random pause, see below

select_by_id(browser, "cboCartera", "93702")
click_by_id(browser, "btnDescargar")
```

`select_by_id` is the one with extra machinery: it waits up to `timeout`
seconds (20 by default) for the element to appear and then **forces
`display: block` on it via JavaScript** before selecting. That is for the
custom dropdowns that hide the real `<select>` behind their own widget —
Selenium refuses to interact with a hidden element, and this makes it visible
enough to work.

The others do not wait. If the page is still loading they raise
`NoSuchElementException`; add your own `WebDriverWait` where the page is slow.

## `sleep(a, b=None)`

```python
sleep(3)        # exactly 3 seconds
sleep(2, 5)     # a random pause between 2 and 5 seconds
```

The two-argument form is for looking less like a robot: a scraper that pauses
exactly 3.000 s between requests is trivially recognisable.

## `download_dir(browser)`

Returns the download directory the browser was configured with, or `None`.

```python
from pathlib import Path
from fuchitools.selenium import download_dir

descargas = Path(download_dir(browser))
nuevo = max(descargas.glob("*.xlsx"), key=lambda p: p.stat().st_mtime)
```

Works for both drivers built here: it reads Firefox's `browser.download.dir`
preference or Chrome's `download.default_directory` pref. **It returns `None`
when no `download_dir` was passed** (downloads went to the browser's own
folder) or when the driver exposes no options at all — check for it before
building a `Path`.

## Tests

`tests/test_selenium.py` starts no browser: it checks the option builders,
`sleep` (with time patched) and `download_dir` against fake drivers. The
whole file is skipped when the `selenium` extra is not installed.
