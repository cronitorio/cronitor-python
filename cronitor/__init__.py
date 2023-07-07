import logging
import os
from datetime import datetime
from functools import wraps
import sys
import requests
import yaml
from yaml.loader import SafeLoader

from .monitor import Monitor, YAML

logger = logging.getLogger(__name__)
logger.setLevel(logging.INFO)

# configuration variables
api_key = os.getenv('CRONITOR_API_KEY', None)
api_version = os.getenv('CRONITOR_API_VERSION', None)
environment = os.getenv('CRONITOR_ENVIRONMENT', None)
config = os.getenv('CRONITOR_CONFIG', None)
timeout = os.getenv('CRONITOR_TIMEOUT', None)
if timeout is not None:
    timeout = int(timeout)
    cronitor_timeout = timeout
else:
    cronitor_timeout = None

celerybeat_only = False

# this is a pointer to the module object instance itself.
this = sys.modules[__name__]
if this.config:
    this.read_config() # set config vars contained within

class MonitorNotFound(Exception):
    pass

class ConfigValidationError(Exception):
    pass

class APIValidationError(Exception):
    pass

class AuthenticationError(Exception):
    pass

class APIError(Exception):
    pass

class State(object):
    OK = 'ok'
    RUN = 'run'
    COMPLETE = 'complete'
    FAIL = 'fail'

# include_output is deprecated in favor of log_output and can be removed in 5.0 release
def job(key, env=None, log_output=True, include_output=True):
    def wrapper(func):
        @wraps(func)
        def wrapped(*args, **kwargs):
            start = datetime.now().timestamp()

            monitor = Monitor(key, env=env)
            # use start as the series param to match run/fail/complete correctly
            monitor.ping(state=State.RUN, series=start)
            try:
                out = func(*args, **kwargs)
            except Exception as e:
                duration = datetime.now().timestamp() - start
                monitor.ping(state=State.FAIL, message=str(e), metrics={'duration': duration}, series=start)
                raise e

            duration = datetime.now().timestamp() - start
            message = str(out) if all([log_output, include_output]) else None
            monitor.ping(state=State.COMPLETE, message=message, metrics={'duration': duration}, series=start)
            return out

        return wrapped
    return wrapper

def generate_config(timeout=10):
    timeout = cronitor_timeout or timeout
    config = this.config or './cronitor.yaml'
    with open(config, 'w') as conf:
        conf.writelines(Monitor.as_yaml(timeout=timeout))

def validate_config(timeout=10):
    timeout = cronitor_timeout or timeout
    return apply_config(rollback=True, timeout=timeout)

def apply_config(rollback=False, timeout=10):
    timeout = cronitor_timeout or timeout
    if not this.config:
        raise ConfigValidationError("Must set a path to config file e.g. cronitor.config = './cronitor.yaml'")

    config = read_config(output=True)
    try:
        monitors = Monitor.put(monitors=config, timeout=timeout, rollback=rollback, format=YAML)
        job_count = len(monitors.get('jobs', []))
        check_count = len(monitors.get('checks', []))
        heartbeat_count = len(monitors.get('heartbeats', []))
        total_count = sum([job_count, check_count, heartbeat_count])
        logger.info('{} monitor{} {}'.format(total_count, 's' if total_count != 1 else '', 'validated.' if rollback else 'synced.',))
        return True
    except (yaml.YAMLError, ConfigValidationError, APIValidationError, APIError, AuthenticationError) as e:
        logger.error(e)
        return False

def read_config(path=None, output=False):
    this.config = path or this.config
    if not this.config:
        raise ConfigValidationError("Must include a path to config file e.g. cronitor.read_config('./cronitor.yaml')")

    with open(this.config, 'r') as conf:
        data = yaml.load(conf, Loader=SafeLoader)
        if output:
            return data
