"""Exact source, preflight, deployment and readiness gates. No inference."""
from __future__ import annotations
import json
import dataclasses
from pathlib import Path
from development.core import IntegrityError, encoded, digest, file_hash, tree, write_new
from .service import load
from development.native_backend import NativeBackend,NativeConfig,ProcessLimits
from runtime.transport import CLI

EXECUTION_AREAS=('owner','runtime','development','task','tools')
FROZEN_AREAS=EXECUTION_AREAS+('protocol','evaluation')
REQUIRED_CHECKS=('real_multiagent_preflight','native_aa','wrong_result_mutants','input_mutation',
                 'resource_and_timeout_controls','reviewer_reexecution','source_binding',
                 'journal_corrections','descendant_accounting','endpoint_embargo','final_evaluator_verified')


def code_manifest(root,areas=EXECUTION_AREAS):
    root=Path(root).resolve(strict=True);files={}
    for area in areas:
        path=root/area
        if not path.is_dir():raise IntegrityError('required frozen area absent: '+area)
        for file in sorted(path.rglob('*')):
            if '__pycache__' in file.parts or file.suffix=='.pyc':continue
            if file.is_symlink():raise IntegrityError('symlink in executable/frozen materials')
            if file.is_file():files[str(file.relative_to(root))]=file_hash(file)
    return {'root':str(root),'files':files,'sha256':digest(encoded(files))}


def check_manifest(root,manifest):
    if manifest.get('root')!=str(Path(root).resolve()):raise IntegrityError('deployment directory differs from verified absolute path')
    for relative,expected in manifest['files'].items():
        path=Path(root)/relative
        if not path.is_file() or path.is_symlink() or file_hash(path)!=expected:raise IntegrityError('verified material changed: '+relative)
    if digest(encoded(manifest['files']))!=manifest['sha256']:raise IntegrityError('manifest digest inconsistent')


def evidence_file(root,item):
    path=(Path(root)/item['path']).resolve()
    if not path.is_relative_to(Path(root).resolve()) or not path.is_file() or path.is_symlink():raise IntegrityError('readiness evidence path invalid')
    if file_hash(path)!=item['sha256']:raise IntegrityError('readiness evidence hash mismatch')
    return path


def native_configuration(path):
    row=load(path)
    def guard(value):
        if isinstance(value,dict):
            for key,child in value.items():guard(key);guard(child)
        elif isinstance(value,(list,tuple)):
            for child in value:guard(child)
        elif isinstance(value,str) and value.startswith('/') and any(x in Path(value).parts for x in ('.study-codex-runtime','.aws','.ssh','.codex')):
            raise IntegrityError('native artifact configuration cannot refer to authentication/private runtime paths')
    guard(row)
    for key in ('ordinary','diagnostic'):
        values=dict(row[key]);values['cpus']=tuple(values['cpus']);row[key]=ProcessLimits(**values)
    if 'allowed_suites' in row:row['allowed_suites']=tuple(row['allowed_suites'])
    return NativeConfig(**row)


def final_configurations(root,readiness_path=None):
    ready=load(readiness_path or Path(root)/'evaluation/readiness.json')
    if ready.get('status')!='ready':raise IntegrityError('final evaluator is not verified ready')
    if set(ready.get('configurations',{}))!={'transfer','shift'}:raise IntegrityError('both final strata configurations required')
    result={}
    for name,item in ready['configurations'].items():
        path=evidence_file(root,item);config=native_configuration(path)
        if config.paired_blocks!=30 or config.benchmark_suite!=name:raise IntegrityError('final stratum/block config mismatch')
        NativeBackend(config).verify();result[name]=config
    return result


def freeze_runtime_artifacts(root,final_readiness_path):
    root=Path(root);artifacts={}
    native=root/'setup/launch-native/native-config.json'
    if not native.is_file():raise IntegrityError('real deployed native preparation missing')
    configurations=[native_configuration(native),*final_configurations(root,final_readiness_path).values()]
    artifacts[str(native.resolve())]=file_hash(native)
    from .deployment import official_artifacts
    artifacts.update(official_artifacts())
    for config in configurations:
        NativeBackend(config).verify();artifacts.update(config.pinned_files)
    ready=load(final_readiness_path)
    for item in ready['configurations'].values():
        path=evidence_file(root,item);artifacts[str(path)]=file_hash(path)
    artifacts.update(ready.get('artifact_files',{}))
    for path,expected in artifacts.items():
        p=Path(path)
        if not p.is_absolute() or any(x in p.parts for x in ('.study-codex-runtime','.aws','.ssh','.codex')):
            raise IntegrityError('invalid artifact pin path; no authentication metadata access')
        if not p.is_file() or p.is_symlink() or file_hash(p)!=expected:raise IntegrityError('runtime artifact changed')
    return artifacts


