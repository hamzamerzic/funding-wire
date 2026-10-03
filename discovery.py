"""Seb/Scaling Europe link discovery; original publisher evidence only."""
from __future__ import annotations
import datetime as dt
import concurrent.futures as cf
import hashlib
from html.parser import HTMLParser
import ipaddress
import json
import os
from pathlib import Path
import re
import urllib.error
import urllib.request
from urllib.parse import urljoin, urlsplit, urlunsplit
from archive import (ROOT, START, END, UA, EVIDENCE_REVISION, PublisherBodyText,
                     atomic_json, extracted_text, html_publication, html_timestamp,
                     in_window, publisher_evidence, safe_http_url, SAFE_OPENER,
                     stamp_evidence)
import gzip
from collector import FUNDING_WORD, canonical_url

HOME = 'https://scaling-europe.beehiiv.com/'
AUTHOR = HOME + 'authors/seb-johnson'
KNOWN = 'https://tech.eu/2026/05/29/london-based-ai-lab-inherent-emerges-from-stealth-with-50m-raise/'
KNOWN_SOAPBOX = 'https://www.soapbox.vc/feed/outerlimit-pre-seed'
KNOWN_INDEX = 'https://www.indexventures.com/perspectives/inherent-designing-for-discovery/'
MAX_NEWSLETTERS = 25
MAX_LINKS_PER_NEWSLETTER = 40
MAX_DAILY_NEWSLETTERS = 2
MAX_DAILY_LINKS = 24
BLOCK_HOSTS = ('beehiiv.com','linkedin.com','facebook.com','instagram.com','twitter.com','x.com','tiktok.com','youtube.com','google.com','substack.com','reddit.com','pinterest.com','whatsapp.com','t.co','bit.ly','linktr.ee','calendly.com','eventbrite.com','spotify.com','apple.com','lu.ma')
BLOCK_PATH = re.compile(r'/(?:subscribe|signup|login|sign-in|privacy|terms|about|contact|advertis|sponsor|share|category|tag|author)(?:/|$)', re.I)

class Anchors(HTMLParser):
    def __init__(self): super().__init__(convert_charrefs=True); self.links=[]; self.href=None; self.words=[]
    def handle_starttag(self, tag, attrs):
        if tag == 'a': self.href=dict(attrs).get('href'); self.words=[]
    def handle_data(self, data):
        if self.href is not None: self.words.append(data)
    def handle_endtag(self, tag):
        if tag == 'a' and self.href:
            self.links.append((self.href, ' '.join(' '.join(self.words).split())))
            self.href=None; self.words=[]

def safe_url(href, base=None):
    if not href or href.startswith(('#','mailto:','javascript:','tel:')): return None
    url=urljoin(base or HOME, href)
    if not safe_http_url(url): return None
    p=urlsplit(url); host=p.hostname.lower().rstrip('.')
    return urlunsplit((p.scheme,host,p.path or '/', '', ''))

def original_link(href, base, label=''):
    url=safe_url(href,base)
    if not url: return None
    p=urlsplit(url); host=p.hostname
    if any(host == x or host.endswith('.'+x) for x in BLOCK_HOSTS): return None
    if BLOCK_PATH.search(p.path) or p.path in ('','/'): return None
    if re.search(r'\b(?:follow|share|subscribe|advertis|sponsor)\b', label, re.I): return None
    return url

def cached_html(url, base, *, refresh=True, opener=urllib.request.urlopen):
    key=hashlib.sha256(url.encode()).hexdigest()[:24]
    bodyfile=base / f'{key}.html'; metafile=base / f'{key}.json'
    meta=json.loads(metafile.read_text()) if metafile.exists() else {}
    if not refresh and bodyfile.exists(): return bodyfile.read_bytes(), 'cached'
    headers={'User-Agent':UA,'Accept':'text/html'}
    if bodyfile.exists() and meta.get('etag'): headers['If-None-Match']=meta['etag']
    request=urllib.request.Request(url, headers=headers)
    if opener is urllib.request.urlopen: opener=SAFE_OPENER
    try:
        with opener(request, timeout=25) as response:
            raw=response.read(1_500_001)
            if len(raw)>1_500_000: raise ValueError('newsletter too large')
            base.mkdir(parents=True,exist_ok=True); bodyfile.write_bytes(raw)
            atomic_json(metafile,{'url':url,'etag':response.headers.get('ETag'), 'sha256':hashlib.sha256(raw).hexdigest(), 'bytes':len(raw)})
            return raw, 'fresh'
    except urllib.error.HTTPError as exc:
        if exc.code == 304 and bodyfile.exists(): return bodyfile.read_bytes(), 'not_modified'
        if bodyfile.exists(): return bodyfile.read_bytes(), 'stale'
        raise

