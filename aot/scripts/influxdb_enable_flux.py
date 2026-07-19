"""Enable Flux query language in the InfluxDB 1.x config and restart the service."""
import subprocess
from os import fdopen, remove
from shutil import move, copymode
from tempfile import mkstemp

influx_file = "/etc/influxdb/influxdb.conf"
changed = False

fd, abs_path = mkstemp()
with fdopen(fd, 'w') as new_file:
    with open(influx_file, 'r') as old_file:
        for line in old_file:
            if 'flux-enabled' in line and line != 'flux-enabled = true\n':
                changed = True
                new_file.write('flux-enabled = true')
            else:
                new_file.write(line)

copymode(influx_file, abs_path)
remove(influx_file)
move(abs_path, influx_file)

if changed:
    print("Enabling Flux and restarting influxdb.")
    subprocess.Popen('service influxdb restart', shell=True)
else:
    print("Flux is already enabled. No changes necessary.")
