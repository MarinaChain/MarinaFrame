"""Configured SSH transport for one resource-limited official solver container.

No credentials or host defaults are stored here. Remote work is confined to the
lane root; control operations target only the named container created by a run.
"""
from dataclasses import dataclass
import json
from pathlib import Path
import re
import shlex
import subprocess
import time


def sustained_high_load(samples):
    """Two high observations at least ten minutes apart; no intervening low."""
    since = None
    for timestamp, load in samples:
        if load <= 7:
            since = None
        elif since is None:
            since = timestamp
        elif timestamp - since >= 600:
            return True
    return False


def _run_name(name):
    if not re.fullmatch(r'[a-z0-9][a-z0-9-]{0,63}', name):
        raise ValueError('Invalid lane run name')
    return name


@dataclass(frozen=True)
class RemoteHost:
    host: str
    image: str
    root: str = '~/marinaframe-cfd'

    def __post_init__(self):
        if not re.fullmatch(r'[A-Za-z0-9][A-Za-z0-9_.@-]*', self.host):
            raise ValueError('Invalid SSH destination')
        if self.root != '~/marinaframe-cfd':
            raise ValueError('Remote work must remain in ~/marinaframe-cfd')
        if not re.fullmatch(r'opencfd/openfoam-default:(?:[0-9]{4})(?:@sha256:[0-9a-f]{64})?', self.image):
            raise ValueError('Use a versioned official OpenCFD image')

    def execute(self, script):
        result = subprocess.run(['ssh', '-o', 'BatchMode=yes', self.host, 'bash', '-s'],
                                input=script, text=True, capture_output=True, check=True)
        return result.stdout

    def launch_script(self, name, command):
        name = _run_name(name)
        allowed = {'blockMesh', 'snappyHexMesh', 'checkMesh', 'surfaceCheck', 'interFoam',
                   'simpleFoam', 'decomposePar', 'reconstructPar', 'foamDictionary'}
        if not command or command[0] not in allowed or any(not isinstance(s, str) for s in command):
            raise ValueError('Unsupported solver argument list')
        for argument in command[1:]:
            if argument.startswith('/') or '..' in argument.split('/') or not re.fullmatch(r'[A-Za-z0-9_./+-]+', argument):
                raise ValueError('Solver arguments must be confined relative paths or simple options')
        version = self.image.split(':')[1].split('@')[0]
        solver = f'source /usr/lib/openfoam/openfoam{version}/etc/bashrc; exec nice -n 10 {shlex.join(command)}'
        # Keep the flock descriptor in the monitor for the entire container life,
        # including a safety pause. The monitor survives an SSH disconnect.
        return f'''#!/bin/bash
set -eu
cd "$HOME/marinaframe-cfd"
exec 9>.solver.lock
flock -n 9 || {{ printf 'another lane solver is active\\n'; exit 1; }}
active=$(docker ps --filter 'name=^/mf-cfd-' --format '{{{{.Names}}}}')
[ -z "$active" ] || {{ printf 'an mf-cfd container is active\\n'; exit 1; }}
cd {shlex.quote(name)}
[ ! -e run-receipt.json ] && [ ! -e container-id ]
used=$(du -sb "$HOME/marinaframe-cfd" | cut -f1)
image_bytes=$(docker image inspect --format '{{{{.Size}}}}' {shlex.quote(self.image)})
planned_peak_bytes=8000000000
[ $((used + image_bytes + planned_peak_bytes)) -lt 40000000000 ]
free=$(df -B1 --output=avail . | awk 'NR==2 {{print $1}}')
[ $((free - planned_peak_bytes)) -ge 10000000000 ]
uptime >> load.log
started=$(date +%s)
high_since=0
if awk 'BEGIN {{exit !('"$(cut -d' ' -f1 /proc/loadavg)"' > 7)}}'; then high_since=$started; fi
# Keep fd 9 only in this monitor, not in Docker or container descendants.
# Each docker command explicitly closes the inherited descriptor.
container_started=0
monitor_failure() {{
 if [ "$container_started" = 1 ]; then docker pause mf-cfd-{name} >> monitor.log 2>&1 || true; fi
 printf 'paused or launch failed: monitor failure; inspect lane logs\\n' > safety-pause.txt
}}
trap monitor_failure ERR HUP INT TERM
(exec 9>&-; docker run -d --name mf-cfd-{name} --cpus 5 --memory 12g \\
 --network none --cap-drop ALL --security-opt no-new-privileges \\
 --user "$(id -u):$(id -g)" --workdir /case \\
 --mount "type=bind,src=$PWD,dst=/case" \\
 --entrypoint /bin/bash {shlex.quote(self.image)} -lc {shlex.quote(solver)}) > container-id
container_started=1
next_check=$((started+600))
paused=0
while :; do
 state=$(docker inspect --format '{{{{.State.Status}}}}' mf-cfd-{name})
 now=$(date +%s)
 if [ "$state" = exited ] || [ "$state" = dead ]; then break; fi
 if [ "$now" -ge "$next_check" ]; then
  uptime >> load.log
  load=$(cut -d' ' -f1 /proc/loadavg)
  high=$(awk -v load="$load" 'BEGIN {{print (load > 7)}}')
  if [ "$high" = 1 ]; then
   if [ "$high_since" = 0 ]; then high_since=$now; fi
  else high_since=0; fi
  used=$(du -sb "$HOME/marinaframe-cfd" | cut -f1)
  if [ "$paused" = 0 ] && {{ [ $((used + image_bytes)) -ge 40000000000 ] || {{ [ "$high_since" != 0 ] && [ $((now-high_since)) -ge 600 ]; }}; }}; then
   docker pause mf-cfd-{name} >> monitor.log
   printf 'paused: resource safety; manual decision required\\n' > safety-pause.txt
   paused=1
  fi
  next_check=$((now+600))
 fi
 sleep 5
done
docker logs mf-cfd-{name} > solver.log 2>&1
code=$(docker inspect --format '{{{{.State.ExitCode}}}}' mf-cfd-{name})
ended=$(date +%s)
state=failed
if [ "$code" = 0 ]; then state=completed; fi
if [ -f cancel-requested ]; then state=cancelled; fi
printf '{{"state":"%s","exit_code":%s,"wall_seconds":%s,"allocated_cores":5,"engineering_approved":false}}\\n' "$state" "$code" "$((ended-started))" > run-receipt.json
'''


