import datetime as dt
import json
import html
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
import archive

UTC=dt.timezone.utc

def rss(day, link='https://example.com/story', title='Acme raises seed'):
    return f'<rss><channel><item><title>{title}</title><link>{link}</link><pubDate>{day}</pubDate><guid>{link}</guid></item></channel></rss>'.encode()

class Response:
    def __init__(self, raw, url): self.raw=raw;self.url=url
    def __enter__(self): return self
    def __exit__(self,*a): pass
    def read(self,n): return self.raw[:n]
    def geturl(self): return self.url

class ArchiveTests(unittest.TestCase):
    def test_window_inclusive_april_2_october_2(self):
        self.assertLessEqual(archive.START,dt.datetime(2026,4,2,0,tzinfo=UTC))
        self.assertLess(dt.datetime(2026,10,2,23,59,tzinfo=UTC),archive.END)
        self.assertFalse(archive.START<=dt.datetime(2026,4,1,23,59,tzinfo=UTC))
    def test_repeated_page_stops_and_resume_no_refetch(self):
        calls=[]
        def fake(url,limit,opener=None):
            calls.append(url)
            if '/feed/' in url:return rss('Thu, 01 Oct 2026 12:00:00 GMT'),url
            return b'<html><head><meta property="article:published_time" content="2026-10-01T12:00:00Z"><title>Acme raises seed</title></head><article>Publisher evidence sentence. Publisher evidence sentence. Publisher evidence sentence. Publisher evidence sentence. Publisher evidence sentence. Publisher evidence sentence. Publisher evidence sentence. Publisher evidence sentence. Publisher evidence sentence. Publisher evidence sentence. </article></html>',url
        with tempfile.TemporaryDirectory() as d, patch.object(archive,'fetch',side_effect=fake):
            h,rows=archive.collect_source(('x','X','https://example.com/feed/','World'),d,max_pages=5)
            self.assertEqual(h['status'],'repeated_page'); self.assertEqual(len(rows),1)
            n=len(calls)
            archive.collect_source(('x','X','https://example.com/feed/','World'),d,max_pages=5)
            self.assertEqual(len(calls),n)
            self.assertTrue((Path(d)/'archive/x/pages/001.xml').exists())
    def test_cutoff_and_no_semantic_guess(self):
        with tempfile.TemporaryDirectory() as d:
            def fake(url,limit,opener=None):
                if 'feed' in url:return rss('Wed, 01 Apr 2026 12:00:00 GMT'),url
                raise AssertionError('older article should not fetch')
            with patch.object(archive,'fetch',side_effect=fake):
                h,rows=archive.collect_source(('x','X','https://example.com/feed/','World'),d)
            self.assertEqual(h['status'],'reached_cutoff');self.assertEqual(rows,[])
    def test_chronology_gap_and_cross_source_url_dedup(self):
        pages=[rss('Thu, 01 Oct 2026 12:00:00 GMT',link='https://example.com/one'),
               rss('Thu, 01 Jan 2026 12:00:00 GMT',link='https://example.com/two')]
        def fake(url,limit,opener=None):
            if '/feed/' in url: return (pages[1] if 'paged=2' in url else pages[0]),url
            return b'<html><meta property="article:published_time" content="2026-10-01T12:00:00Z"><title>A</title><article>body</article></html>',url
        with tempfile.TemporaryDirectory() as d,patch.object(archive,'fetch',side_effect=fake):
            h,_=archive.collect_source(('x','X','https://example.com/feed/','World'),d)
            self.assertTrue(any(g['reason']=='possible_interpage_gap' for g in h['gaps']))
        row={'url':'https://example.com/one','published_at':'2026-10-01T12:00:00+00:00'}
        with tempfile.TemporaryDirectory() as d,patch.object(archive,'collect_source',side_effect=[({'id':'a'},[row]),({'id':'b'},[row])]):
            result=archive.collect_archive(d,[('a',),('b',)])
            self.assertEqual(len(result['items']),1)

    def test_ambiguous_publisher_date(self):
        raw=b'<meta property="article:published_time" content="2026-05-01T00:00:00Z"><meta property="article:published_time" content="2026-06-01T00:00:00Z">'
        self.assertIsNone(archive.html_timestamp(raw))
        self.assertIsNone(archive.html_timestamp(b'<script type="application/ld+json">{"datePublished":"2026-09-22"}</script>'))

    def test_reported_article_day_is_not_fabricated_timestamp(self):
        raw=(b'<script type="application/ld+json">'
             b'{"@type":"NewsArticle","datePublished":"2026-09-22"}'
             b'</script><article>' + b'Original publisher text. '*12 + b'</article>')
        self.assertEqual(archive.html_publication(raw),('2026-09-22','day'))
        self.assertTrue(archive.in_window('2026-04-02'))
        self.assertFalse(archive.in_window('2026-04-01'))
        with patch.object(archive,'fetch',return_value=(raw,'https://example.com/story')):
            row=archive.publisher_evidence('https://example.com/story','x','X','World')
        self.assertEqual(row['published_at'],'2026-09-22')
        self.assertEqual(row['publication_precision'],'day')
        conflict=raw.replace(b'</script>',b'</script><meta property="article:published_time" content="2026-09-23">')
        self.assertEqual(archive.html_publication(conflict),(None,None))

    def test_extraction_skips_scripts_styles_and_navigation(self):
        raw=b'<html><nav>MENU</nav><article><style>.noise{bad:1}</style><script>BAD_JSON</script><p>Actual publisher prose</p></article></html>'
        self.assertEqual(archive.extracted_text(raw), 'Actual publisher prose')

    def test_sidebar_articles_before_balanced_entry_content(self):
        raw=(b'<html><article><p>Short sidebar card</p></article>'
             b'<article><p>Another sidebar card</p></article>'
             b'<main><div class="entry-content"><p>First publisher paragraph.</p>'
             b'<nav>Navigation noise</nav><script>BAD_JSON</script>'
             b'<style>.noise{bad:1}</style><div><p>Second publisher paragraph.</p></div>'
             b'</div></main></html>')
        self.assertEqual(archive.extracted_text(raw),
                         'First publisher paragraph.\nSecond publisher paragraph.')
        self.assertEqual(archive.extracted_text(
            b'<html><article>Short sidebar card</article><article>Another card</article></html>'), '')

    def test_stale_archive_cache_repaired_from_saved_rss_without_fetch(self):
        url='https://example.com/story'
        markup='<article><nav>MENU</nav><script>BAD_JSON</script><style>.noise{bad:1}</style><p>Clean original RSS prose</p></article>'
        xml=(f'<rss><channel><item><title>Acme raises seed</title><link>{url}</link>'
             f'<pubDate>Thu, 01 Oct 2026 12:00:00 GMT</pubDate>'
             f'<description>{html.escape(markup)}</description></item></channel></rss>').encode()
        with tempfile.TemporaryDirectory() as d:
            base=Path(d)/'archive/x'; (base/'pages').mkdir(parents=True); (base/'articles').mkdir()
            (base/'pages/001.xml').write_bytes(xml)
            row={'id':'identity','title':'Preserved title','url':url,
                 'published_at':'2026-10-01T12:00:00+00:00','article_text':'BAD_JSON .noise'}
            file=base/'articles/old.json';file.write_text(json.dumps(row))
            state={'next_page':2,'page_signatures':[],'seen_ids':[],
                   'pages':[{'page':1,'oldest':row['published_at'],'newest':row['published_at']}],
                   'gaps':[],'terminal':'reached_cutoff'}
            (base/'state.json').write_text(json.dumps(state))
            with patch.object(archive,'fetch',side_effect=AssertionError('network forbidden')):
                _,rows=archive.collect_source(('x','X','https://example.com/feed/','World'),d)
            self.assertEqual(len(rows),1)
            self.assertEqual(rows[0]['article_text'],'Clean original RSS prose')
            self.assertEqual([rows[0][k] for k in ('id','title','published_at')],
                             ['identity','Preserved title','2026-10-01T12:00:00+00:00'])
            self.assertEqual(rows[0]['evidence_revision'],archive.EVIDENCE_REVISION)
            self.assertEqual(rows[0]['evidence_kind'],'publisher_rss')

if __name__=='__main__':unittest.main()
