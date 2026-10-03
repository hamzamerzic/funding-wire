"""Deterministic collection of public RSS evidence, not deal extraction.

RSS text is untrusted evidence. The agent decides whether a current company
financing exists; this module deliberately never guesses amounts or investors.
"""
from __future__ import annotations

import concurrent.futures
import datetime as dt
import hashlib
import html
import json
import math
from html.parser import HTMLParser
import re
import urllib.request
import xml.etree.ElementTree as ET
from email.utils import parsedate_to_datetime
from urllib.parse import urlsplit, urlunsplit

SOURCES = [
    ('tech-eu', 'Tech.eu', 'https://tech.eu/feed/', 'Europe'),
    ('eu', 'EU-Startups', 'https://www.eu-startups.com/feed/', 'Europe'),
    ('latam', 'LatamList', 'https://latamlist.com/feed/', 'Latin America'),
    ('africa', 'Disrupt Africa', 'https://disruptafrica.com/feed/', 'Africa'),
    ('asia', 'TNGlobal', 'https://technode.global/feed/', 'Asia'),
    ('asia-deals', 'TNGlobal Investments', 'https://technode.global/category/industry/investments/feed/', 'Asia'),
    ('tc', 'TechCrunch', 'https://techcrunch.com/feed/', 'Worldwide'),
    ('au', 'Startup Daily', 'https://www.startupdaily.net/feed/', 'Oceania'),
]
CONTENT = '{http://purl.org/rss/1.0/modules/content/}encoded'
MAX_FEED_BYTES = 2_000_000
MAX_ARTICLE_CHARS = 3200
MAX_ITEMS_PER_SOURCE = 30
FUNDING_WORD = re.compile(r'\b(?:funding|financing|investment|investors?|series [a-h]|pre[- ]seed|seed round|venture|raises?|raised|secures?|secured|capital|debt|credit facility)\b|[$€£]\s*\d', re.I)


def fetch_rates(opener=urllib.request.urlopen):
    """USD per currency unit, with one explicit ECB reference date."""
    request = urllib.request.Request(
        'https://api.frankfurter.dev/v2/providers/ecb/rates?base=USD',
        headers={'User-Agent': 'FundingWire/1.0', 'Accept': 'application/json'})
    with opener(request, timeout=22) as response:
        raw = response.read(100_001)
    if len(raw) > 100_000:
        raise ValueError('Currency response exceeds limit')
    rows = json.loads(raw)
    rates, dates = {'USD': 1.0}, set()
    for row in rows:
        rate = row['rate']
        if row['base'] != 'USD' or not isinstance(rate, (int, float)) or not math.isfinite(rate) or rate <= 0:
            raise ValueError('Invalid USD reference rate')
        dt.date.fromisoformat(row['date'])
        dates.add(row['date'])
        rates[row['quote']] = 1 / rate
    if len(dates) != 1 or len(rates) < 2:
        raise ValueError('Missing or mixed reference dates')
    return {'date': dates.pop(), 'base': 'USD', 'usd_per_unit': rates,
            'provider': 'ECB via Frankfurter', 'url': 'https://frankfurter.dev/'}


class _Text(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.parts = []

    def handle_data(self, data):
        self.parts.append(data)

    def handle_starttag(self, tag, attrs):
        if tag in {'p', 'br', 'li', 'div', 'h1', 'h2', 'h3'}:
            self.parts.append('\n')

    def handle_endtag(self, tag):
        if tag in {'p', 'li', 'div', 'h1', 'h2', 'h3'}:
            self.parts.append('\n')


def plain_text(raw):
    parser = _Text()
    parser.feed(raw or '')
    return '\n'.join(line for part in ''.join(parser.parts).splitlines()
                     if (line := re.sub(r'\s+', ' ', part).strip()))


def canonical_url(url):
    p = urlsplit(url.strip())
    if p.scheme not in {'http', 'https'} or not p.netloc:
        return None
    return urlunsplit((p.scheme, p.netloc.lower(), p.path, '', ''))


def item_evidence(item, source, now, days=45):
    title = html.unescape(item.findtext('title', '')).strip()
    if not title or not FUNDING_WORD.search(title):
        return None
    url = canonical_url(item.findtext('link', ''))
    if not url:
        return None
    try:
        published = parsedate_to_datetime(item.findtext('pubDate', ''))
        if published.tzinfo is None:
            return None
        published = published.astimezone(dt.timezone.utc)
    except (TypeError, ValueError, OverflowError):
        return None
    if not (now - dt.timedelta(days=days) <= published <= now + dt.timedelta(days=1)):
        return None
    raw = item.findtext(CONTENT) or item.findtext('description', '')
    article = plain_text(raw)[:MAX_ARTICLE_CHARS]
    return {
        'id': hashlib.sha256(url.encode()).hexdigest()[:20],
        'title': title,
        'url': url,
        'published_at': published.isoformat(),
        'source_id': source[0],
        'source_name': source[1],
        'source_region': source[3],
        'article_text': article,
    }


def fetch_source(source, now, opener=urllib.request.urlopen):
    request = urllib.request.Request(
        source[2],
        headers={'User-Agent': 'FundingWire/1.0 (public RSS reader)',
                 'Accept': 'application/rss+xml, application/xml, text/xml'},
    )
    with opener(request, timeout=22) as response:
        raw = response.read(MAX_FEED_BYTES + 1)
    if len(raw) > MAX_FEED_BYTES:
        raise ValueError('Feed exceeds 2 MB limit')
    root = ET.fromstring(raw)
    items = root.findall('.//item')
    if not items:
        raise ValueError('No RSS items returned')
    candidates = [e for item in items[:MAX_ITEMS_PER_SOURCE]
                  if (e := item_evidence(item, source, now))]
    return candidates


def collect(now=None):
    now = now or dt.datetime.now(dt.timezone.utc)
    evidence, health = [], []
    with concurrent.futures.ThreadPoolExecutor(max_workers=len(SOURCES)) as pool:
        tasks = {pool.submit(fetch_source, source, now): source for source in SOURCES}
        for future in concurrent.futures.as_completed(tasks):
            source = tasks[future]
            status = {'id': source[0], 'name': source[1], 'url': source[2],
                      'region': source[3]}
            try:
                items = future.result()
                evidence.extend(items)
                status.update(ok=True, count=len(items))
            except Exception as exc:
                status.update(ok=False, count=0,
                              error=f'{type(exc).__name__}: {exc}'[:160])
            health.append(status)
    return {
        'version': 1,
        'checked_at': now.isoformat(),
        'sources': sorted(health, key=lambda entry: entry['id']),
        'items': sorted(evidence, key=lambda entry: entry['published_at'], reverse=True),
    }
