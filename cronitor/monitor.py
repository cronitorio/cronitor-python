import logging
import json
import os
import cronitor
import requests

from collections import namedtuple
from urllib3.util.retry import Retry
from requests.adapters import HTTPAdapter
from types import MethodType


logging.basicConfig()
logger = logging.getLogger(__name__)


class MonitorNotFound(Exception):
    pass

class MonitorNotCreated(Exception):
    pass

class MonitorNotUpdated(Exception):
    pass

class InvalidPingUrl(Exception):
    pass

class InvalidMonitorParams(Exception):
    pass


class Monitor(object):
    api_key = os.getenv('CRONITOR_API_KEY', None)
    ping_api_key = os.getenv('CRONITOR_PING_API_KEY', '')
    environment = os.getenv('CRONITOR_ENVIRONMENT', 'production')

    @classmethod
    def get(cls, id, **kwargs):
        return cls(id=id, lazy=False, **kwargs)

    @classmethod
    def create(cls, **kwargs):
        api_key = kwargs.get('api_key', Monitor.api_key)
        return cls(id=None, api_key=api_key, data=kwargs, lazy=False)

    @classmethod
    def get_or_create(cls, *args, **kwargs):
        try:
            return cls.get(*args, **kwargs)
        except MonitorNotFound:
            kwargs['name'] = kwargs.get('name', args[0])
            return cls.create(**kwargs)


    @classmethod
    def clone(cls, id, name=None, api_key=None):
        api_key = api_key or Monitor.api_key
        resp = requests.post(monitor_api_url(),
                            auth=(api_key, ''),
                            timeout=10,
                            data=json.dumps({"code": id, name: name}),
                            headers={'content-type': 'application/json'})

        if resp.status_code != 201:
            raise MonitorNotCreated("Unable to clone monitor with id %s" % id)

        return cls(data=resp.json())

    def __init__(self, id=None, key=None, data=None, schedule=None, api_key=None, ping_api_key=None, retry_count=3, env=None, lazy=True):
        if (not key and not id) and (not data and not schedule):
            raise InvalidMonitorParams("must include a valid id, key, or data object")

        self.key = key
        self.id = id
        self._data = data
        self.api_key = api_key or Monitor.api_key
        self.ping_api_key = ping_api_key or Monitor.ping_api_key
        self.env = env or Monitor.environment
        self._req = retry_session(retries=retry_count)

        if self.id or self.key:
            self.ping_url = self._set_ping_url()

        if id and not lazy:
            self.data = self._fetch()

        if not id and not lazy and data:
           self.data = self._create(data)

        # define ping endpoints
        for endpoint in ('run', 'complete', 'fail', 'tick', 'ok'):
            def ping_wrapper():
                ep = endpoint
                def ping(self, **kwargs):
                    # we never want a network exception to raise an error in the calling code
                    # return a boolean so that calling code can differentiate between a successful
                    # or failed ping (it is rare to need to track this information).
                    try:
                        self._ping(ep, kwargs)
                        return True
                    except Exception as e:
                        logger.debug(str(e))
                        return False
                return ping

            setattr(self, endpoint, MethodType(ping_wrapper(), self))

    @property
    def data(self):
        if self._data and type(self._data) is not Struct:
            self._data = Struct(**self._data)
        elif not self._data:
            self._data = Struct(**self._fetch())
        return self._data

    @data.setter
    def data(self, data):
        if 'id' in data and not self.id:
            self.id = data['id']
        self._data = Struct(**data)

    def update(self, *args, **kwargs):
        payload = self.data.__dict__
        payload.update(kwargs)
        resp = requests.put(monitor_api_url(self.id),
                            auth=(self.api_key, ''),
                            data=json.dumps(payload),
                            headers={'content-type': 'application/json'},
                            timeout=10)

        if resp.status_code != 200:
            raise MonitorNotUpdated(resp.json())

        self.data = resp.json()

    def delete(self):
        return requests.delete(
                        monitor_api_url(self.id),
                        auth=(self.api_key, ''),
                        headers={'content-type': 'application/json'},
                        timeout=10)

    def pause(self, hours):
        return self._req.get(url='{}/pause/{}'.format(monitor_api_url(self.id), hours))

    def _ping(self, method, params):
        return self._req.get(url=self.ping_url(method), params=self._clean_params(params), timeout=5)

    def _fetch(self):
        resp = requests.get(monitor_api_url(self.id),
                            timeout=10,
                            auth=(self.api_key, ''),
                            headers={'content-type': 'application/json'})

        if resp.status_code == 404:
            raise MonitorNotFound("No monitor matching: %s" % id)
        return resp.json()

    def _create(self, data):
        # if an id is already set we should not be making a post request
        # look the monitor up by id instead and return the result of that lookup
        if 'id' in data:
            self.id = data['id']
            return self._fetch()

        payload = self._prepare_payload(data)
        resp = requests.post(monitor_api_url(),
                             auth=(self.api_key, ''),
                             data=json.dumps(payload),
                             headers={'content-type': 'application/json'},
                             timeout=10)

        if resp.status_code == 201:
            return resp.json()

        raise MonitorNotCreated(resp.json())


    def _clean_params(self, params):
        return {
            'auth_key': params.get('ping_api_key', self.ping_api_key),
            'env': self.env,
            'msg': params.get('message', None),
            'duration': params.get('duration', None),
            'host': params.get('host', os.getenv('COMPUTERNAME', None)),
            'series': params.get('series', None),
            'stamp': params.get('stamp', None),
            'metric:count': params.get('count', None),
            'metric:error_count': params.get('error_count', None)
        }

    def _set_ping_url(self):
        try:
            if self.id:
                return lambda endpoint: ping_api_url(self.id, endpoint)
            elif self.ping_api_key and self.key:
                return lambda endpoint: ping_api_url(slugify(self.key), endpoint, ping_api_key=self.ping_api_key)
            return None
        except Exception as e:
            raise InvalidPingUrl

    def _prepare_notifications(self, notifications={}):
        return {
            "emails": notifications.get('emails', []),
            "phones": notifications.get('phones', []),
            "hipchat": notifications.get('hipchat', []),
            "pagerduty": notifications.get('pagerduty', []),
            "slack": notifications.get('slack', []),
            "templates": notifications.get('templates', []),
            "webhooks": notifications.get('webhooks', [])
        }

    def _prepare_payload(self, tags=[], name='', note=None, notifications={}, rules=[], type='task', timezone=None, schedule=None, key=None):
        if schedule:
            rules.append({'rule_type': 'not_on_schedule', 'value': schedule})
            type = 'cron'
        elif list(filter(lambda r: r['rule_type'] == 'not_on_schedule', rules)):
            type = 'cron'

        return {
            "name": name,
            "type": type,
            "timezone": timezone,
            "notifications": self._prepare_notifications(notifications),
            "rules": rules,
            "tags": tags,
            "note": note,
            "key": key,
        }


def slugify(input):
    if ' ' not in input:
        return input
    return input.replace(' ', '-')

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


def ping_api_url(id, endpoint, ping_api_key=None):
    if ping_api_key:
        return "https://cronitor.link/ping/{}/{}/{}".format(ping_api_key, id, endpoint)
    return "https://cronitor.link/{}/{}".format(id, endpoint)


def monitor_api_url(id=None):
    if id:
        return "https://cronitor.io/v3/monitors/{}".format(id)
    return "https://cronitor.io/v3/monitors"


class Struct(object):
    def __init__(self, **kwargs):
        self.__dict__.update(kwargs)
