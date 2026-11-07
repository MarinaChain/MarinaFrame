"""Versioned research datasets with checked annotations and group separation.

This is data preparation, not a professional review or an inference-time source
of reference geometry. Sealed/validation examples are never emitted as training
rows. Files and local role labels do not authenticate a qualified engineer.
"""
from __future__ import annotations

import base64
from datetime import datetime
import hashlib
import html
import importlib.metadata
import json
from pathlib import Path
import re
from urllib.parse import urlsplit

from .provenance import safe_relative_file
from .schema import load_bounded_json


ANNOTATION_VERSION = 'marinaframe-annotation-1'
DATASET_VERSION = 'marinaframe-dataset-1'
MAX_JSON_BYTES = 4 * 1024 * 1024
MAX_ASSET_BYTES = 200_000_000
MAX_PACKET_IMAGE_BYTES = 32_000_000
ALLOWED = {'allowed', 'owner_authorized', 'public_domain_allowed', 'mit_license_allowed'}


class DatasetError(ValueError):
    pass


def digest(path: Path) -> str:
    hasher = hashlib.sha256()
    with path.open('rb') as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b''):
            hasher.update(block)
    return hasher.hexdigest()


def canonical_digest(value) -> str:
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(',', ':'),
                                     allow_nan=False).encode()).hexdigest()


def _load(path: Path):
    return load_bounded_json(path, max_bytes=MAX_JSON_BYTES, max_nodes=300_000)


def _validator(schema_path: Path):
    try:
        from jsonschema import Draft202012Validator, FormatChecker
        from referencing import Registry
    except ImportError as exc:
        raise DatasetError('Install the hash-pinned data dependencies before validation') from exc
    schema = _load(schema_path)
    if schema.get('$schema') != 'https://json-schema.org/draft/2020-12/schema':
        raise DatasetError('Only the declared Draft 2020-12 schema is supported')

    def check_refs(value):
        if isinstance(value, dict):
            for key, child in value.items():
                if key in ('$ref', '$dynamicRef') and not (isinstance(child, str) and child.startswith('#')):
                    raise DatasetError('Annotation schemas may not retrieve external references')
                check_refs(child)
        elif isinstance(value, list):
            for child in value:
                check_refs(child)

    check_refs(schema)
    Draft202012Validator.check_schema(schema)
    checker = FormatChecker()

    @checker.checks('date-time')
    def project_datetime(value):
        if not isinstance(value, str):
            return True
        if not re.fullmatch(r'\d{4}-\d\d-\d\dT\d\d:\d\d:\d\d(?:\.\d+)?(?:Z|[+-]\d\d:\d\d)', value):
            return False
        try:
            parsed = datetime.fromisoformat(value.replace('Z', '+00:00'))
            return parsed.tzinfo is not None
        except ValueError:
            return False

    @checker.checks('uri')
    def source_uri(value):
        if not isinstance(value, str):
            return True
        try:
            parsed = urlsplit(value)
            return (parsed.scheme in ('https', 'http') and bool(parsed.hostname)
                    and not parsed.username and not parsed.password and not any(c.isspace() for c in value))
        except ValueError:
            return False

    def no_remote(uri):
        raise DatasetError('External schema reference retrieval is disabled')

    return Draft202012Validator(schema, format_checker=checker,
                                 registry=Registry(retrieve=no_remote))


def _verified_image(root: Path, file: str, expected: str) -> dict:
    from PIL import Image
    path = safe_relative_file(root, file)
    size = path.stat().st_size
    if size < 1 or size > MAX_ASSET_BYTES:
        raise DatasetError('Asset byte budget exceeded')
    before = path.stat()
    actual = digest(path)
    if expected != actual:
        raise DatasetError('Asset hash mismatch')
    with Image.open(path) as image:
        width, height = image.size
    after = path.stat()
    if (before.st_ino, before.st_mtime_ns, before.st_size) != (after.st_ino, after.st_mtime_ns, after.st_size):
        raise DatasetError('Asset changed during inspection')
    if min(width, height) < 1 or width * height > 150_000_000:
        raise DatasetError('Asset pixel budget exceeded')
    return {'file': file, 'sha256': actual, 'bytes': size, 'width_px': width, 'height_px': height}


