from types import SimpleNamespace

from nebula_one.services.flow_display import exact_flow_labels


def test_exact_display_keeps_identity_and_uses_source_languages():
    port = {'id': 'in', 'flowSourceNamespace': 'custom', 'flowUuid': 'flow', 'flowVersion': '1.0.0'}
    graph = {'nodes': [{'id': 'a', 'inputs': [port]}, {'id': 'b', 'inputs': [port]}]}
    calls = []
    def resolve(request):
        calls.append(request)
        return SimpleNamespace(payload={'items': [{'status': 'resolved', 'value': {
            'source_namespace': 'custom', 'flow_uuid': 'flow', 'version': '1.0.0',
            'display_names': {'zh': '实际来源名称', 'en': 'Actual source name'}}}]})
    client = SimpleNamespace(resolve_provider_catalog=resolve)
    assert exact_flow_labels(client, graph, 'zh') == ({'a::in': '实际来源名称', 'b::in': '实际来源名称'}, [])
    assert len(calls[0]['flows']) == 1
    assert exact_flow_labels(client, graph, 'en')[0]['a::in'] == 'Actual source name'
    assert graph['nodes'][0]['inputs'][0] == port


def test_different_version_cannot_supply_a_name():
    graph = {'nodes': [{'id': 'p', 'inputs': [{'id': 'in', 'flowSourceNamespace': 'tg', 'flowUuid': 'f', 'flowVersion': '1'}]}]}
    client = SimpleNamespace(resolve_provider_catalog=lambda _: SimpleNamespace(payload={'items': [
        {'status': 'resolved', 'key': 'f@2', 'value': {'source_namespace': 'tg', 'flow_uuid': 'f', 'version': '2', 'name': 'Wrong version'}}]}))
    labels, issues = exact_flow_labels(client, graph, 'zh')
    assert labels == {}
    assert issues


def test_report_labels_use_exchange_identity_instead_of_shared_quantity_key():
    from nebula_one.analysis.frozen_report import names
    graph = {'nodes': [{'id': 'supplier', 'process_uuid': 'supplier', 'outputs': [{'id': 'out', 'name': 'Output'}]},
                      {'id': 'consumer', 'process_uuid': 'consumer', 'inputs': [{'id': 'in', 'name': 'Input'}]}]}
    _, exchanges = names(graph, {'fields': [
        {'key': 'supplier::out', 'process_id': 'supplier', 'port_id': 'out', 'label': 'Supplier label'},
        {'key': 'supplier::out', 'process_id': 'consumer', 'port_id': 'in', 'label': 'Consumer label'},
    ]})
    assert exchanges['supplier::out']['name'] == 'Supplier label'
    assert exchanges['consumer::in']['name'] == 'Consumer label'
