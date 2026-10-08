"""Small exec wrapper: avoids unsafe preexec_fn in the threaded host."""
import json
import os
import resource
import sys

spec = json.loads(open(sys.argv[1]).read())
limits = spec['limits']
os.sched_setaffinity(0, set(limits['cpus']))
resource.setrlimit(resource.RLIMIT_CORE, (0, 0))
for kind, key in ((resource.RLIMIT_AS, 'address_space_bytes'), (resource.RLIMIT_FSIZE, 'file_size_bytes')):
    value = limits[key]
    resource.setrlimit(kind, (value, value))
if limits.get('cpu_seconds') is not None:
    value = limits['cpu_seconds']
    resource.setrlimit(resource.RLIMIT_CPU, (value, value + 1))
os.chdir(spec['cwd'])
os.execvpe(spec['command'][0], spec['command'], spec['environment'])
