import copy
import unittest

from review_import import import_history, import_reviewed, merge_reviewed


def record(ident, **fields):
    return dict(id=ident, company=ident, published_at='2026-05-29',
                sources=[{'name': 'Publisher', 'url': 'https://example.org/' + ident}], **fields)


class HistoryImportTests(unittest.TestCase):
    def test_reviewed_null_replaces_known_amount_without_erasing_unrelated_data(self):
        live = {'records': [record('a', amount_value=15000000, valuation='£2B', owner_note='keep')]}
        incoming = record('a', amount_value=15000000,
                          replace_fields={'amount_value': None, 'amount_kind': 'Facility ceiling'})
        merged = merge_reviewed(live, [incoming], 'now')
        report = merged['records'][0]
        self.assertIsNone(report['amount_value'])
        self.assertEqual(report['amount_kind'], 'Facility ceiling')
        self.assertEqual(report['valuation'], '£2B')
        self.assertEqual(report['owner_note'], 'keep')
        self.assertNotIn('replace_fields', report)
        self.assertEqual(live['records'][0]['amount_value'], 15000000)

    def test_new_report_applies_reviewed_fields_without_persisting_commands(self):
        incoming = record('a', amount_value=15000000, valuation=None, stage='Not stated',
                          replace_fields={'amount_value': None, 'company_key': 'distinctcompany'})
        merged = merge_reviewed({'records': []}, [incoming], 'now')
        self.assertIsNone(merged['records'][0]['amount_value'])
        self.assertEqual(merged['records'][0]['company_key'], 'distinctcompany')
        self.assertNotIn('replace_fields', merged['records'][0])
        self.assertIn('valuation', merged['records'][0])
        self.assertEqual(merged['records'][0]['stage'], 'Not stated')

    def test_replaying_explicit_null_correction_needs_no_write(self):
        incoming = record('a', amount_value=15000000, replace_fields={'amount_value': None})
        live = merge_reviewed({'records': [record('a', amount_value=15000000)]}, [incoming], 'first')
        merged = import_reviewed(133, [incoming], read=lambda _: (live, 'etag'),
                                 write=lambda *_: self.fail('Redundant correction write'))
        self.assertEqual(merged, live)

    def test_correction_retry_preserves_concurrent_daily_report(self):
        snapshots = iter([({'records': [record('a', amount_value=15)]}, 'old'),
                          ({'records': [record('a', amount_value=15), record('daily')]}, 'fresh')])
        writes = []
        def write(feed, etag):
            writes.append(etag)
            return etag == 'fresh'
        merged = import_reviewed(133, [record('a', replace_fields={'amount_value': None})],
                                 read=lambda _: next(snapshots), write=write)
        self.assertEqual({r['id'] for r in merged['records']}, {'a', 'daily'})
        self.assertIsNone(next(r for r in merged['records'] if r['id'] == 'a')['amount_value'])
        self.assertEqual(writes, ['old', 'fresh'])

    def test_history_preserves_current_metadata_extra_fields_and_input(self):
        live = {'records': [record('live', valuation='£2B', owner_note='keep')],
                'checked_at': '2026-10-02', 'evidence_hash': 'daily', 'history': {'note': 'keep'}}
        before = copy.deepcopy(live)
        merged = merge_reviewed(live, [record('old')], 'now')
        self.assertEqual(live, before)
        self.assertEqual(merged['checked_at'], live['checked_at'])
        self.assertEqual(merged['evidence_hash'], 'daily')
        self.assertEqual(merged['history'], live['history'])
        self.assertEqual(next(r for r in merged['records'] if r['id'] == 'live')['owner_note'], 'keep')

    def test_explicit_duplicate_enriches_without_erasing_existing_valuation(self):
        live = {'records': [record('original', valuation='£2B', amount_currency=None)]}
        incoming = record('other', duplicate_of='original', valuation=None, amount_currency='GBP')
        merged = merge_reviewed(live, [incoming], 'now')
        self.assertEqual(len(merged['records']), 1)
        self.assertEqual(merged['records'][0]['valuation'], '£2B')
        self.assertEqual(merged['records'][0]['amount_currency'], 'GBP')
        self.assertEqual(len(merged['records'][0]['sources']), 2)
        self.assertNotIn('duplicate_of', merged['records'][0])

    def test_same_company_different_rounds_are_not_silently_collapsed(self):
        live = {'records': [record('first', company_key='company')]}
        merged = merge_reviewed(live, [record('second', company_key='company')], 'now')
        self.assertEqual(len(merged['records']), 2)

    def test_unresolved_duplicate_fails_before_any_write(self):
        with self.assertRaisesRegex(ValueError, 'Unresolved duplicate'):
            merge_reviewed({'records': []}, [record('a', duplicate_of='missing')], 'now')

    def test_retry_remerges_a_concurrent_daily_report(self):
        snapshots = iter([({'records': [record('a')]}, 'old'),
                          ({'records': [record('a'), record('daily')]}, 'fresh')])
        writes = []
        def write(feed, etag):
            writes.append((feed, etag))
            return etag == 'fresh'
        merged = import_reviewed(133, [record('history')], read=lambda _: next(snapshots), write=write)
        self.assertEqual({r['id'] for r in merged['records']}, {'a', 'daily', 'history'})
        self.assertEqual(len(writes), 2)

    def test_identical_review_is_idempotent_and_needs_no_write(self):
        live = {'records': [record('a')], 'updated_at': 'earlier'}
        merged = import_reviewed(133, [record('a')], read=lambda _: (live, 'etag'),
                                 write=lambda *_: self.fail('Redundant write'))
        self.assertEqual(merged, live)

    def test_capacity_does_not_silently_delete_existing_or_new_history(self):
        live = {'records': [record(str(i)) for i in range(1000)]}
        with self.assertRaisesRegex(ValueError, 'archival retention'):
            merge_reviewed(live, [record('extra')], 'now')
        self.assertEqual(len(live['records']), 1000)

    def test_history_remains_accessible_without_relaxing_the_live_feed_bound(self):
        live = {'records': [record(str(i)) for i in range(1000)]}
        documents = {'feed.json': live, 'history-reports.json': {'records': []}}
        def read(_, path='feed.json', **kwargs):
            return documents[path], 'version'
        def write(_, path, document, etag):
            documents[path] = document
            return True
        current, archive = import_history(133, [record('old')], read=read, write=write)
        self.assertEqual(len(current['records']), 1000)
        self.assertEqual(current, live)
        self.assertEqual(archive['records'][0]['id'], 'old')

    def test_partial_archive_acceptance_can_be_replayed_after_feed_conflict(self):
        documents = {'feed.json': {'records': [record('live', amount_currency=None)]},
                     'history-reports.json': {'records': []}}
        writes = []
        def read(_, path='feed.json', **kwargs):
            return copy.deepcopy(documents[path]), 'version'
        def write(_, path, document, etag):
            writes.append(path)
            if path == 'feed.json' and writes.count(path) == 1:
                documents[path]['records'].append(record('daily'))
                return False
            documents[path] = document
            return True
        current, archive = import_history(133, [record('old'), record('other', duplicate_of='live', amount_currency='USD')], read=read, write=write)
        self.assertEqual({r['id'] for r in current['records']}, {'live', 'daily'})
        self.assertEqual({r['id'] for r in archive['records']}, {'old'})
        self.assertEqual(writes.count('history-reports.json'), 1)
        self.assertEqual(writes.count('feed.json'), 2)


if __name__ == '__main__':
    unittest.main()