def _geometry_errors(geometry: dict | None, width: int, height: int) -> list[str]:
    if geometry is None:
        return []
    errors = []
    box = geometry.get('bbox_px')
    if box is not None and not (0 <= box[0] < box[2] <= width and 0 <= box[1] < box[3] <= height):
        errors.append('invalid_or_outside_bbox')
    points = list(geometry.get('polyline_px', []))
    if 'point_px' in geometry:
        points.append(geometry['point_px'])
    if any(not (0 <= x < width and 0 <= y < height) for x, y in points):
        errors.append('point_outside_asset')
    return errors


def validate_annotation(annotation_path: Path, asset_root: Path, schema_path: Path,
                        *, reviewer_registry: dict | None = None,
                        previous_revision_path: Path | None = None) -> dict:
    """Apply full JSON Schema plus file, bounds, identity and lineage checks.

    An optional reviewer registry is a locally supplied assertion, not identity
    authentication. Automated work does not create it. In its absence gold
    promotion fails; structural success never changes annotation review status.
    """
    report = {'annotation_file': annotation_path.name, 'valid': False, 'errors': [],
              'validation_standard': 'JSON Schema Draft 2020-12 with format assertions and domain checks',
              'schema_sha256': digest(schema_path), 'professional_identity_authenticated': False,
              'engineering_approved': False}

    def error(code, path='$', message=None):
        row = {'code': code, 'path': path}
        if message:
            row['message'] = str(message)[:240]
        report['errors'].append(row)

    try:
        document = _load(annotation_path)
        report['annotation_sha256'] = digest(annotation_path)
        validator = _validator(schema_path)
        report['validator_version'] = importlib.metadata.version('jsonschema')
        for failure in validator.iter_errors(document):
            error('schema_error', '$.' + '.'.join(map(str, failure.absolute_path)), failure.message)
            if len(report['errors']) >= 64:
                break
        if report['errors']:
            return report
        if document['schema_version'] != ANNOTATION_VERSION:
            error('unknown_annotation_version')
            return report
        asset = document['asset']
        verified = _verified_image(asset_root, asset['file'], asset['sha256'])
        if (asset['width_px'], asset['height_px']) != (verified['width_px'], verified['height_px']):
            error('asset_dimension_mismatch', '$.asset')
        width, height = verified['width_px'], verified['height_px']
        ids = [feature['id'] for feature in document['features']]
        if len(ids) != len(set(ids)):
            error('duplicate_feature_id', '$.features')
        image_cache = {(asset['file'], asset['sha256']): verified}
        for feature in document['features']:
            fp = '$.features.' + feature['id']
            for code in _geometry_errors(feature['geometry'], width, height):
                error(code, fp + '.geometry')
            alternatives = feature['alternatives']
            alternative_ids = [alternative['id'] for alternative in alternatives]
            if len(set(alternative_ids)) != len(alternative_ids):
                error('duplicate_alternative_id', fp + '.alternatives')
            if sum(a['selected'] is True for a in alternatives) > 1:
                error('contradictory_alternative_selection', fp + '.alternatives')
            for alternative in alternatives:
                for code in _geometry_errors(alternative['geometry'], width, height):
                    error(code, fp + '.alternatives.' + alternative['id'])
            for evidence in feature['evidence']:
                key = (evidence['asset_file'], evidence['asset_sha256'])
                if key not in image_cache:
                    image_cache[key] = _verified_image(asset_root, *key)
                info = image_cache[key]
                for code in _geometry_errors({'bbox_px': evidence['bbox_px']} if 'bbox_px' in evidence else None,
                                             info['width_px'], info['height_px']):
                    error(code, fp + '.evidence')
            if feature['observation'] == 'unknown' and feature['value'] is not None:
                error('unknown_value_must_be_null', fp)
            if feature['observation'] == 'inferred' and not feature.get('derivation'):
                error('inference_requires_basis', fp)
        for review in document['reviews']:
            if not set(review['features']) <= set(ids):
                error('review_unknown_feature', '$.reviews')
        for dispute in document['disagreements']:
            if not set(dispute['feature_ids']) <= set(ids):
                error('disagreement_unknown_feature', '$.disagreements')
            if dispute['status'] == 'adjudicated' and not dispute.get('adjudication'):
                error('missing_adjudication_record', '$.disagreements')
        if document['revision'] == 1:
            if document['previous_revision_sha256'] is not None:
                error('first_revision_has_parent', '$.previous_revision_sha256')
        elif previous_revision_path is None:
            error('previous_revision_evidence_required', '$.previous_revision_sha256')
        else:
            previous = _load(previous_revision_path)
            if (digest(previous_revision_path) != document['previous_revision_sha256']
                    or previous['annotation_id'] != document['annotation_id']
                    or previous['revision'] + 1 != document['revision']
                    or previous['source_item_id'] != document['source_item_id']):
                error('revision_lineage_mismatch', '$.previous_revision_sha256')
        if document['gold_truth']:
            reviews = document['reviews']
            reviewers = {review['reviewer_id'] for review in reviews}
            if len(reviewers) < 2 or document['annotator']['id'] in reviewers:
                error('independent_reviewers_required', '$.reviews')
            if not reviewer_registry or reviewer_registry.get('schema_version') != 'marinaframe-reviewer-registry-1':
                error('external_reviewer_registry_required', '$.reviews')
            else:
                eligible = {r['id']: r for r in reviewer_registry.get('reviewers', [])
                            if r.get('qualified') is True and r.get('role') in ('human_engineer', 'independent_adjudicator')}
                if document['annotator']['id'] not in eligible:
                    error('unrecognized_qualified_annotator', '$.annotator')
                for feature_id in ids:
                    coverage = {review['reviewer_id'] for review in reviews
                                if feature_id in review['features'] and review['decision'] == 'accept'}
                    if len(coverage) < 2:
                        error('two_independent_acceptances_required_per_feature', '$.features.' + feature_id)
                if not reviewers <= set(eligible):
                    error('unrecognized_qualified_reviewer', '$.reviews')
                for review in reviews:
                    if review['reviewer_id'] in eligible and eligible[review['reviewer_id']]['role'] != review['reviewer_role']:
                        error('reviewer_role_mismatch', '$.reviews')
                report['reviewer_registry_sha256'] = canonical_digest(reviewer_registry)
        report.update(annotation_id=document['annotation_id'], source_item_id=document['source_item_id'],
                      vessel_id=document['vessel_id'], source_family=document['source_family'],
                      split=document['split'], gold_truth=document['gold_truth'],
                      feature_count=len(document['features']), verified_assets=list(image_cache.values()))
    except Exception as exc:
        error('invalid_annotation_or_evidence', message=type(exc).__name__ + ': ' + str(exc)[:180])
    report['valid'] = not report['errors']
    return report