def archive_text_index(root):
    """Only already-repaired publisher RSS evidence may replace missing HTML."""
    path = Path(root) / 'archive-summary.json'
    if not path.exists(): return {}
    document = json.loads(path.read_text())
    return {row['url']: row for row in document.get('items', [])
            if row.get('article_text') and (
                row.get('evidence_revision') == EVIDENCE_REVISION or
                (row.get('evidence_revision') == 2 and row.get('evidence_kind') == 'publisher_rss'))}

def repair_cached_original(file, archive_rows):
    """Re-extract stale cache offline or fail closed; never reuse bad prose."""
    row = json.loads(file.read_text())
    raw_path = file.parent.parent / 'raw-originals' / (file.stem + '.html.gz')
    if not raw_path.exists():
        # The later bounded re-evidence pass saved publisher HTML separately.
        candidate = file.parent.parent / 're-evidenced-raw' / (file.stem + '.html.gz')
        if candidate.exists(): raw_path = candidate
    short_raw_card = (raw_path.exists() and row.get('evidence_kind') == 'original_publisher'
                      and len(row.get('article_text', '')) < 200)
    if row.get('evidence_revision') == EVIDENCE_REVISION and not short_raw_card:
        return row
    content = None
    kind = None
    if raw_path.exists():
        candidate = extracted_text(gzip.decompress(raw_path.read_bytes()))
        # A short card/sidebar is not sufficient original-article evidence.
        if len(candidate) >= 200:
            content = candidate
            kind = 'original_publisher'
    if not content and row.get('url') in archive_rows:
        content = archive_rows[row['url']]['article_text']
        kind = 'publisher_rss'
    if not content:
        raise ValueError('stale cached text; no saved original HTML or matching publisher RSS')
    # Identity/title/dates and newsletter provenance are immutable during repair.
    stamp_evidence(row, content, kind)
    atomic_json(file, row)
    return row

def repair_discovery_cache(root=ROOT):
    """Create a corrected historical discovery artifact without any HTTP requests."""
    root = Path(root)
    base = root / 'discovery'
    old = json.loads((base / 'backfill-summary.json').read_text())
    archive_rows = archive_text_index(root)
    files = {}
    for file in (base / 'originals').glob('*.json'):
        try: files.setdefault(json.loads(file.read_text())['url'], file)
        except (ValueError, KeyError): pass
    rows, gaps = [], []
    for old_row in old.get('items', []):
        url = old_row['url']
        file = files.get(url)
        if file is None:
            gaps.append({'url':url,'reason':'cached_original_file_missing'})
            continue
        try:
            rows.append(repair_cached_original(file, archive_rows))
        except Exception as exc:
            gaps.append({'url':url,'reason':f'unrepairable_cached_original: {exc}'[:200]})
    result = {'version':1,'evidence_revision':EVIDENCE_REVISION,
              'checked_at':old.get('checked_at'), 'sources':old.get('sources', []),
              'items':sorted(rows,key=lambda x:x['published_at'],reverse=True),
              'cache_repair':{'input_count':len(old.get('items', [])),
                              'repaired_count':len(rows),
                              'unrecoverable_count':len(gaps),
                              'gaps':gaps}}
    atomic_json(base / f'corrected-summary-v{EVIDENCE_REVISION}.json', result)
    return result

def re_evidence_gaps(root=ROOT, *, opener=urllib.request.urlopen):
    """Bounded, resumable GETs for the exact offline-repair gaps plus two known links."""
    root = Path(root)
    base = root / 'discovery'
    corrected = json.loads((base / 'corrected-summary-v2.json').read_text())
    gap_urls = [gap['url'] for gap in corrected['cache_repair']['gaps']]
    known_urls = [KNOWN_SOAPBOX, KNOWN_INDEX]
    urls = list(dict.fromkeys(gap_urls + known_urls))
    old_rows = {}
    for file in (base / 'originals').glob('*.json'):
        try:
            row = json.loads(file.read_text()); old_rows[row['url']] = row
        except (ValueError, KeyError): pass
    results_dir = base / 're-evidenced-cache'
    def one(url):
        key = hashlib.sha256(url.encode()).hexdigest()[:24]
        status_path = results_dir / f'{key}.json'
        if status_path.exists():
            status = json.loads(status_path.read_text())
            if status.get('url') == url and status.get('status') in {'ok','gap'}:
                return status
        raw_path = base / 're-evidenced-raw' / f'{key}.html.gz'
        try:
            name = urlsplit(url).hostname
            row = publisher_evidence(url,'discovery',name,'Worldwide',
                                     raw_path=raw_path,opener=opener,max_attempts=1)
            if not in_window(row['published_at']):
                raise ValueError('reported publication date outside six-month window')
            prior = old_rows.get(url)
            if prior and prior.get('discovered_via'):
                row['discovered_via'] = prior['discovered_via']
            status = {'url':url,'status':'ok','item':row,'max_gets':3}
        except Exception as exc:
            status = {'url':url,'status':'gap',
                      'reason':f'{type(exc).__name__}: {exc}'[:220],'max_gets':3}
        atomic_json(status_path,status)
        return status
    with cf.ThreadPoolExecutor(max_workers=4) as pool:
        statuses = list(pool.map(one,urls))
    result = {'version':1,'evidence_revision':EVIDENCE_REVISION,
              'requested_gap_count':len(gap_urls),'known_extra_count':len([x for x in known_urls if x not in gap_urls]),
              'attempted_url_count':len(urls), 'items':[x['item'] for x in statuses if x['status']=='ok'],
              'gaps':[{'url':x['url'],'reason':x['reason']} for x in statuses if x['status']=='gap']}
    atomic_json(base / 're-evidenced-v2.json',result)
    return result

