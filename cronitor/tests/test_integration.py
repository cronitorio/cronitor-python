"""
Integration tests that make real API calls to Cronitor.

These tests are skipped by default unless CRONITOR_TEST_API_KEY environment
variable is set. They test against the real Cronitor API to verify behavior.

Usage:
    export CRONITOR_TEST_API_KEY=your_api_key_here
    python -m pytest cronitor/tests/test_integration.py -v
    # or
    python -m unittest cronitor.tests.test_integration -v
"""

import os
import unittest
import cronitor


# Check if integration tests should run
INTEGRATION_API_KEY = os.getenv('CRONITOR_TEST_API_KEY')
SKIP_INTEGRATION = not INTEGRATION_API_KEY
SKIP_REASON = "Set CRONITOR_TEST_API_KEY environment variable to run integration tests"


@unittest.skipIf(SKIP_INTEGRATION, SKIP_REASON)
class MonitorListIntegrationTests(unittest.TestCase):
    """Integration tests for Monitor.list() against real API"""

    @classmethod
    def setUpClass(cls):
        """Set up API key for all tests"""
        cronitor.api_key = INTEGRATION_API_KEY

    def test_list_all_monitors(self):
        """Test listing all monitors (first page)"""
        monitors = cronitor.Monitor.list()

        # Should return a list (may be empty for new accounts)
        self.assertIsInstance(monitors, list)

        # If there are monitors, verify structure
        if len(monitors) > 0:
            monitor = monitors[0]
            self.assertIsInstance(monitor, cronitor.Monitor)
            self.assertIsNotNone(monitor.data.key)
            self.assertIsNotNone(monitor.data.name)
            print(f"\n✓ Found {len(monitors)} monitors on first page (default pageSize=100)")
            print(f"  First monitor: {monitor.data.name} ({monitor.data.key})")

    def test_list_all_monitors_auto_paginate(self):
        """Test listing all monitors with auto_paginate"""
        monitors_all = cronitor.Monitor.list(auto_paginate=True)

        self.assertIsInstance(monitors_all, list)

        # Check if there were multiple pages
        monitors_page1 = cronitor.Monitor.list(pageSize=100)
        if len(monitors_all) > 100:
            print(f"\n✓ Auto-paginate fetched all {len(monitors_all)} monitors across multiple pages")
            print(f"  First page had {len(monitors_page1)}, total is {len(monitors_all)}")
        else:
            print(f"\n✓ Auto-paginate fetched {len(monitors_all)} monitors (all fit in one page)")

    def test_list_with_pagination(self):
        """Test listing monitors with specific page size"""
        monitors = cronitor.Monitor.list(pageSize=5)

        self.assertIsInstance(monitors, list)
        # Should return at most 5 monitors
        self.assertLessEqual(len(monitors), 5)
        print(f"\n✓ Pagination works, got {len(monitors)} monitors (max 5)")

    def test_list_with_filter(self):
        """Test listing monitors with type filter"""
        monitors = cronitor.Monitor.list(type='job')

        self.assertIsInstance(monitors, list)

        # Verify all returned monitors are jobs
        for monitor in monitors:
            self.assertEqual(monitor.data.type, 'job')

        print(f"\n✓ Filter works, got {len(monitors)} job monitors")

    def test_list_with_search(self):
        """Test listing monitors with search parameter"""
        monitors = cronitor.Monitor.list(search='test job')

        self.assertIsInstance(monitors, list)

        # Should return monitors matching search term
        if len(monitors) > 0:
            print(f"\n✓ Search works, found {len(monitors)} monitors matching 'test job'")
            for monitor in monitors[:3]:  # Show first 3
                print(f"  - {monitor.data.name} ({monitor.data.key})")
        else:
            print(f"\n✓ Search works, found 0 monitors matching 'test job'")

    def test_list_specific_keys(self):
        """Test listing specific monitors by key"""
        # First get some monitors to test with
        all_monitors = cronitor.Monitor.list(pageSize=2)

        if len(all_monitors) == 0:
            self.skipTest("No monitors found in account")

        # Get keys to fetch
        keys_to_fetch = [m.data.key for m in all_monitors[:min(2, len(all_monitors))]]

        # Fetch them specifically
        monitors = cronitor.Monitor.list(keys_to_fetch)

        self.assertEqual(len(monitors), len(keys_to_fetch))
        returned_keys = [m.data.key for m in monitors]
        self.assertEqual(set(returned_keys), set(keys_to_fetch))

        print(f"\n✓ Fetched specific monitors: {', '.join(keys_to_fetch)}")

    def test_monitor_data_structure(self):
        """Test that monitor data structure is correct"""
        monitors = cronitor.Monitor.list(pageSize=1)

        if len(monitors) == 0:
            self.skipTest("No monitors found in account")

        monitor = monitors[0]

        # Test basic fields exist
        self.assertIsNotNone(monitor.data.key)
        self.assertIsNotNone(monitor.data.name)
        self.assertIsNotNone(monitor.data.type)

        # Test nested attribute access works
        self.assertIsNotNone(monitor.data.attributes)
        self.assertIsNotNone(monitor.data.attributes.code)

        # Test pretty printing works
        json_str = str(monitor.data)
        self.assertIn(monitor.data.key, json_str)
        self.assertIn('\n', json_str)  # Pretty formatted

        print(f"\n✓ Monitor data structure correct")
        print(f"  Key: {monitor.data.key}")
        print(f"  Name: {monitor.data.name}")
        print(f"  Type: {monitor.data.type}")


if __name__ == '__main__':
    if SKIP_INTEGRATION:
        print(f"\n⚠️  {SKIP_REASON}\n")
        print("Example:")
        print("  export CRONITOR_TEST_API_KEY=your_api_key_here")
        print("  python -m unittest cronitor.tests.test_integration -v\n")
    else:
        print(f"\n🚀 Running integration tests against Cronitor API...\n")
        unittest.main()
