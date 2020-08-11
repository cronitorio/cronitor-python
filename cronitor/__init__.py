import os
from .monitor import Monitor, MonitorNotFound, MonitorNotCreated, MonitorNotUpdated

api_key = os.getenv('CRONITOR_API_KEY', None)
ping_api_key = os.getenv('CRONITOR_PING_API_KEY', None)
environment = os.getenv('CRONITOR_ENVIRONMENT', 'production')

def ping(name, schedule=None, rules=[], notifications={}, timezone=None):
    def wrapper(func):
        def wrapped(*args, **kwargs):
            monitor = Monitor.get_or_create(name=name, schedule=schedule, rules=rules, notifications=notifications, timezone=timezone)
            monitor.run()
            try:
                out = func(*args, **kwargs)
            except Exception as e:
                monitor.fail(str(e))
                raise e
            monitor.complete()
            return out
        return wrapped
    return wrapper

