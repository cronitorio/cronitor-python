import yaml
import cronitor
import unittest
from unittest.mock import call, patch, ANY

import cronitor

FAKE_API_KEY = 'cb54ac4fd16142469f2d84fc1bbebd84XXXDEADXXX'
YAML_PATH = './cronitor/tests/cronitor.yaml'

cronitor.api_key = FAKE_API_KEY

with open(YAML_PATH, 'r') as conf:
    YAML_DATA = yaml.safe_load(conf)

class CronitorTests(unittest.TestCase):

    def setUp(self):
        return super().setUp()

    def test_read_config(self):
        data = cronitor.read_config(YAML_PATH, output=True)
        self.assertIn('jobs', data)
        self.assertIn('checks', data)
        self.assertIn('heartbeats', data)

    @patch('cronitor.Monitor.put', return_value=YAML_DATA)
    def test_validate_config(self, mock):
            cronitor.config = YAML_PATH
            cronitor.validate_config()
            mock.assert_called_once_with(monitors=YAML_DATA, rollback=True, format='yaml')

    @patch('cronitor.Monitor.put')
    def test_apply_config(self, mock):
        cronitor.config = YAML_PATH
        cronitor.apply_config()
        mock.assert_called_once_with(monitors=YAML_DATA, rollback=False, format='yaml')
