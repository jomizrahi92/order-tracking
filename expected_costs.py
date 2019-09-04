import pickle
import os.path
import imaplib
import re

OUTPUT_FOLDER = "output"
COSTS_FILE = OUTPUT_FOLDER + "/expected_costs.pickle"


class ExpectedCosts:

  def __init__(self, config):
    self.email_config = config['email']
    self.costs_dict = self.load_dict()

  def flush(self):
    if not os.path.exists(OUTPUT_FOLDER):
      os.mkdir(OUTPUT_FOLDER)

    with open(COSTS_FILE, 'wb') as stream:
      pickle.dump(self.costs_dict, stream)

  def load_dict(self):
    if not os.path.exists(COSTS_FILE):
      return {}

    with open(COSTS_FILE, 'rb') as stream:
      return pickle.load(stream)

  def get_expected_cost(self, order_id):
    print("Getting cost for order_id %s" % order_id)
    if order_id not in self.costs_dict:
      from_email = self.load_order_total(order_id)
      self.costs_dict.update(from_email)
      self.flush()
    return self.costs_dict[order_id]

  def load_order_total(self, order_id):
    mail = imaplib.IMAP4_SSL(self.email_config['imapUrl'])
    mail.login(self.email_config['username'], self.email_config['password'])
    mail.select('"[Gmail]/All Mail"')

    status, search_result = mail.uid('SEARCH', None,
                                     'FROM "auto-confirm@amazon.com"',
                                     'BODY "%s"' % order_id)
    email_id = search_result[0]
    if not email_id:
      return {order_id: 0.0}

    result, data = mail.uid("FETCH", email_id, "(RFC822)")
    raw_email = str(data[0][1])

    regex_pretax = r'Total Before Tax: \$([\d,]+\.\d{2})'
    regex_est_tax = r'Estimated Tax: \$([\d,]+\.\d{2})'
    regex_order = r'(\d{3}-\d{7}-\d{7})'

    # Sometimes it's been split into multiple orders. Find totals for each
    pretax_totals = [
        float(cost.replace(',', ''))
        for cost in re.findall(regex_pretax, raw_email)
    ]
    taxes = [
        float(cost.replace(',', ''))
        for cost in re.findall(regex_est_tax, raw_email)
    ]
    orders_with_duplicates = re.findall(regex_order, raw_email)
    orders = []
    for order in orders_with_duplicates:
      if order not in orders:
        orders.append(order)

    order_totals = [t[0] + t[1] for t in zip(pretax_totals, taxes)]
    return dict(zip(orders, order_totals))