def group_items(items: list[dict]) -> list[dict]:
    """Connected components of vessel/design/source-family/exact-duplicate links."""
    if not isinstance(items, list) or not 1 <= len(items) <= 10_000:
        raise DatasetError('Dataset needs one to 10,000 bounded items')
    parents = list(range(len(items)))

    def find(index):
        while parents[index] != index:
            parents[index] = parents[parents[index]]
            index = parents[index]
        return index

    seen = {}
    item_ids = set()
    for index, item in enumerate(items):
        for field in ('item_id', 'vessel_id', 'design_group_id', 'source_family', 'asset_sha256', 'split'):
            if not isinstance(item.get(field), str) or not item[field]:
                raise DatasetError('Dataset item is missing a declared grouping field: ' + field)
        if item['item_id'] in item_ids:
            raise DatasetError('Duplicate dataset item ID')
        item_ids.add(item['item_id'])
        if item['split'] not in ('development', 'validation', 'sealed_final'):
            raise DatasetError('Unknown dataset split')
        for field in ('vessel_id', 'design_group_id', 'source_family', 'asset_sha256', 'duplicate_group_id'):
            if not item.get(field):
                continue
            key = (field, item[field])
            if key in seen:
                parents[find(index)] = find(seen[key])
            else:
                seen[key] = index
    groups = {}
    for index, item in enumerate(items):
        groups.setdefault(find(index), []).append(item)
    output = []
    for members in groups.values():
        splits = {item['split'] for item in members}
        if len(splits) != 1:
            raise DatasetError('Connected vessel/design/source/duplicate group crosses dataset splits')
        identities = sorted(item['item_id'] for item in members)
        output.append({'group_id': 'group-' + canonical_digest(identities)[:20], 'items': identities,
                       'split': next(iter(splits)), 'vessels': sorted({m['vessel_id'] for m in members}),
                       'source_families': sorted({m['source_family'] for m in members})})
    return sorted(output, key=lambda group: group['group_id'])