def repair_tfn_bodies(root=ROOT):
    """Offline structural-body repair of only the 56 saved TFN gap pages."""
    root = Path(root)
    base = root / 'discovery'
    prior = json.loads((base / 're-evidenced-v2.json').read_text())
    files = {}
    for file in (base / 'originals').glob('*.json'):
        try:
            row = json.loads(file.read_text()); files[row['url']] = file
        except (ValueError, KeyError): pass
    tfn = [gap for gap in prior['gaps'] if urlsplit(gap['url']).hostname == 'techfundingnews.com']
    repaired, still_bad = [], []
    for gap in tfn:
        url = gap['url']
        key = hashlib.sha256(url.encode()).hexdigest()[:24]
        raw_path = base / 're-evidenced-raw' / f'{key}.html.gz'
        try:
            if url not in files or not raw_path.exists():
                raise ValueError('saved original row or raw publisher HTML missing')
            old = json.loads(files[url].read_text())
            raw = gzip.decompress(raw_path.read_bytes())
            body_parser = PublisherBodyText(); body_parser.feed(raw.decode('utf-8',errors='replace'))
            if len(body_parser.bodies) != 1:
                raise ValueError('no unique structural publisher-body container')
            body = extracted_text(raw)
            if len(body) < 200:
                raise ValueError('structural publisher body under 200 characters')
            reported, precision = html_publication(raw)
            if reported is None or not in_window(reported):
                raise ValueError('missing, conflicting or out-of-window publication metadata')
            if old['published_at'][:10] != reported[:10] or not in_window(old['published_at']):
                raise ValueError('saved publication date conflicts with publisher HTML')
            # Identity, headline and date remain the original cached values.
            row = stamp_evidence(old.copy(),body,'original_publisher')
            row['body_source'] = 'saved_original_html:structural_body_container'
            row['raw_html_sha256'] = hashlib.sha256(raw).hexdigest()
            row['raw_html_path'] = str(raw_path)
            repaired.append(row)
        except Exception as exc:
            still_bad.append({'url':url,'reason':f'{type(exc).__name__}: {exc}'[:220]})
    repaired_urls = {row['url'] for row in repaired}
    failures = [gap for gap in prior['gaps'] if gap['url'] not in repaired_urls]
    replacement = {gap['url']:gap for gap in still_bad}
    failures = [replacement.get(gap['url'],gap) for gap in failures]
    result = {'version':1,'evidence_revision':EVIDENCE_REVISION,
              'source_artifact':str(base/'re-evidenced-v2.json'),
              'attempted_tfn_count':len(tfn), 'repaired_tfn_count':len(repaired),
              'remaining_gap_count':len(failures),
              'items':sorted(repaired,key=lambda x:x['published_at'],reverse=True),
              'gaps':failures}
    atomic_json(base/'repaired-body-v3.json',result)
    return result

