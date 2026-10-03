#!/usr/bin/env python3
"""Scheduled refresh admission: fetch public evidence, start one app-owned agent.

The job never extracts deals or writes feed.json. Active reviews are reused,
and successful unchanged evidence does not start another agent. Each explicit
retry has its own scope. The agent owns review and conditional feed commit.
"""
import datetime as dt
import json
import hashlib
import os
from pathlib import Path
import sys
import urllib.error
import urllib.request

from collector import collect, fetch_rates
from discovery import collect_discovery

BASE = os.environ.get('API_BASE_URL', 'http://localhost:8000').rstrip('/')
PROMPT = Path(__file__).with_name('refresh-prompt.md')


def request(path, token, *, method='GET', body=None, headers=None):
    data = json.dumps(body, ensure_ascii=False).encode() if body is not None else None
    h = {'Authorization': f'Bearer {token}', 'Accept': 'application/json'}
    if data is not None:
        h['Content-Type'] = 'application/json'
    h.update(headers or {})
    req = urllib.request.Request(BASE + path, data=data, headers=h, method=method)
    with urllib.request.urlopen(req, timeout=30) as response:
        return json.load(response) if response.headers.get('Content-Type', '').startswith('application/json') else None


def evidence_hash(evidence):
    """Ignore clock-only changes; a changed article or source health gets review."""
    stable = {'sources': sorted((s['id'], s['ok']) for s in evidence['sources']),
              'items': sorted((i['id'], i['title'], i.get('published_at', ''), i['article_text']) for i in evidence['items'])}
    return hashlib.sha256(json.dumps(stable, ensure_ascii=False, sort_keys=True).encode()).hexdigest()


def collect_public_evidence(now):
    """RSS plus newsletter original-story leads, with independent failure health."""
    evidence = collect(now)
    try:
        cache = Path(os.environ['APP_JOB_STATE_DIR']) / 'discovery-cache'
        discovered = collect_discovery(now, root=cache)
    except Exception as exc:
        discovered = {'sources': [{'id': 'scaling-europe-newsletters', 'name': 'Scaling Europe discovery',
                                   'url': 'https://scaling-europe.beehiiv.com/', 'region': 'Europe',
                                   'ok': False, 'count': 0, 'error': f'{type(exc).__name__}: {exc}'[:180]}], 'items': []}
    rows = {item['id']: item for item in evidence['items']}
    for item in discovered['items']:
        existing = rows.get(item['id'])
        if not existing or len(item['article_text']) > len(existing['article_text']):
            rows[item['id']] = item
    return {**evidence, 'sources': evidence['sources'] + discovered['sources'],
            'items': sorted(rows.values(), key=lambda item: (item.get('published_at', ''), item['id']), reverse=True)}


def refresh_rates(app_id, token):
    # Rate failure must not erase a useful cache or block funding review.
    try:
        rates = fetch_rates()
        request(f'/api/storage/apps/{app_id}/fx.json', token, method='PUT', body=rates)
    except Exception as exc:
        print(f'Currency check failed; keeping prior reference rates: {type(exc).__name__}', file=sys.stderr)


def read_state(app_id, token):
    path = f'/api/storage/apps/{app_id}/refresh-state.json'
    req = urllib.request.Request(BASE + path, headers={'Authorization': f'Bearer {token}'})
    try:
        with urllib.request.urlopen(req, timeout=30) as response:
            return json.load(response), response.headers.get('ETag')
    except urllib.error.HTTPError as exc:
        if exc.code == 404:
            return None, None
        raise


