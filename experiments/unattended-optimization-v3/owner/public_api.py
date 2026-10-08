"""Explicit public parameter vocabulary, shared by schemas and owner handlers."""
import copy
import inspect
from development.schema import RequestArgumentsError

ENUMS={
 ('history','collection'):('hypotheses','queue','nominations','reviews','closures','promotions','trajectories','journal'),
 ('hypothesis','claim_kind'):('performance','correctness','profile','resource','buildability'),
 ('report_hypothesis','disposition'):('supported','contradicted','inconclusive'),
 ('queue','status'):('actionable','resolved','retired'),
 ('review_target','target_kind'):('nomination','hypothesis','closure'),
 ('inspect','target_kind'):('source','evidence','closure'),
 ('claim_review','assessment'):('endorsed','needs_work'),
 ('nomination_review','recommendation'):('approve','reject','needs_work'),
 ('closure_review','decision'):('endorse','continue'),
}

TEXT={'type':'string','minLength':1,'pattern':r'\S'}
IDS={'type':'array','items':{'type':'string','minLength':1}}
PARAMETERS={
 'collection':{'type':'string','description':'Own-campaign factual record collection; large numeric usage histories are separate artifacts.'},
 'record_id':{'type':['string','null'],'description':'Optional exact record ID from compact status; omit/null to page the selected collection.'},
 'offset':{'type':'integer','minimum':0,'description':'Zero-based record offset; use next_offset to continue.'},
 'limit':{'type':'integer','minimum':1,'maximum':20,'description':'Records per page, not a limit on investigations or history length.'},
 'source_hash':{'type':['string','null'],'description':'Exact immutable source hash from study_dev_snapshot/index or study_owner_status. When optional, omit or use null for the documented current source.'},
 'evidence_ids':{**IDS,'description':'Recorded development operation IDs from study_dev_* results/index; do not use source hashes, plan IDs or inspection IDs.'},
 'failed_evidence_ids':{**IDS,'description':'For reject/needs_work only: your own failed official exact-source operations, inspected first. Omit for the complete successful review route.'},
 'text':{**TEXT,'description':'Factual text. Corrections append a new entry; empty text is a correctable request error.'},
 'corrects':{'type':['string','null'],'description':'Optional prior owner journal ID to correct; retrieve it from study_owner_status. Omit/null for a new entry.'},
 'mechanism':dict(TEXT),'predictions':dict(TEXT),'against':dict(TEXT),'metrics':dict(TEXT),'risks':dict(TEXT),
 'exploratory':{'type':'boolean','description':'True labels an exploratory follow-up; false registers a prospective hypothesis.'},
 'claim_kind':{'type':'string','description':'Required empirical evidence: performance=bench+profile; correctness=test; profile=profile; resource=memcheck; buildability=build.'},
 'hypothesis_id':{**TEXT,'description':'Existing hypothesis ID returned by study_owner_hypothesis/status.'},
 'disposition':{'type':'string','description':'Scientific outcome of the hypothesis prediction. Independent reviewer assessment uses different verdict labels.'},
 'observations':dict(TEXT),'limits':{'type':'string','description':'Bounded uncertainties; may be omitted or empty if no additional limits are supplied.'},
 'experiment':dict(TEXT),'motivation':dict(TEXT),'observable':dict(TEXT),'decision_impact':dict(TEXT),
 'queue_id':{'type':['string','null'],'description':'Existing queue ID for an update; omit/null to create an item.'},
 'status':{'type':'string','description':'actionable keeps work open; resolved/retired require factual evidence IDs. Reviewers may add actionable concerns; only lead records disposition.'},
 'claim':dict(TEXT),'nomination_id':{**TEXT,'description':'Existing nomination ID from study_owner_nominate/status.'},
 'reason':dict(TEXT),'target_kind':{'type':'string'},
 'target_id':{**TEXT,'description':'ID for the selected target_kind, never a caller-supplied role or authority.'},
 'assessment':{'type':'string','description':'endorsed means your own evidence supports the reported conclusion, whether supported, contradicted or inconclusive. needs_work means the report needs further work. This is not the hypothesis disposition.'},
 'explanation':dict(TEXT),'build_id':{**TEXT,'description':'Your recorded reviewer build operation ID. For a failed-build rejection, provide that failed build ID and failed_evidence_ids.'},
 'recommendation':{'type':'string','description':'approve requests mechanical promotion gates; reject records no promotion; needs_work asks for repair/further evidence. Failed official execution can use failed_evidence_ids without invented passes.'},
 'uncertainties':dict(TEXT),'branch_dispositions':dict(TEXT),
 'closure_id':{**TEXT,'description':'Closure dossier ID returned by study_owner_propose_closure.'},
 'decision':{'type':'string','description':'endorse closes the task only after required review evidence and an empty actionable queue; continue records more work.'},
 'endpoint_build_id':{'type':['string','null'],'description':'Required for endorsing an unpromoted seed endpoint: your own complete official endpoint-review build ID. Omit/null when reusing a promoted independently verified endpoint.'},
}


def allowed_value(method, field, value):
    choices=ENUMS[(method,field)]
    if value not in choices:
        raise RequestArgumentsError('study_owner_'+method,[{'field':field,'allowed_values':list(choices),
            'message':f'{field} must be one of: {", ".join(choices)}.'}])
    return value


def input_schema(method, function):
    props={};required=[]
    for key,param in inspect.signature(function).parameters.items():
        if key in ('self','agent'):continue
        if key not in PARAMETERS:raise RuntimeError('Missing explicit public parameter contract: '+method+'.'+key)
        schema=copy.deepcopy(PARAMETERS[key])
        if (method,key) in ENUMS:schema['enum']=list(ENUMS[(method,key)])
        if param.default is inspect.Parameter.empty:
            required.append(key)
            if isinstance(schema.get('type'),list):schema['type']=[t for t in schema['type'] if t!='null']
        else:
            schema['default']=param.default
            if param.default is None:
                types=schema['type'] if isinstance(schema['type'],list) else [schema['type']]
                schema['type']=list(dict.fromkeys([*types,'null']))
        props[key]=schema
    for key in ('source_hash','queue_id','corrects','endpoint_build_id'):
        if key in props:props[key].update(minLength=1,pattern=r'\S')
    if method in ('report_hypothesis','claim_review'):props['evidence_ids']['minItems']=1
    if method=='review_target':props['target_id']['description']='Nomination, reported hypothesis, or closure ID from owner status. Binding yields the exact source and official reference for your own review.'
    if method=='inspect':props['target_id']['description']='source: bound exact source hash; evidence: bound-source development operation ID; closure: bound closure dossier ID. Bind the relevant review target first.'
    return {'type':'object','additionalProperties':False,'properties':props,'required':required}
