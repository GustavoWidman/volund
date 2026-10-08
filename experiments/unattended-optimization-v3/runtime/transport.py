"""Concurrent stdio JSON-RPC. Importing or constructing never launches anything.

The official CLI enforces nested-runtime restrictions. Inherited environment is
preserved; this module never unsets restriction variables or reads credentials.
"""
from __future__ import annotations
import asyncio
import json
import os
from pathlib import Path
import signal
import time
from .contracts import RuntimeFailure
from .process_tree import DescendantTracker

CLI = Path('/workspace/scratch/eeae3ae186b3/build-tools/codex-stable/node_modules/.bin/codex')
AUTH_HOME = Path('/workspace/scratch/eeae3ae186b3/.study-codex-runtime')  # Path only; never open.
MAX_LINE = 8 * 1024 * 1024
_DEFAULT_TIMEOUT = object()


class StdioRPC:
    def __init__(self, command, cwd, *, request_timeout=120.0, env=None):
        self.command, self.cwd, self.request_timeout = command, cwd, request_timeout
        self.env = env
        self.pending = {}
        self.handlers = set()
        self.sequence = 0
        self.failure = None
        self.closing = False
        self.stderr_bytes = 0
        self.stdout_eof = False
        self.stderr_eof = False
        self.abandoned_requests = set()
        self.late_rpc_responses_ignored = 0
        self.event_processing_errors = 0
        self.cleanup_caller_cancellation_observed = False
        self._close_task = None
        self.process = None
        self.on_event = lambda msg: None
        self.on_request = None
        self._send_lock = asyncio.Lock()

    @classmethod
    def official(cls, cwd, *, direct_terminal_authorized=False, request_timeout=120.0):
        if direct_terminal_authorized is not True:
            raise RuntimeFailure('direct_terminal_launch_not_authorized')
        env = os.environ.copy()
        env['CODEX_HOME'] = str(AUTH_HOME)
        return cls([str(CLI), 'app-server', '--listen', 'stdio://', '-c', 'forced_login_method="chatgpt"',
                    '-c', 'history.persistence="none"'], cwd, request_timeout=request_timeout, env=env)


    async def open(self):
        self.process = await asyncio.create_subprocess_exec(*self.command, cwd=self.cwd, env=self.env,
            stdin=asyncio.subprocess.PIPE, stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE, start_new_session=True, limit=MAX_LINE)
        try:
            self.tracker = DescendantTracker(self.process.pid)
        except Exception:
            self.process.kill()
            await self.process.wait()
            raise
        self.reader = asyncio.create_task(self._read())
        self.stderr_reader = asyncio.create_task(self._stderr())
        self.process_tracker = asyncio.create_task(self._track())

    async def _track(self):
        while self.process.returncode is None:
            self.tracker.refresh()
            await asyncio.sleep(.1)

    async def _stderr(self):
        while data := await self.process.stderr.read(65536):
            self.stderr_bytes += len(data)  # No raw stderr, auth diagnostics, or secrets retained.
        self.stderr_eof = True

    async def send(self, message):
        data = (json.dumps(message, separators=(',', ':')) + '\n').encode()
        if len(data) > MAX_LINE:
            raise RuntimeFailure('protocol_message_too_large')
        async with self._send_lock:
            self.process.stdin.write(data)
            await asyncio.wait_for(self.process.stdin.drain(), self.request_timeout)

    async def request(self, method, params, *, timeout=_DEFAULT_TIMEOUT):
        # Model/session admission retains its short safeguard. Standalone
        # commands can use their watchdog plus cleanup/transport allowance,
        # without inheriting the short model-metadata admission timeout.
        # Explicit None remains available for a caller that owns its lifetime.
        timeout = self.request_timeout if timeout is _DEFAULT_TIMEOUT else timeout
        if self.failure:
            raise RuntimeFailure(self.failure)
        self.sequence += 1
        request_id = 'owner-' + str(self.sequence)
        future = asyncio.get_running_loop().create_future()
        self.pending[request_id] = future
        try:
            await self.send({'id': request_id, 'method': method, 'params': params})
            return await asyncio.wait_for(future, timeout)
        except asyncio.TimeoutError:
            self.abandoned_requests.add(request_id)
            raise RuntimeFailure('rpc_command_response_timeout' if method == 'command/exec'
                                 else 'rpc_admission_timeout') from None
        except asyncio.CancelledError:
            self.abandoned_requests.add(request_id)
            raise
        finally:
            self.pending.pop(request_id, None)

    async def _respond(self, msg):
        try:
            if msg['method'] != 'item/tool/call' or self.on_request is None:
                # Approval/auth/input requests are never automatically approved.
                await self.send({'id': msg['id'], 'error': {'code': -32601, 'message': 'Unsupported unattended request'}})
                self._fail('unexpected_server_request')
                return
            result = await self.on_request(msg['params'])
            await self.send({'id': msg['id'], 'result': result})
        except Exception:
            self._fail('dynamic_tool_handler_failure')
        except asyncio.CancelledError:
            if not self.closing:
                await self.send({'id': msg['id'], 'result': {'success': False,
                    'contentItems': [{'type': 'inputText', 'text': 'runtime_stopping'}]}})

    def _fail(self, category):
        self.failure = self.failure or category
        for future in self.pending.values():
            if not future.done():
                future.set_exception(RuntimeFailure(self.failure))

    async def _read(self):
        try:
            while line := await self.process.stdout.readline():
                if len(line) > MAX_LINE:
                    raise RuntimeFailure('protocol_line_too_large')
                try:
                    msg = json.loads(line)
                    if not isinstance(msg, dict):
                        raise RuntimeFailure('invalid_protocol_message')
                    if 'method' in msg:
                        if 'id' in msg:
                            task = asyncio.create_task(self._respond(msg))
                            self.handlers.add(task)
                            task.add_done_callback(self.handlers.discard)
                        else:
                            self.on_event(msg)
                    else:
                        request_id = msg.get('id')
                        future = self.pending.get(request_id)
                        if future is None:
                            if request_id in self.abandoned_requests:
                                self.abandoned_requests.remove(request_id)
                                self.late_rpc_responses_ignored += 1
                                continue  # Cancellation/timeout does not end the event stream.
                            raise RuntimeFailure('unexpected_rpc_response')
                        if not future.done():
                            if 'error' in msg:
                                future.set_exception(RuntimeFailure('rpc_request_failed'))
                            elif not isinstance(msg.get('result'), dict):
                                future.set_exception(RuntimeFailure('invalid_rpc_result'))
                            else:
                                future.set_result(msg['result'])
                except Exception as exc:
                    # Preserve subsequent numeric notifications even after a bad
                    # event/response. Failure remains explicit, never a clean run.
                    self.event_processing_errors += 1
                    self._fail(str(exc) if isinstance(exc, RuntimeFailure) else 'invalid_protocol_message')
            self.stdout_eof = True
            if not self.closing:
                self._fail('app_server_exited')
        except asyncio.CancelledError:
            self._fail('protocol_reader_cancelled')
            raise
        except Exception as exc:
            self._fail(str(exc) if isinstance(exc, RuntimeFailure) else 'invalid_protocol_stream')

    async def close(self):
        """Idempotent cleanup survives cancellation of its caller, not the reader.

        Signal handlers must cancel only the workflow task; asyncio.run-wide
        teardown has already destroyed the event pump and cannot be repaired here.
        """
        if self._close_task is None:
            self._close_task = asyncio.create_task(self._close())
        while True:
            try:
                result = await asyncio.shield(self._close_task)
                return {**result, 'cleanup_caller_cancellation_observed': self.cleanup_caller_cancellation_observed}
            except asyncio.CancelledError:
                self.cleanup_caller_cancellation_observed = True
                self._fail('shutdown_caller_cancelled')
                if self._close_task.cancelled():
                    raise RuntimeFailure('shutdown_cleanup_task_cancelled') from None

    async def _close(self):
        if self.process is None:
            return {'launched': False}
        self.closing = True
        self.tracker.refresh(force=True)
        self.tracker.signal_all(signal.SIGTERM)
        try:
            await asyncio.wait_for(self.process.wait(), .5)
        except asyncio.TimeoutError:
            self.tracker.refresh(force=True)
            self.tracker.signal_all(signal.SIGKILL)
            await asyncio.wait_for(self.process.wait(), 2)
        # Descendants can outlive their leader; always finish all tracked identities.
        self.tracker.refresh(force=True)
        self.tracker.signal_all(signal.SIGKILL)
        end = time.monotonic() + .5
        while not self.tracker.all_exited() and time.monotonic() < end:
            await asyncio.sleep(.01)
        # Process exit is not the same as consuming the final buffered protocol
        # lines. Drain both pipes before cancelling readers or exporting usage.
        event_stream_drained = False
        done, pending = await asyncio.wait([self.reader, self.stderr_reader], timeout=2.0)
        event_stream_drained = self.stdout_eof and self.stderr_eof
        if pending:
            self._fail('shutdown_event_drain_timeout')
        if not event_stream_drained:
            self._fail('shutdown_event_drain_incomplete')
        for task in list(self.handlers) + [self.reader, self.stderr_reader, self.process_tracker]:
            task.cancel()
        await asyncio.gather(*list(self.handlers), self.reader, self.stderr_reader, self.process_tracker, return_exceptions=True)
        for future in self.pending.values():
            if not future.done():
                future.set_exception(RuntimeFailure('transport_closed'))
        return {'launched': True, 'stderr_bytes': self.stderr_bytes,
                'event_stream_drained': event_stream_drained,
                'event_processing_complete': self.event_processing_errors == 0 and event_stream_drained,
                'event_processing_errors': self.event_processing_errors,
                'late_rpc_responses_ignored': self.late_rpc_responses_ignored,
                **self.tracker.finish()}
