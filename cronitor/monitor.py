from __future__ import print_function

import json
import os

import requests

PING_API_URL = "https://cronitor.link"
MONITOR_API_URL = "https://cronitor.io/v3/monitors"

class Monitor(object):
    def __init__(self, id=None, api_key=None, ping_api_key=None, time_zone='UTC'):
        self.id = id
        self.api_key = api_key or os.getenv('CRONITOR_API_KEY')
        self.ping_api_key = ping_api_key or os.getenv('CRONITOR_PING_API_KEY')
        self.timezone = time_zone

    # TODO - IS THIS SEPARATE?
    def create(self, name=None, note=None, notifications=None,
               rules=None, tags=None):
        payload = self.__prepare_payload(tags, name, note,
                                         notifications, rules)
        return self.__create(payload=payload)

    def update(self, name=None, code=None, note=None,
               notifications=None, rules=None, tags=None):
        payload = self.__prepare_payload(tags, name, note,
                                         notifications, rules)
        return self.__update(payload=payload, code=code)

    def delete(self, code):
        return self.__delete(code)

    def get(self, code):
        return self.__get('{0}/{1}'.format(MONITOR_API_URL, code))

    def run(self, msg=''):
        return self.__ping(self.id, 'run', msg=msg)

    def complete(self, msg=''):
        return self.__ping(self.id, 'complete', msg=msg)

    def failed(self, msg=''):
        return self.__ping(self.id, 'fail', msg=msg)

    def pause(self, code, hours):
        return self.__get('{0}/{1}/pause/{2}'.format(MONITOR_API_URL,
                                                     code, hours))

    def clone(self, code, name=None):
        return requests.post(MONITOR_API_URL,
                             auth=(self.api_key, ''),
                             timeout=10,
                             data=json.dumps({"code": code, name: name}),
                             headers={'content-type': 'application/json'})


    def __ping(self, code, method, msg=''):
        return requests.get(
            '{0}/{1}/{2}'.format(PING_API_URL, code, method),
            params=dict(ping_api_key=self.ping_api_key, msg=msg),
            timeout=10
        )

    def __get(self, url):
        return requests.get(url,
                            timeout=10,
                            auth=(self.api_key, ''),
                            headers={'content-type': 'application/json'}
                            )

    def __create(self, payload):
        return requests.post(MONITOR_API_URL,
                             auth=(self.api_key, ''),
                             data=json.dumps(payload),
                             headers={'content-type': 'application/json'},
                             timeout=10
                             )

    def __update(self, payload=None, code=None):
        return requests.put('{0}/{1}'.format(MONITOR_API_URL, code),
                            auth=(self.api_key, ''),
                            data=json.dumps(payload),
                            headers={'content-type': 'application/json'},
                            timeout=10
                            )

    def __delete(self, code):
        return requests.delete('{0}/{1}'.format(MONITOR_API_URL, code),
                               auth=(self.api_key, ''),
                               headers={'content-type': 'application/json'},
                               timeout=10
                               )

    @staticmethod
    def __prepare_notifications(notifications):
        if notifications:
            return {
                "emails": notifications.get('emails', []),
                "phones": notifications.get('phones', []),
                "hipchat": notifications.get('hipchat', []),
                "pagerduty": notifications.get('pagerduty', []),
                "slack": notifications.get('slack', []),
                "templates": notifications.get('templates', []),
                "webhooks": notifications.get('webhooks', [])
            }
        else:
            return {}

    def __prepare_payload(self, tags, name, note, notifications, rules):
        return {
            "code": "new_monitor",
            "name": name,
            "type": "heartbeat",
            "timezone": self.timezone,
            "notifications": self.__prepare_notifications(notifications),
            "rules": rules or [],
            "tags": tags or [],
            "note": note
        }
