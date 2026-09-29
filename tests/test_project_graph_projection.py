from nebula_one.services.seed_projects import process_graph_projection


def test_process_graph_projection_uses_only_declared_exchanges():
    graph = {
        "nodes": [{"id": "a", "name": "Alpha"}, {"id": "b", "name": "Beta"}, {"id": "c"}],
        "exchanges": [
            {"id": "e1", "name": "flow", "fromNode": "a", "toNode": "b"},
            {"id": "e2", "fromNode": "b", "toNode": "b"},
            {"id": "e3", "fromNode": "b", "toNode": "ghost"},
        ],
    }
    projected = process_graph_projection(graph)
    assert [node["id"] for node in projected["nodes"]] == ["a", "b", "c"]
    assert projected["nodes"][2]["name"] == "c"
    assert projected["edges"] == [{"source": "a", "target": "b", "label": "flow"}]
