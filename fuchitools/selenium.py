import os
import random
import time

from selenium import webdriver
from selenium.webdriver.common.by import By
from selenium.webdriver.firefox.options import Options
from selenium.webdriver.firefox.service import Service
from selenium.webdriver.support import expected_conditions as EC
from selenium.webdriver.support.ui import Select, WebDriverWait


def sleep(a, b=None):
    if b is None:
        time.sleep(a)
    else:
        time.sleep(random.uniform(a,b ))


def firefox(
    download_dir=None, binary_path=None, firefox_driver_path=None, headless=False
):
    """
    Initializes and returns a Firefox WebDriver instance with custom configurations.

    Args:
        download_dir (str, optional): Path to the directory for downloads. Defaults to None.
        binary_path (str, optional): Path to the Firefox browser executable. Defaults to None.
        firefox_driver_path (str, optional): Path to the GeckoDriver executable. Defaults to None.
        headless (bool, optional): Run browser in headless mode. Defaults to False.

    Returns:
        selenium.webdriver.firefox.webdriver.WebDriver: The browser object.
    """

    # 1. Configure Options
    options = Options()

    # Set headless mode
    if headless:
        #options.headless = True
        options.add_argument("-headless")
        options.add_argument("-width=1920")      # Ancho de ventana
        options.add_argument("-height=1080")     # Alto de ventana
        options.add_argument("-disable-gpu")     # Desactivar aceleración por GPU
        options.add_argument("-no-remote")       # Evitar conexión a instancia existente

    # Set Firefox binary location if provided
    if binary_path is not None:
        options.binary_location = binary_path

    # Configure Download Preferences if directory is provided
    if download_dir is not None:
        # Ensure the path is absolute
        abs_download_dir = os.path.abspath(download_dir)

        # Set preference to use a custom download folder
        options.set_preference("browser.download.folderList", 2)
        options.set_preference("browser.download.dir", abs_download_dir)

        # Hide the download start dialog
        options.set_preference("browser.download.manager.showWhenStarting", False)

        # Set MIME types to download automatically without asking
        # You can add more MIME types to this string as needed
        mime_types = (
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
        options.set_preference("browser.helperApps.neverAsk.saveToDisk", mime_types)

        # Disable the built-in PDF viewer to force PDF downloads
        options.set_preference("pdfjs.disabled", True)


    options.set_preference("devtools.jsonview.enabled", False)
    options.set_preference("browser.download.folderList", 2)
    options.set_preference("browser.download.manager.showWhenStarting", False)
    options.set_preference(
        "browser.helperApps.neverAsk.saveToDisk", "application/octet-stream"
    )

    # 2. Configure Service (Driver Path)
    service = None
    if firefox_driver_path is not None:
        service = Service(executable_path=firefox_driver_path)
    else:
        # If None, Selenium Manager (built into Selenium 4.6+) will attempt
        # to find or download the correct driver automatically.
        service = Service()

    # 3. Initialize Driver
    driver = webdriver.Firefox(service=service, options=options)

    return driver


def input_by_id(browser, id, value):
    element = browser.find_element(By.ID, id)
    element.send_keys(str(value))


def click_by_id(browser, id):
    element = browser.find_element(By.ID, id)
    element.click()


def select_by_id(browser, element_id, value):
    wait = WebDriverWait(browser, 20)

    select_element = wait.until(EC.presence_of_element_located((By.ID, element_id)))

    browser.execute_script("arguments[0].style.display = 'block';", select_element)

    select = Select(select_element)
    select.select_by_value(value)


def submit_by_id(browser, id):
    form_element = browser.find_element(By.ID, id)
    form_element.submit()


def click_by_class(browser, id):
    element = browser.find_element(By.CLASS_NAME, id)
    element.click()
