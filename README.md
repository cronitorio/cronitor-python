# Cronitor

[Cronitor](https://cronitor.io/) is a service for heartbeat-style monitoring of just about anything that can send an HTTP request.

This library provides a simple abstraction for the creation and pinging of a Cronitor monitor. For a better understanding of the API this module talks to, please see [How Cronitor Works](https://cronitor.io/help/how-cronitor-works).

## Installation


```
pip install cronitor
```



## Usage

### Creating a Monitor

A Cronitor monitor (hereafter referred to only as a monitor for brevity) is created if it does not already exist and response object will be returned.

```python
from cronitor.monitor import Monitor

# Notification object
notifications =  {
    "emails": ['test@example.com'],
    "slack": [],
    "pagerduty": [],
    "phones": [],
    "webhooks": []
  }

# Rules object
rules = [
    {
      "rule_type": 'not_run_in',
      "duration": 5,
      "time_unit": 'seconds'
    }
  ]
  
# Tags
tags = ['cron-jobs']
    
# Notes 
note = 'A human-friendly description of this monitor'

my_monitor = Monitor(
                    api_key='<api_key> or set CRONITOR_API_KEY in env',
                    time_zone='<timezone> : default is UTC'
                    )


# Create monitor
my_monitor.create(name="unique_monitor_name",
                    note=note,
                    notifications=notifications, 
                    rules=rules, 
                    tags=tags
                    )

# Update Monitor
my_monitor.update(name="unique_monitor_name",
                    note=note,
                    notifications=notifications,
                    rules=rules,
                    tags=tags,
                    code='monitor_code'
                     )

# Delete 
my_monitor.delete("monitor_code")

# Get Monitor 
my_monitor.get("monitor_code")

# Pause
my_monitor.pause("monitor_code", 10) # 10 is total hours monitor should be paused

```

### Pinging a Monitor

Once you’ve created a monitor and got monitor code, you can continue to use that code to ping the monitor about your task status: `run`, `complete`, or `failed`.

```python
my_monitor.run('<monitor_code>')
my_monitor.complete('<monitor_code>')
my_monitor.failed('<monitor_code>')
```

## Contributing

1. Fork it ( https://github.com/vylabs/cronitor/fork )
2. Create your feature branch (`git checkout -b my-new-feature`)
3. Commit your changes (`git commit -am 'Add some feature'`)
4. Push to the branch (`git push origin my-new-feature`)
5. Create a new Pull Request
