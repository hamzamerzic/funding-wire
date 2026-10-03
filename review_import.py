"""Add source-reviewed historical reports without resetting the live feed.

Reviewers decide which article describes a financing and which report it
duplicates. This module only applies those explicit decisions. Daily checks
and saved-company snapshots remain independently owned.
"""
import copy
import datetime as dt
import json
from pathlib import Path
import subprocess
import tempfile


def union_sources(old, incoming):
    by_url = {s['url']: copy.deepcopy(s) for s in (old or [])}
    for source in incoming or []:
        by_url.setdefault(source['url'], copy.deepcopy(source))
    return list(by_url.values())


def enrich_report(old, incoming):
    """Add evidence; apply only explicit reviewed replacements, including null.

    Ordinary missing-field enrichment cannot distinguish an unknown from an
    intentionally unranked amount. replace_fields carries the reviewer's
    correction intent and is never persisted as report data.
    """
    result = copy.deepcopy(old)
    for field, value in incoming.items():
        if field in {'id', 'duplicate_of', 'replace_fields'}:
            continue
        if field in {'sources', 'amount_sources', 'valuation_sources'}:
            result[field] = union_sources(result.get(field), value)
        elif result.get(field) in (None, '', 'Not stated') and value not in (None, '', 'Not stated'):
            result[field] = copy.deepcopy(value)
    result.update(copy.deepcopy(incoming.get('replace_fields', {})))
    return result


def merge_reviewed(feed, reviewed, now, *, max_records=1000):
    """Pure additive merge. Explicit duplicate_of must resolve, never guess."""
    result = copy.deepcopy(feed)
    records = {r['id']: copy.deepcopy(r) for r in feed.get('records', [])}
    aliases = {}
    # Plain records precede explicit aliases, including a target from this batch.
    for incoming in sorted(reviewed, key=lambda r: bool(r.get('duplicate_of'))):
        ident = incoming['id']
        target = incoming.get('duplicate_of') or ident
        target = aliases.get(target, target)
        if incoming.get('duplicate_of') and target not in records:
            raise ValueError(f'Unresolved duplicate target {target}; nothing imported')
        aliases[ident] = target
        if target in records:
            records[target] = enrich_report(records[target], incoming)
        else:
            records[target] = {k: copy.deepcopy(v) for k, v in incoming.items()
                               if k not in {'duplicate_of', 'replace_fields'}}
            records[target].update(copy.deepcopy(incoming.get('replace_fields', {})))
    # The existing reviewer has a bounded-feed contract. A history import must
    # not achieve it by clipping existing or newly reviewed partner reports.
    if max_records is not None and len(records) > max_records:
        raise ValueError('History exceeds the 1000-report feed; preserve it and arrange accessible archival retention first')
    if list(records.values()) == feed.get('records', []):
        return result
    result['records'] = sorted(records.values(), key=lambda r: (r['published_at'], r['id']), reverse=True)
    if result['records'] != feed.get('records', []):
        result['updated_at'] = now
    return result


def read_document(app_id, path='feed.json', *, missing_ok=False):
    with tempfile.TemporaryDirectory(prefix='funding-read-') as directory:
        headers, body = Path(directory) / 'headers', Path(directory) / 'body'
        receipt = subprocess.run(['mapi', '-D', str(headers), '-o', str(body),
                                  f'/api/storage/apps/{app_id}/{path}'], capture_output=True, text=True)
        if receipt.returncode:
            if missing_ok and any(line.startswith('HTTP/') and ' 404 ' in line for line in headers.read_text().splitlines()):
                return {'version': 1, 'records': []}, None
            raise RuntimeError(receipt.stderr.strip() or receipt.stdout.strip())
        etag = next((line.split(':', 1)[1].strip() for line in headers.read_text().splitlines()
                     if line.lower().startswith('etag:')), None)
        if not etag:
            raise RuntimeError('Document version missing; cannot safely import')
        return json.loads(body.read_text()), etag


def write_document(app_id, path, document, etag):
    guard = f'If-Match: {etag}' if etag else 'If-None-Match: *'
    receipt = subprocess.run(['mapi', '-X', 'PUT', '-H', 'Content-Type: application/json',
                              '-H', guard, '--data-binary', '@-',
                              f'/api/storage/apps/{app_id}/{path}'],
                             input=json.dumps(document, ensure_ascii=False), capture_output=True, text=True)
    if receipt.returncode and '412' in receipt.stderr:
        return False
    if receipt.returncode:
        raise RuntimeError(receipt.stderr.strip() or receipt.stdout.strip())
    return True


def import_reviewed(app_id, reviewed, *, read=read_document, write=None):
    if write is None:
        write = lambda feed, etag: write_document(app_id, 'feed.json', feed, etag)
    for _ in range(3):
        current, etag = read(app_id)
        merged = merge_reviewed(current, reviewed, dt.datetime.now(dt.timezone.utc).isoformat())
        if merged == current:
            return current
        if write(merged, etag):
            return merged
    raise RuntimeError('Feed changed during all three import attempts; reviewed artifacts retained for retry')


def import_history(app_id, reviewed, *, read=read_document, write=write_document, preview=False):
    """Archive new history; enrich existing live reports without moving them.

Archive acceptance precedes the feed update. A conflict or interruption may
therefore leave a partially imported batch, but never erase a report. Replaying
the same artifacts is additive/idempotent and finishes the remaining updates.
"""
    for _ in range(3):
        live, live_etag = read(app_id)
        archive, archive_etag = read(app_id, 'history-reports.json', missing_ok=True)
        live_ids = {r['id'] for r in live.get('records', [])}
        to_live, to_archive = [], []
        for record in reviewed:
            target = record.get('duplicate_of') or record['id']
            (to_live if target in live_ids else to_archive).append(record)
        now = dt.datetime.now(dt.timezone.utc).isoformat()
        merged_live = merge_reviewed(live, to_live, now)
        merged_archive = merge_reviewed(archive, to_archive, now, max_records=None)
        if preview:
            return merged_live, merged_archive
        if merged_archive != archive and not write(app_id, 'history-reports.json', merged_archive, archive_etag):
            continue
        if merged_live != live and not write(app_id, 'feed.json', merged_live, live_etag):
            continue
        return merged_live, merged_archive
    raise RuntimeError('History import conflicted three times; accepted records remain safe and artifacts can be replayed')


if __name__ == '__main__':
    import argparse
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('app_id', type=int)
    parser.add_argument('reviews', nargs='+', type=Path)
    parser.add_argument('--preview', action='store_true', help='Read and merge only; do not write')
    parser.add_argument('--history', action='store_true', help='Archive historical reports and enrich existing live matches')
    args = parser.parse_args()
    reviewed = [r for file in args.reviews for r in json.loads(file.read_text())['records']]
    if args.history:
        merged, archive = import_history(args.app_id, reviewed, preview=args.preview)
    elif args.preview:
        live, _ = read_document(args.app_id)
        merged = merge_reviewed(live, reviewed, dt.datetime.now(dt.timezone.utc).isoformat())
    else:
        merged = import_reviewed(args.app_id, reviewed)
    print(json.dumps({'preview': args.preview, 'live_reports': len(merged['records']),
                      'archived_reports': len(archive['records']) if args.history else 0,
                      'reviewed_inputs': len(reviewed)}))
