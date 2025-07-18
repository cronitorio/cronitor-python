# Cronitor Python Library
![Test](https://github.com/cronitorio/cronitor-python/workflows/Test/badge.svg)

[Cronitor](https://cronitor.io/) provides end-to-end monitoring for background jobs, websites, APIs, and anything else that can send or receive an HTTP request. This library provides convenient access to the Cronitor API from applications written in Python. See our [API docs](https://cronitor.io/docs/api) for detailed references on configuring monitors and sending telemetry pings.

In this guide:

- [Installation](#Installation)
- [Monitoring Background Jobs](#monitoring-background-jobs)
- [Sending Telemetry Events](#sending-telemetry-events)
- [Configuring Monitors](#configuring-monitors)
- [Package Configuration & Env Vars](#package-configuration)
- [Command Line Usage](#command-line-usage)

## Installation

```
pip install cronitor
```

## Monitoring Background Jobs

#### Celery Auto-Discover
`cronitor-python` can automatically discover all of your declared Celery tasks, including your Celerybeat scheduled tasks,
creating monitors for them and sending pings when tasks run, succeed, or fail. Your API keys can be found [here](https://cronitor.io/settings/api).

Requires Celery 4.0 or higher. Celery auto-discover utilizes the Celery [message protocol version 2](https://docs.celeryproject.org/en/stable/internals/protocol.html#version-2).

**Some important notes on support**

* Tasks on [solar schedules](https://docs.celeryproject.org/en/stable/userguide/periodic-tasks.html#solar-schedules) are not supported and will be ignored.
* [`django-celery-beat`](https://docs.celeryproject.org/en/stable/userguide/periodic-tasks.html#using-custom-scheduler-classes) is not yet supported, but is in the works.
* If you use the default `PersistentScheduler`, the celerybeat integration overrides the celerybeat local task run database (as referenced [here](https://docs.celeryproject.org/en/stable/userguide/periodic-tasks.html#starting-the-scheduler) in the docs), named `celerybeat-schedule` by default. If you currently specify a custom location for this database, this integration will override it. **Very** few people require setting custom locations for this database. If you fall into this group and want to use `cronitor-python`'s celerybeat integration, please reach out to Cronitor support.


```python
import cronitor.celery
from celery import Celery

app = Celery()
app.conf.beat_schedule = {
    'run-me-every-minute': {
        'task': 'tasks.every_minute_celery_task',
        'schedule': 60
    }
}

# Discover all of your celery tasks and automatically add monitoring.
cronitor.celery.initialize(app, api_key="apiKey123")

@app.task
def every_minute_celery_task():
    print("running a background job with celery...")

@app.task
def non_scheduled_celery_task():
    print("Even though I'm not on a schedule, I'll still be monitored!")
```

If you want only to monitor Celerybeat periodic tasks, and not tasks triggered any other way, you can set `celereybeat_only=True` when initializing:
```python
app = Celery()
cronitor.celery.initialize(app, api_key="apiKey123", celerybeat_only=True)
```

#### Manual Integration

The `@cronitor.job` is a lightweight way to monitor any background task regardless of how it is executed. It will send telemetry events before calling your function and after it exits. If your function raises an exception a `fail` event will be sent (and the exception re-raised).

```python
import cronitor

# your api keys can found here - https://cronitor.io/settings/api
cronitor.api_key = 'apiKey123'

# Apply the cronitor decorator to monitor any function.
# If no monitor matches the provided key, one will be created automatically.
@cronitor.job('send-invoices')
def send_invoices_task(*args, **kwargs):
    ...
```

#### You can provide monitor attributes that will be synced when your app starts

To sync attributes, provide an API key with monitor:write privileges.

```python
import cronitor

# Copy your SDK Integration key from https://cronitor.io/app/settings/api
cronitor.api_key = 'apiKey123'

@cronitor.job('send-invoices', attributes={'schedule': '0 8 * * *', 'notify': ['devops-alerts']})
def send_invoices_task(*args, **kwargs):
    ...
```

## Sending Telemetry Events

If you want to send a heartbeat events, or want finer control over when/how [telemetry events](https://cronitor.io/docs/telemetry-api) are sent for your jobs, you can create a monitor instance and call the `.ping` method.

```python
import cronitor

# your api keys can found here - https://cronitor.io/settings/api
cronitor.api_key = 'apiKey123'

# optionally, set an environment
cronitor.environment = 'staging'

monitor = cronitor.Monitor('heartbeat-monitor')
monitor.ping() # send a heartbeat event

# optional params can be passed as keyword arguements.
# for a complete list see https://cronitor.io/docs/telemetry-api#parameters
monitor.ping(
    state='run|complete|fail|ok', # run|complete|fail used to measure lifecycle of a job, ok used for manual reset only.
    message='', # message that will be displayed in alerts as well as monitor activity panel on your dashboard.
    metrics={
        'duration': 100, # how long the job ran (complete|fail only). cronitor will calculate this when not provided
        'count': 4500, # if your job is processing a number of items you can report a count
        'error_count': 10 # the number of errors that occurred while this job was running
    }
)
```

## Configuring Monitors

### YAML Configuration File

You can configure all of your monitors using a single YAML file. This can be version controlled and synced to Cronitor as part of
a deployment or build process. For details on all of the attributes that can be set, see the [Monitor API](https://cronitor.io/docs/monitor-api) documentation.

```python
import cronitor

# your api keys can found here - https://cronitor.io/settings/api
cronitor.api_key = 'apiKey123'

cronitor.read_config('./cronitor.yaml') # parse the yaml file of monitors

cronitor.validate_config() # send monitors to Cronitor for configuration validation

cronitor.apply_config() # sync the monitors from the config file to Cronitor

cronitor.generate_config() # generate a new config file from the Cronitor API
```

The timeout value for validate_config, apply_config and generate_config is 10 seconds by default. The value can be rewritten by setting the environment variable `CRONITOR_TIMEOUT`. It can also be rewritten by assigning a value to cronitor.timeout.

```python
import cronitor

cronitor.timeout = 30
cronitor.apply_config()
```

The `cronitor.yaml` file includes three top level keys `jobs`, `checks`, `heartbeats`. You can configure monitors under each key by defining [monitors](https://cronitor.io/docs/monitor-api#attributes).

```yaml
jobs:
    nightly-database-backup:
        schedule: 0 0 * * *
        notify:
            - devops-alert-pagerduty
        assertions:
            - metric.duration < 5 minutes

    send-welcome-email:
        schedule: every 10 minutes
        assertions:
            - metric.count > 0
            - metric.duration < 30 seconds

checks:
    cronitor-homepage:
        request:
            url: https://cronitor.io
            regions:
                - us-east-1
                - eu-central-1
                - ap-northeast-1
        assertions:
            - response.code = 200
            - response.time < 2s

    cronitor-ping-api:
        request:
            url: https://cronitor.link/ping
        assertions:
            - response.body contains ok
            - response.time < .25s

heartbeats:
    production-deploy:
        notify:
            alerts: ['deploys-slack']
            events: true # send alert when the event occurs

```
#### Async Uploads
If you are working with large YAML files (300+ monitors), you may hit timeouts when trying to sync monitors in a single http request. This workload to be processed asynchronously by adding the key `async: true` to the config file. The request will immediately return a `batch_key`. If a `webhook_url` parameter is included, Cronitor will POST to that URL with the results of the background processing and will include the `batch_key` matching the one returned in the initial response.

### Monitor.put

You can also create and update monitors by calling `Monitor.put`. For details on all of the attributes that can be set see the Monitor API [documentation](https://cronitor.io/docs/monitor-api#attributes).

```python
import cronitor

monitors = cronitor.Monitor.put([
  {
    'type': 'job',
    'key': 'send-customer-invoices',
    'schedule': '0 0 * * *',
    'assertions': [
        'metric.duration < 5 min'
    ],
    'notify': ['devops-alerts-slack']
  },
  {
    'type': 'check',
    'key': 'Cronitor Homepage',
    'schedule': 'every 45 seconds',
    'request': {
        'url': 'https://cronitor.io'
    },
    'assertions': [
        'response.code = 200',
        'response.time < 600ms',
    ]
  }
])
```

### Pausing, Reseting, and Deleting

```python
import cronitor

monitor = cronitor.Monitor('heartbeat-monitor');

monitor.pause(24) # pause alerting for 24 hours
monitor.unpause() # alias for .pause(0)
monitor.ok() # manually reset to a passing state alias for monitor.ping({state: ok})
monitor.delete() # destroy the monitor
```

## Package Configuration

The package needs to be configured with your account's `API key`, which is available on the [account settings](https://cronitor.io/settings) page. You can also optionally specify an `api_version` and an `environment`. If not provided, your account default is used. These can also be supplied using the environment variables `CRONITOR_API_KEY`, `CRONITOR_API_VERSION`, `CRONITOR_ENVIRONMENT`.

```python
import cronitor

# your api keys can found here - https://cronitor.io/settings
cronitor.api_key = 'apiKey123'
cronitor.api_version = '2020-10-01'
cronitor.environment = 'cluster_1_prod'
```

## Command Line Usage

```bash
>> python -m cronitor -h

usage: cronitor [-h] [--apikey APIKEY] [--key KEY] [--msg MSG]
                (--run | --complete | --fail | --ok | --pause PAUSE)

Send status messages to Cronitor ping API.

optional arguments:
  -h, --help            show this help message and exit
  --authkey AUTHKEY, -a AUTHKEY
                        Auth Key from Account page
  --key KEY, -k KEY     Unique key for the monitor to take ping
  --msg MSG, -m MSG     Optional message to send with ping/fail
  --tick, -t            Call ping on given monitor
  --run, -r             Call ping with state=run on given monitor
  --complete, -C        Call ping with state=complete on given monitor
  --fail, -f            Call ping with state=fail on given monitor
  --pause PAUSE, -P PAUSE
                        Call pause on given monitor
```


## Contributing

Pull requests and features are happily considered! By participating in this project you agree to abide by the [Code of Conduct](http://contributor-covenant.org/version/2/0).

### To contribute

Fork, then clone the repo:

    git clone git@github.com:your-username/cronitor-python.git

Set up your machine:

    pip install -r requirements

Make sure the tests pass:

    pytest

Make your change. Add tests for your change. Make the tests pass:

    pytest


Push to your fork and [submit a pull request]( https://github.com/cronitorio/cronitor-python/compare/)