def create_freeze(root,readiness_path,preflight_path):
    root=Path(root).resolve(strict=True);ready=load(readiness_path);preflight=load(preflight_path)
    if preflight.get('status')!='pass' or preflight.get('real_runtime_observed') is not True:raise IntegrityError('actual preflight pass required')
    check_manifest(root,preflight['execution_manifest'])
    if code_manifest(root)['sha256']!=preflight['execution_manifest']['sha256']:raise IntegrityError('execution inventory drift since actual preflight')
    if ready.get('status')!='ready' or ready.get('campaign_count')!=3:raise IntegrityError('explicit owner readiness missing')
    for key in REQUIRED_CHECKS:
        item=ready.get('checks',{}).get(key)
        if not item or item.get('status')!='pass':raise IntegrityError('readiness control incomplete: '+key)
        evidence_file(root,item)
    final_manifest=evidence_file(root,ready['final_evaluator_manifest'])
    runtime_artifacts=freeze_runtime_artifacts(root,final_manifest)
    manifest=code_manifest(root,FROZEN_AREAS)
    config=load(root/'owner/config.draft.json')
    if any(config.get(k) is not None for k in ('campaign_wall_cap','reviewer_wall_cap','token_cap')):raise IntegrityError('superseded research caps')
    freeze={'schema_version':2,'manifest':manifest,'readiness_sha256':file_hash(readiness_path),
            'readiness_path':str(Path(readiness_path).resolve()),'preflight_sha256':file_hash(preflight_path),
            'preflight_path':str(Path(preflight_path).resolve()),'final_evaluator_manifest_sha256':file_hash(final_manifest),
            'runtime_artifacts':runtime_artifacts,
            'campaign_count':3,'config':config,'status':'frozen'}
    path=root/'state/freeze.json';path.parent.mkdir(exist_ok=True);write_new(path,freeze)
    return {'freeze_path':str(path),'freeze_sha256':file_hash(path),'manifest_sha256':manifest['sha256']}


def verify_authorization(root,authorization_path):
    root=Path(root).resolve(strict=True);authorization=load(authorization_path);freeze_path=root/'state/freeze.json'
    if authorization.get('action')!='launch_three_fresh_campaigns' or authorization.get('authorized') is not True:
        raise IntegrityError('explicit measured launch gate missing')
    if file_hash(freeze_path)!=authorization.get('freeze_sha256'):raise IntegrityError('authorized freeze hash differs')
    freeze=load(freeze_path);check_manifest(root,freeze['manifest'])
    current=code_manifest(root,FROZEN_AREAS)
    if current!=freeze['manifest']:raise IntegrityError('frozen file inventory drift')
    for key in ('readiness','preflight'):
        if file_hash(freeze[key+'_path'])!=freeze[key+'_sha256']:raise IntegrityError(key+' evidence changed')
    for path,expected in freeze.get('runtime_artifacts',{}).items():
        if not Path(path).is_file() or Path(path).is_symlink() or file_hash(path)!=expected:raise IntegrityError('frozen runtime/fixture artifact changed')
    if authorization.get('readiness_sha256')!=freeze['readiness_sha256'] or authorization.get('preflight_sha256')!=freeze['preflight_sha256']:
        raise IntegrityError('authorization evidence binding mismatch')
    return freeze


def authorize_freeze(root,freeze_sha256,readiness_sha256,preflight_sha256):
    """Explicit owner handoff after review; exact hashes, no inference or retry."""
    root=Path(root).resolve(strict=True);launch=root/'state/launch'
    if load(launch/'status.json').get('status')!='awaiting_exact_owner_readiness_no_inference':
        raise IntegrityError('launcher is not awaiting its owner readiness handoff')
    freeze=load(root/'state/freeze.json')
    if (file_hash(root/'state/freeze.json'),freeze['readiness_sha256'],freeze['preflight_sha256'])!=(freeze_sha256,readiness_sha256,preflight_sha256):
        raise IntegrityError('explicit authorization hashes differ from freeze')
    authorization={'authorized':True,'action':'launch_three_fresh_campaigns','freeze_sha256':freeze_sha256,
                   'readiness_sha256':readiness_sha256,'preflight_sha256':preflight_sha256}
    path=launch/'authorization.json';write_new(path,authorization)
    verify_authorization(root,path)
    return {'authorization_path':str(path),'status':'authorized_exact_frozen_workflow'}
