# coding=utf-8
from blinker import signal

# Signal emitted when a trigger is fired
# Arguments: trigger_id (str), name (str), next_run (float, optional)
trigger_fired = signal('trigger_fired')

# Signal emitted when a conditional is fired
# Arguments: conditional_id (str), name (str), next_run (float, optional)
conditional_fired = signal('conditional_fired')
