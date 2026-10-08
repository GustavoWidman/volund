"""One FIFO execution lane for native work and sandbox-routed general commands.

Small bounded file reads do not acquire this lane. No command-text classifier,
performance result, model budget, or research deadline influences admission.
The runtime owns sandbox execution and must establish child cleanup before it
leaves a workspace-execution lease.
"""
from __future__ import annotations

import asyncio
import contextlib
import json
import threading
import time
import uuid

from development.core import Cancelled, write_new
from .overlap import AuditedBackend, CommandIntervals


class MeasurementCoordinationError(RuntimeError):
    """Resource cleanup is unresolved; never candidate evidence or retry permission."""


class MeasurementCoordinator:
    def __init__(self, command_intervals=None):
        self.commands = command_intervals or CommandIntervals()
        self._condition = threading.Condition(threading.RLock())
        self._waiting = []
        self._active = None
        self._quarantine = None
        self._sequence = 0
        self._completed = 0

    def snapshot(self):
        with self._condition:
            return {'active': dict(self._active) if self._active else None,
                    'queued': [{'lease_id': row['lease_id'], 'kind': row['kind'],
                                'actor_id': row['actor_id']} for row in self._waiting],
                    'completed_leases': self._completed,
                    'quarantine': dict(self._quarantine) if self._quarantine else None}

    def quarantine(self, reason, evidence=None):
        """Call only when a routed job's remaining resource use cannot be excluded."""
        if not isinstance(reason, str) or not reason.strip():
            raise ValueError('quarantine requires a concrete reason')
        with self._condition:
            if self._quarantine is None:
                self._quarantine = {'reason': reason, 'evidence': evidence or {},
                                    'observed_unix': time.time()}
            self._condition.notify_all()

    def acquire(self, kind, *, actor_id, check_active=lambda: None):
        check_active()
        receipt = {'lease_id': uuid.uuid4().hex, 'kind': kind, 'actor_id': actor_id,
                   'queued_monotonic': time.monotonic(), 'admitted_monotonic': None,
                   'released_monotonic': None}
        with self._condition:
            self._sequence += 1
            receipt['queue_sequence'] = self._sequence
            self._waiting.append(receipt)
            try:
                while True:
                    check_active()
                    unresolved = self.commands.unresolved()
                    if unresolved:
                        self.quarantine('unleased command cleanup unresolved', {'commands': unresolved})
                    if self._quarantine:
                        raise MeasurementCoordinationError('measurement_resource_quarantined: ' + self._quarantine['reason'])
                    first = self._waiting[0] is receipt
                    # Ordinary shell is absent in the configured runtime. An
                    # observed unleased command is a contamination backstop;
                    # its end must be observed before fresh timing can start.
                    quiet = kind != 'bench' or not self.commands.active()
                    if first and self._active is None and quiet:
                        self._waiting.pop(0)
                        receipt['admitted_monotonic'] = time.monotonic()
                        self._active = receipt
                        return receipt
                    self._condition.wait(.01)
            except BaseException:
                if receipt in self._waiting:
                    self._waiting.remove(receipt)
                self._condition.notify_all()
                raise

    def release(self, receipt):
        with self._condition:
            if self._active is not receipt:
                raise MeasurementCoordinationError('unknown_or_already_released_measurement_lease')
            receipt['released_monotonic'] = time.monotonic()
            self._active = None
            self._completed += 1
            self._condition.notify_all()

    @contextlib.contextmanager
    def lease(self, kind, *, actor_id, check_active=lambda: None):
        receipt = self.acquire(kind, actor_id=actor_id, check_active=check_active)
        try:
            yield receipt
        finally:
            self.release(receipt)

    @contextlib.asynccontextmanager
    async def async_lease(self, kind, *, actor_id, check_active=lambda: None):
        """Cancellation cannot abandon a queued ticket or just-admitted lease.

        The caller must shield its own process termination/cleanup inside the
        context before exiting it; this context cannot prove subprocess exit.
        """
        cancelled = threading.Event()

        def checked():
            if cancelled.is_set():
                raise Cancelled('execution lease caller cancelled while queueing')
            check_active()

        pending = asyncio.create_task(asyncio.to_thread(self.acquire, kind,
                    actor_id=actor_id, check_active=checked))
        try:
            receipt = await asyncio.shield(pending)
        except asyncio.CancelledError:
            cancelled.set()
            while True:
                try:
                    abandoned = await asyncio.shield(pending)
                except asyncio.CancelledError:
                    if pending.cancelled():
                        raise MeasurementCoordinationError('lease_acquisition_task_cancelled')
                    continue
                except Cancelled:
                    break
                else:
                    self.release(abandoned)
                    break
            raise
        try:
            yield receipt
        finally:
            self.release(receipt)


class CoordinatedBackend:
    """All native operations, including automatic trajectories, share the lane."""
    def __init__(self, backend, coordinator):
        self.backend = AuditedBackend(backend, coordinator.commands)
        self.coordinator = coordinator

    def __getattr__(self, name):
        return getattr(self.backend, name)

    def _check_cleanup_receipts(self, out):
        """Native process wrappers seal cleanup evidence before backend return."""
        command_paths = set(out.rglob('command.json'))
        command_paths.update(path.with_name('command.json') for path in out.rglob('exec-spec.json'))
        for path in sorted(command_paths):
            try:
                record = json.loads(path.read_text())
                cleanup = record.get('cleanup')
                # Only an explicit owner receipt can establish failed Popen.
                no_process = (record.get('process_started') is False and 'process_pid' not in record
                              and 'exit_code' not in record and cleanup is None
                              and isinstance(record.get('error'), str) and bool(record['error']))
                tracked = cleanup.get('tracked_processes') if isinstance(cleanup, dict) else None
                valid_rows = (isinstance(tracked, list) and bool(tracked)
                              and all(isinstance(row, dict) and type(row.get('pid')) is int and row['pid'] > 1
                                      and type(row.get('start_time_ticks')) is int and row['start_time_ticks'] >= 0
                                      and row.get('exit_observed') is True and row.get('signal_denied') is False
                                      for row in tracked))
                clean_process = (record.get('process_started') is True
                                 and type(record.get('process_pid')) is int and record['process_pid'] > 1
                                 and isinstance(cleanup, dict) and cleanup.get('tracked_processes_exited') is True
                                 and type(cleanup.get('tracking_scan_failures')) is int
                                 and cleanup['tracking_scan_failures'] == 0 and valid_rows
                                 and any(row['pid'] == record['process_pid'] for row in tracked))
                valid = no_process or clean_process
            except (OSError, ValueError, TypeError, AttributeError):
                valid = False
            if not valid:
                self.coordinator.quarantine('native process cleanup unresolved',
                    {'command_record': str(path), 'operation_directory': str(out)})
                return False
        return True

    def execute(self, kind, context, out):
        receipt = None
        try:
            with self.coordinator.lease(kind, actor_id=context['grant'].actor_id,
                                        check_active=context['check_active']) as receipt:
                try:
                    result = self.backend.execute(kind, context, out)
                finally:
                    clean = self._check_cleanup_receipts(out)
                if not clean:
                    result = {**result, 'status': 'infra_error', 'measurement_retry_authorized': False,
                              'resource_cleanup_unresolved': True}
        finally:
            if receipt is not None:
                write_new(out / 'execution-lease.json', receipt)
        return {**result, 'execution_lease': receipt}
