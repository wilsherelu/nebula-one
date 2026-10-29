from copy import deepcopy
from types import SimpleNamespace
import pytest

from nebula_one.analysis.organization_user_method import apply_organization_user_method
from nebula_one.analysis.frozen_organization_user import organization_user_report
from nebula_one.errors import DomainError
from nebula_one.hashing import canonical_json_sha256


def source(excluded=False, scale=1):
    rules=[]
    paths=[]
    scaled=[]
    for exchange,scope,value in [('site::co2','scope_1',10),('site::power','scope_2',3),('site::material','scope_3',7)]:
        is_background=scope!='scope_1'
        emission=exchange+'-emission' if is_background else exchange
        paths.append(dict(exchange_id=emission,consumer_exchange_id=exchange if is_background else None,
            process_uuid=scope,attribution_basis='background_consumer_path' if is_background else 'foreground_direct',path_contribution_value=value))
        scaled.append(dict(exchange_id=emission,process_id=scope,direction='output',flow_uuid='co2'))
        rules.append(dict(process_instance_id='site',exchange_id=exchange,flow_uuid=None,direction='input' if is_background else 'emission',
            scope=scope,location_role='onsite' if not is_background else 'purchased_energy' if scope=='scope_2' else 'upstream_supply',
            boundary_status='excluded' if excluded and scope=='scope_3' else 'selected',
            categories={'source':'material' if scope=='scope_3' else 'rest'}))
    snapshot=SimpleNamespace(system_revision_id='rev',scaled_elementary_exchanges=scaled,
        provider_receipt={'user_calculation_method':dict(purpose='organization',model_revision_id='rev',method_id='m',version=1,
            content_sha256='a'*64,execution_plan_sha256='b'*64,rules=rules,reporting_dimensions=[dict(id='source',name='Sources',
                categories=[dict(id='material',name='Material',is_leaf=True),dict(id='rest',name='Rest',is_leaf=True)])])},
        lcia_results={'path_weighted_contribution_receipts':[dict(canonical_indicator_key='climate',indicator_unit='kg CO2-Eq',terms=paths)]})
    result=dict(groups={'on_site_direct':dict(value=10*scale,unit='kg CO2-Eq',status='calculated'),
        'purchased_energy_lifecycle':dict(value=3*scale,unit='kg CO2-Eq',status='calculated'),
        'other_value_chain':dict(value=7*scale,unit='kg CO2-Eq',status='calculated',categories=[])},
        climate_source={'indicator_key':'climate'},activity_basis={'scale_factor':scale},combined_total=20*scale,
        coverage={'missing_categories':[]},content_sha256='old')
    return result,snapshot


@pytest.mark.parametrize('scale',[1,2])
def test_rule_exclusion_preserves_supplier_and_base_total_and_moves_contribution(scale):
    result,snapshot=source(excluded=True,scale=scale)
    before=deepcopy(snapshot.provider_receipt)
    answer=apply_organization_user_method(result,snapshot)
    assert answer['counted_total']==13*scale
    assert answer['known_model_total']==20*scale
    assert answer['base_accounting']['groups']['other_value_chain']['value']==7*scale
    assert answer['user_method_grouping']['grouping']['excluded']['value']==7*scale
    assert snapshot.provider_receipt==before
    assert answer['content_sha256']==canonical_json_sha256({k:v for k,v in answer.items() if k!='content_sha256'})


def test_dimension_groups_selectable_background_consumer_not_expanded_node_and_scales_once():
    result,snapshot=source(scale=2)
    answer=apply_organization_user_method(result,snapshot)
    dimensions=answer['user_method_grouping']['dimension_grouping']
    assert dimensions['reconciled'] and dimensions['grouping']['known_total']==40
    values={c['id']:c['subtotal'] for c in dimensions['grouping']['dimensions']['source']['categories']}
    assert values=={'material':14,'rest':26}


def test_legacy_result_without_rules_is_unchanged():
    result,snapshot=source();snapshot.provider_receipt={}
    assert apply_organization_user_method(result,snapshot)==result


def test_missing_business_data_still_prevents_complete_total():
    result,snapshot=source();result['combined_total']=None;result['coverage']['missing_categories']=['missing_supplier']
    answer=apply_organization_user_method(result,snapshot)
    assert answer['counted_total']==20 and answer['combined_total'] is None


def test_custom_dimensions_without_scope_labels_still_count_selected_contributions():
    result,snapshot=source()
    for rule in snapshot.provider_receipt['user_calculation_method']['rules']: rule['scope']=None
    answer=apply_organization_user_method(result,snapshot)
    assert answer['counted_total']==20
    assert answer['user_method_grouping']['dimension_grouping']['grouping']['known_total']==20
    assert all(group['value'] is None for group in answer['groups'].values())


def test_other_purpose_refused_instead_of_silently_ignored():
    result,snapshot=source();snapshot.provider_receipt['user_calculation_method']['purpose']='cbam'
    with pytest.raises(DomainError) as error: apply_organization_user_method(result,snapshot)
    assert error.value.code=='ORGANIZATION_USER_METHOD_SOURCE_MISMATCH'


def test_screen_export_projection_reconciles_and_keeps_excluded_source_identity():
    result,snapshot=source(excluded=True)
    answer=apply_organization_user_method(result,snapshot)
    snapshot_dict=dict(provider_receipt=snapshot.provider_receipt,lcia_results=snapshot.lcia_results)
    report=organization_user_report(answer,snapshot_dict,{'nodes':[{'id':'site','process_uuid':'site','name':'Site','inputs':[],'outputs':[]}]},{'fields':[]})
    assert sum(row['value'] for row in report['summary'] if row['value'] is not None)==20
    excluded=[row for row in report['details'] if row['group']=='user_excluded']
    assert len(excluded)==1 and excluded[0]['identity']['source_exchange_id']=='site::material-emission'
    assert report['outside_boundary'] and report['custom_dimensions'][0]['reconciled']
