"""Resumable public RSS archive evidence, never deal extraction or app storage."""
from __future__ import annotations
import concurrent.futures as cf
import datetime as dt
import hashlib
import gzip
import html
import ipaddress
import json
import os
from pathlib import Path
import re
import time
import urllib.error
import urllib.request
import xml.etree.ElementTree as ET
from email.utils import parsedate_to_datetime
from html.parser import HTMLParser
from urllib.parse import urlencode, urlsplit, urlunsplit
from collector import SOURCES, CONTENT, FUNDING_WORD, canonical_url, plain_text

ROOT = Path('/data/shared/funding-wire/backfill-2026-04-02')
START = dt.datetime(2026, 4, 2, tzinfo=dt.timezone.utc)
END = dt.datetime(2026, 10, 3, tzinfo=dt.timezone.utc)  # exclusive
UA = 'FundingWire/1.0 (public RSS reader)'
MAX_PAGES = 200
MAX_FEED_BYTES = 2_000_000
MAX_ARTICLE_BYTES = 1_000_000
MAX_ARTICLE_CHARS = 6000
EVIDENCE_REVISION = 3  # Structural publisher-body extraction; v2 could select sidebar cards.
DATE_RE = re.compile(r'<meta\s+[^>]*(?:property|name)=["\'](?:article:published_time|datePublished|date|pubdate)["\'][^>]*>', re.I)
JSON_LD_RE = re.compile(r'<script\b[^>]*type=["\']application/ld\+json["\'][^>]*>(.*?)</script>', re.I | re.S)
ATTR_RE = re.compile(r'([\w:-]+)\s*=\s*["\']([^"\']*)["\']')
TITLE_RE = re.compile(r'<title[^>]*>(.*?)</title>', re.I | re.S)
ARTICLE_RE = re.compile(r'<article\b[^>]*>(.*?)</article>', re.I | re.S)


def atomic_json(path, data):
    path.parent.mkdir(parents=True, exist_ok=True)
    temp = path.with_name(path.name + '.tmp')
    temp.write_text(json.dumps(data, ensure_ascii=False, indent=2))
    os.replace(temp, path)


def safe_http_url(url):
    try:
        p = urlsplit(url)
        if p.scheme not in {'http', 'https'} or not p.hostname or p.username or p.password or p.port not in (None, 80, 443):
            return False
        host = p.hostname.lower().rstrip('.')
        if host == 'localhost' or host.endswith(('.local', '.internal')):
            return False
        try:
            return ipaddress.ip_address(host).is_global
        except ValueError:
            return True
    except ValueError:
        return False

class SafeRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        if not safe_http_url(newurl):
            raise ValueError('unsafe HTTP redirect')
        redirects = getattr(req, '_fw_redirects', 0)
        if redirects >= 2:
            raise ValueError('more than two HTTP redirects')
        next_request = super().redirect_request(req, fp, code, msg, headers, newurl)
        next_request._fw_redirects = redirects + 1
        return next_request

SAFE_OPENER = urllib.request.build_opener(SafeRedirect()).open

def fetch(url, limit, opener=urllib.request.urlopen, *, max_attempts=3):
    if not safe_http_url(url): raise ValueError('unsafe HTTP URL')
    if opener is urllib.request.urlopen: opener = SAFE_OPENER
    request = urllib.request.Request(url, headers={'User-Agent': UA, 'Accept': 'text/html, application/rss+xml, application/xml, text/xml'})
    for attempt in range(max_attempts):
        try:
            with opener(request, timeout=25) as response:
                raw = response.read(limit + 1)
                if len(raw) > limit:
                    raise ValueError(f'response exceeds {limit} bytes')
                return raw, response.geturl()
        except urllib.error.HTTPError as exc:
            if exc.code not in {429, 500, 502, 503, 504, 522} or attempt == max_attempts - 1:
                raise
        except (TimeoutError, urllib.error.URLError):
            if attempt == max_attempts - 1:
                raise
        time.sleep(1.5 * (attempt + 1))


def page_url(feed, number):
    return feed if number == 1 else feed + ('&' if '?' in feed else '?') + urlencode({'paged': number})


def parse_rss(raw):
    root = ET.fromstring(raw)
    return root.findall('.//item')


