"""Explicit no-inference CLI workspace/supervisor setup probe; one output path."""
from __future__ import annotations
import asyncio
import base64
import hashlib
import json
import os
from pathlib import Path
import sys
import time

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
from runtime.transport import StdioRPC
from runtime.contracts import initialize_params,RoleSpec,start_thread_params,validate_thread_response,sandbox,thread_start_metadata

async def main():
    out=ROOT/'setup/workspace-cli-probe-01';out.mkdir(parents=True,exist_ok=False)
    actor=out/'actor';actor.mkdir();outside=out/'outside';outside.mkdir()
    rpc=StdioRPC.official(actor,direct_terminal_authorized=True)
    report={'schema_version':1,'status':'running','model_turns_requested':0,'started_unix':time.time(),'checks':[]}
    supervisor=ROOT/'runtime/command_supervisor.py'
    try:
        await rpc.open();await rpc.request('initialize',initialize_params());await rpc.send({'method':'initialized','params':{}})
        account=await rpc.request('account/read',{'refreshToken':False})
        if (account.get('account') or {}).get('type')!='chatgpt':raise RuntimeError('unexpected_auth_mode')
        spec=RoleSpec('gpt-6.1-sol','high',actor,(actor,),'Setup metadata only. No turn may start.')
        response=await rpc.request('thread/start',start_thread_params('lead',spec))
        validate_thread_response(response,spec)
        report['thread_start_metadata']=thread_start_metadata(response)
        report['requested_shell_tool_enabled']=False
        cases=[('normal','printf ready',0),('background','sleep 20 >/dev/null 2>&1 & exit 0',0),
               ('outside_write',f"printf no > '{outside}/forbidden'",None),
               ('network',"/usr/bin/python3 -c 'import socket; s=socket.create_connection((\"1.1.1.1\",80),timeout=0.5); s.close()'",None)]
        for name,command,expected in cases:
            capture=actor/name;capture.mkdir()
            data={'invocation_id':name,'command':command,'cwd':str(actor),'actor_root':str(actor),
                  'output_directory':str(capture),'timeout_seconds':3,'path':os.defpath,'cpus':[]}
            raw=json.dumps(data,sort_keys=True,separators=(',',':')).encode()
            result=await rpc.request('command/exec',{'command':[sys.executable,'-B',str(supervisor),base64.b64encode(raw).decode()],
                   'cwd':str(actor),'sandboxPolicy':sandbox(spec),'processId':'setup-'+name,
                   'disableTimeout':True,'outputBytesCap':65536})
            # Persist only our supervisor protocol and controlled command output.
            (out/(name+'-rpc.json')).write_text(json.dumps(result,indent=2)+'\n')
            receipt=json.loads(result['stdout'])
            ok=(result['exitCode']==0 and receipt['cleanup_complete'] is True and receipt['remaining_direct_children']==[]
                and receipt['spec_sha256']==hashlib.sha256(raw).hexdigest()
                and receipt['supervisor_sha256']==hashlib.sha256(supervisor.read_bytes()).hexdigest())
            if expected is not None:ok=ok and receipt['root_exit_code']==expected
            else:ok=ok and receipt['root_exit_code']!=0
            if name=='outside_write':ok=ok and not (outside/'forbidden').exists()
            report['checks'].append({'name':name,'pass':ok,'root_exit_code':receipt['root_exit_code'],
                                     'cleanup_complete':receipt['cleanup_complete'],'reason':receipt['reason']})
            if not ok:raise RuntimeError('workspace_probe_check_failed_'+name)
        report['status']='pass'
    except BaseException as exc:
        report['status']='failed';report['error_category']=type(exc).__name__;report['safe_error']=str(exc) if isinstance(exc,(ValueError,RuntimeError)) else None
    finally:
        report['cleanup']=await rpc.close();report['finished_unix']=time.time()
        (out/'result.json').write_text(json.dumps(report,indent=2)+'\n')
        print(json.dumps({'status':report['status'],'output':str(out/'result.json'),'model_turns_requested':0}))
    return 0 if report['status']=='pass' else 1

if __name__=='__main__':raise SystemExit(asyncio.run(main()))
