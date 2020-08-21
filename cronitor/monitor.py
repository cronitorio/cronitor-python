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

ping_api_url = lambda id, endpoint: "https://cronitor.link/{}/{}".format(id, endpoint)
monitor_api_url = lambda id=None:  "https://cronitor.io/v3/monitors/{}".format(id) if id else "https://cronitor.io/v3/monitors"


class MonitorNotFound(Exception):
    pass

class MonitorNotCreated(Exception):
    pass

class MonitorNotUpdated(Exception):
    pass


class Monitor(object):
    api_key = os.getenv('CRONITOR_API_KEY', None)
    ping_api_key = os.getenv('CRONITOR_PING_API_KEY', '')
    environment = os.getenv('CRONITOR_ENVIRONMENT', 'production')

    @classmethod
    def get_or_create(cls, **kwargs):
        key = kwargs.get('id', kwargs.get('name', None))
        api_key = kwargs.get('api_key', None)
        if key:
            try:
                return cls.get(key, api_key=api_key)
            except MonitorNotFound:
                pass
        return cls.create(**kwargs)

    @classmethod
    def get(cls, id, api_key=None):
        api_key = api_key or Monitor.api_key
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
        a_key = kwargs.get('api_key', Monitor.api_key)
        if 'api_key' in kwargs: del kwargs['api_key']

        payload = cls.__prepare_payload(**kwargs)
        resp = requests.post(monitor_api_url(),
                             auth=(a_key, ''),
                             data=json.dumps(payload),
                             headers={'content-type': 'application/json'},
                             timeout=10)

        if resp.status_code != 201:
            raise MonitorNotCreated(resp.json())

        return cls(data=resp.json())

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
    def __prepare_payload(cls, tags=[], name='', note=None, notifications={}, rules=[], type='task', timezone=None, schedule=None):
        if schedule:
            rules.append({'rule_type': 'not_on_schedule', 'value': schedule})
            type = 'cron'
        elif list(filter(lambda r: r['rule_type'] == 'not_on_schedule', rules)):
            type = 'cron'

        return {
            "name": name,
            "type": type,
            "timezone": timezone,
            "notifications": cls.__prepare_notifications(notifications),
            "rules": rules,
            "tags": tags,
            "note": note
        }

    def __init__(self, id=None, data={}, api_key=None, ping_api_key=None, retry_count=3, env=environment):
        if not id and 'id' not in data:
            raise MonitorNotFound("You must provide a monitorId")

        self.id = id
        self.api_key = api_key or Monitor.api_key
        self.ping_api_key = ping_api_key or Monitor.ping_api_key
        self.env = env
        self.req = retry_session(retries=retry_count)
        self._set_data(data)

        # define ping endpoints
        for endpoint in ('run', 'complete', 'fail', 'tick', 'ok'):
            def ping_wrapper():
                ep = endpoint
                def ping(self, **kwargs):
                    # we never want a network exception to raise an error in calling code
                    # return a boolean to that calling code can differentiate between a successful
                    # or failed ping. it is rare to need to know this information.
                    try:
                        self._ping(ep, kwargs)
                        return True
                    except Exception as e:
                        logger.debug(str(e))
                        return False
                return ping

            setattr(self, endpoint, MethodType(ping_wrapper(), self))


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
        return requests.delete(
                        monitor_api_url(self.id),
                        auth=(self.api_key, ''),
                        headers={'content-type': 'application/json'},
                        timeout=10)

    def pause(self, hours):
        return self.req.get(url='{}/pause/{}'.format(monitor_api_url(self.id), hours))

    def _ping(self, method, params):
        return self.req.get(url=ping_api_url(self.id, method), params=self._clean_params(params), timeout=5)

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

