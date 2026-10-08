"""Copied process cleanup utility from frozen v1; the frozen file is unchanged."""
import collections
import os
import select
import signal
import time
from .contracts import RuntimeFailure as ClientFailure

class DescendantTracker:
    """Track only this spawned process tree, including ordinary setsid children.

    /proc reads are restricted to PID/PPID/start-time fields of stat. No cmdline,
    environ, fd contents, credentials, logs, or process memory are read. pidfds
    bind signals to the observed process identity even after a numeric PID is
    reused. This is cleanup, not cgroup containment or hostile-code isolation.
    """
    def __init__(self, root_pid):
        self.root_pid = root_pid
        self.tracked = {}
        self.last_refresh = 0.0
        self.scan_failures = 0
        self.capture(root_pid, self.identity(root_pid), 0)
        if root_pid not in self.tracked:
            raise ClientFailure('process_identity_tracking_unavailable')

    @staticmethod
    def identity(pid):
        try:
            # comm may contain spaces/parentheses; the numeric fields follow the
            # final closing parenthesis. Never retain or emit comm itself.
            with open(f'/proc/{pid}/stat', 'r', encoding='utf-8') as f:
                raw = f.read(8192)
            rest = raw[raw.rfind(')') + 2:].split()
            return (int(rest[1]), int(rest[19]))  # PPID; starttime in clock ticks
        except (OSError, ValueError, IndexError):
            return None

    def capture(self, pid, identity, depth, parent=None):
        if identity is None or pid <= 1 or pid == os.getpid():
            return
        if pid in self.tracked:
            return  # Never retarget an existing pidfd to a reused numeric PID.
        if parent is not None:
            if self.exited(parent):
                return
            now = self.identity(parent['pid'])
            if now is None or now[1] != parent['start_time_ticks']:
                return
        try:
            fd = os.pidfd_open(pid, 0)
        except ProcessLookupError:
            return
        except (OSError, AttributeError):
            self.scan_failures += 1
            return
        current = self.identity(pid)
        parent_current = self.identity(parent['pid']) if parent else None
        if (current is None or current[1] != identity[1] or
            (parent and (self.exited(parent) or parent_current is None or
                         parent_current[1] != parent['start_time_ticks']))):
            os.close(fd)
            return
        self.tracked[pid] = {'pid': pid, 'observed_ppid': identity[0],
                             'start_time_ticks': identity[1], 'depth': depth,
                             'fd': fd, 'sigterm_sent': False, 'sigkill_sent': False,
                             'signal_denied': False}

    def refresh(self, force=False):
        now = time.monotonic()
        if not force and now - self.last_refresh < .1:
            return
        self.last_refresh = now
        snapshot = {}
        try:
            with os.scandir('/proc') as entries:
                for entry in entries:
                    if entry.name.isdecimal():
                        pid = int(entry.name)
                        identity = self.identity(pid)
                        if identity is not None:
                            snapshot[pid] = identity
        except OSError:
            self.scan_failures += 1
            return
        children = collections.defaultdict(list)
        for pid, identity in snapshot.items():
            children[identity[0]].append(pid)
        queue = collections.deque(row for pid, row in self.tracked.items()
                                  if pid in snapshot and snapshot[pid][1] == row['start_time_ticks']
                                  and not self.exited(row))
        visited = set()
        while queue:
            parent = queue.popleft()
            if parent['pid'] in visited:
                continue
            visited.add(parent['pid'])
            for child_pid in children[parent['pid']]:
                identity = snapshot[child_pid]
                # A child cannot have started before the observed parent.
                if identity[1] < parent['start_time_ticks']:
                    continue
                self.capture(child_pid, identity, parent['depth'] + 1, parent)
                child = self.tracked.get(child_pid)
                if child and child['start_time_ticks'] == identity[1]:
                    queue.append(child)

    @staticmethod
    def exited(row):
        return bool(select.select([row['fd']], [], [], 0)[0])

    def signal_all(self, sig):
        # Parent-first TERM lets controller finally blocks start their own reaps.
        # Every signal uses its pidfd, never a later numeric-PID lookup.
        for row in sorted(self.tracked.values(), key=lambda p: p['depth']):
            if self.exited(row):
                continue
            try:
                signal.pidfd_send_signal(row['fd'], sig, None, 0)
                row['sigterm_sent' if sig == signal.SIGTERM else 'sigkill_sent'] = True
            except ProcessLookupError:
                pass
            except PermissionError:
                row['signal_denied'] = True

    def all_exited(self):
        return all(self.exited(row) for row in self.tracked.values())

    def finish(self):
        rows = []
        for row in self.tracked.values():
            rows.append({**{k: v for k, v in row.items() if k != 'fd'},
                         'exit_observed': self.exited(row)})
            os.close(row['fd'])
        return {'tracked_processes': rows, 'tracking_scan_failures': self.scan_failures,
                'tracked_processes_exited': all(p['exit_observed'] for p in rows),
                'tracking_scope': 'observed app-server descendants, including separate sessions; pidfd-bound identities',
                'tracking_limit': 'A process that reparents before it can be observed can escape tracking; no cgroup/subreaper containment claim'}
