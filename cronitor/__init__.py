import os
from functools import wraps
from datetime import datetime
from random import random
from .monitor import Monitor, MonitorNotFound, MonitorNotCreated, MonitorNotUpdated
import logging

logging.basicConfig()
logger = logging.getLogger(__name__)

def ping(name, schedule=None, rules=[], notifications={}, timezone=None, api_key=None, type=None):
    def wrapper(func):
        @wraps(func)
        def wrapped(*args, **kwargs):
            create_args = {
                'name':name,
                'schedule':schedule,
                'rules':rules,
                'notifications':notifications,
                'timezone':timezone,}

            if api_key:
                create_args['api_key'] = api_key

            if type:
                create_args['type'] = type

            try:
                monitor = Monitor.get_or_create(**create_args)
            except Exception as e:
                logger.debug(str(e))
                return func(*args, **kwargs)

            start = datetime.now().timestamp()
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