def timestamp(value):
    try:
        result = parsedate_to_datetime(value)
        return result.astimezone(dt.timezone.utc) if result.tzinfo else None
    except (ValueError, TypeError, OverflowError):
        return None


def html_timestamp(raw):
    value, precision = html_publication(raw)
    return dt.datetime.fromisoformat(value) if value and precision == 'instant' else None

def html_publication(raw):
    """Return only explicit, unambiguous article publication metadata.

    A reported ISO day stays a day; no midnight or timezone is invented.
    """
    text = raw.decode('utf-8', errors='replace')
    values = []
    for tag in DATE_RE.findall(text):
        attrs = dict(ATTR_RE.findall(tag))
        val = attrs.get('content') or attrs.get('datetime')
        if val:
            values.append(val)
    def visit(node):
        if isinstance(node, dict):
            types = node.get('@type', [])
            if isinstance(types, str): types = [types]
            if any(t in {'Article','NewsArticle','BlogPosting','ReportageNewsArticle'} for t in types):
                value = node.get('datePublished')
                if isinstance(value, str): values.append(value)
            for child in node.values(): visit(child)
        elif isinstance(node, list):
            for child in node: visit(child)
    for match in JSON_LD_RE.finditer(text):
        try: visit(json.loads(html.unescape(match.group(1))))
        except (ValueError, TypeError): pass
    parsed = []
    for value in values:
        value = value.strip()
        if re.fullmatch(r'\d{4}-\d{2}-\d{2}', value):
            try: parsed.append((dt.date.fromisoformat(value), None))
            except ValueError: pass
        else:
            try:
                instant = dt.datetime.fromisoformat(value.replace('Z', '+00:00'))
                if instant.tzinfo:
                    parsed.append((instant.date(), instant.astimezone(dt.timezone.utc)))
            except ValueError: pass
    if not parsed or len({day for day, _ in parsed}) != 1:
        return None, None
    instants = {instant for _, instant in parsed if instant}
    if len(instants) > 1:
        return None, None
    if instants:
        return next(iter(instants)).isoformat(), 'instant'
    return parsed[0][0].isoformat(), 'day'

def in_window(value, start=START, end=END):
    """Compare an exact instant or a source-reported ISO calendar day."""
    if re.fullmatch(r'\d{4}-\d{2}-\d{2}', value):
        day = dt.date.fromisoformat(value)
        return start.date() <= day < end.date()
    instant = dt.datetime.fromisoformat(value)
    return instant.tzinfo is not None and start <= instant.astimezone(dt.timezone.utc) < end


class ArticleText(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True); self.parts=[]; self.skip=0
    def handle_starttag(self, tag, attrs):
        if tag in {'script','style','nav','footer','header','form','noscript'}: self.skip+=1
        elif not self.skip and tag in {'p','br','li','div','h1','h2','h3'}: self.parts.append('\n')
    def handle_endtag(self, tag):
        if tag in {'script','style','nav','footer','header','form','noscript'}: self.skip=max(0,self.skip-1)
        elif not self.skip and tag in {'p','li','div','h1','h2','h3'}: self.parts.append('\n')
    def handle_data(self, data):
        if not self.skip: self.parts.append(data)
    def text(self):
        return '\n'.join(line for part in ''.join(self.parts).splitlines() if (line:=re.sub(r'\s+',' ',part).strip()))

class PublisherBodyText(HTMLParser):
    """Capture only balanced, explicitly marked publisher article-body elements."""
    BODY_CLASSES = {'entry-content', 'article-content', 'post-content',
                    'article-body', 'story-body'}
    VOID = {'area','base','br','col','embed','hr','img','input','link','meta',
            'param','source','track','wbr'}
    SKIP = {'script','style','nav','footer','header','form','noscript'}
    BLOCK = {'p','br','li','div','h1','h2','h3','h4','blockquote'}
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.active = False; self.depth = 0; self.skip = 0
        self.parts = []; self.bodies = []
    def handle_starttag(self, tag, attrs):
        attrs = dict(attrs)
        if not self.active:
            classes = set((attrs.get('class') or '').split())
            if (tag in {'div','section','main','article'} and
                    (classes & self.BODY_CLASSES or attrs.get('itemprop') == 'articleBody')):
                self.active = True; self.depth = 1; self.skip = 0; self.parts = []
            return
        if tag not in self.VOID: self.depth += 1
        if tag in self.SKIP: self.skip += 1
        elif not self.skip and tag in self.BLOCK: self.parts.append('\n')
    def handle_startendtag(self, tag, attrs):
        if self.active and not self.skip and tag in self.BLOCK: self.parts.append('\n')
    def handle_endtag(self, tag):
        if not self.active: return
        if tag in self.SKIP: self.skip = max(0,self.skip-1)
        elif not self.skip and tag in self.BLOCK: self.parts.append('\n')
        if tag not in self.VOID: self.depth -= 1
        if self.depth <= 0:
            if not self.skip:
                body = '\n'.join(line for part in ''.join(self.parts).splitlines()
                                 if (line:=re.sub(r'\s+',' ',part).strip()))
                if body: self.bodies.append(body)
            self.active = False; self.depth = 0; self.parts = []
    def handle_data(self, data):
        if self.active and not self.skip: self.parts.append(data)

