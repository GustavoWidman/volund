"""Owner-direct-terminal diagnostic: initialize/account-mode/thread-start only.

There is no model turn, task prompt, shell tool, or inference method in this
script. It retains only allowlisted startup metadata, unsubscribes the ephemeral
thread, and drains/cleans up the app-server. Existing output paths are refused.
"""
from __future__ import annotations

import argparse
import asyncio
import json
from pathlib import Path

from .contracts import (APPROVED_MODELS, RoleSpec, RuntimeFailure, initialize_params,
                        sandbox, start_thread_params, thread_start_metadata,
                        validate_thread_response)
from .transport import StdioRPC


async def diagnose(output_dir, *, direct_terminal_authorized=False, rpc=None):
    output_dir = Path(output_dir).resolve()
    # Constructing this guard performs no launch and refuses implicit permission.
    if rpc is None and direct_terminal_authorized is not True:
        raise RuntimeFailure('direct_terminal_launch_not_authorized')
    output_dir.mkdir(parents=True, exist_ok=False)
    workspace = output_dir / 'scratch'
    workspace.mkdir()
    spec = RoleSpec(*APPROVED_MODELS['lead'], workspace, (workspace,),
                    'Startup metadata diagnostic only. No model turn is authorized.')
    rpc = rpc or StdioRPC.official(workspace, direct_terminal_authorized=direct_terminal_authorized)
    report = {'schema_version': 1, 'stage': 'thread_start_metadata_only',
              'turn_start_sent': False, 'model_activity_observed': False,
              'account_mode': None, 'failure': None, 'thread_start_metadata': None,
              'requested': {'model': spec.model, 'reasoningEffort': spec.effort,
                            'modelProvider': 'openai', 'cwd': str(spec.cwd),
                            'approvalPolicy': 'never', 'sandbox': sandbox(spec)},
              'validation_passed': False, 'unsubscribe_status': None,
              'event_counts': {}, 'raw_content_retained': False}

    def on_event(msg):
        method = msg.get('method', '')
        lifecycle = ('thread/started', 'thread/status/changed', 'thread/closed')
        category = method if method in lifecycle else 'other'
        if method.startswith(('turn/', 'item/', 'rawResponse')) or method == 'thread/tokenUsage/updated':
            report['model_activity_observed'] = True
            report['failure'] = 'unexpected_model_activity'
            category = 'unexpected_model_activity'
        report['event_counts'][category] = report['event_counts'].get(category, 0) + 1

    rpc.on_event = on_event
    thread_id = None
    try:
        await rpc.open()
        await rpc.request('initialize', initialize_params())
        await rpc.send({'method': 'initialized', 'params': {}})
        account = await rpc.request('account/read', {'refreshToken': False})
        report['account_mode'] = 'chatgpt' if (account.get('account') or {}).get('type') == 'chatgpt' else 'unapproved'
        del account
        if report['account_mode'] != 'chatgpt':
            raise RuntimeFailure('chatgpt_auth_required')
        response = await rpc.request('thread/start', start_thread_params('lead', spec))
        report['thread_start_metadata'] = thread_start_metadata(response)
        thread_id = report['thread_start_metadata']['thread']['id']
        validate_thread_response(response, spec)
        report['validation_passed'] = True
    except (RuntimeFailure, KeyboardInterrupt, asyncio.CancelledError) as exc:
        report['failure'] = report['failure'] or (str(exc) if isinstance(exc, RuntimeFailure) else 'operator_interrupt')
    except Exception:
        report['failure'] = report['failure'] or 'diagnostic_internal_error'
    finally:
        if thread_id and not rpc.failure:
            try:
                result = await rpc.request('thread/unsubscribe', {'threadId': thread_id})
                status = result.get('status')
                report['unsubscribe_status'] = status if status in ('unsubscribed', 'notLoaded', 'notSubscribed') else 'invalid'
            except RuntimeFailure:
                report['unsubscribe_status'] = 'request_failed'
        report['cleanup'] = await rpc.close()
        report['failure'] = report['failure'] or rpc.failure
        if not report['cleanup'].get('event_stream_drained'):
            report['failure'] = report['failure'] or 'shutdown_event_drain_incomplete'
        if not report['cleanup'].get('tracked_processes_exited'):
            report['failure'] = report['failure'] or 'process_cleanup_incomplete'
        with (output_dir / 'diagnostic.json').open('x', encoding='utf-8') as stream:
            json.dump(report, stream, indent=2)
            stream.write('\n')
    return report


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output-dir', type=Path, required=True)
    parser.add_argument('--direct-terminal-authorized', action='store_true')
    args = parser.parse_args()
    result = asyncio.run(diagnose(args.output_dir, direct_terminal_authorized=args.direct_terminal_authorized))
    print(json.dumps({'diagnostic': str(args.output_dir / 'diagnostic.json'),
                      'validation_passed': result['validation_passed'], 'failure': result['failure']}))
    return 0 if not result['failure'] else 1


if __name__ == '__main__':
    raise SystemExit(main())