def build_dataset(manifest_path: Path, asset_root: Path, schema_path: Path, out: Path,
                  *, allow_provisional: bool = False) -> dict:
    manifest = _load(manifest_path)
    if manifest.get('schema_version') != DATASET_VERSION:
        raise DatasetError('Unknown dataset manifest schema')
    items = manifest['items']
    groups = group_items(items)
    reports, training_rows, public_files, restricted_files = [], [], set(), set()
    for item in items:
        annotation = safe_relative_file(asset_root, item['annotation_file'])
        validation = validate_annotation(annotation, asset_root, schema_path)
        reports.append(validation)
        if not validation['valid']:
            raise DatasetError('Invalid annotation for item: ' + item['item_id'])
        document = _load(annotation)
        if (document['source_item_id'] != item['item_id'] or document['vessel_id'] != item['vessel_id']
                or document['source_family'] != item['source_family'] or document['split'] != item['split']
                or document['asset']['sha256'] != item['asset_sha256']):
            raise DatasetError('Manifest/annotation identity or split mismatch')
        rights = item.get('rights')
        if not isinstance(rights, dict):
            raise DatasetError('Each item requires an explicit rights record')
        if rights.get('local_processing') not in ALLOWED:
            raise DatasetError('Local-processing right is absent')
        public = rights.get('source_redistribution') in ALLOWED and rights.get('derived_distribution') in ALLOWED
        files = [annotation.relative_to(asset_root).as_posix()] + [a['file'] for a in validation['verified_assets']]
        (public_files if public else restricted_files).update(files)
        if item['split'] != 'development' or rights.get('training') not in ALLOWED:
            continue
        for feature in document['features']:
            provisional = feature['review_status'] == 'provisional'
            if (feature['review_status'] not in ('accepted', 'provisional') or feature['observation'] == 'unknown'
                    or provisional and not allow_provisional):
                continue
            training_rows.append({
                'item_id': item['item_id'], 'vessel_id': item['vessel_id'],
                'source_family': item['source_family'], 'asset': document['asset'],
                'annotation_sha256': validation['annotation_sha256'], 'feature': feature,
                'label_status': 'provisional_assistant_label' if provisional else 'accepted_annotation',
                'gold_truth': document['gold_truth'], 'rights': rights,
                'professional_identity_authenticated': False,
            })
    # A file referenced by a restricted item cannot enter a public release merely
    # because another item claims it has broader rights.
    public_files.difference_update(restricted_files)
    out.mkdir(parents=True, exist_ok=False)
    version_basis = {'manifest_sha256': digest(manifest_path), 'schema_sha256': digest(schema_path),
                     'annotation_hashes': [r['annotation_sha256'] for r in reports],
                     'allow_provisional': allow_provisional, 'groups': groups}
    report = {'schema_version': 'marinaframe-built-dataset-1',
              'dataset_sha256': canonical_digest(version_basis), **version_basis,
              'items': len(items), 'independent_vessels': len({item['vessel_id'] for item in items}),
              'source_families': len({item['source_family'] for item in items}),
              'groups': groups, 'training_rows': len(training_rows),
              'gold_annotation_documents': sum(r['gold_truth'] is True for r in reports),
              'validation': reports, 'public_release_allowlist': sorted(public_files),
              'restricted_files_excluded_from_public_release': sorted(restricted_files),
              'sealed_final_rows_emitted_for_training': 0,
              'review_registry_used': False, 'engineering_approved': False}
    (out / 'dataset-version.json').write_text(json.dumps(report, indent=2, allow_nan=False) + '\n')
    with (out / 'development-labels.jsonl').open('w') as handle:
        for row in training_rows:
            handle.write(json.dumps(row, allow_nan=False) + '\n')
    (out / 'input-manifest.json').write_bytes(manifest_path.read_bytes())
    return report


