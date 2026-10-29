from copy import deepcopy
from nebula_one.services.results import _semantic_solved_output


def test_rechecking_or_renaming_same_frozen_rules_does_not_conflict_with_snapshot_cache():
    first={'provider_receipt':{'user_calculation_method':{'method_id':'m','version':1,
        'content_sha256':'a'*64,'execution_plan_sha256':'b'*64,'validated_at':'2026-10-14',
        'name':'Original','rules':[{'exchange_id':'node::co2','boundary_status':'selected'}]}},
        'lcia_results':{'value':10}}
    rechecked=deepcopy(first)
    rechecked['provider_receipt']['user_calculation_method'].update(validated_at='2026-10-15',name='Renamed')
    assert _semantic_solved_output(first)==_semantic_solved_output(rechecked)
    assert first['provider_receipt']['user_calculation_method']['name']=='Original'
    changed=deepcopy(rechecked);changed['provider_receipt']['user_calculation_method']['rules'][0]['boundary_status']='excluded'
    assert _semantic_solved_output(first)!=_semantic_solved_output(changed)
    changed=deepcopy(rechecked);changed['lcia_results']['value']=11
    assert _semantic_solved_output(first)!=_semantic_solved_output(changed)
