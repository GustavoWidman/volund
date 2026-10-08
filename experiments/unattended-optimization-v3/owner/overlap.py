"""Backstop audit for unleased execution and independently attested interruptions.

Bounded read tools are real reads, not commands. General shell execution is
routed through the coordinator. This module never labels shell text harmless.
"""
import threading
import time
from development.core import write_new

RETRY_POLICY = 'infrastructure_only_first_valid_v1'
RETRYABLE_REASONS = {'competing_study_command_execution', 'attested_external_interruption'}


class MeasurementInterrupted(RuntimeError):
    """Owner-only notification of external preemption after verified cleanup.

    Never construct this from a candidate exit, resource limit, timeout, bad
    score, generic exception, or a participant-supplied tool argument.
    """
    def __init__(self, *, observer, event_id, cleanup_confirmed):
        if not isinstance(observer, str) or not observer.strip() or not isinstance(event_id, str) or not event_id.strip():
            raise ValueError('external interruption needs observer and event evidence')
        if cleanup_confirmed is not True:
            raise ValueError('retryable interruption requires confirmed cleanup')
        self.attestation = {'observer': observer, 'event_id': event_id,
                            'cleanup_confirmed': True, 'cause': 'external_preemption'}
        super().__init__('attested external measurement interruption')


class CommandIntervals:
    def __init__(self):self.lock=threading.RLock();self.rows={}
    def event(self,msg):
        method=msg.get('method');params=msg.get('params') or {};item=params.get('item') or {}
        if method in ('turn/completed','thread/closed'):
            self.mark_unresolved('command_end_missing_at_'+method.replace('/','_'),thread_id=params.get('threadId'))
            return
        if method not in ('item/started','item/completed') or item.get('type')!='commandExecution':return
        key=(params.get('threadId'),item.get('id'))
        with self.lock:
            row=self.rows.setdefault(key,{'thread_id':key[0],'item_id':key[1],'start':None,'end':None})
            field='startedAtMs' if method=='item/started' else 'completedAtMs'
            value=params.get(field);when=value/1000 if type(value) in (int,float) else time.time()
            if method=='item/started':row['start']=when
            else:
                row['end']=when
                if row['start'] is None:
                    duration=item.get('durationMs')
                    row['start']=when-duration/1000 if type(duration) in (int,float) else None
            row['timestamp_provenance']='runtime_wall_timestamp' if type(value) in (int,float) else 'notification_receipt_or_duration'
    def overlaps(self,start,end):
        with self.lock:
            return [dict(row) for row in self.rows.values() if (row['start'] is None or row['start']<end) and (row['end'] is None or row['end']>start)]

    def active(self):
        with self.lock:
            return [dict(row) for row in self.rows.values() if row['end'] is None]

    def mark_unresolved(self, reason, *, thread_id=None):
        """Terminal/failed event streams cannot establish that open commands ended."""
        with self.lock:
            for row in self.rows.values():
                if row['end'] is None and (thread_id is None or row['thread_id']==thread_id):
                    row['cleanup_uncertainty']=reason

    def unresolved(self):
        with self.lock:
            return [dict(row) for row in self.rows.values() if row['end'] is None and row.get('cleanup_uncertainty')]


class AuditedBackend:
    def __init__(self,backend,commands):self.backend,self.commands=backend,commands
    def __getattr__(self,name):return getattr(self.backend,name)
    def execute(self,kind,context,out):
        if kind!='bench':
            return self.backend.execute(kind,context,out)
        start=time.time();interruption=None;result=None;error=None
        try:
            result=self.backend.execute(kind,context,out)
        except MeasurementInterrupted as exc:
            interruption=exc.attestation
            result={'status':'infra_error','summary':'Measurement externally interrupted after confirmed cleanup'}
        except BaseException as exc:
            error=exc
        end=time.time();overlap=self.commands.overlaps(start,end)
        audit={'native_start_unix':start,'native_end_unix':end,'ordinary_command_overlaps':overlap,
               'status':'invalid_overlap' if overlap else 'no_observed_overlap',
               'external_interruption':interruption,
               'backend_exception':type(error).__name__ if error else None,
               'limitation':'Unleased study-command event audit; external host load and missed command events are not ruled out'}
        write_new(out/'ordinary-command-overlap.json',audit)
        if error is not None:
            raise error
        result={**result,'ordinary_command_overlap_audit':audit}
        # Never hide a candidate/correctness/resource failure behind overlap.
        negative=(result.get('confirmed_semantic_failure') is True or result.get('confirmed_memory_error') is True)
        reason=('attested_external_interruption' if interruption else
                'competing_study_command_execution' if overlap and result.get('status')=='pass' else None)
        if reason and not negative:
            result.update(status='infra_error',measurement_invalidated=reason,
                          measurement_retry_policy=RETRY_POLICY,measurement_retry_authorized=True)
        return result
