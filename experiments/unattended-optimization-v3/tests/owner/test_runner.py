"""Real Host + owner + development dispatch, scripted JSON-RPC peer, fake native work.

No Codex process, model call, authenticated API or measured native workload runs.
"""
import asyncio
import json
from pathlib import Path
import sys
import tempfile
import unittest

ROOT=Path(__file__).resolve().parents[2];sys.path.insert(0,str(ROOT));sys.path.insert(0,str(Path(__file__).parent))
from test_owner import FakeBackend
from owner.runner import run_workflow,inspect_preflight
from owner.service import load
from runtime.contracts import sandbox


class ScriptedRPC:
    def __init__(self,cwd):
        self.cwd=cwd;self.failure=None;self.rows={};self.sequence=0;self.tool_sequence=0;self.tasks=[];self.errors=[];self.shared={};self.hypothesis_disposition='contradicted'
    async def open(self):pass
    async def send(self,msg):pass
    async def close(self):
        await asyncio.gather(*self.tasks,return_exceptions=True)
        return {'tracked_processes_exited':True,'event_stream_drained':True,'event_processing_complete':True,'synthetic_transport':True}
    async def request(self,method,p):
        if method=='initialize':return {}
        if method=='account/read':return {'account':{'type':'chatgpt'}}
        if method=='thread/start':
            self.sequence+=1;tid='thread-'+str(self.sequence)
            self.rows[tid]={'role':Path(p['cwd']).parent.name,'turn':0,'params':p}
            s=p['config']['sandbox_workspace_write']
            return {'thread':{'id':tid,'cliVersion':'0.159.3','ephemeral':True},'model':p['model'],'modelProvider':'openai',
                    'reasoningEffort':p['config']['model_reasoning_effort'],'approvalPolicy':'never','cwd':p['cwd'],
                    'sandbox':{'type':'workspaceWrite','writableRoots':s['writable_roots'],'networkAccess':False,'excludeTmpdirEnvVar':True,'excludeSlashTmp':True}}
        if method=='turn/start':
            tid=p['threadId'];self.rows[tid]['turn']+=1;turn='turn-'+str(self.rows[tid]['turn'])
            self.tasks.append(asyncio.create_task(self.script(tid,turn,p['input'][0]['text'])))
            return {'turn':{'id':turn}}
        if method=='turn/interrupt':return {}
        raise AssertionError(method)
    async def tool(self,tid,name,args):
        self.tool_sequence+=1;turn='turn-'+str(self.rows[tid]['turn'])
        r=await self.on_request({'threadId':tid,'turnId':turn,'callId':'call-'+str(self.tool_sequence),'tool':name,'arguments':args,'namespace':None})
        if not r['success']:raise AssertionError(r)
        result=json.loads(r['contentItems'][0]['text'])
        if isinstance(result,dict) and result.get('status') in ('request_error','integrity_stop','cancelled'):
            raise AssertionError(result)
        return result
    async def wait(self,tid,agent):
        while True:
            rows=await self.tool(tid,'study_wait',{'agent_ids':[agent],'timeout_seconds':1})
            if rows[0]['state']=='completed':return rows[0]
            if rows[0]['state'] in ('failed','startup_failed','interrupted'):raise AssertionError(rows)
    async def suite(self,tid,source,official=False):
        purpose={'purpose':'official_review'} if official else {}
        b=await self.tool(tid,'study_dev_build',{'source_hash':source,**purpose});ops={}
        for kind in ('test','profile','memcheck','bench'):
            extra={'fixture_id':'public-profile'} if kind=='profile' else {}
            ops[kind]=await self.tool(tid,'study_dev_'+kind,{'build_id':b['operation_id'],**purpose,**extra})
        return b,ops
    async def inspect(self,tid,source,ops):
        await self.tool(tid,'study_owner_inspect',{'target_kind':'source','target_id':source})
        for kind in ('profile','bench'):
            await self.tool(tid,'study_owner_inspect',{'target_kind':'evidence','target_id':ops[kind]['operation_id']})
    async def script(self,tid,turn,task):
        await asyncio.sleep(0)
        role=self.rows[tid]['role']
        try:
            if role=='lead':
                status=await self.tool(tid,'study_owner_status',{});source=status['seed']['source_hash'];self.shared['source']=source
                h=await self.tool(tid,'study_owner_hypothesis',{'mechanism':'Synthetic unchanged code cannot supply a real optimization mechanism','predictions':'unchanged source remains neutral' if self.hypothesis_disposition=='supported' else 'claimed speedup exceeds threshold','against':'independent seed comparison remains neutral','metrics':'paired performance ratio','risks':'Synthetic fixture only','evidence_ids':[]})
                self.shared['hypothesis']=h['id']
                measurement=await self.tool(tid,'study_spawn',{'role':'measurement','task':'baseline'})
                await self.wait(tid,measurement['agent_id'])
                implementation=await self.tool(tid,'study_spawn',{'role':'implementation','task':'repair'})
                await self.wait(tid,implementation['agent_id'])
                await self.tool(tid,'study_message',{'agent_id':implementation['agent_id'],'task':'followup'})
                await self.wait(tid,implementation['agent_id'])
                self.tool_sequence+=1
                invalid=await self.on_request({'threadId':tid,'turnId':turn,'callId':'invalid-'+str(self.tool_sequence),'tool':'study_owner_journal','arguments':{'text':''}})
                self.shared['invalid']=json.loads(invalid['contentItems'][0]['text'])
                await self.tool(tid,'study_owner_journal',{'text':'Recorded synthetic failure, repair, and unchanged source','evidence_ids':[self.shared['measurement_bench']]})
                await self.tool(tid,'study_owner_report_hypothesis',{'hypothesis_id':h['id'],'disposition':self.hypothesis_disposition,'observations':'Synthetic ratio is one','evidence_ids':[self.shared['measurement_bench']],'source_hash':source,'limits':'Only a scripted integration fixture'})
                n=await self.tool(tid,'study_owner_nominate',{'hypothesis_id':h['id'],'source_hash':source,'claim':'Unchanged-seed setup gate','evidence_ids':[self.shared['measurement_bench']]});self.shared['nomination']=n['id']
                review=await self.tool(tid,'study_spawn',{'role':'reviewer','task':'nomination'})
                await self.wait(tid,review['agent_id'])
                await self.tool(tid,'study_message',{'agent_id':review['agent_id'],'task':'hypothesis'})
                await self.wait(tid,review['agent_id'])
                closure=await self.tool(tid,'study_owner_propose_closure',{'uncertainties':'Synthetic transport and native operations only','branch_dispositions':'Intentional compile error repaired; no code promoted','reason':'All scripted discriminating checks are now closed'})
                self.shared['closure']=closure['id']
                await self.tool(tid,'study_message',{'agent_id':review['agent_id'],'task':'closure'})
                await self.wait(tid,review['agent_id'])
            elif role=='measurement':
                b,ops=await self.suite(tid,self.shared['source']);self.shared['measurement_bench']=ops['bench']['operation_id']
            elif role=='implementation':
                if task=='followup':
                    await self.tool(tid,'study_dev_test',{'build_id':self.shared['implementation_build']})
                else:
                    checkout=await self.tool(tid,'study_owner_checkout',{})
                    path=Path(checkout['candidate_directory'])/'engine.cpp';original=path.read_text();path.write_text(original+'#error V2_PREFLIGHT_REPAIR\n')
                    bad=await self.tool(tid,'study_dev_snapshot',{'candidate':str(path.parent)})
                    failed=await self.tool(tid,'study_dev_build',{'source_hash':bad['source_hash']});assert failed['status']=='candidate_failure'
                    path.write_text(original);good=await self.tool(tid,'study_dev_snapshot',{'candidate':str(path.parent)})
                    b,ops=await self.suite(tid,good['source_hash']);self.shared['implementation_build']=b['operation_id']
            elif role=='reviewer':
                key={'nomination':'nomination','hypothesis':'hypothesis','closure':'closure'}[task]
                await self.tool(tid,'study_owner_review_target',{'target_kind':key,'target_id':self.shared[key]})
                b,ops=await self.suite(tid,self.shared['source'],True);await self.inspect(tid,self.shared['source'],ops)
                if task=='nomination':
                    await self.tool(tid,'study_owner_nomination_review',{'nomination_id':self.shared[key],'build_id':b['operation_id'],'recommendation':'reject','explanation':'Unchanged exact source is not an improvement'})
                elif task=='hypothesis':
                    await self.tool(tid,'study_owner_claim_review',{'hypothesis_id':self.shared[key],'assessment':'endorsed','evidence_ids':[ops['profile']['operation_id'],ops['bench']['operation_id']],'explanation':'Own synthetic benchmark and profile support the negative finding'})
                else:
                    await self.tool(tid,'study_owner_inspect',{'target_kind':'closure','target_id':self.shared[key]})
                    await self.tool(tid,'study_owner_closure_review',{'closure_id':self.shared[key],'decision':'endorse','explanation':'No concrete scripted work remains','endpoint_build_id':b['operation_id']})
            n=self.rows[tid]['turn'];last={'inputTokens':100,'cachedInputTokens':20,'cacheWriteInputTokens':0,'outputTokens':30,'reasoningOutputTokens':10,'totalTokens':130};total={k:v*n for k,v in last.items()}
            self.on_event({'method':'thread/tokenUsage/updated','params':{'threadId':tid,'turnId':turn,'tokenUsage':{'last':last,'total':total}}})
            report=json.dumps({'summary':'Synthetic integration task completed','artifacts':[],'checks':['Synthetic actual service dispatch'],'limitations':['No model/native execution']})
            self.on_event({'method':'item/completed','params':{'threadId':tid,'turnId':turn,'item':{'type':'agentMessage','id':'report-'+turn,'phase':'final_answer','text':report}}})
            self.on_event({'method':'turn/completed','params':{'threadId':tid,'turn':{'id':turn,'status':'completed'}}})
        except BaseException as exc:
            self.errors.append(repr(exc));self.failure='scripted_fixture_failed'
            self.on_event({'method':'turn/completed','params':{'threadId':tid,'turn':{'id':turn,'status':'failed'}}})


