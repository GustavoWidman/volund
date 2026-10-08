import copy
from decimal import Decimal
from pathlib import Path
import sys
import unittest

sys.path.insert(0,str(Path(__file__).resolve().parents[2]))
from runtime.pricing import price_ledger, PricingFailure


def agent(thread='sol-1', model='gpt-6.1-sol', role='lead', incoming=1_000_000,
          read=200_000, output=100_000, writes=0, reasoning=50_000, verified=False):
    return {'agent_id':thread,'thread_id':thread,'model':model,'role':role,
            'token_usage':{'observed_accounting_complete':True,
              'cache_write_reporting_verified':verified,
              'total':{'inputTokens':incoming,'cachedInputTokens':read,'cacheWriteInputTokens':writes,
                       'outputTokens':output,'reasoningOutputTokens':reasoning,'totalTokens':incoming+output}}}


def ledger(*agents):
    return {'agents':list(agents),'accounting_complete':True}


class PricingTests(unittest.TestCase):
    def test_default_zero_write_is_unknown_and_bounds_both_context_bands(self):
        result=price_ledger(ledger(agent()))
        bounds=result['observed_subtotal_bounds']
        self.assertEqual(Decimal(bounds['lower_usd_decimal']),Decimal('2.62'))
        self.assertEqual(Decimal(bounds['upper_usd_decimal']),Decimal('5.54'))
        row=result['threads'][0]
        self.assertEqual(row['cache_write_tokens_considered'],{'minimum':0,'maximum':800000})
        self.assertFalse(row['cache_write_reporting_verified'])
        self.assertIsNone(result['actual_billed_cost'])
        self.assertIsNone(result['whole_run_cost_bounds'])
        self.assertIsNone(result['context_band_threshold_tokens'])

    def test_mixed_models_and_roles_sum_final_endpoints(self):
        a=agent(); b=agent('luna-1','gpt-6-luna','measurement')
        result=price_ledger(ledger(a,b))
        self.assertEqual(Decimal(result['observed_subtotal_bounds']['lower_usd_decimal']),Decimal('2.752'))
        self.assertEqual(Decimal(result['observed_subtotal_bounds']['upper_usd_decimal']),Decimal('5.819'))
        self.assertEqual(result['per_role']['measurement']['observed_subtotal_bounds']['lower_usd'],.132)
        self.assertEqual(result['per_role']['lead']['priced_threads'],1)

    def test_duplicate_thread_is_rejected_even_under_another_role(self):
        row=agent(); duplicate=copy.deepcopy(row);duplicate['role']='reviewer'
        with self.assertRaisesRegex(PricingFailure,'duplicate_thread_id'):
            price_ledger(ledger(row,duplicate))

    def test_missing_usage_is_not_zero_or_whole_run_bound(self):
        missing=agent('missing');missing['token_usage']['total']=None
        result=price_ledger(ledger(agent(),missing))
        self.assertEqual(result['observed_subtotal_bounds']['lower_usd'],2.62)
        self.assertEqual(len(result['missing_usage']),1)
        self.assertFalse(result['observed_accounting_complete'])
        self.assertIsNone(result['whole_run_cost_bounds'])
        self.assertIsNone(price_ledger(ledger(missing))['observed_subtotal_bounds'])
        self.assertIsNone(price_ledger(ledger())['observed_subtotal_bounds'])

    def test_invalid_partition_rejected(self):
        for field,value in [('cachedInputTokens',1000001),('cacheWriteInputTokens',800001),
                            ('reasoningOutputTokens',100001),('totalTokens',1),('inputTokens',-1)]:
            with self.subTest(field=field):
                row=agent();row['token_usage']['total'][field]=value
                with self.assertRaises(PricingFailure):price_ledger(ledger(row))

    def test_no_snapshot_cached_or_reasoning_double_charge(self):
        row=agent();baseline=price_ledger(ledger(row))['observed_subtotal_bounds']
        row['token_usage']['updates']=[{'total':row['token_usage']['total']}] * 100
        row['token_usage']['total']['reasoningOutputTokens']=100000
        polluted=ledger(row);polluted['total_tokens']={'totalTokens':10**15}
        polluted['per_role_tokens']={'lead':{'inputTokens':10**15}}
        self.assertEqual(price_ledger(polluted)['observed_subtotal_bounds'],baseline)

    def test_authoritative_writes_narrow_only_write_uncertainty(self):
        row=agent(writes=100000,verified=True)
        result=price_ledger(ledger(row))
        bounds=result['observed_subtotal_bounds']
        self.assertEqual(bounds['lower_usd'],2.67)
        self.assertEqual(bounds['upper_usd'],4.84)
        self.assertEqual(result['threads'][0]['cache_write_tokens_considered'],{'minimum':100000,'maximum':100000})
        self.assertEqual(result['threads'][0]['context_band'],'unknown')

    def test_missing_write_field_still_priceable_as_observed_interval(self):
        row=agent(writes=None)
        self.assertEqual(price_ledger(ledger(row))['observed_subtotal_bounds']['upper_usd'],5.54)

    def test_all_cached_input_does_not_get_an_ordinary_input_charge(self):
        row=agent(read=1000000)
        bounds=price_ledger(ledger(row))['observed_subtotal_bounds']
        self.assertEqual(bounds['lower_usd'],1.1)
        self.assertEqual(bounds['upper_usd'],1.7)

    def test_regressed_usage_cannot_silently_produce_a_price_interval(self):
        row=agent(); row['token_usage']['issues']=['cumulative_counter_regression']
        with self.assertRaisesRegex(PricingFailure,'regressed_cumulative'):
            price_ledger(ledger(row))

    def test_partial_valid_observation_is_labeled_incomplete(self):
        row=agent(); row['token_usage']['observed_accounting_complete']=False
        row['token_usage']['issues']=['context_capacity_replaced_usage']
        result=price_ledger(ledger(row))
        self.assertEqual(result['observed_subtotal_bounds']['lower_usd'],2.62)
        self.assertFalse(result['observed_accounting_complete'])
        self.assertEqual(len(result['incomplete_usage_threads']),1)
        self.assertIsNone(result['whole_run_cost_bounds'])


if __name__=='__main__':unittest.main()
