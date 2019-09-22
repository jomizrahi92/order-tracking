import os
import sys
import urllib.request
import zipfile
from selenium import webdriver
from typing import Any


class DriverCreator:

  def __init__(self, args) -> None:
    args = [str(arg).upper() for arg in args]
    if "--FIREFOX" in args:
      self.type = "FIREFOX"
    else:
      self.type = "CHROME"

    if "--NO-HEADLESS" in args:
      self.headless = False
    else:
      self.headless = True

  def new(self) -> Any:
    if self.type == "CHROME":
      return self._new_chrome_driver()
    elif self.type == "FIREFOX":
      return self._new_firefox_driver()
    raise Exception("Unknown type " + self.type)

  def fix_perms(self, path):
    for root, dirs, files in os.walk(path):
      for d in dirs:
        os.chmod(os.path.join(root, d), 0o755)
      for f in files:
        os.chmod(os.path.join(root, f), 0o755)

  def _create_osx_windows_driver(self, options, url, base_dir, binary_location,
                                 chromedriver_filename):
    current_working_dir = os.getcwd()
    base = current_working_dir + base_dir
    download_location = base + "Chrome.zip"
    if not os.path.exists(base + binary_location):
      urllib.request.urlretrieve(url, download_location)
      os.chmod(download_location, 0o755)
      with zipfile.ZipFile(download_location, 'r') as zip_ref:
        zip_ref.extractall(base)
      self.fix_perms(base)
      os.remove(download_location)
    options.binary_location = (base + binary_location)
    return webdriver.Chrome(base + chromedriver_filename, options=options)

  def _create_osx_driver(self, options):
    url = "https://github.com/macchrome/chromium/releases/download/v78.0.3901.0-r692376-macOS/Chromium.78.0.3901.0.sync.app.zip"
    return self._create_osx_windows_driver(
        options, url, "/chrome/osx/", "Chromium.app/Contents/MacOS/Chromium",
        "chromedriver")

  def _create_windows_driver(self, options):
    url = "https://github.com/RobRich999/Chromium_Clang/releases/download/v78.0.3901.0-r692535-win32/chrome.zip"
    return self._create_osx_windows_driver(options, url, "/chrome/windows/",
                                           "chrome-win32/chrome.exe",
                                           "chromedriver.exe")

  def _new_chrome_driver(self) -> Any:
    options = webdriver.chrome.options.Options()
    options.headless = self.headless

    if sys.platform.startswith("darwin"):  # osx
      return self._create_osx_driver(options)
    elif sys.platform.startswith("win"):  # windows
      return self._create_windows_driver(options)
    else:  # ??? probably Linux. Linux users can figure this out themselves
      driver = webdriver.Chrome(options=options)

    driver.set_window_size(2000, 1600)
    driver.implicitly_wait(10)
    driver.set_page_load_timeout(10)
    return driver

  def _new_firefox_driver(self) -> Any:
    profile = webdriver.FirefoxProfile()
    profile.native_events_enabled = False
    options = webdriver.firefox.options.Options()
    options.headless = self.headless
    driver = webdriver.Firefox(profile, options=options)
    driver.set_window_size(1500, 1200)
    driver.set_page_load_timeout(60)
    return driver