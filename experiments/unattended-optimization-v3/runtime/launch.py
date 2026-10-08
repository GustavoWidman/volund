"""Direct-terminal entry point. Never run this from a nested Codex task.

This runner does NOT manufacture approval. The owner must supply an approved
preflight manifest and explicitly invoke it from their terminal. No default
manifest, API credentials, fallback models, or experimental campaigns are used.
"""
from __future__ import annotations
import argparse
import asyncio
import json
from pathlib import Path
from .contracts import APPROVED_MODELS, RoleSpec, Safeguards, RuntimeFailure
from .multiagent import Host, TERMINAL
from .transport import StdioRPC


async def run_manifest(config, *, direct_terminal_authorized=False, rpc=None):
    if config.get('phase') != 'integration-preflight' or config.get('owner_approved') is not True:
        raise RuntimeFailure('approved_integration_preflight_required')
    if any(key in config for key in ('wall_seconds', 'token_budget', 'reviewer_seconds')):
        raise RuntimeFailure('superseded_budget_config')
    roles = {}
    for role, (model, effort) in APPROVED_MODELS.items():
        row = config['roles'][role]
        if (row['model'], row['effort']) != (model, effort):
            raise RuntimeFailure('unapproved_role_model')
        roles[role] = RoleSpec(model, effort, Path(row['cwd']),
                              tuple(Path(p) for p in row['writable_roots']), row['instructions'])
    safeguards = Safeguards(config.get('rpc_admission_timeout_seconds', 120.0))
    rpc = rpc or StdioRPC.official(roles['lead'].cwd,
        direct_terminal_authorized=direct_terminal_authorized,
        request_timeout=safeguards.rpc_admission_timeout_seconds)
    host = Host(rpc, roles, safeguards, config['evidence_dir'])
    outcome, cleanup = None, None
    try:
        await rpc.open()
        await host.initialize()
        lead = await host.spawn('lead', config['task'])
        while True:
            await host.enforce_safeguards()
            if host.failure or rpc.failure:
                raise RuntimeFailure(host.failure or rpc.failure)
            if all(a.state in TERMINAL for a in host.agents.values()):
                break
            host.changed.clear()
            try:
                await asyncio.wait_for(host.changed.wait(), .1)
            except asyncio.TimeoutError:
                pass
        outcome = host.export()
    except (RuntimeFailure, KeyboardInterrupt, asyncio.CancelledError) as exc:
        host.failure = str(exc) if isinstance(exc, RuntimeFailure) else 'operator_interrupt'
        await host.stop(host.failure)
    finally:
        cleanup = await rpc.close()
        if not cleanup.get('tracked_processes_exited', False):
            host.failure = host.failure or 'process_cleanup_incomplete'
        if not cleanup.get('event_stream_drained', False):
            host.failure = host.failure or 'shutdown_event_drain_incomplete'
        if all(a.state in TERMINAL for a in host.agents.values()):
            host.seal()
        outcome = host.export()
        outcome['cleanup'] = cleanup
        outcome['measured_campaign'] = False
        path = host.evidence_dir / 'telemetry.json'
        with path.open('x', encoding='utf-8') as stream:
            json.dump(outcome, stream, indent=2)
            stream.write('\n')
    return outcome


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--config', type=Path, required=True)
    parser.add_argument('--direct-terminal-authorized', action='store_true')
    args = parser.parse_args()
    # Config is owner-authored research metadata, never the authentication home.
    config = json.loads(args.config.read_text())
    result = asyncio.run(run_manifest(config, direct_terminal_authorized=args.direct_terminal_authorized))
    print(json.dumps({'accounting_complete': result['accounting_complete'],
                      'failure': result['failure'], 'evidence_dir': config['evidence_dir']}))
    return 0 if result['accounting_complete'] and not result['failure'] else 1


if __name__ == '__main__':
    raise SystemExit(main())
