import os
from datetime import datetime
from functools import wraps
from random import random
from .monitor import Monitor, MonitorNotFound, MonitorNotCreated, MonitorNotUpdated, InvalidPingUrl, InvalidMonitorParams
import logging

logging.basicConfig()
logger = logging.getLogger(__name__)

def ping(key, id=None, schedule=None, api_key=None):
    def wrapper(func):
        @wraps(func)
        def wrapped(*args, **kwargs):
            start = datetime.now().timestamp()

            try:
                monitor = Monitor(id, key=key)
            except Exception:
                return func(*args, **kwargs)

            # use start as the series param to match run/completes correctly
            monitor.run(stamp=start, series=start)
            try:
                out = func(*args, **kwargs)
            except Exception as e:
                monitor.fail(message=str(e))
                raise e

            end = datetime.now().timestamp()
            duration = end - start

            monitor.complete(stamp=end, duration=duration, series=start)
            return out

        return wrapped
    return wrapper

