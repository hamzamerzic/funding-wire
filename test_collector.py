import datetime as dt
from io import BytesIO
import unittest
import unittest.mock as mock
import xml.etree.ElementTree as ET

import collector
import job

NOW = dt.datetime(2026, 10, 2, tzinfo=dt.timezone.utc)
SOURCE = collector.SOURCES[0]


def item(title, description='Current article', date='Thu, 01 Oct 2026 12:00:00 GMT'):
    node = ET.Element('item')
    for tag, value in [('title', title), ('link', 'https://example.org/story?utm=x'),
                       ('pubDate', date), ('description', description)]:
        ET.SubElement(node, tag).text = value
    return node


class CollectorTests(unittest.TestCase):
    def setUp(self):
        env = mock.patch.dict(job.os.environ, {'APP_JOB_STATE_DIR': '/test/job-state'})
        env.start()
        self.addCleanup(env.stop)
        rates = mock.patch.object(job, 'refresh_rates')
        self.rates_mock = rates.start()
        self.addCleanup(rates.stop)

    def test_reference_rates_are_inverted_to_usd_per_currency_unit(self):
        rows=b'[{"base":"USD","quote":"EUR","rate":0.8,"date":"2026-10-01"}]'
        with mock.patch.object(collector.urllib.request,'urlopen',return_value=BytesIO(rows)) as opener:
            rates=collector.fetch_rates(opener)
        self.assertEqual(rates['usd_per_unit'],{'USD':1.0,'EUR':1.25})
        self.assertEqual(rates['date'],'2026-10-01')

    def test_failed_currency_check_does_not_write_or_erase_the_cache(self):
        with mock.patch.object(job,'fetch_rates',side_effect=ValueError('bad')), mock.patch.object(job,'request') as request:
            # Call the owning implementation, not the admission-test mock.
            self.refresh_rates_impl(42,'test')
        request.assert_not_called()

    refresh_rates_impl = staticmethod(job.refresh_rates)

    def test_acquisition_headline_is_only_evidence_not_a_funding_record(self):
        evidence = collector.item_evidence(item('Ampol to buy startup for $225 million'), SOURCE, NOW)
        self.assertIsNotNone(evidence)
        self.assertNotIn('company', evidence)
        self.assertNotIn('amount', evidence)
        self.assertNotIn('backers', evidence)

    def test_fund_close_can_be_reviewed_but_never_regex_misclassified(self):
        evidence = collector.item_evidence(item('VC closes $400M fund'), SOURCE, NOW)
        self.assertIsNotNone(evidence)
        self.assertEqual(evidence['url'], 'https://example.org/story')
        self.assertNotIn('stage', evidence)

    def test_old_article_is_not_reintroduced_as_current(self):
        self.assertIsNone(collector.item_evidence(
            item('Startup raises $4M', date='Tue, 01 Sep 2020 12:00:00 GMT'), SOURCE, NOW))

    def test_full_article_text_is_cleaned_without_inventing_investors(self):
        evidence = collector.item_evidence(item('Startup raises $4M', '<p>Founders Alice and Bob.</p><p>Prior round was led by Old VC.</p>'), SOURCE, NOW)
        self.assertIn('Founders Alice and Bob.', evidence['article_text'])
        self.assertIn('Old VC', evidence['article_text'])
        self.assertNotIn('backers', evidence)

    def test_all_sources_failing_reports_error_without_touching_feed(self):
        bad = {'version': 1, 'checked_at': NOW.isoformat(), 'sources': [{'ok': False}], 'items': []}
        with mock.patch.object(job, 'collect_public_evidence', return_value=bad), mock.patch.object(job, 'read_state', return_value=(None, None)), mock.patch.object(job, 'set_state') as state, mock.patch.object(job, 'request') as request:
            with self.assertRaisesRegex(RuntimeError, 'existing verified feed retained'):
                job.run(42, 'test-token', NOW)
        request.assert_not_called()
        self.rates_mock.assert_not_called()
        self.assertEqual(state.call_args.args[2]['phase'], 'error')

    def test_job_stores_evidence_and_starts_idempotent_app_chat_only(self):
        snapshot = {'version': 1, 'checked_at': NOW.isoformat(), 'sources': [{'id':'test','ok': True}], 'items': []}
        with mock.patch.object(job, 'collect_public_evidence', return_value=snapshot), mock.patch.object(job, 'read_state', return_value=(None, None)), mock.patch.object(job, 'set_state') as state, mock.patch.object(job, 'request', side_effect=[None, None, {'chat_id':'chat-1','outcome':'started'}]) as request:
            self.assertEqual(job.run(42, 'test-token', NOW)['outcome'], 'started')
        self.assertEqual(request.call_args_list[0].args[0], '/api/storage/apps/42/feed.json')
        self.assertTrue(request.call_args_list[1].args[0].startswith('/api/storage/apps/42/evidence/'))
        self.assertEqual(request.call_args_list[1].kwargs['headers'], {'If-None-Match': '*'})
        self.assertEqual(request.call_args_list[2].args[0], '/api/app-chats/start')
        self.assertEqual(state.call_args.args[2]['chat_id'], 'chat-1')
        self.assertFalse(any('feed.json' in call.args[0] and call.kwargs.get('method') == 'PUT' for call in request.call_args_list))

    def test_unchanged_evidence_skips_paid_agent(self):
        snapshot = {'version': 1, 'sources': [{'id':'test','ok': True}], 'items': []}
        digest = job.evidence_hash(snapshot)
        with mock.patch.object(job, 'collect_public_evidence', return_value=snapshot), mock.patch.object(job, 'read_state', return_value=(None,None)), mock.patch.object(job, 'set_state') as state, mock.patch.object(job, 'request', return_value={'evidence_hash':digest}) as request:
            self.assertEqual(job.run(42, 'test-token', NOW)['outcome'], 'unchanged')
        self.assertEqual(request.call_count, 1)
        self.rates_mock.assert_called_once_with(42, 'test-token')
        self.assertEqual(state.call_args.args[2]['phase'], 'unchanged')

    def test_active_review_is_reused_but_stopped_review_can_retry(self):
        snapshot = {'version': 1, 'sources': [{'id':'test','ok': True}], 'items': []}
        digest = job.evidence_hash(snapshot)
        prior = {'phase':'reviewing','evidence_hash':digest,'chat_id':'old','started_at':NOW.isoformat()}
        with mock.patch.object(job, 'collect_public_evidence', return_value=snapshot) as collect, mock.patch.object(job, 'read_state', return_value=(prior,'etag')), mock.patch.object(job, 'set_state'), mock.patch.object(job, 'request', return_value=[{'id':'old','running':True}]) as request:
            self.assertEqual(job.run(42, 'test-token', NOW)['outcome'], 'reviewing')
        self.assertEqual(request.call_count, 1)
        collect.assert_not_called()

    def test_concurrent_source_completion_order_does_not_spend_another_agent_turn(self):
        source=[{'id':'a','ok':True},{'id':'b','ok':True}]
        items=[{'id':'1','title':'a','article_text':'a'},{'id':'2','title':'b','article_text':'b'}]
        self.assertEqual(job.evidence_hash({'sources':source,'items':items}),job.evidence_hash({'sources':source[::-1],'items':items[::-1]}))

    def test_late_admission_receipt_never_overwrites_completed_review(self):
        with mock.patch.object(job,'read_state',return_value=({'run_id':'same','phase':'complete'},'etag')), mock.patch.object(job,'request') as request:
            job.set_state(42,'test',{'run_id':'same','phase':'reviewing'},only_if_run='same')
        request.assert_not_called()

    def test_stopped_review_gets_a_new_attempt_not_reused_failed_scope(self):
        prior={'phase':'reviewing','chat_id':'old','run_id':'old-run'}
        snapshot={'sources':[{'id':'test','ok':True}],'items':[]}
        with mock.patch.object(job,'read_state',return_value=(prior,'etag')), mock.patch.object(job,'set_state'), mock.patch.object(job,'collect_public_evidence',return_value=snapshot), mock.patch.object(job,'request',side_effect=[[{'id':'old','running':False}],None,None,{'chat_id':'new','outcome':'started'}]) as request:
            result=job.run(42,'test',NOW)
        self.assertEqual(result['chat_id'],'new')
        self.assertNotIn('old-run',request.call_args.kwargs['body']['scope'])

    def test_discovery_failure_does_not_erase_rss_or_block_its_review(self):
        rss = {'sources': [{'id': 'rss', 'ok': True}], 'items': [{'id': 'one', 'title': 'Raises', 'article_text': 'Evidence'}]}
        with mock.patch.object(job, 'collect', return_value=rss), mock.patch.object(job, 'collect_discovery', side_effect=OSError('offline')):
            result = job.collect_public_evidence(NOW)
        self.assertEqual(result['items'], rss['items'])
        self.assertFalse(result['sources'][-1]['ok'])
        self.assertEqual(result['sources'][-1]['name'], 'Scaling Europe discovery')

    def test_newsletter_is_discovery_not_a_second_copy_of_original_story(self):
        rss = {'sources': [{'id': 'rss', 'ok': True}], 'items': [{'id': 'one', 'title': 'Raises', 'article_text': 'Short evidence'}]}
        discovery = {'sources': [{'id': 'newsletter', 'ok': True}], 'items': [{'id': 'one', 'title': 'Raises', 'article_text': 'Longer original publisher evidence'}]}
        with mock.patch.object(job, 'collect', return_value=rss), mock.patch.object(job, 'collect_discovery', return_value=discovery):
            result = job.collect_public_evidence(NOW)
        self.assertEqual(len(result['items']), 1)
        self.assertEqual(result['items'][0]['article_text'], discovery['items'][0]['article_text'])
        self.assertEqual(len(result['sources']), 2)

    def test_publication_date_correction_is_reviewed_not_skipped_as_unchanged(self):
        earlier = {'sources': [{'id': 'rss', 'ok': True}], 'items': [{'id': 'one', 'title': 'Raises', 'article_text': 'Evidence', 'published_at': '2026-09-01'}]}
        corrected = {**earlier, 'items': [{**earlier['items'][0], 'published_at': '2026-09-02'}]}
        self.assertNotEqual(job.evidence_hash(earlier), job.evidence_hash(corrected))


if __name__ == '__main__':
    unittest.main()
