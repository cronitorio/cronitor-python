from __future__ import print_function

import json
import os

import requests


class Monitor(object):
    def __init__(self, api_key=None, auth_key=None, time_zone='UTC'):
        self.api_endpoint = 'https://cronitor.io/v3/monitors'
        self.ping_endpoint = "https://cronitor.link"
        self.api_key = api_key or os.getenv('CRONITOR_API_KEY')
        self.auth_key = auth_key or os.getenv('CRONITOR_AUTH_KEY')
        self.timezone = time_zone

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
        return self.__get('{0}/{1}'.format(self.api_endpoint, code))

    def run(self, code, msg=''):
        return self.__ping(code, 'run', msg=msg)

    def complete(self, code, msg=''):
        return self.__ping(code, 'complete')

    def failed(self, code, msg=''):
        return self.__ping(code, 'failed', msg=msg)

    def pause(self, code, hours):
        return self.__get('{0}/{1}/pause/{2}'.format(self.api_endpoint,
                                                     code, hours))

    def clone(self, code, name=None):
        return requests.post(self.api_endpoint,
                             auth=(self.api_key, ''),
                             timeout=10,
                             data=json.dumps({"code": code, name: name}),
                             headers={'content-type': 'application/json'})

    def __ping(self, code, method, msg=''):
        params = dict(auth_key=self.auth_key, msg=msg)
        return requests.get(
            '{0}/{1}/{2}'.format(self.ping_endpoint, code, method),
            params=params,
            timeout=10
        )

    def __get(self, url):
        return requests.get(url,
                            timeout=10,
                            auth=(self.api_key, ''),
                            headers={'content-type': 'application/json'}
                            )

    def __create(self, payload):
        return requests.post(self.api_endpoint,
                             auth=(self.api_key, ''),
                             data=json.dumps(payload),
                             headers={'content-type': 'application/json'},
                             timeout=10
                             )

    def __update(self, payload=None, code=None):
        return requests.put('{0}/{1}'.format(self.api_endpoint, code),
                            auth=(self.api_key, ''),
                            data=json.dumps(payload),
                            headers={'content-type': 'application/json'},
                            timeout=10
                            )

    def __delete(self, code):
        return requests.delete('{0}/{1}'.format(self.api_endpoint, code),
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
