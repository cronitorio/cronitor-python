from collections import namedtuple

import json
import os

import cronitor
import requests

PING_API_URL = "https://cronitor.link"
MONITOR_API_URL = "https://cronitor.io/v3/monitors"

class MonitorNotFound(Exception):
    pass

class MonitorNotCreated(Exception):
    pass


class Monitor(object):

    @classmethod
    def get_or_create(cls, **kwargs):
        key = kwargs.get('id', kwargs.get('name', None))
        if key:
            try:
                return cls.get(key)
            except MonitorNotFound:
                pass
        return cls.create(**kwargs)


    @classmethod
    def get(cls, id, api_key=None):
        api_key = api_key or cronitor.api_key
        resp = requests.get('{0}/{1}'.format(MONITOR_API_URL, id),
                            timeout=10,
                            auth=(api_key, ''),
                            headers={'content-type': 'application/json'}).json()

        if 'id' in resp:
            return cls(resp['id'], data=resp)

        raise MonitorNotFound("No monitor matching: %s" % id)


    @classmethod
    def create(cls, **kwargs):
        api_key = kwargs['api_key']if 'api_key' in kwargs else cronitor.api_key
        payload = cls.__prepare_payload(**kwargs)
        resp = requests.post(MONITOR_API_URL,
                             auth=(api_key, ''),
                             data=json.dumps(payload),
                             headers={'content-type': 'application/json'},
                             timeout=10)

        if resp.status_code == 201:
            return cls(data=resp.json())

        raise MonitorNotCreated("Unable to create monitor with payload %s" % payload)


    @classmethod
    def __prepare_notifications(cls, notifications={}):
        return {
            "emails": notifications.get('emails', []),
            "phones": notifications.get('phones', []),
            "hipchat": notifications.get('hipchat', []),
            "pagerduty": notifications.get('pagerduty', []),
            "slack": notifications.get('slack', []),
            "templates": notifications.get('templates', []),
            "webhooks": notifications.get('webhooks', [])
        }

    @classmethod
    def __prepare_payload(cls, tags=[], name='', note=None, notifications={}, rules=[], type='cron', timezone='UTC', schedule=None):
        if schedule:
            rules.append({'rule_type': 'not_on_schedule', 'value': schedule})

        return {
            "name": name,
            "type": type,
            # "timezone": timezone,
            "notifications": cls.__prepare_notifications(notifications),
            "rules": rules,
            "tags": tags,
            "note": note
        }

    def __init__(self, id=None, data=None, api_key=None, ping_api_key=None):
        data = data if data else {'id': id}
        assert 'id' in data, "You must provide a monitor Id"

        # TODO need to set the full list of attrs not just what's provided
        MonitorData = namedtuple('Monitor', data.keys())
        self.data = MonitorData(**data)
        self.api_key = api_key or cronitor.api_key
        self.ping_api_key = ping_api_key or cronitor.ping_api_key

    def update(self, name=None, code=None, note=None, notifications=None, rules=None, tags=None):
        payload = self.__prepare_payload(tags, name, note, notifications, rules)
        return requests.put('{0}/{1}'.format(MONITOR_API_URL, self.data.id),
                            auth=(self.api_key, ''),
                            data=json.dumps(payload),
                            headers={'content-type': 'application/json'},
                            timeout=10)

    def delete(self):
        requests.delete('{0}/{1}'.format(MONITOR_API_URL, self.data.id),
                               auth=(self.api_key, ''),
                               headers={'content-type': 'application/json'},
                               timeout=10)

    def clone(self, id, name=None):
        return requests.post(MONITOR_API_URL,
                            auth=(self.api_key, ''),
                            timeout=10,
                            data=json.dumps({"code": self.data.id, name: name}),
                            headers={'content-type': 'application/json'})

    def run(self, msg=''):
        return self.__ping('run', msg=msg)

    def complete(self, msg=''):
        return self.__ping('complete', msg=msg)

    def tick(self, msg=''):
        return self.__ping('tick', msg=msg)

    def fail(self, msg=''):
        return self.__ping('fail', msg=msg)

    def pause(self, hours):
        return self.__get('{0}/{1}/pause/{2}'.format(MONITOR_API_URL, self.data.id, hours))

    def __ping(self, method, msg=''):
        return requests.get(
            '{0}/{1}/{2}'.format(PING_API_URL, self.data.id, method),
            params=dict(ping_api_key=self.ping_api_key, msg=msg),
            timeout=10)