def set_state(app_id, token, state, *, only_if_run=None):
    if only_if_run is None:
        return request(f'/api/storage/apps/{app_id}/refresh-state.json', token,
                       method='PUT', body=state)
    current, etag = read_state(app_id, token)
    if not current or current.get('run_id') != only_if_run or not etag:
        return None  # A newer run or completed review owns the visible state.
    if current.get('phase') in {'complete','error','unchanged'} and state.get('phase') == 'reviewing':
        return None  # Fast review completed before admission returned its id.
    try:
        return request(f'/api/storage/apps/{app_id}/refresh-state.json', token,
                       method='PUT', body=state, headers={'If-Match': etag})
    except urllib.error.HTTPError as exc:
        if exc.code != 412:
            raise
        return None


def run(app_id, token, now=None):
    now = now or dt.datetime.now(dt.timezone.utc)
    run_id = now.strftime('%Y%m%dT%H%M%S%f')
    prior, _ = read_state(app_id, token)
    if prior and prior.get('phase') == 'reviewing' and prior.get('chat_id'):
        chats = request('/api/app-chats', token)
        chat = next((c for c in chats if c['id'] == prior['chat_id']), None)
        if chat and (chat['running'] or chat.get('awaiting_owner')):
            return {'outcome': 'reviewing', 'chat_id': prior['chat_id']}
    state = {'phase': 'collecting', 'run_id': run_id,
             'started_at': now.isoformat(), 'finished_at': None,
             'error': None, 'chat_id': None, 'evidence_hash': None}
    set_state(app_id, token, state)
    try:
        evidence = collect_public_evidence(now)
        if not any(source['ok'] for source in evidence['sources']):
            raise RuntimeError('All public sources failed; existing verified feed retained')
        refresh_rates(app_id, token)
        digest = evidence_hash(evidence)
        evidence['evidence_hash'] = digest
        try:
            previous = request(f'/api/storage/apps/{app_id}/feed.json', token)
        except urllib.error.HTTPError as exc:
            if exc.code != 404:
                raise
            previous = None
        if previous and previous.get('evidence_hash') == digest:
            state.update(phase='unchanged', finished_at=dt.datetime.now(dt.timezone.utc).isoformat(), evidence_hash=digest)
            set_state(app_id, token, state)
            return {'outcome': 'unchanged'}
        state['evidence_hash'] = digest
        set_state(app_id, token, state)
        snapshot = f'evidence/{digest[:32]}.json'
        path = f'/api/storage/apps/{app_id}/{snapshot}'
        try:
            request(path, token, method='PUT', body=evidence,
                    headers={'If-None-Match': '*'})
        except urllib.error.HTTPError as exc:
            if exc.code != 412:
                raise
        state.update(phase='reviewing')
        set_state(app_id, token, state, only_if_run=run_id)
        body = {
            'title': f'Funding Wire refresh {now:%Y-%m-%d} UTC',
            'scope': f'funding-wire:{digest[:20]}:{run_id}',
            'scope_label': f'Review {now:%Y-%m-%d} UTC',
            'owner_visible': False,
            'system_prompt': PROMPT.read_text(),
            'content': (f'Review Funding Wire public publisher evidence at {path}. '
                        f'App ID: {app_id}. Refresh run ID: {run_id}. '
                        'Follow your system instructions; commit only verified deals.'),
        }
        result = request('/api/app-chats/start', token, method='POST', body=body)
        state['chat_id'] = result['chat_id']
        set_state(app_id, token, state, only_if_run=run_id)
        return result
    except Exception as exc:
        state.update(phase='error', finished_at=dt.datetime.now(dt.timezone.utc).isoformat(),
                     error=f'{type(exc).__name__}: {exc}'[:240])
        set_state(app_id, token, state, only_if_run=run_id)
        raise


def main():
    if len(sys.argv) != 2 or not sys.argv[1].isdigit():
        raise SystemExit('Usage: job.py APP_ID')
    token = os.environ.get('APP_TOKEN')
    if not token:
        raise SystemExit('APP_TOKEN missing; run only through supervised app job')
    result = run(int(sys.argv[1]), token)
    print(f"Funding Wire refresh admitted: {result['outcome']}")


if __name__ == '__main__':
    main()
