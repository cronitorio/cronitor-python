import logging
import os
from datetime import datetime
from functools import wraps
import sys
import requests
import yaml
from yaml.loader import SafeLoader

from .monitor import Monitor, YAML

logging.basicConfig()
logger = logging.getLogger(__name__)
logger.setLevel(logging.INFO)

CONFIG_KEYS = (
    'api_key',
    'api_version',
    'environment',
)
MONITOR_TYPES = ('job', 'heartbeat', 'check')
YAML_KEYS = CONFIG_KEYS + tuple(map(lambda t: '{}s'.format(t), MONITOR_TYPES))

# configuration variables
api_key = os.getenv('CRONITOR_API_KEY', None)
api_version = os.getenv('CRONITOR_API_VERSION', None)
environment = os.getenv('CRONITOR_ENVIRONMENT', None)
config = os.getenv('CRONITOR_CONFIG', None)
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

def job(key, include_output=True):
    def wrapper(func):
        @wraps(func)
        def wrapped(*args, **kwargs):
            start = datetime.now().timestamp()

            monitor = Monitor(key)
            # use start as the series param to match run/fail/complete correctly
            monitor.ping(state=State.RUN, series=start)
            try:
                out = func(*args, **kwargs)
            except Exception as e:
                duration = datetime.now().timestamp() - start
                monitor.ping(state=State.FAIL, message=str(e), metrics={'duration': duration}, series=start)
                raise e

            duration = datetime.now().timestamp() - start
            message = str(out) if include_output else None
            monitor.ping(state=State.COMPLETE, message=message, metrics={'duration': duration}, series=start)
            return out

        return wrapped
    return wrapper

def generate_config():
    config = this.config or './cronitor.yaml'
    with open(config, 'w') as conf:
        conf.writelines(Monitor.as_yaml())

def validate_config():
    return apply_config(rollback=True)

def apply_config(rollback=False):
    if not this.config:
        raise ConfigValidationError("Must set a path to config file e.g. cronitor.config = './cronitor.yaml'")

    config = read_config(output=True)
    try:
        monitors = Monitor.put(monitors=config, rollback=rollback, format=YAML)
        job_count = len(monitors['jobs']) if 'jobs' in monitors else 0
        check_count = len(monitors['checks']) if 'checks' in monitors else 0
        heartbeat_count = len(monitors['heartbeats']) if 'heartbeats' in monitors else 0
        total_count = sum([job_count, check_count, heartbeat_count])
        logger.info('{} monitor{} {}'.format(total_count, 's' if total_count != 1 else '', 'validated.' if rollback else 'synced.',))
    except (yaml.YAMLError, ConfigValidationError, APIValidationError, APIError, AuthenticationError) as e:
        logger.error(e)

def read_config(path=None, output=False):
    this.config = path or this.config
    if not this.config:
        raise ConfigValidationError("Must include a path to config file e.g. cronitor.read_config('./cronitor.yaml')")

    with open(this.config, 'r') as conf:
        data = yaml.load(conf, Loader=SafeLoader)
        if output:
            return data