class StopRPC(ScriptedRPC):
    def __init__(self,cwd):
        super().__init__(cwd);self.started=asyncio.Event();self.release=asyncio.Event();self.closing=asyncio.Event();self.close_count=0
    async def request(self,method,p):
        if method=='turn/interrupt':self.release.set();return {}
        return await super().request(method,p)
    async def script(self,tid,turn,task):
        self.started.set();await self.release.wait();await asyncio.sleep(.02)
        numeric={'inputTokens':90,'cachedInputTokens':30,'cacheWriteInputTokens':0,'outputTokens':7,'reasoningOutputTokens':3,'totalTokens':97}
        self.on_event({'method':'thread/tokenUsage/updated','params':{'threadId':tid,'turnId':turn,'tokenUsage':{'last':numeric,'total':numeric}}})
        self.on_event({'method':'turn/completed','params':{'threadId':tid,'turn':{'id':turn,'status':'interrupted'}}})
    async def close(self):
        self.close_count+=1;self.closing.set()
        await asyncio.gather(*self.tasks);await asyncio.sleep(.05)
        return {'tracked_processes_exited':True,'event_stream_drained':True,'event_processing_complete':True,'synthetic_transport':True}


class FullRunnerTest(unittest.IsolatedAsyncioTestCase):
    async def test_actual_host_dispatch_and_owner_closure_with_fake_peer(self):
        await self._scenario('contradicted')

    async def test_supported_exact_seed_no_code_result_keeps_new_workspace_gates(self):
        await self._scenario('supported')

    async def test_workflow_stop_shields_reader_and_retains_late_interrupted_usage(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);(root/'task/seed').mkdir(parents=True);(root/'task/seed/engine.cpp').write_text('int source=1;\n')
            (root/'task/contract').mkdir();(root/'task/contract/SPEC.md').write_text('Synthetic')
            cfg=load(ROOT/'owner/config.draft.json');made=[]
            def factory(cwd):peer=StopRPC(cwd);made.append(peer);return peer
            task=asyncio.create_task(run_workflow(root,root/'setup/stopping',FakeBackend(),cfg,setup=True,rpc_factory=factory))
            while not made:await asyncio.sleep(0)
            await made[0].started.wait();task.cancel()
            await made[0].closing.wait();task.cancel()  # A second cancellation must not cancel drain.
            owner,telemetry=await asyncio.wait_for(task,2)
            self.assertEqual(made[0].close_count,1)
            self.assertTrue(telemetry['cleanup']['event_stream_drained'])
            self.assertEqual(telemetry['total_tokens']['totalTokens'],97)
            self.assertFalse(telemetry['accounting_complete'])
            self.assertEqual(owner.state['status'],'incomplete')
            self.assertEqual(telemetry['failure'],'owner_stop_requested')
            self.assertEqual(load(owner.directory/'telemetry.json')['total_tokens']['totalTokens'],97)

    async def _scenario(self, disposition):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);(root/'task/seed').mkdir(parents=True);(root/'task/seed/engine.cpp').write_text('int source=1;\n')
            (root/'task/contract').mkdir();(root/'task/contract/SPEC.md').write_text('Synthetic')
            cfg=load(ROOT/'owner/config.draft.json');cfg['bootstrap_resamples']=100
            backend=FakeBackend();backend.ratios=[1.0]*10;made=[]
            def factory(cwd):peer=ScriptedRPC(cwd);peer.hypothesis_disposition=disposition;made.append(peer);return peer
            owner,telemetry=await asyncio.wait_for(run_workflow(root,root/'setup/preflight',backend,cfg,setup=True,rpc_factory=factory),10)
            self.assertEqual(made[0].errors,[])
            self.assertEqual(owner.state['status'],'complete');self.assertTrue(telemetry['accounting_complete'])
            report=inspect_preflight(owner,telemetry,{'root':str(root),'files':{},'sha256':'synthetic'})
            # This scripted peer exercises the owner workflow, but it does not
            # call the newly required real workspace routes. It must not be
            # mistaken for a complete v3 launch preflight.
            self.assertEqual(report['status'],'fail',report)
            missing={name for name,passed in report['checks'].items() if not passed}
            self.assertEqual(missing,{'participant_bounded_workspace_read_observed',
                                      'participant_sandboxed_workspace_exec_observed'})
            self.assertFalse(report['real_runtime_observed'])
            self.assertEqual(telemetry['total_tokens']['totalTokens'],130*7)
            self.assertEqual(owner.state['promotions'],[])


if __name__=='__main__':unittest.main(verbosity=2)
