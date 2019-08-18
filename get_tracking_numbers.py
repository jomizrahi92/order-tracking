import yaml
import sys
import traceback
import upload_tracking_numbers
from email_sender import EmailSender
from amazon_tracking_retriever import AmazonTrackingRetriever
from driver_creator import DriverCreator
from output import TrackingOutput
from upload_tracking_numbers import Uploader
from sheets_uploader import SheetsUploader

CONFIG_FILE = "config.yml"


def send_error_email(email_sender, subject):
  type, value, trace = sys.exc_info()
  formatted_trace = traceback.format_tb(trace)
  lines = [str(type), str(value)] + formatted_trace
  email_sender.send_email_content(subject, "\n".join(lines))


if __name__ == "__main__":
  driver_creator = DriverCreator(sys.argv)

  with open(CONFIG_FILE, 'r') as config_file_stream:
    config = yaml.safe_load(config_file_stream)
  email_config = config['email']
  email_sender = EmailSender(email_config)

  print("Retrieving tracking numbers from email...")
  amazon_tracking_retriever = AmazonTrackingRetriever(config, driver_creator)
  try:
    groups_dict = amazon_tracking_retriever.get_trackings()
  except:
    send_error_email(email_sender, "Error retrieving emails")
    raise

  if amazon_tracking_retriever.failed_email_ids:
    print(
        "Found %d emails without buying group labels and marked them as unread. Continuing..."
        % len(amazon_tracking_retriever.failed_email_ids))

  try:
    total_trackings = sum(
        [len(trackings) for trackings in groups_dict.values()])
    print("Found %d total tracking numbers" % total_trackings)
    email_sender.send_email(groups_dict)

    print("Uploading tracking numbers...")
    uploader = Uploader(config, driver_creator)
    try:
      uploader.upload(groups_dict)
    except:
      send_error_email(email_sender, "Error uploading tracking numbers")
      raise

    print("Adding results to Google Sheets")
    sheets_uploader = SheetsUploader(config)
    try:
      sheets_uploader.upload(groups_dict)
    except:
      send_error_email(email_sender, "Error uploading to Google Sheets")
      raise

    print("Writing results to file")
    tracking_output = TrackingOutput(groups_dict)
    try:
      tracking_output.save_trackings()
    except:
      send_error_email(email_sender, "Error writing output file")
      raise

    print("Done")
  except:
    print(
        "Exception thrown after looking at the emails. Marking all relevant emails as unread to reset."
    )
    amazon_tracking_retriever.back_out_of_all()
    print("Marked all as unread")
    raise
