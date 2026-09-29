from test_api_flow import _attach_model, _create_application


def test_same_revision_distinguishes_methods_and_demand_but_not_retry_keys(client):
    app = _create_application(client)
    model = _attach_model(client, app['id'])
    rid = model['upstream_receipt']['base_revision_id']
    url = f"/api/v1/applications/{app['id']}/system-revisions/{rid}/solve"
    demand = [{'reference_flow_uuid': 'flow-product', 'amount': 1, 'unit': 'kg'}]
    results = []
    for extras in ({}, {'lcia_methods': ['EF v3.1']}, {'demand': [{**demand[0], 'amount': 2}]}):
        response = client.post(url, json={'demand': demand, **extras})
        assert response.status_code == 201, response.text
        results.append(response.json())
    assert len({r['solve_hash'] for r in results}) == 3
    retry = client.post(url, json={'demand': demand, 'lcia_methods': ['EF v3.1'], 'idempotency_key': 'new-delivery-same-calculation'})
    assert retry.status_code == 201, retry.text
    assert retry.json()['id'] == results[1]['id']