def collect_discovery(now=None, root=None, *, daily=True, opener=urllib.request.urlopen):
    now=now or dt.datetime.now(dt.timezone.utc)
    root = root or (os.environ.get('APP_JOB_STATE_DIR') if daily else None) or ROOT
    cutoff=now-dt.timedelta(days=183) if daily else START
    upper=now+dt.timedelta(days=1) if daily else END
    base=Path(root)/'discovery'; gaps=[]; health=[]; rows={}; issues=[]
    archive_rows = None
    for index_url in (HOME,AUTHOR):
        try:
            raw, cache_status=cached_html(index_url,base/'index',refresh=daily,opener=opener)
            if cache_status=='stale': gaps.append({'url':index_url,'reason':'stale_index_cache_after_http_error'})
            parser=Anchors(); parser.feed(raw.decode('utf-8',errors='replace'))
            found=[safe_url(href,index_url) for href,_ in parser.links]
            found=[u for u in found if u and urlsplit(u).hostname=='scaling-europe.beehiiv.com' and urlsplit(u).path.startswith('/p/')]
            issues.extend(found)
            health.append({'id':'scaling-europe-index-'+('home' if index_url==HOME else 'seb'), 'url':index_url,'ok':cache_status!='stale','name':'Scaling Europe index','region':'Europe','cache_status':cache_status,'count':len(found)})
        except Exception as exc:
            health.append({'id':'scaling-europe-index-'+('home' if index_url==HOME else 'seb'),'url':index_url,'ok':False,'name':'Scaling Europe index','region':'Europe','count':0,'error':str(exc)[:180]})
    issues=list(dict.fromkeys(issues))[:MAX_DAILY_NEWSLETTERS if daily else MAX_NEWSLETTERS]
    link_budget=MAX_DAILY_LINKS if daily else MAX_NEWSLETTERS*MAX_LINKS_PER_NEWSLETTER
    seen=set(); newsletters=0
    for issue in issues:
        try:
            raw, cache_status=cached_html(issue,base/'newsletters',refresh=daily,opener=opener)
            if cache_status=='stale': gaps.append({'url':issue,'reason':'stale_newsletter_cache_after_http_error'})
            published=html_timestamp(raw)
            if published is None:
                gaps.append({'url':issue,'reason':'missing_or_ambiguous_newsletter_date'}); continue
            if not cutoff<=published<upper: continue
            newsletters+=1
            parser=Anchors(); parser.feed(raw.decode('utf-8',errors='replace'))
            links=[]
            for href,label in parser.links:
                u=original_link(href,issue,label)
                if u and u not in seen:
                    seen.add(u);links.append(u)
            for u in links[:MAX_LINKS_PER_NEWSLETTER]:
                if link_budget<=0:break
                link_budget-=1
                key=hashlib.sha256(u.encode()).hexdigest()[:24]
                file=base/'originals'/f'{key}.json'
                try:
                    if file.exists():
                        if archive_rows is None: archive_rows=archive_text_index(root)
                        row=repair_cached_original(file,archive_rows)
                    else:
                        host=urlsplit(u).hostname
                        row=publisher_evidence(u,'discovery',host,'Worldwide',raw_path=base/'raw-originals'/f'{key}.html.gz',opener=opener)
                        if not safe_url(row['url']): raise ValueError('unsafe redirect')
                    via=row.setdefault('discovered_via',[])
                    if issue not in via: via.append(issue)
                    atomic_json(file,row)
                    if in_window(row['published_at'],cutoff,upper): rows[row['url']]=row
                except Exception as exc:
                    gaps.append({'url':u,'newsletter':issue,'reason':f'{type(exc).__name__}: {exc}'[:180]})
        except Exception as exc:
            gaps.append({'url':issue,'reason':f'{type(exc).__name__}: {exc}'[:180]})
    # Known Seb-indexed original historical story, not a newsletter claim.
    if not daily:
        for known,name in ((KNOWN,'Tech.eu'),(KNOWN_SOAPBOX,'Soapbox'),(KNOWN_INDEX,'Index Ventures')):
            if known in seen: continue
            key=hashlib.sha256(known.encode()).hexdigest()[:24]
            try:
                row=publisher_evidence(known,'discovery',name,'Europe',raw_path=base/'raw-originals'/(key+'.html.gz'),opener=opener)
                if in_window(row['published_at'],cutoff,upper):
                    rows[row['url']]=row
                    atomic_json(base/'originals'/(key+'.json'),row)
            except Exception as exc: gaps.append({'url':known,'reason':f'{type(exc).__name__}: {exc}'[:180]})
    health.append({'id':'scaling-europe-newsletters','url':AUTHOR,'ok':newsletters>0 and not any('stale_' in g['reason'] for g in gaps),'name':'Scaling Europe newsletters','region':'Europe','count':newsletters,
                   'status':'bounded_recent' if daily else 'bounded_six_month','gaps':gaps})
    result={'version':1,'evidence_revision':EVIDENCE_REVISION,
            'checked_at':now.isoformat(),'sources':health,
            'items':sorted(rows.values(),key=lambda x:x['published_at'],reverse=True)}
    atomic_json(base/('daily-summary.json' if daily else 'backfill-summary.json'),result)
    return result

if __name__=='__main__':
    import sys
    if len(sys.argv)==2 and sys.argv[1]=='--re-evidence-gaps':
        result=re_evidence_gaps()
        print(json.dumps({'attempted':result['attempted_url_count'],
                          'items':len(result['items']),'gaps':len(result['gaps'])}))
    else:
        result=collect_discovery(daily=False)
        print(json.dumps({'newsletters':result['sources'][-1]['count'],'items':len(result['items']),'gaps':len(result['sources'][-1]['gaps'])}))