def extracted_text(raw):
    """Extract publisher prose only; this function's changes require a revision bump."""
    text = raw.decode('utf-8', errors='replace') if isinstance(raw, bytes) else raw
    body_parser = PublisherBodyText(); body_parser.feed(text)
    if len(body_parser.bodies) == 1:
        return body_parser.bodies[0][:MAX_ARTICLE_CHARS]
    if len(body_parser.bodies) > 1:
        return ''  # Multiple explicit bodies are ambiguous; do not pick the longest.
    articles = ARTICLE_RE.findall(text)
    if len(articles) > 1:
        return ''  # Sidebar cards are not an article-body boundary.
    if not articles and re.search(r'<html\b', text, re.I):
        return ''  # A full page with no article boundary is not publisher prose.
    parser = ArticleText()
    parser.feed(articles[0] if articles else text)  # one article or RSS fragment
    return parser.text()[:MAX_ARTICLE_CHARS]

def stamp_evidence(row, text, kind):
    row.update(article_text=text, evidence_kind=kind,
               evidence_revision=EVIDENCE_REVISION,
               article_text_truncated=len(text) >= MAX_ARTICLE_CHARS,
               article_text_hash=hashlib.sha256(text.encode()).hexdigest())
    return row

def rss_index(base):
    """Index durable publisher RSS pages, never the network, for old-cache repair."""
    index = {}
    for page in sorted((base / 'pages').glob('*.xml')):
        for item in parse_rss(page.read_bytes()):
            url = canonical_url(item.findtext('link', ''))
            if url:
                index.setdefault(url, item)
    return index

def repair_cached_archive(base, source):
    """Return sound cached rows plus precise gaps; never refetch to repair text."""
    files = list((base / 'articles').glob('*.json'))
    stale = []
    rows, gaps = {}, []
    for file in files:
        try:
            row = json.loads(file.read_text())
            if row.get('evidence_revision') == EVIDENCE_REVISION:
                rows[row['url']] = row
            else:
                stale.append((file, row))
        except (ValueError, KeyError) as exc:
            gaps.append({'url': str(file), 'reason': f'invalid_cached_evidence: {exc}'})
    index = rss_index(base) if stale else {}
    for file, row in stale:
        url = row.get('url')
        key = hashlib.sha256(url.encode()).hexdigest()[:24] if url else ''
        raw_path = base / 'raw-articles' / f'{key}.html.gz'
        try:
            if raw_path.exists():
                content = extracted_text(gzip.decompress(raw_path.read_bytes()))
                kind = 'original_publisher' if len(content) >= 200 else None
            else:
                content = None
                kind = None
            if kind is None and url in index:
                item = index[url]
                raw = item.findtext(CONTENT) or item.findtext('description', '')
                content = extracted_text(raw)
                kind = 'publisher_rss'
            if kind is None:
                raise ValueError('no saved publisher HTML or matching RSS item')
            if not content:
                raise ValueError('saved original has no extractable prose')
            # Preserve identity, title and both publication timestamps exactly.
            stamp_evidence(row, content, kind)
            atomic_json(file, row)
            rows[row['url']] = row
        except Exception as exc:
            gaps.append({'url': url or str(file), 'reason': f'unrepairable_cached_text: {exc}'[:180]})
    return rows, gaps

