import copy
import cronitor
import unittest
from unittest.mock import call, patch, ANY

import cronitor

FAKE_API_KEY = 'cb54ac4fd16142469f2d84fc1bbebd84XXXDEADXXX'

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

YAML_FORMAT_MONITORS = {
    'jobs': {
        MONITOR['key']: MONITOR,
        MONITOR_2['key']: MONITOR_2
    }
}

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

    @patch('cronitor.Monitor._put', return_value=YAML_FORMAT_MONITORS)
    def test_create_monitors_yaml_body(self, mocked_create):
        monitors = cronitor.Monitor.put(monitors=YAML_FORMAT_MONITORS, format='yaml')
        self.assertIn(MONITOR['key'], monitors['jobs'])
        self.assertIn(MONITOR_2['key'], monitors['jobs'])

    @patch('requests.delete')
    def test_delete_no_id(self, mocked_delete):
        mocked_delete.return_value.status_code = 204
        monitor = cronitor.Monitor(MONITOR['key'])
        monitor.delete()

    @patch('cronitor.Monitor._put')
    def test_struct_nested_dict_access(self, mocked_put):
        """Test that nested dicts are converted to Structs for attribute access"""
        monitor_with_nested = {
            'key': 'test-key',
            'name': 'Test Monitor',
            'attributes': {
                'code': 'ABC123',
                'group_name': 'production',
            },
            'latest_event': {
                'stamp': 1234567890.0,
                'event': 'complete',
                'metrics': {'duration': 1.5},
            }
        }
        mocked_put.return_value = [monitor_with_nested]

        monitor = cronitor.Monitor.put(**monitor_with_nested)

        # Test nested attribute access
        self.assertEqual(monitor.data.attributes.code, 'ABC123')
        self.assertEqual(monitor.data.attributes.group_name, 'production')
        self.assertEqual(monitor.data.latest_event.event, 'complete')
        self.assertEqual(monitor.data.latest_event.stamp, 1234567890.0)

        # Test deeply nested dict is also converted to Struct
        self.assertEqual(monitor.data.latest_event.metrics.duration, 1.5)

    @patch('cronitor.Monitor._put')
    def test_struct_list_with_dicts(self, mocked_put):
        """Test that lists containing dicts are converted properly"""
        monitor_with_list = {
            'key': 'test-key',
            'name': 'Test Monitor',
            'latest_events': [
                {'stamp': 1234567890.0, 'event': 'run'},
                {'stamp': 1234567900.0, 'event': 'complete'},
            ]
        }
        mocked_put.return_value = [monitor_with_list]

        monitor = cronitor.Monitor.put(**monitor_with_list)

        # Test list items are converted to Structs
        self.assertEqual(len(monitor.data.latest_events), 2)
        self.assertEqual(monitor.data.latest_events[0].event, 'run')
        self.assertEqual(monitor.data.latest_events[1].event, 'complete')
        self.assertEqual(monitor.data.latest_events[1].stamp, 1234567900.0)

    @patch('cronitor.Monitor._put')
    def test_struct_str_pretty_print(self, mocked_put):
        """Test that Struct.__str__ returns pretty JSON"""
        monitor_data = {
            'key': 'test-key',
            'name': 'Test Monitor',
            'type': 'job',
            'passing': True,
        }
        mocked_put.return_value = [monitor_data]

        monitor = cronitor.Monitor.put(**monitor_data)

        # Test str() returns valid JSON
        import json
        json_str = str(monitor.data)
        parsed = json.loads(json_str)

        self.assertEqual(parsed['key'], 'test-key')
        self.assertEqual(parsed['name'], 'Test Monitor')
        self.assertEqual(parsed['type'], 'job')
        self.assertEqual(parsed['passing'], True)

        # Test it's pretty formatted (contains newlines and indentation)
        self.assertIn('\n', json_str)
        self.assertIn('  ', json_str)

    @patch('cronitor.Monitor._put')
    def test_struct_repr(self, mocked_put):
        """Test that Struct.__repr__ is useful for debugging"""
        monitor_data = {
            'key': 'test-key',
            'name': 'Test Monitor',
        }
        mocked_put.return_value = [monitor_data]

        monitor = cronitor.Monitor.put(**monitor_data)

        # Test repr starts with Struct and contains key-value pairs
        repr_str = repr(monitor.data)
        self.assertTrue(repr_str.startswith('Struct('))
        self.assertIn('key=', repr_str)
        self.assertIn('name=', repr_str)
        self.assertIn('test-key', repr_str)

    @patch('requests.get')
    def test_list_with_specific_keys(self, mocked_get):
        """Test Monitor.list() with specific keys fetches each individually"""
        monitor1_data = {'key': 'key1', 'name': 'Monitor 1', 'type': 'job'}
        monitor2_data = {'key': 'key2', 'name': 'Monitor 2', 'type': 'check'}

        # Mock responses for individual monitor fetches
        def get_side_effect(url, **kwargs):
            mock_resp = unittest.mock.Mock()
            mock_resp.status_code = 200
            if 'key1' in url:
                mock_resp.json.return_value = monitor1_data
            elif 'key2' in url:
                mock_resp.json.return_value = monitor2_data
            return mock_resp

        mocked_get.side_effect = get_side_effect

        monitors = cronitor.Monitor.list(['key1', 'key2'])

        # Should return 2 monitors
        self.assertEqual(len(monitors), 2)
        self.assertEqual(monitors[0].data.key, 'key1')
        self.assertEqual(monitors[1].data.key, 'key2')

        # Should have made 2 GET requests
        self.assertEqual(mocked_get.call_count, 2)

    @patch('cronitor.Monitor._req.get')
    def test_list_with_filters(self, mocked_get):
        """Test Monitor.list() with type and other filters"""
        monitor1 = {'key': 'job1', 'name': 'Job 1', 'type': 'job'}
        monitor2 = {'key': 'job2', 'name': 'Job 2', 'type': 'job'}

        mock_resp = unittest.mock.Mock()
        mock_resp.status_code = 200
        mock_resp.json.return_value = {'monitors': [monitor1, monitor2]}
        mocked_get.return_value = mock_resp

        monitors = cronitor.Monitor.list(type='job', group='production')

        # Should return 2 monitors
        self.assertEqual(len(monitors), 2)
        self.assertEqual(monitors[0].data.key, 'job1')
        self.assertEqual(monitors[1].data.key, 'job2')

        # Should have made 1 GET request with correct params
        self.assertEqual(mocked_get.call_count, 1)
        call_kwargs = mocked_get.call_args[1]
        self.assertEqual(call_kwargs['params']['type'], 'job')
        self.assertEqual(call_kwargs['params']['group'], 'production')
        self.assertEqual(call_kwargs['params']['page'], 1)
        self.assertEqual(call_kwargs['params']['pageSize'], 100)

    @patch('cronitor.Monitor._req.get')
    def test_list_with_pagination(self, mocked_get):
        """Test Monitor.list() with specific page and pageSize"""
        monitor1 = {'key': 'job1', 'name': 'Job 1'}

        mock_resp = unittest.mock.Mock()
        mock_resp.status_code = 200
        mock_resp.json.return_value = {'monitors': [monitor1]}
        mocked_get.return_value = mock_resp

        monitors = cronitor.Monitor.list(page=3, pageSize=25)

        # Should return monitors
        self.assertEqual(len(monitors), 1)

        # Should have made 1 GET request with correct pagination params
        self.assertEqual(mocked_get.call_count, 1)
        call_kwargs = mocked_get.call_args[1]
        self.assertEqual(call_kwargs['params']['page'], 3)
        self.assertEqual(call_kwargs['params']['pageSize'], 25)

    @patch('cronitor.Monitor._req.get')
    def test_list_auto_paginate(self, mocked_get):
        """Test Monitor.list() with auto_paginate=True fetches all pages"""
        # First page has 2 monitors (equals pageSize, so more pages exist)
        page1 = {'monitors': [{'key': 'job1', 'name': 'Job 1'}, {'key': 'job2', 'name': 'Job 2'}]}
        # Second page has 1 monitor (less than pageSize, so stop)
        page2 = {'monitors': [{'key': 'job3', 'name': 'Job 3'}]}

        mock_resp1 = unittest.mock.Mock()
        mock_resp1.status_code = 200
        mock_resp1.json.return_value = page1

        mock_resp2 = unittest.mock.Mock()
        mock_resp2.status_code = 200
        mock_resp2.json.return_value = page2

        mocked_get.side_effect = [mock_resp1, mock_resp2]

        monitors = cronitor.Monitor.list(pageSize=2, auto_paginate=True)

        # Should return all 3 monitors from both pages
        self.assertEqual(len(monitors), 3)
        self.assertEqual(monitors[0].data.key, 'job1')
        self.assertEqual(monitors[1].data.key, 'job2')
        self.assertEqual(monitors[2].data.key, 'job3')

        # Should have made 2 GET requests (page 1 and page 2)
        self.assertEqual(mocked_get.call_count, 2)

        # Verify pagination params
        call1_kwargs = mocked_get.call_args_list[0][1]
        call2_kwargs = mocked_get.call_args_list[1][1]
        self.assertEqual(call1_kwargs['params']['page'], 1)
        self.assertEqual(call2_kwargs['params']['page'], 2)

    @patch('cronitor.Monitor._req.get')
    def test_list_empty_results(self, mocked_get):
        """Test Monitor.list() with no matching monitors"""
        mock_resp = unittest.mock.Mock()
        mock_resp.status_code = 200
        mock_resp.json.return_value = {'monitors': []}
        mocked_get.return_value = mock_resp

        monitors = cronitor.Monitor.list(type='nonexistent')

        # Should return empty list
        self.assertEqual(len(monitors), 0)
        self.assertEqual(monitors, [])

    @patch('cronitor.Monitor._req.get')
    def test_list_api_error(self, mocked_get):
        """Test Monitor.list() handles API errors"""
        mock_resp = unittest.mock.Mock()
        mock_resp.status_code = 500
        mock_resp.text = 'Internal Server Error'
        mocked_get.return_value = mock_resp

        with self.assertRaises(cronitor.APIError):
            cronitor.Monitor.list(type='job')

