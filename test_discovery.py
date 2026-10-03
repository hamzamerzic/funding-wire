import datetime as dt
import gzip
import hashlib
import json
import tempfile
import unittest
from unittest.mock import patch
from pathlib import Path
import discovery

class DiscoveryTests(unittest.TestCase):
    def test_unsafe_and_non_story_links(self):
        for u in ('http://127.0.0.1/a','https://127.0.0.1/a','javascript:alert(1)','https://x.com/post/1','https://site.com/subscribe'):
            self.assertIsNone(discovery.original_link(u,discovery.HOME))
        self.assertEqual(discovery.original_link('https://tech.eu/2026/05/29/story/',discovery.HOME),'https://tech.eu/2026/05/29/story/')
        self.assertEqual(discovery.original_link(discovery.KNOWN_SOAPBOX, discovery.HOME), discovery.KNOWN_SOAPBOX)
    def test_public_http_allowed_but_private_and_bad_port_blocked(self):
        self.assertEqual(discovery.safe_url('http://example.com/story'), 'http://example.com/story')
        self.assertIsNone(discovery.safe_url('https://example.com:8080/story'))
        self.assertIsNone(discovery.safe_url('http://192.168.1.1/story'))
    def test_bounded_daily_and_no_newsletter_as_record(self):
        issue='https://scaling-europe.beehiiv.com/p/a'
        index=f'<a href="/p/a">A</a><a href="/p/b">B</a><a href="/p/c">C</a>'.encode()
        newsletter=b'<meta property="article:published_time" content="2026-09-28T06:00:00Z"><a href="https://tech.eu/2026/09/28/acme/">Acme raises</a>'
        def cached(url,base,refresh=True,opener=None): return (index if '/p/' not in url else newsletter), 'fresh'
        def evidence(url,*args,**kwargs):
            return {'id':'one','url':url,'title':'Acme raises','published_at':'2026-09-28T06:00:00+00:00','article_text':'publisher','source_id':'discovery'}
        with tempfile.TemporaryDirectory() as d,patch.object(discovery,'cached_html',side_effect=cached),patch.object(discovery,'publisher_evidence',side_effect=evidence) as pub:
            result=discovery.collect_discovery(dt.datetime(2026,10,2,tzinfo=dt.timezone.utc),d,daily=True)
            self.assertEqual(result['sources'][-1]['count'],2)
            self.assertEqual(len(result['items']),1)
            self.assertTrue(result['items'][0]['url'].startswith('https://tech.eu/'))
            self.assertEqual(pub.call_count,1)

    def test_offline_cache_repair_html_rss_or_exact_gap(self):
        with tempfile.TemporaryDirectory() as d:
            root=Path(d); base=root/'discovery';(base/'originals').mkdir(parents=True)
            (base/'raw-originals').mkdir()
            rows=[]
            for n in range(3):
                row={'id':str(n),'title':f'Title {n}','url':f'https://example.com/{n}',
                     'published_at':'2026-09-28T06:00:00+00:00','article_text':'BAD_JSON .noise'}
                rows.append(row)
                (base/'originals'/f'{n}.json').write_text(json.dumps(row))
            (base/'raw-originals/0.html.gz').write_bytes(gzip.compress(
                ('<article><style>.noise{bad:1}</style><script>BAD_JSON</script><p>' + 'Clean HTML publisher prose. '*12 + '</p></article>').encode()))
            (root/'archive-summary.json').write_text(json.dumps({'items':[{
                'url':rows[1]['url'],'article_text':'Clean publisher RSS',
                'evidence_revision':discovery.EVIDENCE_REVISION}]}))
            (base/'backfill-summary.json').write_text(json.dumps({'items':rows,'sources':[],
                                                                  'checked_at':'2026-10-02T00:00:00+00:00'}))
            with patch.object(discovery,'publisher_evidence',side_effect=AssertionError('network forbidden')):
                result=discovery.repair_discovery_cache(root)
            self.assertEqual(len(result['items']),2)
            self.assertEqual(result['cache_repair']['unrecoverable_count'],1)
            self.assertEqual(result['cache_repair']['gaps'][0]['url'],rows[2]['url'])
            self.assertEqual({r['id']:r['article_text'] for r in result['items']},
                             {'0':('Clean HTML publisher prose. '*12).strip(),'1':'Clean publisher RSS'})
            self.assertTrue((base/'corrected-summary-v3.json').exists())
            self.assertEqual({r['id']:r['title'] for r in result['items']},
                             {'0':'Title 0','1':'Title 1'})

    def test_re_evidence_exact_gaps_is_bounded_and_resumable(self):
        with tempfile.TemporaryDirectory() as d:
            base=Path(d)/'discovery';base.mkdir()
            urls=['https://example.com/a','https://example.com/b']
            (base/'corrected-summary-v2.json').write_text(json.dumps({
                'cache_repair':{'gaps':[{'url':u,'reason':'missing raw'} for u in urls]}}))
            def evidence(url,*args,**kwargs):
                self.assertEqual(kwargs['max_attempts'],1)
                return {'id':url,'url':url,'title':'Preserved day',
                        'published_at':'2026-09-22','publication_precision':'day',
                        'article_text':'Original publisher prose','evidence_revision':discovery.EVIDENCE_REVISION}
            with patch.object(discovery,'publisher_evidence',side_effect=evidence) as pub:
                result=discovery.re_evidence_gaps(d)
                self.assertEqual(result['requested_gap_count'],2)
                self.assertEqual(result['attempted_url_count'],4)
                self.assertEqual(len(result['items']),4)
                self.assertEqual(pub.call_count,4)
            with patch.object(discovery,'publisher_evidence',side_effect=AssertionError('no refetch')):
                again=discovery.re_evidence_gaps(d)
            self.assertEqual(len(again['items']),4)

    def test_structural_tfn_repair_is_offline_and_preserves_identity(self):
        url='https://techfundingnews.com/nomos-raises-20m/'
        other='https://example.com/unrepaired'
        with tempfile.TemporaryDirectory() as d:
            base=Path(d)/'discovery';(base/'originals').mkdir(parents=True)
            (base/'re-evidenced-raw').mkdir()
            old={'id':'fixed-id','title':'Original title','url':url,
                 'published_at':'2026-09-22T11:00:00+00:00','article_text':'old sidebar'}
            (base/'originals/old.json').write_text(json.dumps(old))
            key=hashlib.sha256(url.encode()).hexdigest()[:24]
            raw=(b'<html><script type="application/ld+json">'
                 b'{"@type":"NewsArticle","datePublished":"2026-09-22"}</script>'
                 b'<article>Short sidebar</article><article>Another sidebar</article>'
                 b'<div class="entry-content"><style>BAD_CSS</style><script>BAD_JS</script><nav>MENU</nav><p>'
                 + b'Actual publisher body prose. '*12 + b'</p></div></html>')
            (base/'re-evidenced-raw'/(key+'.html.gz')).write_bytes(gzip.compress(raw))
            (base/'re-evidenced-v2.json').write_text(json.dumps({'gaps':[
                {'url':url,'reason':'short sidebar'},{'url':other,'reason':'unchanged'}]}))
            with patch.object(discovery,'publisher_evidence',side_effect=AssertionError('no network')):
                result=discovery.repair_tfn_bodies(d)
            self.assertEqual(result['attempted_tfn_count'],1)
            self.assertEqual(result['repaired_tfn_count'],1)
            self.assertEqual(result['remaining_gap_count'],1)
            self.assertEqual(result['gaps'][0]['url'],other)
            row=result['items'][0]
            self.assertEqual((row['id'],row['title'],row['published_at']),
                             ('fixed-id','Original title','2026-09-22T11:00:00+00:00'))
            self.assertNotIn('BAD_CSS',row['article_text'])
            self.assertNotIn('sidebar',row['article_text'])

    def test_daily_cache_revision_mismatch_uses_saved_re_evidence_raw(self):
        with tempfile.TemporaryDirectory() as d:
            base=Path(d)/'discovery';(base/'originals').mkdir(parents=True)
            (base/'re-evidenced-raw').mkdir()
            url='https://techfundingnews.com/example-story/'
            key=hashlib.sha256(url.encode()).hexdigest()[:24]
            file=base/'originals'/(key+'.json')
            file.write_text(json.dumps({'id':'kept','title':'Kept title','url':url,
                                        'published_at':'2026-09-22','article_text':'old sidebar',
                                        'evidence_revision':2,'evidence_kind':'original_publisher'}))
            raw=(b'<html><article>Sidebar</article><div class="entry-content"><p>'+
                 b'Original publisher body. '*12+b'</p></div></html>')
            (base/'re-evidenced-raw'/(key+'.html.gz')).write_bytes(gzip.compress(raw))
            with patch.object(discovery,'publisher_evidence',side_effect=AssertionError('network forbidden')):
                row=discovery.repair_cached_original(file,{})
            self.assertEqual(row['evidence_revision'],discovery.EVIDENCE_REVISION)
            self.assertEqual((row['id'],row['title'],row['published_at']),
                             ('kept','Kept title','2026-09-22'))
            self.assertNotIn('Sidebar',row['article_text'])

if __name__=='__main__':unittest.main()