def review_packet(manifest_path: Path, asset_root: Path, schema_path: Path, out: Path,
                  *, audience: str = 'local') -> dict:
    if audience not in ('local', 'release'):
        raise DatasetError('Unknown review-packet audience')
    manifest = _load(manifest_path)
    if manifest.get('schema_version') != DATASET_VERSION:
        raise DatasetError('Unknown dataset manifest schema')
    group_items(manifest['items'])
    sections, included, omitted = [], [], []
    total_image_bytes = 0
    for item in manifest['items']:
        annotation_path = safe_relative_file(asset_root, item['annotation_file'])
        result = validate_annotation(annotation_path, asset_root, schema_path)
        if not result['valid']:
            raise DatasetError('Cannot make a packet from invalid annotations')
        annotation = _load(annotation_path)
        rights = item.get('rights')
        if not isinstance(rights, dict):
            raise DatasetError('Each item requires an explicit rights record')
        permitted = (rights.get('local_processing') in ALLOWED if audience == 'local'
                     else rights.get('source_redistribution') in ALLOWED and rights.get('derived_distribution') in ALLOWED)
        if not permitted:
            omitted.append(item['item_id'])
            sections.append('<section><h2>' + html.escape(item['item_id']) + '</h2><p>Drawing and annotations omitted: release permission is unresolved. Local training/testing authorization remains recorded.</p></section>')
            continue
        asset = safe_relative_file(asset_root, annotation['asset']['file'])
        total_image_bytes += asset.stat().st_size
        if total_image_bytes > MAX_PACKET_IMAGE_BYTES:
            raise DatasetError('Aggregate review-packet image budget exceeded; create smaller packets')
        if asset.stat().st_size > 5_000_000:
            raise DatasetError('Review packets require an explicitly declared bounded preview asset')
        suffix = asset.suffix.lower()
        mime = {'.png': 'image/png', '.jpg': 'image/jpeg', '.jpeg': 'image/jpeg'}.get(suffix)
        if mime is None:
            raise DatasetError('Review packets require PNG or JPEG display assets')
        image = '<img alt="Untouched source display asset" src="data:' + mime + ';base64,' + base64.b64encode(asset.read_bytes()).decode() + '">'
        rows = ''.join('<tr><td>' + html.escape(feature['id']) + '</td><td>' + html.escape(feature['kind'])
                       + '</td><td>' + html.escape(feature['observation']) + ' / ' + html.escape(feature['review_status'])
                       + '</td><td>' + html.escape(feature['uncertainty'])
                       + '<details><summary>Label, coordinates and evidence</summary><pre>'
                       + html.escape(json.dumps(feature,indent=2,allow_nan=False))
                       + '</pre></details></td></tr>' for feature in annotation['features'])
        limitations = ''.join('<li>' + html.escape(note) + '</li>' for note in annotation['source_limitations'])
        sections.append('<section><h2>' + html.escape(item['item_id']) + '</h2>' + image
                        + '<p>Asset SHA-256: <code>' + annotation['asset']['sha256'] + '</code></p>'
                        + '<table><thead><tr><th>Feature</th><th>Kind</th><th>Status</th><th>Uncertainty / review question</th></tr></thead><tbody>'
                        + rows + '</tbody></table><ul>' + limitations + '</ul></section>')
        included.append(item['item_id'])
    content = '<!doctype html><html lang="en"><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>MarinaFrame annotation review packet</title><style>body{font:16px/1.6 system-ui,sans-serif;background:#edf3f5;color:#183443;margin:0}main{max-width:1100px;margin:auto;padding:24px;background:white}h1,h2{line-height:1.2}section{margin:36px 0;border-top:1px solid #bcced7;padding-top:20px}img{width:100%;max-height:900px;object-fit:contain}table{display:block;overflow:auto;border-collapse:collapse;font-size:13px}th,td{padding:9px;border:1px solid #cbd9df;text-align:left;vertical-align:top}code{overflow-wrap:anywhere}pre{white-space:pre-wrap;overflow-wrap:anywhere;min-width:20em;max-width:65em}summary{cursor:pointer;font-weight:600}aside{padding:16px;background:#fff2ce;border-left:4px solid #b87b26}</style><main><h1>MarinaFrame: source annotation review</h1><aside>Provisional assistant annotations. No qualified professional review has been completed. Schema validity checks structure and file identity; it does not establish correct interpretation or hull accuracy. Engineering approval remains false. Audience: ' + audience + '.</aside>' + ''.join(sections) + '</main></html>'
    out.parent.mkdir(parents=True, exist_ok=True)
    with out.open('x', encoding='utf-8') as handle:
        handle.write(content)
    return {'file': out.name, 'sha256': digest(out), 'audience': audience,
            'included_items': included, 'rights_omitted_items': omitted,
            'engineering_approved': False, 'external_requests': 0,
            'embedded_image_bytes': total_image_bytes, 'max_image_bytes': MAX_PACKET_IMAGE_BYTES}
