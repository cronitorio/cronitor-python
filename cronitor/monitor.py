import json
import os
import cronitor
import requests

from collections import namedtuple
from urllib3.util.retry import Retry
from requests.adapters import HTTPAdapter


ping_api_url = lambda id, endpoint: "https://cronitor.link/{}/{}".format(id, endpoint)
monitor_api_url = lambda id=None:  "https://cronitor.io/v3/monitors/{}".format(id) if id else "https://cronitor.io/v3/monitors"


class MonitorNotFound(Exception):
    pass

class MonitorNotCreated(Exception):
    pass

class MonitorNotUpdated(Exception):
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
        resp = requests.get(monitor_api_url(id),
                            timeout=10,
                            auth=(api_key, ''),
                            headers={'content-type': 'application/json'})

        if resp.status_code == 404:
            raise MonitorNotFound("No monitor matching: %s" % id)
        data = resp.json()
        return cls(data=data)

    @classmethod
    def create(cls, **kwargs):
        api_key = kwargs['api_key']if 'api_key' in kwargs else cronitor.api_key
        payload = cls.__prepare_payload(**kwargs)
        resp = requests.post(monitor_api_url(),
                             auth=(api_key, ''),
                             data=json.dumps(payload),
                             headers={'content-type': 'application/json'},
                             timeout=10)

        if resp.status_code != 201:
            raise MonitorNotCreated(resp.json())

        return cls(data=resp.json())

    @classmethod
    def clone(cls, id, name=None, api_key=None):
        api_key = api_key or cronitor.api_key
        resp = requests.post(monitor_api_url(),
                            auth=(api_key, ''),
                            timeout=10,
                            data=json.dumps({"code": id, name: name}),
                            headers={'content-type': 'application/json'})

        if resp.status_code != 201:
            raise MonitorNotCreated("Unable to clone monitor with id %s" % id)

        return cls(data=resp.json())


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
    def __prepare_payload(cls, tags=[], name='', note=None, notifications={}, rules=[], type='cron', timezone=None, schedule=None):
        if schedule:
            rules.append({'rule_type': 'not_on_schedule', 'value': schedule})

        return {
            "name": name,
            "type": type,
            "timezone": timezone,
            "notifications": cls.__prepare_notifications(notifications),
            "rules": rules,
            "tags": tags,
            "note": note
        }

    def __init__(self, id=None, data={}, api_key=None, ping_api_key=None, retry_pings=True):
        if not id and 'id' not in data:
            raise MonitorNotFound("You must provide a monitorId")

        self.id = id
        self.api_key = api_key or cronitor.api_key
        self.ping_api_key = ping_api_key or cronitor.ping_api_key
        self.req = retry_session(retries=5 if retry_pings else 0)
        self._set_data(data)

    def update(self, *args, **kwargs):
        payload = self.data._asdict()
        payload.update(kwargs)
        resp = requests.put(monitor_api_url(self.id),
                            auth=(self.api_key, ''),
                            data=json.dumps(payload),
                            headers={'content-type': 'application/json'},
                            timeout=10)

        if resp.status_code != 200:
            raise MonitorNotUpdated(resp.json())

        self._set_data(resp.json())
        return self


    def delete(self):
        return requests.delete(monitor_api_url(self.id),
                        auth=(self.api_key, ''),
                        headers={'content-type': 'application/json'},
                        timeout=10)

    def run(self, *args, **kwargs):
        return self._ping('run', kwargs)

    def complete(self, *args, **kwargs):
        return self._ping('complete', kwargs)

    def tick(self, *args, **kwargs):
        return self._ping('tick', kwargs)

    def ok(self, *args, **kwargs):
        return self._ping('ok', kwargs)

    def fail(self, *args, **kwargs):
        return self._ping('fail', kwargs)

    def pause(self, hours):
        return self.req.get(url='{}/pause/{}'.format(monitor_api_url(self.id), hours))

    def _ping(self, method, params):
        return self.req.get(url=ping_api_url(self.id, method), params=self._clean_params(params), timeout=5)

    def _clean_params(self, params):
        return {
            'auth_key': self.ping_api_key,
            'msg': params.get('message', None),
            'env': params.get('env', cronitor.environment),
            'duration': params.get('duration', None),
            'host': params.get('host', None),
            'series': params.get('series', None),
            'count': params.get('count', None),
            'error_count': params.get('error_count', None)
        }

    def _set_data(self, data):
        if 'id' in data and not self.id:
            self.id = data['id']

        self.data = namedtuple('MonitorData', data.keys())(**data)



# https://stackoverflow.com/questions/49121365/implementing-retry-for-requests-in-python
def retry_session(retries, session=None, backoff_factor=0.3):
    session = session or requests.Session()
    retry = Retry(
        total=retries,
        read=retries,
        connect=retries,
        backoff_factor=backoff_factor,
        method_whitelist=False,
    )
    adapter = HTTPAdapter(max_retries=retry)
    session.mount('http://', adapter)
    session.mount('https://', adapter)
    return session

