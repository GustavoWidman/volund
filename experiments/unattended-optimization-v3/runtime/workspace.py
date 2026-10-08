"""Bounded filesystem tools and leased commands through the CLI's own sandbox.

This router never executes agent code in an owner subprocess. The command/exec
supervisor receipt must establish cleanup before the shared execution lease ends.
Read tools are a narrow convenience boundary, not a hostile-code read sandbox:
the unchanged CLI workspace-write policy restricts writes, not all host reads.
"""
from __future__ import annotations
import asyncio
import base64
import copy
import hashlib
import json
import math
import os
from pathlib import Path
import stat
import sys
import time
import uuid

from .contracts import RuntimeFailure, sandbox

READ_CAP = 65536
SEARCH_CAP = 1048576
WRITE_CAP = 1048576
CAPTURE_CAP = 8 * 1024 * 1024
EXCERPT_CAP = 8192
# The supervisor can spend at most 10 + 10 + 2 seconds in cleanup/drain after
# its command watchdog. Leave additional CLI/transport allowance, without a
# fixed cap on the requested command duration or on the campaign.
COMMAND_RESPONSE_GRACE_SECONDS = 90
CURSOR_SECONDS = 300
CURSOR_CAP = 64
SUPERVISOR = Path(__file__).with_name('command_supervisor.py')


def canonical(value):
    return json.dumps(value, sort_keys=True, separators=(',', ':'), ensure_ascii=False, allow_nan=False).encode()


def sha(data):
    return hashlib.sha256(data).hexdigest()


class WorkspaceError(ValueError):
    pass


def tool_specs(role=None):
    path = {'type': 'string', 'minLength': 1, 'maxLength': 4096,
            'description': 'Absolute allowed path, or path relative to your own current workspace. No symlinks or parent traversal.'}
    integer = lambda low, high: {'type': 'integer', 'minimum': low, 'maximum': high}
    fields = {
        'read': ({'path': path, 'offset': integer(0, 2**63-1), 'max_bytes': integer(1, READ_CAP)}, ['path'],
                 'Read a bounded slice of one regular file in your workspace, public contract, or this campaign evidence. No execution lease is needed.'),
        'list': ({'path': path, 'max_entries': integer(1, 256), 'cursor': {'type': 'string', 'maxLength': 64}}, ['path'],
                 'List a bounded directory page; continue with its opaque cursor and the same path. Unsafe entries are labeled, never followed.'),
        'search': ({'path': path, 'query': {'type': 'string', 'minLength': 1, 'maxLength': 1024},
                    'max_files': integer(1, 256), 'max_bytes': integer(1, SEARCH_CAP),
                    'max_matches': integer(1, 100), 'cursor': {'type': 'string', 'maxLength': 64}}, ['path', 'query'],
                   'Search a literal UTF-8 byte sequence in bounded regular-file slices. Continuation may be required even when this page finds no match.'),
        'write': ({'path': path, 'content': {'type': 'string', 'maxLength': WRITE_CAP},
                   'append': {'type': 'boolean'}, 'mkdir_parents': {'type': 'boolean'}}, ['path', 'content'],
                  'Write UTF-8 text only in your own scratch, sharing the execution lease with native work and shell commands. Existing files must be regular and unlinked elsewhere.'),
        'exec': ({'command': {'type': 'string', 'minLength': 1, 'maxLength': 131072}, 'cwd': path,
                  'timeout_seconds': {'type': 'number', 'exclusiveMinimum': 0,
                    'description': 'Optional technical watchdog for this command only; default 600 seconds, adjustable for a long profile or test. No campaign or token budget.'}}, ['command'],
                 'Execute arbitrary Bash inside your existing CLI workspace-write sandbox, with network disabled and the shared native execution lease. Compile, test, inspect and profile repeatedly; output and cleanup receipts are retained.'),
    }
    return [{'type': 'function', 'name': 'study_workspace_' + name, 'description': description,
             'inputSchema': {'type': 'object', 'additionalProperties': False,
                             'properties': copy.deepcopy(props), 'required': required}}
            for name, (props, required, description) in fields.items()]