class RemoteSolverRun:
    def __init__(self, host: RemoteHost, name: str, case: Path):
        self.host, self.name, self.case = host, _run_name(name), Path(case)

    @classmethod
    def start(cls, command, case, *, host: RemoteHost, name: str):
        self = cls(host, name, case)
        # Upload generated case files only. Never recursively send a repository.
        allowed = {'0', 'constant', 'system', 'case-input.json'}
        files = list(self.case.iterdir())
        if not files or any(p.name not in allowed or p.is_symlink() for p in files):
            raise ValueError('Remote upload accepts only generated case files')
        if any(p.is_symlink() for p in self.case.rglob('*')):
            raise ValueError('Remote case contains symlinks')
        script = host.launch_script(name, command)
        host.execute(f'set -eu; mkdir -p "$HOME/marinaframe-cfd"; mkdir "$HOME/marinaframe-cfd/{name}"')
        subprocess.run(['scp', '-r', *map(str, files), f'{host.host}:marinaframe-cfd/{name}/'], check=True)
        # Write the supervisor through SSH stdin, never interpolate caller code.
        host.execute(f"set -eu; cd \"$HOME/marinaframe-cfd/{name}\"; cat > monitor.sh <<'MF_CFD_MONITOR'\n{script}\nMF_CFD_MONITOR\nnohup bash monitor.sh > monitor.log 2>&1 < /dev/null &\n")
        return self

    def progress(self):
        text = self.host.execute(f'''set -eu
cd "$HOME/marinaframe-cfd/{self.name}"
if [ -f run-receipt.json ]; then cat run-receipt.json
elif [ -f safety-pause.txt ]; then printf '{{"state":"paused"}}\\n'
elif [ -f container-id ]; then
 state=$(docker inspect --format '{{{{.State.Status}}}}' mf-cfd-{self.name})
 last=$(docker logs --tail 200 mf-cfd-{self.name} 2>&1 | awk '/^Time = / {{t=$3}} END {{if(t==\"\") print \"null\"; else print t}}')
 printf '{{"state":"%s","last_time":%s}}\\n' "$state" "$last"
else printf '{{"state":"starting"}}\\n'; fi
''')
        return json.loads(text)

    def cancel(self):
        self.host.execute(f'set -eu; cd "$HOME/marinaframe-cfd/{self.name}"; touch cancel-requested; docker kill mf-cfd-{self.name}')

    def wait(self):
        while True:
            progress = self.progress()
            state = progress.get('state')
            if state in ('completed', 'failed', 'cancelled', 'paused'):
                if 'wall_seconds' in progress:
                    progress['allocated_core_hours'] = progress['wall_seconds'] * 5 / 3600
                    progress['accounting_basis'] = 'allocated quota time; includes pauses, not CPU consumption'
                return progress
            time.sleep(10)

    def collect(self):
        """Retrieve only lane logs/forces/receipts, not meshes or time directories."""
        self.case.mkdir(parents=True, exist_ok=True)
        for name in ('solver.log', 'load.log', 'monitor.log', 'run-receipt.json'):
            subprocess.run(['scp', f'{self.host.host}:marinaframe-cfd/{self.name}/{name}', str(self.case / name)], check=True)
        subprocess.run(['scp', '-r', f'{self.host.host}:marinaframe-cfd/{self.name}/postProcessing', str(self.case)], check=True)
