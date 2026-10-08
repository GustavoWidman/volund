"""A protocol simulator only. It invokes no model, compiler, or benchmark."""
import json
import signal
import sys
import threading
import time

lock = threading.Lock()
threads = {}
sequence = 0
lead_thread = None
child_ids = []


def send(value):
    with lock:
        print(json.dumps(value), flush=True)


def event(method, thread_id, turn_id=None, **params):
    send({'method': method, 'params': {'threadId': thread_id, **({'turnId': turn_id} if turn_id else {}), **params}})


def counters(n):
    return {'inputTokens': 100*n, 'cachedInputTokens': 20*n, 'cacheWriteInputTokens': 0,
            'outputTokens': 30*n, 'reasoningOutputTokens': 10*n, 'totalTokens': 130*n}


def finish(thread, turn, status='completed'):
    event('item/completed', thread, turn, item={'type': 'commandExecution', 'id': 'cmd-'+turn,
        'command': 'printf fixture', 'cwd': threads[thread]['cwd'], 'status': 'completed',
        'aggregatedOutput': 'ordinary fixture output\n', 'exitCode': 0, 'durationMs': 1,
        'unexpectedHiddenField': 'DO_NOT_EXPORT'})
    event('item/completed', thread, turn, item={'type': 'reasoning', 'id': 'private',
        'summary': ['PRIVATE_REASONING_SENTINEL'], 'content': ['PRIVATE_REASONING_SENTINEL']})
    event('item/reasoning/textDelta', thread, turn, delta='PRIVATE_REASONING_SENTINEL')
    total = counters(threads[thread]['turns'])
    event('thread/tokenUsage/updated', thread, turn, tokenUsage={'total': total, 'last': counters(1), 'modelContextWindow': 200000})
    event('thread/tokenUsage/updated', thread, turn, tokenUsage={'total': total, 'last': counters(1), 'modelContextWindow': 200000})
    event('item/completed', thread, turn, item={'type': 'agentMessage', 'id': 'reply-'+turn, 'phase': 'final_answer',
        'text': json.dumps({'summary': 'Fixture role completed', 'artifacts': [], 'checks': ['synthetic'], 'limitations': ['No inference occurred']})})
    event('turn/completed', thread, turn, turn={'id': turn, 'status': status, 'items': []})


def tool_call(call_id, name, arguments):
    event('item/started', lead_thread, 'turn-1', item={'type': 'dynamicToolCall', 'id': call_id,
        'namespace': None, 'tool': name, 'arguments': arguments, 'status': 'inProgress',
        'contentItems': None, 'success': None, 'durationMs': None})
    send({'id': call_id, 'method': 'item/tool/call', 'params': {'threadId': lead_thread,
        'turnId': 'turn-1', 'callId': call_id, 'namespace': None, 'tool': name, 'arguments': arguments}})


def shutdown(signum, frame):
    if lead_thread is not None:
        event('thread/status/changed', lead_thread, status={'type': 'idle'})
        event('turn/completed', lead_thread, 'turn-1', turn={'id': 'turn-1', 'status': 'completed'})
        if '--late-usage-on-shutdown' in sys.argv:
            event('thread/tokenUsage/updated', lead_thread, 'turn-1',
                  tokenUsage={'total': counters(2), 'last': counters(1), 'modelContextWindow': 200000})
        event('thread/closed', lead_thread)
    raise SystemExit(0)


signal.signal(signal.SIGTERM, shutdown)


for line in sys.stdin:
    msg = json.loads(line)
    method = msg.get('method')
    if method is None:  # Host response to a lead-selected dynamic call.
        if not msg.get('result', {}).get('success'):
            continue
        result = json.loads(msg['result']['contentItems'][0]['text'])
        if msg['id'] in ('spawn-measure', 'spawn-review'):
            child_ids.append(result['agent_id'])
            if len(child_ids) == 2:
                tool_call('wait-both', 'study_wait', {'agent_ids': child_ids, 'timeout_seconds': 5})
        elif msg['id'].startswith('wait-both'):
            if any(row['state'] not in ('completed', 'failed', 'interrupted') for row in result):
                tool_call(msg['id']+'-next', 'study_wait', {'agent_ids': [row['agent_id'] for row in result if row['state'] not in ('completed', 'failed', 'interrupted')], 'timeout_seconds': 5})
            else:
                finish(lead_thread, 'turn-1')
        continue
    if method == 'initialize':
        send({'id': msg['id'], 'result': {'userAgent': 'fake/0.159.3'}})
    elif method == 'initialized':
        pass
    elif method == 'account/read':
        send({'id': msg['id'], 'result': {'account': {'type': 'chatgpt'}}})
    elif method == 'thread/start':
        sequence += 1
        tid = 'thread-'+str(sequence)
        params = msg['params']
        threads[tid] = {'cwd': params['cwd'], 'turns': 0}
        if params['dynamicTools'] and any(t['name']=='study_spawn' for t in params['dynamicTools']):
            lead_thread = tid
        sandbox = params['config']['sandbox_workspace_write']
        send({'id': msg['id'], 'result': {'thread': {'id': tid, 'cliVersion': '0.159.3',
                'ephemeral': True, 'parentThreadId': None, 'forkedFromId': None},
            'model': params['model'], 'modelProvider': 'openai', 'reasoningEffort': params['config']['model_reasoning_effort'],
            'approvalPolicy': 'never', 'cwd': params['cwd'],
            'sandbox': {'type': 'workspaceWrite', 'writableRoots': sandbox['writable_roots'],
                'networkAccess': False, 'excludeTmpdirEnvVar': True, 'excludeSlashTmp': True}}})
        event('thread/started', tid, thread={'id': tid, 'parentThreadId': None})
    elif method == 'turn/start':
        tid = msg['params']['threadId']
        threads[tid]['turns'] += 1
        turn = 'turn-'+str(threads[tid]['turns'])
        # Deliberately send lifecycle notification BEFORE the matching RPC result.
        event('turn/started', tid, turn, turn={'id': turn, 'status': 'inProgress'})
        send({'id': msg['id'], 'result': {'turn': {'id': turn, 'status': 'inProgress', 'items': []}}})
        if tid == lead_thread:
            tool_call('spawn-measure', 'study_spawn', {'role': 'measurement', 'task': 'Inspect fixture measurement evidence'})
            tool_call('spawn-review', 'study_spawn', {'role': 'reviewer', 'task': 'Independently inspect fixture review evidence'})
        else:
            def delayed(tid=tid, turn=turn):
                time.sleep(.05 if tid == 'thread-2' else .1)
                finish(tid, turn)
            threading.Thread(target=delayed, daemon=True).start()
    elif method in ('turn/steer', 'turn/interrupt'):
        send({'id': msg['id'], 'result': {}})
        if method == 'turn/interrupt':
            event('turn/completed', msg['params']['threadId'], msg['params']['turnId'],
                  turn={'id': msg['params']['turnId'], 'status': 'interrupted'})
