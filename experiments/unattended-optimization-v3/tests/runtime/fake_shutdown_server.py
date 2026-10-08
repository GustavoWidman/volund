"""Local JSON-RPC shutdown fixture. No models or native benchmark processes."""
import json
import signal
import sys
import threading
import time

threads = {}
lock = threading.Lock()


def send(row):
    with lock:
        print(json.dumps(row), flush=True)


def event(method, tid, **params):
    send({'method': method, 'params': {'threadId': tid, 'turnId': 'turn-1', **params}})


def usage(tid, multiplier):
    if '--missing-child-usage' in sys.argv and tid == 'thread-2':
        return
    def counts(n):
        return {'inputTokens': 100*n, 'cachedInputTokens': 20*n, 'cacheWriteInputTokens': 0,
                'outputTokens': 30*n, 'reasoningOutputTokens': 10*n, 'totalTokens': 130*n}
    event('thread/tokenUsage/updated', tid,
          tokenUsage={'total': counts(multiplier), 'last': counts(1), 'modelContextWindow': 200000})


def shutdown(signum, frame):
    if '--delay-shutdown' in sys.argv:
        time.sleep(.1)
    for tid in threads:
        usage(tid, 3)
        event('thread/status/changed', tid, status={'type': 'idle'})
        event('thread/closed', tid)
    print('UNRETAINED_STDERR', file=sys.stderr, flush=True)
    raise SystemExit(0)


signal.signal(signal.SIGTERM, shutdown)
for line in sys.stdin:
    row=json.loads(line); method=row.get('method'); params=row.get('params', {})
    result={}
    if method == 'initialized':
        continue
    if method == 'initialize':
        result={'userAgent': 'fake/0.159.3'}
    elif method == 'account/read':
        result={'account': {'type': 'chatgpt'}}
    elif method == 'thread/start':
        tid='thread-'+str(len(threads)+1); threads[tid]=params
        result={'thread': {'id': tid,'cliVersion': '0.159.3','ephemeral': True},
                'model': params['model'], 'modelProvider': 'openai',
                'reasoningEffort': params['config']['model_reasoning_effort'],
                'approvalPolicy': 'never', 'cwd': params['cwd'],
                'sandbox': {'type': 'workspaceWrite','writableRoots': [],'networkAccess': False,
                            'excludeTmpdirEnvVar': True,'excludeSlashTmp': True}}
    elif method == 'turn/start':
        tid=params['threadId']
        event('turn/started',tid,turn={'id':'turn-1','status':'inProgress'})
        usage(tid,1)
        result={'turn': {'id': 'turn-1','status': 'inProgress'}}
    elif method == 'turn/interrupt':
        tid=params['threadId']
        if '--bad-event-before-usage' in sys.argv:
            event('turn/completed',tid,turn={'id':'turn-1','status':'invalid'})
        if '--unresponsive-interrupt' in sys.argv:
            continue
        usage(tid,2)
        event('turn/completed',tid,turn={'id':'turn-1','status':'interrupted'})
        if '--delay-interrupt-ack' in sys.argv:
            def reply(request_id=row['id']):
                time.sleep(.1)
                send({'id':request_id,'result':{}})
            threading.Thread(target=reply,daemon=True).start()
            continue
    send({'id': row['id'], 'result': result})