def publisher_evidence(url, source_id, source_name, region, *, fallback_title='', feed_date=None, raw_path=None, opener=urllib.request.urlopen, max_attempts=3):
    """Only original publisher body is used; ambiguous/missing date is a gap."""
    raw, final_url = (fetch(url, MAX_ARTICLE_BYTES, opener) if max_attempts == 3 else
                      fetch(url, MAX_ARTICLE_BYTES, opener, max_attempts=max_attempts))
    url = canonical_url(final_url)
    if not url:
        raise ValueError('unsafe redirect')
    if raw_path is not None:
        raw_path = Path(raw_path); raw_path.parent.mkdir(parents=True, exist_ok=True)
        raw_path.write_bytes(gzip.compress(raw))
    text = raw.decode('utf-8', errors='replace')
    published_at, precision = html_publication(raw)
    if published_at is None and feed_date is not None:
        published_at, precision = feed_date.isoformat(), 'instant'
    if published_at is None:
        raise ValueError('missing or ambiguous publication date')
    content = extracted_text(raw)
    if len(content) < 200:
        raise ValueError('original page has insufficient article prose')
    title = plain_text(TITLE_RE.search(text).group(1)) if TITLE_RE.search(text) else fallback_title
    return stamp_evidence({'id': hashlib.sha256(url.encode()).hexdigest()[:20], 'title': title or fallback_title,
            'url': url, 'published_at': published_at, 'publication_precision': precision,
            'source_id': source_id,
            'source_name': source_name, 'source_region': region, 'article_text': content,
            'feed_published_at': feed_date.isoformat() if feed_date else None}, content, 'original_publisher')


def annotate_chronology(base, state):
    existing={(g.get('page'),g.get('reason'),g.get('index')) for g in state['gaps']}
    for prior,current in zip(state['pages'],state['pages'][1:]):
        if prior.get('oldest') and current.get('newest'):
            days=(dt.datetime.fromisoformat(prior['oldest'])-dt.datetime.fromisoformat(current['newest'])).total_seconds()/86400
            key=(current['page'],'possible_interpage_gap',None)
            if days>7 and key not in existing:
                state['gaps'].append({'page':current['page'],'reason':'possible_interpage_gap','days':round(days,1)})
    for page in state['pages']:
        path=base/'pages'/f"{page['page']:03}.xml"
        if not path.exists(): continue
        dates=[timestamp(x.findtext('pubDate','')) for x in parse_rss(path.read_bytes())]
        dates=[d for d in dates if d]
        for index,(a,b) in enumerate(zip(dates,dates[1:])):
            days=(a-b).total_seconds()/86400
            key=(page['page'],'possible_intrapage_gap',index)
            if days>14 and key not in existing:
                state['gaps'].append({'page':page['page'],'reason':'possible_intrapage_gap','index':index,'days':round(days,1)})

