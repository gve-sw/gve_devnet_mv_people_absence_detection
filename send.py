""" Copyright (c) 2021 Cisco and/or its affiliates.
This software is licensed to you under the terms of the Cisco Sample
Code License, Version 1.1 (the "License"). You may obtain a copy of the
License at
           https://developer.cisco.com/docs/licenses
All use of the material herein must be in accordance with the terms of
the License. All rights not expressly granted by the License are
reserved. Unless required by applicable law or agreed to separately in
writing, software distributed under the License is distributed on an "AS
IS" BASIS, WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express
or implied.
"""

__author__ = "Trevor Maco <tmaco@cisco.com>"
__copyright__ = "Copyright (c) 2023 Cisco and/or its affiliates."
__license__ = "Cisco Sample Code License, Version 1.1"

import logging
import os
import smtplib
import sys
from email import encoders
from email.mime.base import MIMEBase
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText

import meraki
import requests

from config import *

logging.basicConfig(filename='send_logs.log', filemode='a', level=logging.DEBUG,
                    format='%(asctime)s.%(msecs)03d %(levelname)s: %(message)s',
                    datefmt='%Y-%m-%d %H:%M:%S')

# Meraki Dashboard instance
dashboard = meraki.DashboardAPI(MERAKI_API_KEY, suppress_logging=True)


def generate_snapshot(serial, timestamp=None):
    """
    Generate a snapshot of what the camera sees at the specified time and return a link to that image.
     - https://api.meraki.com/api_docs#generate-a-snapshot-of-what-the-camera-sees-at-the-specified-time-and-return-a-link-to-that-image
    :param serial: MV Serial Number
    :param timestamp: Timestamp for snapshot
    :return: URL for snapshot image
    """
    # If a timestamp is defined, generate a snapshot, otherwise grab current snapshot
    if timestamp:
        response = dashboard.camera.generateDeviceCameraSnapshot(serial=serial, timestamp=timestamp)
    else:
        response = dashboard.camera.generateDeviceCameraSnapshot(serial=serial)

    # Return url to snapshot image
    if 'url' in response:
        logging.info("Response url: %s", response['url'])
        return response['url']
    else:
        return None


def download_file(file_name, file_url):
    """
    Download file from URL and write to local tmp storage
    :param file_name: Filename for temporary storage
    :param file_url: Snapshot url
    :return: Path to temp file
    """
    attempts = 1
    while attempts <= 30:
        r = requests.get(file_url, stream=True)
        if r.ok:
            logging.info(f'Retried %d times until successfully retrieved %s', attempts, file_url)
            temp_file = f'./snapshots/{file_name}.jpg'
            with open(temp_file, 'wb') as f:
                for chunk in r:
                    f.write(chunk)
            return temp_file
        else:
            attempts += 1
    logging.error(f'Unsuccessful in 30 attempts retrieving %s', file_url)
    return None


def send_email(recipient, message, serial_number, image_file):
    """
    Send absence alert using SMTP server. This works for both normal email, and text messages.
    :param recipient: Email recipient
    :param message: Email message
    :param serial_number: MV serial number
    :param image_file: Snapshot image
    :return:
    """
    # Source and dst information
    sender = EMAIL_USERNAME
    to = recipient

    # Create email message container
    email = MIMEMultipart()

    # Email meta data
    email['From'] = sender
    email['To'] = to
    email['Subject'] = 'MV Absence Detection - ' + serial_number

    # Add email body
    text = MIMEText(message, 'plain')
    email.attach(text)

    # Attach snapshot to email (if present)
    if image_file:
        with open(image_file, 'rb') as f:
            # set attachment mime and file name, the image type is png
            mime = MIMEBase('image', 'jpg', filename='snapshot.jpg')
            # add required header data:
            mime.add_header('Content-Disposition', 'attachment', filename='snapshot.jpg')
            mime.add_header('X-Attachment-Id', '0')
            mime.add_header('Content-ID', '<0>')
            # read attachment file content into the MIMEBase object
            mime.set_payload(f.read())
            # encode with base64
            encoders.encode_base64(mime)
            # add MIMEBase object to MIMEMultipart object
            email.attach(mime)

    try:
        # Setup SMTP server and login
        with smtplib.SMTP(SMTP_DOMAIN, SMTP_PORT) as server:
            server.ehlo()
            server.starttls()
            server.login(user=EMAIL_USERNAME, password=EMAIL_PASSWORD)
            server.send_message(email, sender, to)

            logging.info('Email/Text sent successfully to %s!', recipient)

    except Exception as e:
        logging.error(f'There was an exception: %s', str(e))


def send_responses(email, text, theText, serial_number, temp_file):
    """
    Send responses driver. Send responses for all configured emails and text messages associated with MV Serial Number.
    :param email: Recipient email addresses
    :param text: Number, Provider list
    :param theText: Message Content
    :param serial_number: Camera Serial Number
    :param temp_file: Snapshot file
    :return:
    """
    # Send an email (with snapshot)
    if len(email) > 0:
        for email in email:
            send_email(email, theText, serial_number, temp_file)

    # Send text messages
    if len(text) > 0:
        # Create text message recipients (special format email)
        for pair in text:
            number = pair[0]
            provider = pair[1]

            if provider in PROVIDERS:
                provider_information = PROVIDERS[provider]

                # If provider has dedicated mms server
                if 'mms' in provider_information:
                    recipient = f'{number}@{provider_information["mms"]}'
                # Provider has combined sms and mms server (or no support for mms)
                else:
                    recipient = f'{number}@{provider_information["sms"]}'

                send_email(recipient, theText, serial_number, temp_file)
            else:
                logging.warning('Error: unsupported cell provider. Skipping...')
                continue


# Main function
if __name__ == '__main__':
    # Get credentials and object count
    theText = sys.argv[1]
    serial_number = sys.argv[2]
    timestamp = sys.argv[3]
    email = sys.argv[4]
    text = sys.argv[5]

    # Extract email and text
    email = email.split(',')
    text = [x.split('-') for x in text.split(',')]

    # Create snapshot folder (if it doesn't exist)
    if not os.path.exists('./snapshots'):
        os.makedirs('./snapshots')

    # Generating screenshot for latest time since when I selected a timestamp that was too close
    # to real time the camera had not had a chance to store it and make it available for sending
    logging.info("About to generate snapshot with serial %s", serial_number)
    theScreenShotURL = generate_snapshot(serial_number, None)

    if theScreenShotURL:  # download/GET image from URL
        temp_file = download_file(serial_number, theScreenShotURL)

        if temp_file:
            # Send configured responses
            send_responses(email, text, theText, serial_number, temp_file)

            # Delete temporary file
            os.remove(temp_file)
        else:
            theText += ' (snapshot unsuccessfully retrieved)'
            send_responses(email, text, theText, serial_number, None)
    else:
        theText += ' (snapshot unsuccessfully requested)'
        send_responses(email, text, theText, serial_number, None)
