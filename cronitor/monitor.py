import time
import yaml
import logging
import json
import os
import requests
from yaml.loader import SafeLoader


import cronitor
from urllib3.util.retry import Retry
from requests.adapters import HTTPAdapter

logger = logging.getLogger(__name__)

# https://stackoverflow.com/questions/49121365/implementing-retry-for-requests-in-python
def retry_session(retries, session=None, backoff_factor=0.3):
    session = session or requests.Session()
    retry = Retry(
        total=retries,
        read=retries,
        connect=retries,
        backoff_factor=backoff_factor,
    )
    adapter = HTTPAdapter(max_retries=retry)
    session.mount('http://', adapter)
    session.mount('https://', adapter)
    return session

JSON = 'json'
YAML = 'yaml'

class Monitor(object):
    _headers = {
        'User-Agent': 'cronitor-python',
    }

    _req = retry_session(retries=3)

    @classmethod
    def as_yaml(cls, api_key=None, api_version=None):
        timeout = cronitor.timeout or 10
        api_key = api_key or cronitor.api_key
        resp = cls._req.get('%s.yaml' % cls._monitor_api_url(),
                        auth=(api_key, ''),
                        headers=dict(cls._headers, **{'Content-Type': 'application/yaml', 'Cronitor-Version': api_version}),
                        timeout=timeout)
        if resp.status_code == 200:
            return resp.text
        else:
            raise cronitor.APIError("Unexpected error %s" % resp.text)

    @classmethod
    def put(cls, monitors=None, **kwargs):
        api_key = cronitor.api_key
        api_version = cronitor.api_version
        request_format = JSON

        rollback = False
        if 'rollback' in kwargs:
            rollback = kwargs['rollback']
            del kwargs['rollback']
        if 'api_key' in kwargs:
            api_key = kwargs['api_key']
            del kwargs['api_key']
        if 'api_version' in kwargs:
            api_version = kwargs['api_version']
            del kwargs['api_version']
        if 'format' in kwargs:
            request_format = kwargs['format']
            del kwargs['format']

        _monitors = monitors or [kwargs]
        nested_format = True if type(monitors) == dict else False

        data = cls._put(_monitors, api_key, rollback, request_format, api_version)

        if nested_format:
            return data

        _monitors = []
        for md in data:
            m = cls(md['key'])
            m.data = md
            _monitors.append(m)

        return _monitors if len(_monitors) > 1 else _monitors[0]

    @classmethod
    def _put(cls, monitors, api_key, rollback, request_format, api_version):
        timeout = cronitor.timeout or 10
        payload = _prepare_payload(monitors, rollback, request_format)
        if request_format == YAML:
            content_type = 'application/yaml'
            data = yaml.dump(payload)
            url = '{}.yaml'.format(cls._monitor_api_url())
        else:
            content_type = 'application/json'
            data = json.dumps(payload)
            url = cls._monitor_api_url()

        resp = cls._req.put(url,
                        auth=(api_key, ''),
                        data=data,
                        headers=dict(cls._headers, **{'Content-Type': content_type, 'Cronitor-Version': api_version}),
                        timeout=timeout)

        if resp.status_code == 200:
            if request_format == YAML:
                return yaml.load(resp.text, Loader=SafeLoader)
            else:
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

    @property
    def data(self):
        """
        Monitor data with attribute access. Nested dicts are automatically
        converted to Structs.

        Example:
            >>> monitor = Monitor('my-monitor')
            >>> print(monitor.data.name)
            >>> print(monitor.data.request.url)
            >>> print(monitor.data)  # Pretty JSON output
        """
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
            logger.error('No API key detected. Set cronitor.api_key or initialize Monitor with kwarg api_key.')
            return

        return self._req.get(url=self._ping_api_url(), params=self._clean_params(params), timeout=5, headers=self._headers)

    def ok(self):
        self.ping(state=cronitor.State.OK)

    def pause(self, hours):
        if not self.api_key:
            logger.error('No API key detected. Set cronitor.api_key or initialize Monitor with kwarg api_key.')
            return

        return self._req.get(url='{}/pause/{}'.format(self._monitor_api_url(self.key), hours), auth=(self.api_key, ''), timeout=5, headers=self._headers)

    def unpause(self):
        return self.pause(0)

    def _fetch(self):
        if not self.api_key:
            raise cronitor.AuthenticationError('No api_key detected. Set cronitor.api_key or initialize Monitor with kwarg.')

        resp = requests.get(self._monitor_api_url(self.key),
                            timeout=10,
                            auth=(self.api_key, ''),
                            headers=dict(self._headers, **{'Content-Type': 'application/json', 'Cronitor-Version': self.api_verion}))

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
        return "https://cronitor.link/p/{}/{}".format(self.api_key, self.key)

    @classmethod
    def list(cls, keys=None, page=1, pageSize=100, auto_paginate=False, **filters):
        """
        Fetch monitors with optional filtering and pagination.

        Args:
            keys: Optional list of monitor keys to fetch specifically
            page: Page number (default: 1)
            pageSize: Results per page (default: 100)
            auto_paginate: If True, automatically fetch all pages (default: False)
            **filters: type, group, tag, state, env, search, sort

        Returns:
            List of Monitor instances

        Examples:
            # Fetch specific monitors
            monitors = Monitor.list(['key1', 'key2'])

            # Fetch first page of job monitors
            monitors = Monitor.list(type='job')

            # Fetch specific page
            monitors = Monitor.list(type='job', page=2, pageSize=50)

            # Fetch all pages automatically
            monitors = Monitor.list(type='job', auto_paginate=True)
        """
        if keys:
            # Fetch specific monitors individually
            monitors = [cls(key) for key in keys]
            # Populate data immediately
            for m in monitors:
                _ = m.data  # Triggers fetch
            return monitors

        # Fetch from API with filters
        monitors = []
        current_page = page

        while True:
            result = cls._fetch_page(current_page, pageSize, **filters)
            monitors.extend(result)

            if not auto_paginate or len(result) < pageSize:
                # Either not auto-paginating or no more results
                break

            current_page += 1

        return monitors

    @classmethod
    def _fetch_page(cls, page, pageSize, **filters):
        """Fetch a single page of monitors from the API"""
        api_key = filters.pop('api_key', None) or cronitor.api_key
        api_version = filters.pop('api_version', None) or cronitor.api_version
        timeout = cronitor.timeout or 10

        params = dict(filters, page=page, pageSize=pageSize)

        resp = cls._req.get(
            cls._monitor_api_url(),
            auth=(api_key, ''),
            params=params,
            headers=dict(cls._headers, **{'Cronitor-Version': api_version}),
            timeout=timeout
        )

        if resp.status_code == 200:
            data = resp.json()
            monitors = []
            for monitor_data in data.get('monitors', []):
                m = cls(monitor_data['key'])
                m.data = monitor_data
                monitors.append(m)
            return monitors
        else:
            raise cronitor.APIError("Unexpected error %s" % resp.text)

    @classmethod
    def _monitor_api_url(cls, key=None):
        if not key: return "https://cronitor.io/api/monitors"
        return "https://cronitor.io/api/monitors/{}".format(key)

def _prepare_payload(monitors, rollback=False, request_format=JSON):
    ret = {}
    if request_format == JSON:
        ret['monitors'] = monitors
    if request_format == YAML:
        ret = monitors
    if rollback:
        ret['rollback'] = True
    return ret


class Struct(object):
    def __init__(self, **kwargs):
        for key, value in kwargs.items():
            if isinstance(value, dict):
                value = Struct(**value)
            elif isinstance(value, list):
                value = [Struct(**item) if isinstance(item, dict) else item for item in value]
            setattr(self, key, value)

    def __repr__(self):
        items = ', '.join(f'{k}={v!r}' for k, v in sorted(self.__dict__.items()))
        return f"Struct({items})"

    def __str__(self):
        return json.dumps(self._to_dict(), indent=2, sort_keys=True, default=str)

    def _to_dict(self):
        result = {}
        for key, value in self.__dict__.items():
            if isinstance(value, Struct):
                result[key] = value._to_dict()
            elif isinstance(value, list):
                result[key] = [item._to_dict() if isinstance(item, Struct) else item for item in value]
            else:
                result[key] = value
        return result