def collect_source(source, root=ROOT, *, max_pages=MAX_PAGES, opener=urllib.request.urlopen):
    sid, name, feed, region = source
    base = Path(root) / 'archive' / sid
    state_path = base / 'state.json'
    state = json.loads(state_path.read_text()) if state_path.exists() else {'next_page': 1, 'page_signatures': [], 'seen_ids': [], 'pages': [], 'gaps': []}
    signatures, seen = set(state['page_signatures']), set(state['seen_ids'])
    items, cache_gaps = repair_cached_archive(base, source)
    for gap in cache_gaps:
        if gap not in state['gaps']:
            state['gaps'].append(gap)
    if state.get('terminal') == 'unavailable':
        state.pop('terminal')  # retry failed page on a later invocation; prior pages remain durable
    if state.get('terminal'):
        annotate_chronology(base, state)
        atomic_json(state_path, state)
        return {'id': sid, 'name': name, 'url': feed, 'region': region, 'ok': bool(state['pages']),
                'status': state['terminal'], 'pages': len(state['pages']), 'count': len(items), 'gaps': state['gaps']}, list(items.values())
    for page in range(state['next_page'], max_pages + 1):
        url = page_url(feed, page)
        try:
            raw, _ = fetch(url, MAX_FEED_BYTES, opener)
            rss_items = parse_rss(raw)
            if not rss_items:
                state['terminal'] = 'empty_page'; break
            ids = [canonical_url(x.findtext('link', '')) or x.findtext('guid', '') for x in rss_items]
            signature = hashlib.sha256('\n'.join(ids).encode()).hexdigest()
            if signature in signatures or (page > 1 and all(i in seen for i in ids)):
                state['terminal'] = 'repeated_page'; state['gaps'].append({'page': page, 'reason': 'RSS pagination repeats; older coverage unavailable'}); break
            signatures.add(signature)
            dates = [timestamp(x.findtext('pubDate', '')) for x in rss_items]
            valid = [x for x in dates if x]
            if len(valid) != len(dates):
                state['gaps'].append({'page': page, 'reason': 'missing_or_invalid_feed_dates', 'count': len(dates)-len(valid)})
            if any(a < b for a,b in zip(valid, valid[1:])):
                state['gaps'].append({'page': page, 'reason': 'non_descending_dates'})
            if state['pages'] and valid and valid[0] > dt.datetime.fromisoformat(state['pages'][-1]['oldest']):
                state['gaps'].append({'page': page, 'reason': 'chronology_overlap_or_jump'})
            candidates = 0
            for x, date, ident in zip(rss_items, dates, ids):
                seen.add(ident)
                title = html.unescape(x.findtext('title', '')).strip()
                link = canonical_url(x.findtext('link', ''))
                if not link or not date or not START <= date < END or not FUNDING_WORD.search(title):
                    continue
                candidates += 1
                key = hashlib.sha256(link.encode()).hexdigest()[:24]
                file = base / 'articles' / f'{key}.json'
                if file.exists() and link in items: continue
                try:
                    row = publisher_evidence(link, sid, name, region, fallback_title=title, feed_date=date, raw_path=base / 'raw-articles' / f'{key}.html.gz', opener=opener)
                    if not in_window(row['published_at']):
                        raise ValueError('publisher publication date outside six-month window')
                    atomic_json(file, row); items[row['url']] = row
                except Exception as exc:
                    state['gaps'].append({'page': page, 'url': link, 'reason': f'{type(exc).__name__}: {exc}'[:180]})
            base.mkdir(parents=True, exist_ok=True)
            (base / 'pages').mkdir(exist_ok=True)
            (base / 'pages' / f'{page:03}.xml').write_bytes(raw)
            state['pages'].append({'page': page, 'url': url, 'items': len(rss_items), 'candidates': candidates,
                                   'newest': max(valid).isoformat() if valid else None,
                                   'oldest': min(valid).isoformat() if valid else None, 'bytes': len(raw)})
            state['next_page'] = page + 1; state['page_signatures'] = sorted(signatures); state['seen_ids'] = sorted(seen)
            if valid and min(valid) < START:
                state['terminal'] = 'reached_cutoff'
            atomic_json(state_path, state)
            if state.get('terminal'): break
            time.sleep(0.15)
        except Exception as exc:
            state['gaps'].append({'page': page, 'reason': f'{type(exc).__name__}: {exc}'[:180]})
            state['terminal'] = 'unavailable'; break
    if not state.get('terminal'):
        state['terminal'] = 'capped' if state['next_page'] > max_pages else 'unavailable'
    annotate_chronology(base, state)
    state['page_signatures'] = sorted(signatures); state['seen_ids'] = sorted(seen)
    atomic_json(state_path, state)
    return {'id': sid, 'name': name, 'url': feed, 'region': region, 'ok': bool(state['pages']),
            'status': state['terminal'], 'pages': len(state['pages']), 'count': len(items), 'gaps': state['gaps']}, list(items.values())


def collect_archive(root=ROOT, sources=SOURCES, max_pages=MAX_PAGES):
    health, items = [], {}
    with cf.ThreadPoolExecutor(max_workers=4) as pool:
        futures = [pool.submit(collect_source, s, root, max_pages=max_pages) for s in sources]
        for future in cf.as_completed(futures):
            h, rows = future.result(); health.append(h)
            for row in rows: items.setdefault(row['url'], row)
    result = {'version': 1, 'evidence_revision': EVIDENCE_REVISION,
              'window_start': START.isoformat(), 'window_end_exclusive': END.isoformat(),
              'sources': sorted(health, key=lambda x: x['id']),
              'items': sorted(items.values(), key=lambda x: x['published_at'], reverse=True)}
    atomic_json(Path(root) / 'archive-summary.json', result)
    return result

if __name__ == '__main__':
    result = collect_archive()
    print(json.dumps({'sources': [{k: s[k] for k in ('id','status','pages','count')} for s in result['sources']], 'unique_items': len(result['items'])}))
