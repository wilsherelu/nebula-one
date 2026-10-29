"""Template workspace acceptance against a live One instance and the real steel seed.

Reads what an exact template version binds, copies one official scheme, narrows a real declared
CO2 path, checks it, saves the template version as the reader's own, creates a project from it and
proves the inherited scheme is an independent draft. Every value asserted here is read back over
HTTP from the running service; nothing is inferred from files or from names.

Artificial acceptance quantities, NOT a measured facility inventory or a regulatory CBAM claim.
"""
from datetime import datetime, timezone
from pathlib import Path
import argparse
import json
import urllib.error
import urllib.request
from uuid import uuid4


def request(base, method, path, body=None):
    data = json.dumps(body, ensure_ascii=False).encode() if body is not None else None
    call = urllib.request.Request(base + path, data=data, method=method,
                                  headers={'Content-Type': 'application/json'})
    try:
        with urllib.request.urlopen(call) as response:
            payload = response.read().decode()
            return response.status, (json.loads(payload) if payload else None)
    except urllib.error.HTTPError as error:
        payload = error.read().decode()
        return error.code, (json.loads(payload) if payload else None)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--one', default='http://127.0.0.1:18951')
    parser.add_argument('--output', default='.local-evidence/u5-template-workspace')
    args = parser.parse_args()
    out = Path(args.output)
    out.mkdir(parents=True, exist_ok=True)
    tag = datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ')
    evidence = {'one': args.one, 'tag': tag, 'steps': []}

    def record(name, value):
        evidence['steps'].append({'step': name, 'ok': True})
        (out / (name + '.json')).write_text(json.dumps(value, ensure_ascii=False, indent=2), encoding='utf-8')
        return value

    def get(path):
        status, body = request(args.one, 'GET', path)
        assert status == 200, (path, status, body)
        return body

    # 1. A freshly initialized library lists the installed template with its own bound schemes.
    templates = get('/api/v1/project-templates?lang=zh')['items']
    assert templates, 'the release catalog installed no template'
    template = next(item for item in templates if item['seed_id'] == 'nebula.iron-steel.bf-bof-crude-steel')
    record('01-templates', templates)
    described = get(f"/api/v1/project-templates/{template['id']}/accounting-methods?lang=zh")
    record('02-accounting-methods', described)
    assert described['schema_version'] == 'nebula_one.template-accounting-methods.v1'
    head = described['template']
    assert head['kind'] == 'seed' and head['official'] is True and head['editable'] is False
    for key in ('id', 'title', 'version', 'template_sha256', 'source_application_id',
                'source_model_id', 'source_revision_id', 'installed_application_id'):
        assert head[key] == template[key], key
    assert head['unresolved_method_package_refs'] == []
    assert head['model']['graph_basis'] == 'source_revision'
    assert head['model']['port_count'] > 0 and head['model']['process_count'] > 0
    officials = [item for item in described['methods'] if item['origin'] == 'official_package']
    assert officials, 'the template binds no official scheme'
    # Every listed scheme states where its rules come from; a package without per-flow rules says so
    # instead of implying the model's ports are covered.
    for item in described['methods']:
        assert item['rule_source']['port_count'] == head['model']['port_count']
        assert item['check']['status_basis']
        if item['rule_source']['kind'] == 'none':
            assert any(gap['code'] == 'NO_PER_FLOW_DECLARATION' for gap in item['coverage_gaps'])
    cbam = next(item for item in officials if item['method_group'] == 'cbam')
    assert cbam['rule_source']['declared_count'] > 0, 'the CBAM package declares no per-flow rule'
    assert cbam['rule_source']['declared_but_absent_from_model'] == []
    boundaries = [item for item in cbam['cbam_boundaries'] if item['boundary_type'] == 'cbam_trial']
    assert len(boundaries) == 1, boundaries

    # 2. Copy the official CBAM scheme against the one frozen boundary the seed installed.
    status, copied = request(args.one, 'POST',
                             f"/api/v1/project-templates/{template['id']}/accounting-methods/copy",
                             {'method_key': cbam['method_key'], 'name': f'CBAM·验收变体 {tag}',
                              'cbam_boundary_ref': boundaries[0]['id']})
    assert status == 201, (status, copied)
    record('03-copy', copied)
    detail = copied['method']
    method_id = detail['method']['id']
    assert detail['method']['purpose'] == 'cbam' and detail['method']['status'] == 'draft'
    assert detail['method']['model_revision_id'] == head['source_revision_id']
    version = detail['versions'][0]
    assert version['cbam_boundary_ref'] == boundaries[0]['id']
    declared = {rule['exchange_id'] for rule in version['rules']}
    # The package's own declarations, minus the reference product port the copy keeps out: a variant
    # narrows emissions, it never re-declares the product the result is per unit of.
    assert declared <= {item['exchange_id'] for item in cbam['rule_source']['declared']}, declared
    assert {item['exchange_id'] for item in cbam['rule_source']['declared']} - declared == \
           {copied['transcription']['reference_product_exchange_id']}
    assert len(declared) < head['model']['port_count']
    assert copied['transcription']['cbam_boundary_ref'] == boundaries[0]['id']

    # The copy is a working method on the template's own source, listed next to the official scheme.
    listed = get(f"/api/v1/project-templates/{template['id']}/accounting-methods?lang=zh")
    mine = [item for item in listed['methods'] if item['origin'] == 'source_user_method']
    assert any(item['user_method']['method_id'] == method_id for item in mine), 'the copy is unreachable'
    record('04-after-copy', listed)

    # 3. Narrow one real declared CO2 path, save the version and pass the check again.
    excluded = 'blast-furnace::co2-bf-raceway-out'
    assert excluded in declared, declared
    rules = [dict(rule, boundary_status='excluded', scope=None) if rule['exchange_id'] == excluded else rule
             for rule in version['rules']]
    status, saved = request(args.one, 'PUT', f'/api/v1/calculation-methods/{method_id}/versions/1',
                            {'rules': rules, 'cbam_boundary_ref': version['cbam_boundary_ref'],
                             'expected_content_sha256': version['content_sha256']})
    assert status == 200, (status, saved)
    # A save never rewrites the version it was based on: the edit lands as the next immutable one.
    assert saved['latest_version'] == version['version'] + 1, saved['latest_version']
    saved_version = next(item for item in saved['versions']
                         if item['version'] == saved['latest_version'])
    assert saved_version['content_sha256'] != version['content_sha256']
    assert next(rule for rule in saved_version['rules']
                if rule['exchange_id'] == excluded)['boundary_status'] == 'excluded'
    record('05-narrowed', saved)
    checked = request(args.one, 'POST',
                      f"/api/v1/calculation-methods/{method_id}/versions/{saved['latest_version']}/validate")[1]
    record('06-validate', checked)
    assert checked['valid'] is True, checked
    # The official scheme is immutable: narrowing the copy never touched the package's declaration.
    after = get(f"/api/v1/project-templates/{template['id']}/accounting-methods?lang=zh")
    official_after = next(item for item in after['methods']
                          if item['origin'] == 'official_package' and item['method_group'] == 'cbam')
    assert official_after['rule_source']['declared_count'] == cbam['rule_source']['declared_count']
    assert official_after['base_method_ref'] == cbam['base_method_ref']

    # 4. What the save offers for this exact template version, and what it refuses.
    plan = get(f"/api/v1/project-templates/{template['id']}/save-plan")
    record('07-save-plan', plan)
    assert plan['schema_version'] == 'nebula_one.template-save.v1'
    assert plan['template_id'] == template['id'] and plan['kind'] == 'seed'
    assert plan['source_revision_id'] == head['source_revision_id']
    assert plan['method_pins'] == [{'package_id': ref.rsplit('@', 1)[0], 'version': ref.rsplit('@', 1)[1],
                                    'content_sha256': head['method_pins'][ref]}
                                   for ref in head['method_package_refs']]
    assert plan['unresolved_method_package_refs'] == []
    candidate = next(item for item in plan['user_methods'] if item['method_id'] == method_id)
    assert candidate['status'] == 'ready' and candidate['rule_count'] == len(rules)
    if candidate['savable']:
        assert candidate['blocking_reason'] is None
        status, result = request(args.one, 'POST',
                                 f"/api/v1/project-templates/{template['id']}/save-template",
                                 {'title': f'钢铁·验收模板 {tag}', 'version': plan['suggested_version'],
                                  'user_methods': [{'method_id': method_id, 'version': candidate['version'],
                                                    'content_sha256': candidate['content_sha256']}]})
        assert status == 201, (status, result)
        record('08-save-template', result)
        saved_template = result['template']
        assert saved_template['kind'] == 'authored' and saved_template['user_method_count'] == 1
        assert result['frozen_user_methods'] == [{'method_id': method_id,
                                                  'version': candidate['version'],
                                                  'content_sha256': candidate['content_sha256']}]
        # A repeated identical submit reads back the same saved version instead of publishing a twin.
        status, repeat = request(args.one, 'POST',
                                 f"/api/v1/project-templates/{template['id']}/save-template",
                                 {'title': f'钢铁·验收模板 {tag}', 'version': plan['suggested_version'],
                                  'user_methods': [{'method_id': method_id, 'version': candidate['version'],
                                                    'content_sha256': candidate['content_sha256']}]})
        assert status == 201, (status, repeat)
        assert repeat['template']['id'] == saved_template['id']
        assert repeat['template']['template_sha256'] == saved_template['template_sha256']
        twins = [item for item in get('/api/v1/project-templates?lang=zh')['items']
                 if item['version'] == plan['suggested_version'] and item['title'] == saved_template['title']]
        assert len(twins) == 1, twins
        record('09-repeat-save', {'template_id': repeat['template']['id'], 'twins': len(twins)})

        # 5. A new project inherits an independent draft copy of the frozen scheme.
        status, project = request(args.one, 'POST',
                                  f"/api/v1/project-templates/{saved_template['id']}/projects",
                                  {'name': f'验收项目·继承 {tag}', 'project_key': str(uuid4()),
                                   'expected_template_sha256': saved_template['template_sha256']})
        assert status == 200, (status, project)
        record('10-project', project)
        application_id = project['application_id']
        inherited = [item for item in get(f'/api/v1/applications/{application_id}/calculation-methods')
                     if item['origin_method_id'] == method_id]
        assert len(inherited) == 1, inherited
        assert inherited[0]['id'] != method_id and inherited[0]['status'] == 'draft'
        inherited_version = get(f"/api/v1/calculation-methods/{inherited[0]['id']}/versions/1")
        assert [rule['exchange_id'] for rule in inherited_version['rules']] == \
               [rule['exchange_id'] for rule in saved_version['rules']]
        assert next(rule for rule in inherited_version['rules']
                    if rule['exchange_id'] == excluded)['boundary_status'] == 'excluded'
        record('11-inherited-method', inherited_version)
        assert request(args.one, 'POST',
                       f"/api/v1/calculation-methods/{inherited[0]['id']}/versions/1/validate")[1]['valid']

        # Editing the source method afterwards changes neither the saved template nor the new project.
        before_sha = get(f"/api/v1/project-templates/{saved_template['id']}/accounting-methods"
                         )['template']['template_sha256']
        status, edited = request(args.one, 'PUT',
                                 f"/api/v1/calculation-methods/{method_id}/versions/{saved['latest_version']}",
                                 {'rules': [dict(rule, boundary_status='selected', scope='scope_1')
                                            if rule['exchange_id'] == excluded else rule
                                            for rule in saved_version['rules']],
                                  'cbam_boundary_ref': saved_version['cbam_boundary_ref'],
                                  'expected_content_sha256': saved_version['content_sha256']})
        assert status == 200, (status, edited)
        assert get(f"/api/v1/project-templates/{saved_template['id']}/accounting-methods"
                   )['template']['template_sha256'] == before_sha
        assert get(f"/api/v1/calculation-methods/{inherited[0]['id']}/versions/1")['rules'] == \
               inherited_version['rules']
        frozen_after = next(item for item in get(
            f"/api/v1/project-templates/{saved_template['id']}/accounting-methods")['methods']
            if item['origin'] == 'template_user_method')
        assert frozen_after['rule_source']['declared_count'] == len(rules)
        record('12-isolation', {'template_sha256': before_sha,
                                'frozen_declared_count': frozen_after['rule_source']['declared_count']})
    else:
        # The plan names the reason instead of letting the reader hit a raw refusal later.
        assert candidate['blocking_reason'], candidate
        record('08-save-blocked', candidate)
        status, refused = request(args.one, 'POST',
                                  f"/api/v1/project-templates/{template['id']}/save-template",
                                  {'title': f'钢铁·验收模板 {tag}', 'version': plan['suggested_version'],
                                   'user_methods': [{'method_id': method_id, 'version': candidate['version'],
                                                     'content_sha256': candidate['content_sha256']}]})
        assert status == 422, (status, refused)
        record('09-save-refused', refused)

    # 6. A title longer than the stored column is refused at the contract, not truncated.
    status, too_long = request(args.one, 'POST', f"/api/v1/project-templates/{template['id']}/save-template",
                               {'title': '长' * 256, 'version': '9.9.9', 'user_methods': []})
    assert status == 422, (status, too_long)
    assert [item for item in get('/api/v1/project-templates?lang=zh')['items']
            if item['version'] == '9.9.9'] == []
    record('13-long-title-refused', too_long)

    # 7. A scheme this version does not bind cannot be copied, and a name is never silently reused.
    status, unbound = request(args.one, 'POST',
                              f"/api/v1/project-templates/{template['id']}/accounting-methods/copy",
                              {'method_key': 'official:not.bound@1.0.0', 'name': 'x'})
    assert status == 404 and unbound['error']['code'] == 'TEMPLATE_METHOD_COPY_SOURCE_NOT_FOUND', unbound
    status, duplicate = request(args.one, 'POST',
                                f"/api/v1/project-templates/{template['id']}/accounting-methods/copy",
                                {'method_key': cbam['method_key'], 'name': f'CBAM·验收变体 {tag}',
                                 'cbam_boundary_ref': boundaries[0]['id']})
    assert status == 409, (status, duplicate)
    record('14-copy-refusals', {'unbound': unbound, 'duplicate_name': duplicate})

    evidence['identities'] = {
        'template_id': template['id'], 'template_title': template['title'],
        'template_version': template['version'], 'template_sha256': template['template_sha256'],
        'source_revision_id': head['source_revision_id'], 'copied_method_id': method_id,
        'excluded_exchange_id': excluded,
        'declared_exchange_ids': sorted(declared),
        'frozen_boundary_id': boundaries[0]['id'],
    }
    (out / 'summary.json').write_text(json.dumps(evidence, ensure_ascii=False, indent=2), encoding='utf-8')
    print(json.dumps(evidence, ensure_ascii=False, indent=2))


if __name__ == '__main__':
    main()
