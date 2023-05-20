#!/usr/bin/env python3
""" Copyright (c) 2023 Cisco and/or its affiliates.
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

import datetime
import json
import logging
import re
import time
from subprocess import Popen

import paho.mqtt.client as mqtt

from config import *

logging.basicConfig(level=logging.DEBUG,
                    format='%(asctime)s.%(msecs)03d %(levelname)s %(module)s - %(funcName)s: %(message)s',
                    datefmt='%Y-%m-%d %H:%M:%S')

# Global objects
threshold_tracker = {}
communication_tracker = {}

# Time increment
INCREMENT = 0.2


def on_connect(client, userdata, flags, rc):
    """
    Subscribe MQTT Client on successful connection
    :param client: MQTT Local Client
    :param rc: MQTT Connection Code
    """
    print("connected with code: " + str(rc))
    client.subscribe(MQTT_TOPICS)


def on_message(client, userdata, msg):
    """
    Callback when MQTT message received. Check if a person has been detected in the zone. If not, increment timer,
    else reset timer. If timer exceeds threshold, send message.
    :param msg: MQTT Message from MV
    """
    global threshold_tracker

    # Extract MQTT message payload
    payload = json.loads(msg.payload.decode("utf-8", "ignore"))
    objects = payload["counts"]

    # Extract camera serial from topic
    camera_serial = msg.topic.split('/')[2]

    if not objects:
        logging.info("There are currently no tracked objects in the frame")
    else:
        logging.info("Detected people:")
        logging.info(payload["counts"])

    # If a person is detected in the zone, reset timer and alerted flag (no need to identify specific people)
    if 'person' in objects and objects['person'] > 0:
        threshold_tracker[camera_serial]['current_age'] = 0
        threshold_tracker[camera_serial]['alerted'] = False
    # If no one is detected, continue incrementing timer
    else:
        threshold_tracker[camera_serial]['current_age'] += INCREMENT

    # If age has exceeded the configured threshold for the zone and alerted is false, send an alert
    if threshold_tracker[camera_serial]['current_age'] >= threshold_tracker[camera_serial]['threshold'] and not \
            threshold_tracker[camera_serial]['alerted']:
        # send alert, a person hasn't been detected in zone for greater than threshold period

        ts = time.time()
        ts_in_datetime = datetime.datetime.fromtimestamp(ts).strftime('%Y-%m-%d %H:%M:%S')

        alert_message = f"""Alert generated at {ts_in_datetime}. A person has not been detected for more than {threshold_tracker[camera_serial]['threshold']} seconds."""

        email = re.escape(','.join(communication_tracker[camera_serial]['email']))
        text = re.escape(','.join(communication_tracker[camera_serial]['text']))

        # Spawn python process containing send logic
        Popen(f'python3 send.py "{alert_message}" {camera_serial} {ts} {email} {text}', shell=True)
        threshold_tracker[camera_serial]['alerted'] = True

    # Sleep for INCREMENT to slow down processing
    time.sleep(INCREMENT)

    logging.info("threshold_tracker:")
    logging.info(threshold_tracker)


if __name__ == "__main__":
    # Architecture: single client subscribing to multiple topics on a single broker, routing done in the backend
    # Build MQTT topics for various camera's
    MQTT_TOPICS = []

    # Load Camera Data
    with open('cameras.json', 'r') as fp:
        cameras = json.load(fp)

    for camera in cameras:
        MQTT_TOPICS.append(("/merakimv/" + camera["CAMERA_SERIAL"] + '/' + camera["ZONE_ID"], 0))

        # Add new time tracker object, starting at 0
        threshold_tracker[camera['CAMERA_SERIAL']] = {'threshold': camera['AGE_THRESHOLD'], 'current_age': 0,
                                                      'alerted': False}
        # Track communication methods per camera (email and text)
        communication_tracker[camera['CAMERA_SERIAL']] = {'email': camera['email'], 'text': camera['text']}

    try:
        client = mqtt.Client()
        client.on_connect = on_connect
        client.on_message = on_message
        client.connect(MQTT_SERVER, MQTT_PORT, 60)
        client.loop_forever()

    except Exception as ex:
        print("[MQTT]failed to connect or receive msg from mqtt, due to: \n {0}".format(ex))
