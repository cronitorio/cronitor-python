import yaml
import cronitor
import unittest
from unittest.mock import call, patch, ANY
import time
import cronitor

FAKE_API_KEY = 'cb54ac4fd16142469f2d84fc1bbebd84XXXDEADXXX'
YAML_PATH = './cronitor/tests/cronitor.yaml'

cronitor.api_key = FAKE_API_KEY
cronitor.timeout = 10

class SyncTests(unittest.TestCase):

    def setUp(self):
        return super().setUp()

    def test_00_monitor_attributes_are_put(self):
        # This test will run first, test that attributes are synced correctly, and then undo the global mock

        with patch('cronitor.Monitor.put') as mock_put:
            time.sleep(2)
            calls = [call([{'key': 'ping-decorator-test', 'name': 'Ping Decorator Test'}])]
            mock_put.assert_has_calls(calls)

    @cronitor.job('ping-decorator-test', attributes={'name': 'Ping Decorator Test'})
    def function_call_with_attributes(self):
        return
