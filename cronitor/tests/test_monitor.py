import copy
import unittest
from unittest.mock import patch

import cronitor

FAKE_API_KEY = '1234567'

MONITOR = {
    'type': 'job',
    'key': 'a-test_key',
    'schedule': '* * * * *',
    'assertions': [
        'metric.duration < 10 seconds'
    ],
    # 'notify': ['devops-alerts']
}
MONITOR_2 = copy.deepcopy(MONITOR)
MONITOR_2['key'] = 'another-test-key'

cronitor.api_key = FAKE_API_KEY

class MonitorTests(unittest.TestCase):

    @patch('cronitor.Monitor._put', return_value=[MONITOR])
    def test_create_monitor(self, mocked_create):
        monitor = cronitor.Monitor.put(**MONITOR)
        self.assertEqual(monitor.data.key, MONITOR['key'])
        self.assertEqual(monitor.data.assertions, MONITOR['assertions'])
        self.assertEqual(monitor.data.schedule, MONITOR['schedule'])

    @patch('cronitor.Monitor._put', return_value=[MONITOR, MONITOR_2])
    def test_create_monitors(self, mocked_create):
        monitors = cronitor.Monitor.put([MONITOR, MONITOR_2])
        self.assertEqual(len(monitors), 2)
        self.assertCountEqual([MONITOR['key'], MONITOR_2['key']], list(map(lambda m: m.data.key, monitors)))

    @patch('cronitor.Monitor._req.put')
    def test_create_monitor_fails(self, mocked_put):
        mocked_put.return_value.status_code = 400
        with self.assertRaises(cronitor.APIValidationError):
             cronitor.Monitor.put(**MONITOR)

    @patch('requests.get')
    def test_get_monitor_invalid_code(self, mocked_get):
        mocked_get.return_value.status_code = 404
        with self.assertRaises(cronitor.MonitorNotFound):
             monitor = cronitor.Monitor("I don't exist")
             monitor.data

    @patch('cronitor.Monitor._put')
    def test_update_monitor_data(self, mocked_update):
        monitor_data = MONITOR.copy()
        monitor_data.update({'name': 'Updated Name'})
        mocked_update.return_value = [monitor_data]

        monitor = cronitor.Monitor.put(key=MONITOR['key'], name='Updated Name')
        self.assertEqual(monitor.data.name, 'Updated Name')

    @patch('cronitor.Monitor._req.put')
    def test_update_monitor_fails_validation(self, mocked_update):
        mocked_update.return_value.status_code = 400
        with self.assertRaises(cronitor.APIValidationError):
            cronitor.Monitor.put(schedule='* * * * *')

    @patch('requests.delete')
    def test_delete_no_id(self, mocked_delete):
        mocked_delete.return_value.status_code = 204
        monitor = cronitor.Monitor(MONITOR['key'])
        monitor.delete()

