import time
import logging
import json
import os
import requests


import cronitor
from urllib3.util.retry import Retry
from requests.adapters import HTTPAdapter

logging.basicConfig()
logger = logging.getLogger(__name__)

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


class Monitor(object):
    _headers = {
        'User-Agent': 'cronitor-python',
        'content-type': 'application/json',
    }

    _req = retry_session(retries=3)

    @classmethod
    def as_yaml(cls, api_key=None):
        api_key = api_key or cronitor.api_key
        resp = cls._req.get('%s.yaml' % cls._monitor_api_url(),
                        auth=(api_key, ''),
                        headers=cls._headers,
                        timeout=10)
        if resp.status_code == 200:
            return resp.text
        else:
            raise cronitor.APIError("Unexpected error %s" % resp.text)

    @classmethod
    def put(cls, monitors=None, **kwargs):
        api_key = cronitor.api_key
        rollback = False
        if 'rollback' in kwargs:
            rollback = kwargs['rollback']
            del kwargs['rollback']
        if 'api_key' in kwargs:
            api_key = kwargs['api_key']
            del kwargs['api_key']
        if 'api_version' in kwargs:
            cls._headers['Cronitor-Version'] = kwargs['api_version']
            del kwargs['api_version']

        data = cls._put(monitors or [kwargs], api_key, rollback)
        _monitors = []
        for md in data:
            m = cls(md['key'])
            m.data = md
            _monitors.append(m)

        return _monitors if len(_monitors) > 1 else _monitors[0]

    @classmethod
    def _put(cls, monitors, api_key, rollback):
        payload = _prepare_payload(monitors, rollback)

        resp = cls._req.put(cls._monitor_api_url(),
                        auth=(api_key, ''),
                        data=json.dumps(payload),
                        headers=cls._headers,
                        timeout=10)

        if resp.status_code == 200:
            return resp.json().get('monitors', [])
        elif resp.status_code == 400:
            raise cronitor.APIValidationError(resp.text)
        else:
            raise cronitor.APIError("Unexpected error %s" % resp.text)

    def __init__(self, key, api_key=None, api_version=None, env=None):
        self.key = key
        self.api_key = api_key or cronitor.api_key
        self.api_verion = api_version or cronitor.api_version
        self.env = env or cronitor.environment
        self._data = None

        if self.api_verion:
            self._headers['Cronitor-Version'] = self.api_version

    @property
    def data(self):
        if self._data and type(self._data) is not Struct:
            self._data = Struct(**self._data)
        elif not self._data:
            self._data = Struct(**self._fetch())
        return self._data

    @data.setter
    def data(self, data):
        self._data = Struct(**data)

    def delete(self):
        resp = requests.delete(
                    self._monitor_api_url(self.key),
                    auth=(self.api_key, ''),
                    headers=self._headers,
                    timeout=10)

        if resp.status_code == 204:
            return True
        elif resp.status_code == 404:
            raise cronitor.MonitorNotFound("Monitor '%s' not found" % self.key)
        else:
            raise cronitor.APIError("An unexpected error occured when deleting '%s'" % self.key)

    def ping(self, **params):
        if not self.api_key:
            logger.error('No API key detected. Set cronitor.api_key or initialize Monitor with kwarg.')
            return
        try:
            self._req.get(url=self._ping_api_url(), params=self._clean_params(params), timeout=5, headers=self._headers)
            return True
        except Exception:
            logger.error('Failed to ping Cronitor with key - %s' % self.key)
            return False

    def ok(self):
        self.ping(state=cronitor.State.ok)

    def pause(self, hours):
        return self._req.get(url='{}/pause/{}'.format(self._monitor_api_url(self.key), hours))

    def unpause(self):
        return self.pause(0)

    def _fetch(self):
        if not self.api_key:
            raise cronitor.AuthenticationError('No api_key detected. Set cronitor.api_key or initialize Monitor with kwarg.')

        resp = requests.get(self._monitor_api_url(self.key),
                            timeout=10,
                            auth=(self.api_key, ''),
                            headers=self._headers)

        if resp.status_code == 404:
            raise cronitor.MonitorNotFound("Monitor '%s' not found" % self.key)
        return resp.json()

    def _clean_params(self, params):
        metrics = None
        if 'metrics' in params and type(params['metrics']) == dict:
            metrics = ['{}:{}'.format(k,v) for k,v in params['metrics'].items()]

        return {
            'state': params.get('state', None),
            'message': params.get('message', None),
            'series': params.get('series', None),
            'host': params.get('host', os.getenv('COMPUTERNAME', None)),
            'metric': metrics,
            'stamp': time.time(),
            'env': self.env,
        }

    def _ping_api_url(self):
        return "https://cronitor.link/ping/{}/{}".format(self.api_key, self.key)

    @classmethod
    def _monitor_api_url(cls, key=None):
        if not key: return "https://cronitor.io/api/monitors"
        return "https://cronitor.io/api/monitors/{}".format(key)


def _prepare_payload(monitors, rollback=False):
    ret = { 'monitors': monitors }
    if rollback:
        ret['rollback'] = True
    return ret


class Struct(object):
    def __init__(self, **kwargs):
        self.__dict__.update(kwargs)
