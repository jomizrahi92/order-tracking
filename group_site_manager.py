import time
import re
import datetime
from selenium import webdriver

LOGIN_EMAIL_FIELD = "fldEmail"
LOGIN_PASSWORD_FIELD = "fldPassword"
LOGIN_BUTTON_SELECTOR = "//button[contains(text(), 'Login')]"

SUBMIT_BUTTON_SELECTOR = "//*[contains(text(), 'SUBMIT')]"

RESULT_SELECTOR = "//*[contains(text(), 'record(s) effected')]"
RESULT_REGEX = r"(\d+) record\(s\) effected"

BASE_URL_FORMAT = "https://www.%s.com"
MANAGEMENT_URL_FORMAT = "https://www.%s.com/p/it@orders-all/"

RECEIPTS_URL_FORMAT = "https://%s.com/p/it@receipts"

USA_LOGIN_URL = "https://usabuying.group/login"
USA_TRACKING_URL = "https://usabuying.group/trackings"
USA_PO_URL = "https://usabuying.group/purchase-orders"

MAX_UPLOAD_ATTEMPTS = 10

TODAY = datetime.date.today().strftime("%Y%m%d")
START = "20000101"


class GroupSiteManager:

  def __init__(self, config, driver_creator):
    self.config = config
    self.driver_creator = driver_creator
    self.melul_portal_groups = config['melulPortals']

  def upload(self, groups_dict):
    for group, trackings in groups_dict.items():
      numbers = [tracking.tracking_number for tracking in trackings]
      group_config = self.config['groups'][group]
      if group_config.get('password') and group_config.get('username'):
        self._upload_to_group(numbers, group)

  def get_tracked_costs(self, group):
    if group not in self.melul_portal_groups:
      return {}

    print("Loading group %s" % group)
    driver = self._login_melul(group)
    try:
      self._load_page(driver, RECEIPTS_URL_FORMAT % group)
      tracking_to_cost_map = {}

      # Clear the search field since it can cache results
      search_button = driver.find_element_by_class_name('pf-search-button')
      search_button.click()
      time.sleep(1)
      driver.find_element_by_xpath('//button[@title="Clear filters"]').click()
      time.sleep(1)
      driver.find_element_by_xpath('//md-icon[text()="last_page"]').click()
      time.sleep(5)

      # go to the first page (page selection can get a bit messed up with the multiple sites)
      first_page_button = driver.find_element_by_xpath(
          "//button[@ng-click='$pagination.first()']")
      first_page_button.click()
      time.sleep(10)

      while True:
        table = driver.find_element_by_xpath("//tbody[@class='md-body']")
        rows = table.find_elements_by_tag_name('tr')
        for row in rows:
          cost = row.find_elements_by_tag_name('td')[13].text.replace(
              '$', '').replace(',', '')
          tracking = row.find_elements_by_tag_name('td')[14].text.replace(
              '-', '')
          tracking_to_cost_map[tracking] = float(cost)

        next_page_button = driver.find_element_by_xpath(
            "//button[@ng-click='$pagination.next()']")
        if next_page_button.get_property("disabled") == False:
          next_page_button.click()
          time.sleep(10)
        else:
          break

      return tracking_to_cost_map
    finally:
      driver.close()

  def _upload_to_group(self, numbers, group):
    for attempt in range(MAX_UPLOAD_ATTEMPTS):
      try:
        if group in self.melul_portal_groups:
          return self._upload_melul(numbers, group)
        elif group == "usa":
          return self._upload_usa(numbers)
        else:
          raise Exception("Unknown group: " + group)
      except Exception as e:
        print("Received exception when uploading: " + str(e))
    raise

  def _load_page(self, driver, url):
    driver.get(url)
    time.sleep(2)

  def _upload_melul(self, numbers, group):
    driver = self._login_melul(group)
    try:
      self._load_page(driver, MANAGEMENT_URL_FORMAT % group)
      driver.find_element_by_xpath("//textarea").send_keys('\n'.join(numbers))
      driver.find_element_by_xpath(SUBMIT_BUTTON_SELECTOR).click()
      time.sleep(1)
    finally:
      driver.close()

  def _login_melul(self, group):
    driver = self.driver_creator.new()
    self._load_page(driver, BASE_URL_FORMAT % group)
    group_config = self.config['groups'][group]
    driver.find_element_by_name(LOGIN_EMAIL_FIELD).send_keys(
        group_config['username'])
    driver.find_element_by_name(LOGIN_PASSWORD_FIELD).send_keys(
        group_config['password'])
    driver.find_element_by_xpath(LOGIN_BUTTON_SELECTOR).click()
    time.sleep(1)
    return driver

  def get_po_to_price(self, group):
    if group != 'usa':
      return {}

    print("Getting tracked prices for USA POs")
    result = {}
    driver = self._login_usa()
    try:
      self._load_page(driver, USA_PO_URL)
      while True:
        table = driver.find_element_by_class_name("react-bs-container-body")
        rows = table.find_elements_by_tag_name('tr')
        for row in rows:
          entries = row.find_elements_by_tag_name('td')
          po = entries[1].text
          cost = float(entries[5].text.replace('$', '').replace(',', ''))
          result[po] = cost

        next_page_button = driver.find_elements_by_xpath(
            "//li[contains(@title, 'next page')]")
        if next_page_button:
          link = next_page_button[0].find_element_by_tag_name('a')
          link.click()
          time.sleep(2)
        else:
          break

      return result
    finally:
      driver.close()

  def get_tracking_to_purchase_order(self, group):
    if group != 'usa':
      return {}

    result = {}
    driver = self._login_usa()
    try:
      # Tell the USA tracking search to find received tracking numbers from the beginning of time
      self._load_page(driver, USA_TRACKING_URL)
      date_filter_div = driver.find_element_by_class_name(
          "reports-dates-filter-cnt")
      date_filter_btn = date_filter_div.find_element_by_tag_name("button")
      date_filter_btn.click()
      time.sleep(1)

      filter_custom = date_filter_div.find_element_by_id("filter-custom")
      filter_custom.click()
      time.sleep(1)

      modal = driver.find_element_by_class_name("modal-dialog")
      inputs = modal.find_elements_by_class_name("form-control")
      inputs[0].send_keys(START)
      inputs[1].send_keys(TODAY)
      modal.find_element_by_class_name("modal-title").click()
      time.sleep(1)

      modal.find_element_by_class_name('btn-primary').click()
      time.sleep(1)

      status_dropdown = driver.find_element_by_name("filterPurchaseid")
      status_dropdown.click()
      time.sleep(1)

      status_dropdown.find_element_by_xpath("//*[text()='Received']").click()
      time.sleep(1)

      driver.find_element_by_xpath("//i[contains(@class, 'fa-search')]").click()
      time.sleep(3)

      while True:
        table = driver.find_element_by_class_name("react-bs-container-body")
        rows = table.find_elements_by_tag_name('tr')
        for row in rows:
          entries = row.find_elements_by_tag_name('td')
          tracking = entries[2].text
          purchase_order = entries[3].text.split(' ')[0]
          result[tracking] = purchase_order

        next_page_button = driver.find_elements_by_xpath(
            "//li[contains(@title, 'next page')]")
        if next_page_button:
          link = next_page_button[0].find_element_by_tag_name('a')
          link.click()
          time.sleep(4)
        else:
          break

      return result
    finally:
      driver.close()

  def _login_usa(self):
    driver = self.driver_creator.new()
    self._load_page(driver, USA_LOGIN_URL)
    group_config = self.config['groups']['usa']
    driver.find_element_by_name("credentials").send_keys(
        group_config['username'])
    driver.find_element_by_name("password").send_keys(group_config['password'])
    # for some reason there's an invalid login button in either the first or second array spot (randomly)
    for element in driver.find_elements_by_name("log-me-in"):
      try:
        element.click()
      except:
        pass
    time.sleep(2)
    return driver

  def _upload_usa(self, numbers):
    driver = self._login_usa()
    try:
      self._load_page(driver, USA_TRACKING_URL)
      driver.find_element_by_xpath("//*[contains(text(), ' Add')]").click()
      driver.find_element_by_xpath("//textarea").send_keys("\n".join(numbers))
      time.sleep(1)
      driver.find_element_by_xpath("//*[contains(text(), 'Submit')]").click()
      time.sleep(3)
    finally:
      driver.close()
