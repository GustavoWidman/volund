"""Context-size and concurrent-read/cancellation checks, no model calls."""
import json
import threading
import time
import unittest
import test_owner as fixture
from development.core import Cancelled

class CompactStatusTests(unittest.TestCase):
    setUp=fixture.OwnerIntegration.setUp
    tearDown=fixture.OwnerIntegration.tearDown
    actor=fixture.OwnerIntegration.actor
    call=fixture.OwnerIntegration.call
    def test_status_never_returns_large_usage_histories(self):
        self.owner.state['trajectories']=[{'source_hash':'a'*64,'operation_id':'op-1','status':'pass',
           'summary':{'portfolio_speedup':1.1},'observed_role_usage':{'updates':['large-history']*100000}}]
        self.owner._change('test_large_usage',{'synthetic':True})
        answer=self.call(self.lead,'status')
        payload=json.dumps(answer)
        self.assertNotIn('large-history',payload)
        self.assertNotIn('observed_role_usage',payload)
        self.assertLess(len(payload),20000)
        self.assertEqual(answer['recent_trajectories'][0]['operation_id'],'op-1')
    def test_complete_records_remain_pageable(self):
        for i in range(35):
            self.owner.state['hypotheses'][f'h-{i}']={'id':f'h-{i}','disposition':'open',
                'mechanism':'complete-mechanism-'+str(i)+'x'*400,'predictions':'all detail retained'}
        self.owner._change('test_many_records',{'synthetic':True})
        answer=self.call(self.lead,'status')
        self.assertEqual(answer['counts']['hypotheses'],35)
        self.assertEqual(answer['omitted_summary_records']['hypotheses'],15)
        page=self.call(self.lead,'history',collection='hypotheses',offset=20,limit=15)
        self.assertEqual(len(page['records']),15)
        self.assertEqual(page['records'][-1]['id'],'h-34')
        self.assertGreater(len(page['records'][-1]['mechanism']),400)
    def test_status_and_history_do_not_wait_for_execution_lock(self):
        entered=threading.Event();release=threading.Event()
        def hold():
            with self.owner.lock:entered.set();release.wait(2)
        worker=threading.Thread(target=hold);worker.start();self.assertTrue(entered.wait(1))
        try:
            start=time.monotonic();self.call(self.lead,'status')
            self.call(self.lead,'history',collection='journal')
            self.assertLess(time.monotonic()-start,.2)
        finally:release.set();worker.join()
    def test_stop_flag_visible_before_long_owner_lock_releases(self):
        entered=threading.Event();release=threading.Event()
        def hold():
            with self.owner.lock:entered.set();release.wait(2)
        worker=threading.Thread(target=hold);worker.start();self.assertTrue(entered.wait(1))
        stopper=threading.Thread(target=self.owner.stop,args=('synthetic_cancel',));stopper.start()
        try:
            deadline=time.monotonic()+1
            while not self.owner.cancelled and time.monotonic()<deadline:time.sleep(.005)
            self.assertTrue(self.owner.cancelled)
            with self.assertRaises(Cancelled):self.owner.owner_service().grant()
        finally:release.set();worker.join();stopper.join()
