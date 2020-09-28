import os
import unittest
from unittest.mock import patch
from unittest.mock import MagicMock

from cronitor import ping, Monitor
import cronitor

# a reserved monitorId for running integration tests against cronitor.link
FAKE_ID = 'd3x0c1'
FAKE_PING_API_KEY = 'ping-api-key'

class MonitorPingTests(unittest.TestCase):

    def test_endpoints(self):
        monitor = cronitor.Monitor(id=FAKE_ID)
        endpoints = ['run', 'complete', 'tick', 'fail', 'ok']

        for endpoint in endpoints:
            pinged = monitor.__getattribute__(endpoint)()
            self.assertTrue(pinged)

    def test_ping_api_key(self):
        monitor = cronitor.Monitor(id=FAKE_ID, ping_api_key=FAKE_PING_API_KEY)
        assert set({'auth_key': FAKE_PING_API_KEY}.items()).issubset(set(monitor._clean_params({}).items()))

    def test_message(self):
        monitor = cronitor.Monitor(id=FAKE_ID)
        message = 'a test message'
        assert set({'msg': message}.items()).issubset(set(monitor._clean_params({'message': message}).items()))

    def test_environment_param(self):
        monitor = cronitor.Monitor(id=FAKE_ID, env='development')
        assert set({'env': 'development'}.items()).issubset(set(monitor._clean_params({}).items()))

    def test_ping_url_with_monitor_id(self):
        monitor = cronitor.Monitor(id=FAKE_ID)
        assert monitor.ping_url('run') == 'https://cronitor.link/{}/{}'.format(FAKE_ID, 'run')

    def test_ping_url_with_user_supplied_key(self):
        monitor = cronitor.Monitor(key=FAKE_ID, ping_api_key=FAKE_PING_API_KEY)
        assert monitor.ping_url('run') == "https://cronitor.link/ping/{}/{}/{}".format(FAKE_PING_API_KEY, FAKE_ID, 'run')

    @patch('cronitor.Monitor._ping')
    def test_all_params_sent(self, ping):
        monitor = Monitor(id=FAKE_ID)
        params = {
            'message': "test",
            'env': 'staging',
            'duration': 1,
            'host': 'blue-oyster',
            'series': 'a.b.c',
            'count': '42',
            'error_count': 0}

        monitor.run(**params)
        ping.assert_called_once_with('run', params)