def _validate(tool, args):
    schema = next((t['inputSchema'] for t in tool_specs() if t['name'] == tool), None)
    if schema is None:
        raise WorkspaceError('unknown_workspace_tool')
    if not isinstance(args, dict):
        raise WorkspaceError('arguments must be an object')
    if set(args) - set(schema['properties']) or set(schema['required']) - set(args):
        raise WorkspaceError('arguments must use the exact advertised required and optional fields')
    for key, value in args.items():
        rule = schema['properties'][key]
        kind = rule['type']
        valid = ((kind == 'string' and isinstance(value, str)) or
                 (kind == 'integer' and type(value) is int) or
                 (kind == 'number' and type(value) in (int, float) and math.isfinite(value)) or
                 (kind == 'boolean' and type(value) is bool))
        if not valid:
            raise WorkspaceError(key + ' has the wrong type')
        if kind == 'string' and not rule.get('minLength', 0) <= len(value) <= rule.get('maxLength', 2**63):
            raise WorkspaceError(key + ' exceeds its text bounds')
        if kind in ('integer', 'number') and (value < rule.get('minimum', -math.inf) or
                value > rule.get('maximum', math.inf) or value <= rule.get('exclusiveMinimum', -math.inf)):
            raise WorkspaceError(key + ' exceeds its numeric bounds')
        if kind == 'string' and '\x00' in value:
            raise WorkspaceError(key + ' contains a null byte')


def _identity(info):
    return (info.st_dev, info.st_ino, info.st_size, info.st_mtime_ns, info.st_ctime_ns)


def _regular(fd):
    info = os.fstat(fd)
    if not stat.S_ISREG(info.st_mode) or info.st_nlink != 1:
        raise WorkspaceError('only regular files with one hard link are accepted')
    return info


def _open_directory(path):
    """Walk from / using directory descriptors, never resolving a symlink."""
    fd = os.open('/', os.O_RDONLY | os.O_DIRECTORY)
    try:
        for part in path.parts[1:]:
            nxt = os.open(part, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW, dir_fd=fd)
            os.close(fd)
            fd = nxt
        return fd
    except BaseException:
        os.close(fd)
        raise


def _open_path(path, *, directory=False):
    if directory:
        return _open_directory(path)
    parent = _open_directory(path.parent)
    try:
        return _open_regular_at(parent, path.name, os.O_RDONLY)
    finally:
        os.close(parent)


def _open_regular_at(parent, name, flags):
    # O_PATH inspects an inode without opening a FIFO/device for data access.
    # Reopen only our own pinned descriptor, never an attacker-replaced pathname.
    guard = os.open(name, os.O_PATH | os.O_NOFOLLOW, dir_fd=parent)
    try:
        before = _regular(guard)
        fd = os.open('/proc/self/fd/' + str(guard), flags | os.O_NONBLOCK)
        try:
            after = _regular(fd)
            if (after.st_dev, after.st_ino) != (before.st_dev, before.st_ino):
                raise WorkspaceError('regular-file descriptor identity changed')
            return fd
        except BaseException:
            os.close(fd)
            raise
    finally:
        os.close(guard)


class _Walk:
    """Resumable finite work per page, with a bounded number of held descriptors."""
    def __init__(self, path, recursive):
        self.recursive = recursive
        self.stack = []
        self.single = None
        try:
            fd = _open_path(path, directory=True)
        except NotADirectoryError:
            fd = _open_path(path)
            self.single = (path, fd)
        else:
            self._push(path, fd)

    def _push(self, path, fd):
        if len(self.stack) >= 64:
            os.close(fd)
            raise WorkspaceError('directory depth limit reached; search a narrower path')
        self.stack.append((path, fd, os.scandir(fd), _identity(os.fstat(fd))))

    def next(self):
        if self.single:
            path, fd = self.single
            self.single = None
            return path, 'file', fd
        while self.stack:
            parent, parent_fd, iterator, before = self.stack[-1]
            if _identity(os.fstat(parent_fd)) != before:
                raise WorkspaceError('directory changed during continuation; start a fresh request')
            try:
                entry = next(iterator)
            except StopIteration:
                iterator.close(); os.close(parent_fd); self.stack.pop()
                continue
            path = parent / entry.name
            mode = entry.stat(follow_symlinks=False).st_mode
            if stat.S_ISDIR(mode):
                if self.recursive:
                    fd = os.open(entry.name, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW, dir_fd=parent_fd)
                    self._push(path, fd)
                return path, 'directory', None
            if stat.S_ISREG(mode):
                try:
                    fd = _open_regular_at(parent_fd, entry.name, os.O_RDONLY)
                except WorkspaceError:
                    return path, 'rejected_hardlink_or_special', None
                return path, 'file', fd
            return path, 'rejected_symlink_or_special', None
        return None

    def close(self):
        if self.single:
            os.close(self.single[1]); self.single = None
        for _, fd, iterator, _ in self.stack:
            iterator.close(); os.close(fd)
        self.stack.clear()


