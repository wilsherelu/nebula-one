"""Apply the frozen user overlay to organizational results, retaining the base answer."""
from copy import deepcopy
from ..errors import DomainError
from ..hashing import canonical_json_sha256
from .pcf import _attach_pcf_user_method_grouping


def apply_organization_user_method(result, snapshot):
    method = (snapshot.provider_receipt or {}).get('user_calculation_method')
    if not method:
        return result
    if method.get('purpose') != 'organization' or method.get('model_revision_id') != snapshot.system_revision_id:
        raise DomainError(code='ORGANIZATION_USER_METHOD_SOURCE_MISMATCH',
                          message='organization rules must bind this frozen model revision and purpose',status_code=422)
    # Supplementary declarations have separate factor evidence, not engine path receipts.
    # Never silently omit them when selecting a path-only user view.
    if any(row.get('activities') or row.get('proxy_activities') for row in result['groups']['other_value_chain']['categories']):
        raise DomainError(code='ORGANIZATION_USER_METHOD_ACTIVITY_UNBOUND',
                          message='supplementary activities need explicit user-rule identities before grouping',status_code=422)
    source = result.get('climate_source') or {}
    analysis = _attach_pcf_user_method_grouping(contribution_analysis={},provider_receipt=snapshot.provider_receipt,
        scaled_elementary_exchanges=snapshot.scaled_elementary_exchanges,lcia_results=snapshot.lcia_results,
        indicator_key=source.get('indicator_key',''),indicator_unit=result['groups']['on_site_direct']['unit'])
    overlay = analysis.get('user_method_grouping')
    if not overlay or overlay['grouping_mode'] != 'path_weighted':
        raise DomainError(code='ORGANIZATION_USER_METHOD_PATH_RECEIPT_REQUIRED',
                          message='frozen path contribution receipts are required for organization rules',status_code=422)
    overlay = deepcopy(overlay)
    scale = result['activity_basis']['scale_factor']
    grouping = overlay['grouping']
    for bucket in [*grouping['scopes'].values(),grouping['excluded'],grouping['unattributed'],grouping['engine_gap']]:
        if bucket['value'] is not None: bucket['value'] *= scale
    grouping['contribution_total'] *= scale
    for path in grouping['paths']: path['path_contribution_value'] *= scale
    # Dimension results are totals in the same period basis, never summed across dimensions.
    def scale_dimensions(value):
        if isinstance(value,dict):
            return {k:(v*scale if k in {'value','subtotal','known_total','contribution_total','included_total','excluded_total','unattributed_total'}
                             and isinstance(v,(int,float)) and not isinstance(v,bool) else scale_dimensions(v)) for k,v in value.items()}
        if isinstance(value,list): return [scale_dimensions(v) for v in value]
        return value
    overlay['dimension_grouping']=scale_dimensions(overlay.get('dimension_grouping'))
    result['base_accounting']={k:deepcopy(result[k]) for k in ('groups','combined_total','coverage')}
    result['user_method_grouping']=overlay
    for scope,key in (('scope_1','on_site_direct'),('scope_2','purchased_energy_lifecycle'),('scope_3','other_value_chain')):
        result['groups'][key]['value']=grouping['scopes'][scope]['value']
        result['groups'][key]['status']='counted' if grouping['scopes'][scope]['value'] is not None else 'unassigned'
    result['counted_total']=sum(b['value'] for b in grouping['scopes'].values() if b['value'] is not None)
    dimension_answer=(overlay.get('dimension_grouping') or {}).get('grouping')
    if dimension_answer is not None:
        result['counted_total']=dimension_answer['known_total']
    result['known_model_total']=grouping['contribution_total']
    # Missing business sources remain missing even if all known engine terms are classified.
    result['combined_total']=result['counted_total'] if result['base_accounting']['combined_total'] is not None and overlay['execution_status']=='executed_full' else None
    result.pop('content_sha256',None)
    result['content_sha256']=canonical_json_sha256(result)
    return result
