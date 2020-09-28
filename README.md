# Cronitor API Client
[![Build Status](https://travis-ci.org/cronitorio/cronitor-python.svg?branch=master)](https://travis-ci.org/cronitorio/cronitor-python)

[Cronitor](https://cronitor.io/) is a monitoring cron jobs, pipelines, daemons, or any other system that can make or receive HTTP requests.

This Python library provides convenient access to the Cronitor API from applications written in the Python language. If you are unfamiliar with Cronitor, read our [Cron Monitoring](https://cronitor.io/docs/cron-job-monitoring) or [Heartbeat Monitoring](https://cronitor.io/docs/heartbeat-monitoring) guide to learn more.


## Installation

```
pip install cronitor
```


## Module Usage

### Monitor Any Python Function

The ping decorator will automatically provision a monitor with the provided name the first time it is run. It wraps the given function with `run` and `complete` calls on start and finish, and pings `fail` if an exception is thrown.

```python
from cronitor import ping

@ping("A Python Script")
def main():
  print("running...")
```
`Nota Bene`: The example above assumes a `CRONITOR_API_KEY` environment variable is present. You can also pass your API key as param to the ping decorator `api_key='cronitor-api-key'`. More on authentication below.

By default you will be alerted whenever an unhandled exception is raised, and you can attach additional rules to your monitors from the Cronitor dashboard.


A monitor object can also be imported and has methods that map to the endpoints of the [Ping API](https://cronitor.io/docs/ping-api).

```python
from cronitor import Monitor

monitor = Monitor('d3x01') # Monitor ID (aka code)
monitor.run() # job has started
monitor.complete() # job has finished
monitor.fail() # job has failed/failure event
monitor.tick() # event has occurred
monitor.ok() # manual reset to passing state
```

All ping methods accept the following optional keyword arguments:

- `message`: A message you would like associated with this ping event. This is displayed in the Cronitor UI as well as on alerts.
- `stamp`: A timestamp associated with the ping. When not present Cronitor creates the stamp at the time of system ingress.
- `duration`: Ignored on all pings except `complete`. Your own custom duration calculation. By default will construct one using `run` and `complete` timestamps.
- `series`: A unique identifier for a pair of run and complete pings. This is useful if your monitor is running on a distributed system and there are many instances pinging simultaneously as it allows cronitor to correctly match the pings.
- `env`: The environment this monitor is running in. Default value is `production`
- `host`: The server host name that this program is running on.
- `ping_api_key`: If you have enabled ping authentication for your account you can pass the api key on each call, or, better, instantiate the monitor object with one `Monitor(id='d3x01', ping_api_key='1234567890'). Even better, set `CRONITOR_PING_API_KEY` as an environment variable.


### Monitor CRUD

You can also perform all of the standard CRUD operations on a monitor. You will need a [monitor API key](https://cronitor.io/settings#integrations). The following map to the REST endpoints of the [Monitor API](http://cronitor.test/docs/monitor-api).

```python
from cronitor import Monitor

# In order to authenticate to cronitor you can set an ENV var
# CRONITOR_API_KEY='cronitor-api-key'
#
# or set your api_key as an attribute of the Monitor class
Monitor.api_key = 'cronitor-api-key'
#
# or pass it as a keyword param to get, create, update, or delete
Monitor.get('My Cron Monitor', api_key='cronitor-api-key')

# monitor look up
monitor = Monitor.get('My Cron Monitor') # by name
monitor = Monitor.get('d3x01') # by monitorId

# create monitor with the provided schedule if no monitor is found matching the name
monitor = Monitor.get_or_create(name="Daily Cron Job", schedule="0 0 * * *")

# create a monitor
monitor = Monitor.create(name="Daily Cron Job", schedule="0 0 * * *")

# access data attributes
print(monitor.data.name) # "Daily Cron Job"
print(monitor.data.status) # "Waiting for first ping"

# update a monitor
monitor.update(name="Sunday At Midnight Cron", schedule="0 0 * * SUN")

# delete a monitor
monitor.delete()
```

Monitors can be created and updated with following optional keyword arguments

- `schedule: str`: A convenient way to add a `not_on_schedule` rule (cron expression) to your monitor
- `rules: List[Dict]`: Rules to set beyond default 'failure' rule. e.g `[{'rule_type': 'ran_longer_than', 'value': 2, 'time_unit': 'hours'}]
- `notifications: Dict`: Where to send alerts. See examples below for list of options
- `tags: List`: A way to group similar monitors together. Use as desired
- `note: str`: A note displayed on the Cronitor UI and on alerts in the case of failure.
- `timezone: str`: The timezone this program is running in. Defaults to account setting, which defaults to `UTC`

```python

notifications =  {
    'emails': ['test@example.com'],
    'phones': ['+15555555555],
    'slack': [ 'slack-identifier'], # found https://cronitor.io/settings#integrations
    'pagerduty': ['pd-identifier'],
    'victorops': ['vc-identifier']
    'teams': ['teams-identifier']
    'webhooks': ['https://example.com/webhooks/incoming']
  }

rules = [
    {
      "rule_type": 'not_run_in',
      "duration": 5,
      "time_unit": 'minutes'
    }
  ]

tags = ['cron-jobs']

# Note: String
note = 'A human-friendly description of this monitor'

```


## Console Usage

```

>> cronitor -h

usage: cronitor [-h] [--authkey AUTHKEY] [--code CODE] [--msg MSG]
                (--run | --complete | --fail | --pause PAUSE)

Send status messages to Cronitor ping API.

optional arguments:
  -h, --help            show this help message and exit
  --authkey AUTHKEY, -a AUTHKEY
                        Auth Key from Account page
  --code CODE, -c CODE  Code for Monitor to take action upon
  --msg MSG, -m MSG     Optional message to send with ping/fail
  --run, -r             Call ping on given Code
  --complete, -C        Call complete on given Code
  --fail, -f            Call fail on given Code
  --pause PAUSE, -P PAUSE
                        Call pause on given Code
```


## Contributing

1. Fork it ( https://github.com/cronitorio/cronitor/fork )
2. Create your feature branch (`git checkout -b my-new-feature`)
3. Commit your changes (`git commit -am 'Add some feature'`)
4. Push to the branch (`git push origin my-new-feature`)
5. Create a new Pull Request