class WorkspaceRouter:
    def __init__(self, rpc, coordinator, campaign_directory, *, public_roots=(), evidence_roots=(),
                 check_active=lambda agent: None, command_path=os.defpath, cpus=(), valgrind_lib=None,
                 technical_timeout_seconds=600):
        self.rpc, self.coordinator = rpc, coordinator
        self.campaign = Path(campaign_directory).resolve(strict=True)
        self.operations = self.campaign / 'workspace-operations'
        self.operations.mkdir(exist_ok=False)
        self.public_roots = tuple(Path(p).absolute() for p in public_roots)
        self.evidence_roots = tuple(Path(p).absolute() for p in evidence_roots) + (self.operations,)
        for path in (*self.public_roots, *self.evidence_roots):
            if '..' in path.parts or path == Path('/'):
                raise ValueError('invalid read root')
            fd = _open_path(path, directory=True); os.close(fd)
        if any(not p.is_relative_to(self.campaign) or p == self.campaign for p in self.evidence_roots):
            raise ValueError('evidence roots must be explicit subtrees of this campaign')
        if not math.isfinite(technical_timeout_seconds) or technical_timeout_seconds <= 0:
            raise ValueError('invalid technical command timeout')
        self.check_active = check_active
        self.command_path, self.cpus, self.valgrind_lib = command_path, tuple(cpus), valgrind_lib
        self.technical_timeout_seconds = technical_timeout_seconds
        self.supervisor_sha256 = sha(SUPERVISOR.read_bytes())
        self.jobs, self.cursors = set(), {}
        self.closing = False
        self._close_task = None

    def schemas(self):
        return tool_specs()

    def _roots(self, agent, write=False):
        roots = tuple(Path(p) for p in agent.spec.writable_roots)
        if any(not p.is_absolute() or '..' in p.parts or p == Path('/') or
               p.is_relative_to(self.operations) or self.operations.is_relative_to(p) for p in roots):
            raise WorkspaceError('invalid actor writable root')
        return roots if write else roots + self.public_roots + self.evidence_roots

    def _path(self, agent, text, write=False):
        path = Path(text)
        if '..' in path.parts or len(path.parts) > 128:
            raise WorkspaceError('parent traversal or excessive path depth is not allowed')
        if not path.is_absolute():
            path = Path(agent.spec.cwd) / path
        if not any(path.is_relative_to(root) for root in self._roots(agent, write)):
            raise WorkspaceError('path is outside your declared workspace/public/campaign scope')
        return path

    def _save(self, directory, name, value):
        with (directory / name).open('xb') as stream:
            stream.write(canonical(value) + b'\n')

    async def dispatch(self, agent, tool, args):
        if self.closing:
            return {'status': 'cancelled', 'error': 'workspace router is closing'}
        task = asyncio.create_task(self._perform(agent, tool, args))
        self.jobs.add(task)
        task.add_done_callback(self.jobs.discard)
        try:
            return await asyncio.shield(task)
        except asyncio.CancelledError:
            task.cancel()
            await self._drain(task)
            raise

    @staticmethod
    async def _drain(task):
        while True:
            try:
                return await asyncio.shield(task)
            except asyncio.CancelledError:
                if task.done():
                    return None
            except Exception:
                return None

    async def _perform(self, agent, tool, args):
        op_id = 'workspace-' + uuid.uuid4().hex
        operation = self.operations / op_id
        operation.mkdir()
        request = {'schema_version': 1, 'operation_id': op_id, 'actor_id': agent.agent_id,
                   'role': agent.role, 'thread_id': agent.thread_id, 'turn_id': agent.turn_id,
                   'tool': tool, 'arguments': args, 'started_unix': time.time()}
        result = {'status': 'cancelled', 'error': 'workspace request cancelled'}
        try:
            self._save(operation, 'request.json', request)
            _validate(tool, args)
            self.check_active(agent)
            name = tool.removeprefix('study_workspace_')
            if name == 'exec':
                result = await self._exec(agent, args, operation, op_id)
            elif name == 'write':
                lease = None
                try:
                    async with self.coordinator.async_lease('workspace_write', actor_id=agent.agent_id,
                                                           check_active=lambda: self.check_active(agent)) as lease:
                        result = self._write(agent, args)
                finally:
                    if lease is not None:
                        self._save(operation, 'execution-lease.json', lease)
            else:
                result = getattr(self, '_' + name)(agent, args)
        except (ValueError, TypeError) as exc:
            result = {'status': 'request_error',
                      'error': str(exc) if isinstance(exc, WorkspaceError) else 'request is not valid finite UTF-8 JSON',
                      'correctable': True,
                      'repair': 'Use the exact tool schema and an allowed ordinary path. Restart an expired or changed continuation.'}
        except OSError as exc:
            result = {'status': 'request_error', 'error': type(exc).__name__, 'errno': exc.errno,
                      'correctable': True, 'repair': 'Check that the scoped path exists and contains only ordinary files/directories; correct and retry.'}
        finally:
            result.update(operation_id=op_id, artifact_directory=str(operation))
            self._save(operation, 'result.json', {**result, 'finished_unix': time.time()})
        return result

    def _read(self, agent, args):
        path = self._path(agent, args['path'])
        fd = _open_path(path)
        try:
            before = _regular(fd)
            offset, count = args.get('offset', 0), args.get('max_bytes', READ_CAP)
            data = os.pread(fd, count, offset)
            if _identity(_regular(fd)) != _identity(before):
                raise WorkspaceError('file changed during read; retry')
        finally:
            os.close(fd)
        end = offset + len(data)
        return {'status': 'ok', 'path': str(path), 'offset': offset, 'bytes_read': len(data),
                'file_size': before.st_size, 'content': data.decode('utf-8', errors='replace'),
                'encoding': 'utf-8; invalid byte sequences replaced', 'slice_sha256': sha(data),
                'truncated': end < before.st_size, 'next_offset': end if end < before.st_size else None}

    def _expire_cursors(self):
        now = time.monotonic()
        for token, state in list(self.cursors.items()):
            if state['expires'] < now:
                self._close_cursor(state); del self.cursors[token]

    def _close_cursor(self, state):
        state['walk'].close()
        if state.get('file'):
            os.close(state['file']['fd']); state['file'] = None

    def _cursor(self, agent, args, name):
        self._expire_cursors()
        path = self._path(agent, args['path'])
        identity = (agent.agent_id, name, str(path), args.get('query'))
        token = args.get('cursor')
        if token:
            state = self.cursors.get(token)
            if state is None or state['identity'] != identity:
                raise WorkspaceError('cursor expired, unknown, or bound to another actor/path/query')
            del self.cursors[token]
            return state
        if len(self.cursors) >= CURSOR_CAP:
            raise WorkspaceError('too many open continuations; finish existing cursors or wait for expiry')
        return {'identity': identity, 'walk': _Walk(path, name == 'search'), 'file': None}

    def _continue(self, state, more):
        if not more:
            self._close_cursor(state)
            return None
        token = uuid.uuid4().hex
        state['expires'] = time.monotonic() + CURSOR_SECONDS
        self.cursors[token] = state
        return token

    def _list(self, agent, args):
        state = self._cursor(agent, args, 'list')
        entries, more = [], True
        try:
            for _ in range(args.get('max_entries', 128)):
                row = state['walk'].next()
                if row is None:
                    more = False; break
                path, kind, fd = row
                try:
                    entries.append({'path': str(path), 'type': kind,
                                    **({'bytes': _regular(fd).st_size} if fd is not None else {})})
                finally:
                    if fd is not None: os.close(fd)
            cursor = self._continue(state, more)
            return {'status': 'ok', 'entries': entries, 'truncated': more, 'cursor': cursor,
                    'continuation': 'Pass cursor with the same path; directory mutation invalidates it.' if more else None}
        except BaseException:
            self._close_cursor(state); raise

    def _search(self, agent, args):
        state = self._cursor(agent, args, 'search')
        matches, scanned, entries, files, skipped = [], 0, 0, 0, 0
        query = args['query'].encode('utf-8')
        byte_cap, file_cap, match_cap = args.get('max_bytes', SEARCH_CAP), args.get('max_files', 64), args.get('max_matches', 40)
        more = True
        try:
            while scanned < byte_cap and files < file_cap and entries < file_cap * 4 and len(matches) < match_cap:
                current = state['file']
                if current is None:
                    row = state['walk'].next()
                    if row is None:
                        more = False; break
                    entries += 1
                    path, kind, fd = row
                    if fd is None:
                        skipped += kind.startswith('rejected'); continue
                    current = state['file'] = {'path': str(path), 'fd': fd, 'offset': 0,
                                                'identity': _identity(_regular(fd)), 'tail': b''}
                files += 1
                fd = current['fd']
                if _identity(_regular(fd)) != current['identity']:
                    raise WorkspaceError('file changed during search continuation; restart search')
                data = os.pread(fd, min(READ_CAP, byte_cap-scanned), current['offset'])
                scanned += len(data)
                if not data:
                    os.close(fd); state['file'] = None; continue
                combined = current['tail'] + data
                base = current['offset'] - len(current['tail'])
                index = 0
                resume = None
                while len(matches) < match_cap:
                    found = combined.find(query, index)
                    if found < 0: break
                    matches.append({'path': current['path'], 'byte_offset': base + found,
                                    'excerpt': combined[max(0, found-80):found+len(query)+160].decode('utf-8', errors='replace')})
                    index = found + 1
                    if len(matches) == match_cap:
                        resume = base + index; break
                if _identity(_regular(fd)) != current['identity']:
                    raise WorkspaceError('file changed during search; retry')
                if resume is not None:
                    current['offset'], current['tail'] = resume, b''
                else:
                    current['offset'] += len(data)
                    current['tail'] = combined[-(len(query)-1):] if len(query) > 1 else b''
                if current['offset'] >= current['identity'][2]:
                    os.close(fd); state['file'] = None
            cursor = self._continue(state, more)
            return {'status': 'ok', 'query': args['query'], 'matches': matches, 'scanned_bytes': scanned,
                    'scanned_file_slices': files, 'scanned_entries': entries, 'rejected_entries': skipped,
                    'truncated': more, 'cursor': cursor,
                    'continuation': 'Continue with cursor and the same path/query; no matches on a bounded page is not an exhaustive negative result.' if more else None}
        except BaseException:
            self._close_cursor(state); raise

    def _write(self, agent, args):
        path = self._path(agent, args['path'], write=True)
        data = args['content'].encode('utf-8')
        if len(data) > WRITE_CAP:
            raise WorkspaceError('content exceeds the UTF-8 byte limit')
        if path in self._roots(agent, write=True):
            raise WorkspaceError('write requires a file below your workspace root')
        if args.get('mkdir_parents'):
            # Descend from an approved root so no mkdir can affect outside scope.
            root = max((p for p in self._roots(agent, True) if path.is_relative_to(p)), key=lambda p: len(p.parts))
            fd = _open_directory(root)
            try:
                for part in path.parent.relative_to(root).parts:
                    try: os.mkdir(part, dir_fd=fd)
                    except FileExistsError: pass
                    nxt = os.open(part, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW, dir_fd=fd)
                    os.close(fd); fd = nxt
            except BaseException:
                os.close(fd); raise
        else:
            fd = _open_directory(path.parent)
        try:
            try:
                output = os.open(path.name, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW,
                                 0o600, dir_fd=fd)
            except FileExistsError:
                output = _open_regular_at(fd, path.name, os.O_WRONLY)
            try:
                _regular(output)
                if args.get('append'):
                    os.lseek(output, 0, os.SEEK_END)
                else:
                    os.ftruncate(output, 0)
                view = memoryview(data)
                while view:
                    size = os.write(output, view); view = view[size:]
            finally:
                os.close(output)
        finally:
            os.close(fd)
        return {'status': 'ok', 'path': str(path), 'bytes_written': len(data),
                'written_sha256': sha(data), 'append': args.get('append', False)}

    def _cancel_marker(self, capture):
        try:
            fd = _open_directory(capture)
            try:
                marker = os.open('cancel-requested', os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600, dir_fd=fd)
                os.close(marker)
            finally:
                os.close(fd)
        except FileExistsError:
            pass
        except OSError:
            # Keep awaiting the original RPC; the watchdog still owns cleanup.
            pass

    def _receipt(self, response, invocation_id, raw):
        if (not isinstance(response, dict) or type(response.get('exitCode')) is not int or
                response['exitCode'] != 0 or not isinstance(response.get('stdout'), str)):
            raise WorkspaceError('supervisor RPC did not return a successful cleanup receipt')
        receipt = json.loads(response['stdout'])
        if not isinstance(receipt, dict) or type(receipt.get('schema_version')) is not int or (receipt.get('schema_version'), receipt.get('invocation_id'),
                receipt.get('spec_sha256'), receipt.get('supervisor_sha256')) != (1, invocation_id, sha(raw), self.supervisor_sha256):
            raise WorkspaceError('supervisor receipt identity mismatch')
        if (receipt.get('cleanup_complete') is not True or receipt.get('remaining_direct_children') != [] or
                receipt.get('subreaper_verified') is not True or receipt.get('sigchld_default_verified') is not True or
                receipt.get('output_drained') is not True or type(receipt.get('process_started')) is not bool):
            raise WorkspaceError('supervisor did not establish complete process and output cleanup')
        started, code = receipt['process_started'], receipt.get('root_exit_code')
        if (started and type(code) is not int) or (not started and code is not None):
            raise WorkspaceError('supervisor root process result is inconsistent')
        reasons = ('command_completed', 'interrupted_before_launch', 'interrupted', 'command_watchdog',
                   'background_descendants_cleaned', 'descendant_cleanup_unverified',
                   'command_launch_failure', 'supervisor_operation_failure')
        if receipt.get('reason') not in reasons:
            raise WorkspaceError('supervisor result reason is missing or unknown')
        if not started and receipt['reason'] not in ('interrupted_before_launch', 'command_launch_failure'):
            raise WorkspaceError('supervisor prelaunch result is inconsistent')
        return receipt

    def _capture(self, capture, operation, receipt):
        outputs = receipt.get('output_files')
        if not isinstance(outputs, dict) or set(outputs) != {'stdout.bin', 'stderr.bin'}:
            raise WorkspaceError('supervisor output file manifest is incomplete')
        result = {}
        for name, metadata in outputs.items():
            if not isinstance(metadata, dict) or type(metadata.get('bytes')) is not int or not 0 <= metadata['bytes'] <= CAPTURE_CAP:
                raise WorkspaceError('invalid captured output size')
            if (type(metadata.get('observed_bytes')) is not int or type(metadata.get('discarded_bytes')) is not int or
                    metadata['observed_bytes'] < metadata['bytes'] or
                    metadata['discarded_bytes'] != metadata['observed_bytes'] - metadata['bytes']):
                raise WorkspaceError('captured output truncation counts are inconsistent')
            fd = _open_path(capture / name)
            try:
                before = _regular(fd)
                if before.st_size != metadata['bytes']:
                    raise WorkspaceError('captured output size changed')
                data = b''
                while len(data) < before.st_size:
                    chunk = os.read(fd, min(READ_CAP, before.st_size-len(data)))
                    if not chunk: break
                    data += chunk
                if _identity(_regular(fd)) != _identity(before) or sha(data) != metadata.get('sha256'):
                    raise WorkspaceError('captured output identity or content changed')
            finally:
                os.close(fd)
            with (operation / name).open('xb') as target: target.write(data)
            result[name.removesuffix('.bin')] = {'artifact': str(operation / name), 'bytes': len(data),
                'sha256': sha(data), 'excerpt': data[:EXCERPT_CAP].decode('utf-8', errors='replace'),
                'excerpt_truncated': len(data) > EXCERPT_CAP, 'observed_bytes': metadata.get('observed_bytes'),
                'capture_truncated': metadata.get('discarded_bytes', 0) > 0}
        return result

    async def _exec(self, agent, args, operation, invocation_id):
        cwd = self._path(agent, args.get('cwd', str(agent.spec.cwd)), write=True)
        cwd_fd = _open_directory(cwd); os.close(cwd_fd)
        actor_root = next(p for p in self._roots(agent, True) if cwd.is_relative_to(p))
        # The command can modify its scratch; the durable owner copy stays outside it.
        capture = actor_root / ('.' + invocation_id)
        spec = {'invocation_id': invocation_id, 'command': args['command'], 'cwd': str(cwd),
                'actor_root': str(actor_root), 'output_directory': str(capture),
                'timeout_seconds': args.get('timeout_seconds', self.technical_timeout_seconds),
                'path': self.command_path, 'cpus': list(self.cpus)}
        if self.valgrind_lib: spec['valgrind_lib'] = self.valgrind_lib
        raw = canonical(spec)
        self._save(operation, 'exec-spec.json', spec)
        params = {'command': [sys.executable, '-B', str(SUPERVISOR), base64.b64encode(raw).decode()],
                  'cwd': str(cwd), 'sandboxPolicy': sandbox(agent.spec), 'processId': invocation_id,
                  'disableTimeout': True, 'outputBytesCap': 2 * 1024 * 1024}
        self._save(operation, 'sandbox-request.json', params)
        response_timeout = spec['timeout_seconds'] + COMMAND_RESPONSE_GRACE_SECONDS
        self._save(operation, 'rpc-policy.json', {'response_timeout_seconds': response_timeout,
                   'command_watchdog_seconds': spec['timeout_seconds'],
                   'cleanup_and_transport_allowance_seconds': COMMAND_RESPONSE_GRACE_SECONDS,
                   'timeout_action': 'quarantine resources; never retry an unattested command'})
        lease = None
        try:
            async with self.coordinator.async_lease('workspace_exec', actor_id=agent.agent_id,
                                                  check_active=lambda: self.check_active(agent)) as lease:
                if sha(SUPERVISOR.read_bytes()) != self.supervisor_sha256:
                    raise WorkspaceError('supervisor changed since router construction; restart setup')
                fd = _open_directory(actor_root)
                try: os.mkdir(capture.name, 0o700, dir_fd=fd)
                finally: os.close(fd)
                pending = asyncio.create_task(self.rpc.request('command/exec', params, timeout=response_timeout))
                interrupted = False
                while True:
                    try:
                        response = await asyncio.shield(pending)
                        break
                    except asyncio.CancelledError:
                        interrupted = True
                        self._cancel_marker(capture)
                        if pending.cancelled():
                            self.coordinator.quarantine('workspace RPC task cancelled before cleanup receipt', {'operation_id': invocation_id})
                            raise RuntimeFailure('workspace_cleanup_unresolved') from None
                    except Exception as exc:
                        self.coordinator.quarantine('workspace command RPC failed before cleanup receipt',
                                                    {'operation_id': invocation_id, 'error_category': type(exc).__name__})
                        return {'status': 'resource_quarantined', 'error': 'command cleanup could not be verified', 'correctable': False}
                try:
                    receipt = self._receipt(response, invocation_id, raw)
                except (ValueError, TypeError, KeyError) as exc:
                    self.coordinator.quarantine('workspace supervisor cleanup receipt invalid',
                                                {'operation_id': invocation_id, 'error_category': type(exc).__name__})
                    return {'status': 'resource_quarantined', 'error': 'command cleanup receipt failed validation', 'correctable': False}
                self._save(operation, 'supervisor-receipt.json', receipt)
                try:
                    outputs = self._capture(capture, operation, receipt)
                except (WorkspaceError, OSError) as exc:
                    return {'status': 'artifact_error', 'error': str(exc) if isinstance(exc, WorkspaceError) else type(exc).__name__,
                            'cleanup_complete': True, 'correctable': True, 'repair': 'Process cleanup was verified, but output files changed or were unavailable. Inspect your workspace and rerun if needed.'}
                code = receipt['root_exit_code']
                status = ('ok' if receipt['process_started'] and code == 0 and
                          receipt['reason'] in ('command_completed', 'background_descendants_cleaned') and
                          receipt.get('error_category') is None else 'command_failed')
                if interrupted or receipt['reason'] in ('interrupted', 'interrupted_before_launch'):
                    status = 'cancelled'
                elif receipt['reason'] == 'command_watchdog':
                    status = 'command_timeout'
                return {'status': status, 'exit_code': code, 'process_started': receipt['process_started'],
                        'reason': receipt['reason'], 'cleanup_complete': True, 'outputs': outputs,
                        'correctable': status != 'ok',
                        'repair': 'Inspect retained stdout/stderr, revise the command or technical timeout, and retry as needed.' if status != 'ok' else None,
                        'evidence_authority': 'ordinary workspace command; does not replace official source-bound development evidence'}
        finally:
            if lease is not None: self._save(operation, 'execution-lease.json', lease)

    async def close(self):
        if self._close_task is None:
            self.closing = True
            self._close_task = asyncio.create_task(self._close())
        await self._drain(self._close_task)
        return {'drained': self._close_task.done() and not self.jobs,
                'quarantine': self.coordinator.snapshot().get('quarantine')}

    async def _close(self):
        jobs = list(self.jobs)
        for job in jobs: job.cancel()
        if jobs:
            await asyncio.gather(*jobs, return_exceptions=True)
        for state in self.cursors.values(): self._close_cursor(state)
        self.cursors.clear()
