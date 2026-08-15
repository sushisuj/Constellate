"""Tests for diagram_vision.py.

Covers the stub path and _parse_graph's JSON-recovery logic -- both pure,
offline, deterministic. The real _extract_vision path (an actual call to
NVIDIA's hosted vision model) isn't covered here, the same way llm.py's
_generate_llm isn't covered by this suite either: it needs a live
NVIDIA_API_KEY and a network call, which doesn't belong in an automated
test run. It was checked by hand against a real generated flowchart
image during development instead -- see the commit this file shipped
with for what that confirmed and what it couldn't (this sandbox's
network doesn't reach integrate.api.nvidia.com, so the live call itself
still needs verifying against a real key outside this environment).
"""

import os

from app.diagram_vision import DiagramGraph, Edge, Node, _parse_graph, extract_diagram_graph


class TestParseGraph:
    def test_clean_json_parses_directly(self):
        raw = (
            '{"nodes": [{"id": "start", "label": "Start"}, {"id": "end", "label": "End"}], '
            '"edges": [{"source": "start", "target": "end", "label": "yes"}]}'
        )
        graph = _parse_graph(raw, page_index=2)
        assert graph.page == 2
        assert graph.backend == "vision"
        assert graph.nodes == [Node(id="start", label="Start"), Node(id="end", label="End")]
        assert graph.edges == [Edge(source="start", target="end", label="yes")]

    def test_json_wrapped_in_code_fence_and_prose_still_parses(self):
        raw = 'Here is the diagram:\n```json\n{"nodes": [{"id": "a", "label": "A"}], "edges": []}\n```\nHope that helps!'
        graph = _parse_graph(raw, page_index=0)
        assert graph.nodes == [Node(id="a", label="A")]
        assert graph.backend == "vision"

    def test_unparseable_response_returns_empty_graph_not_an_error(self):
        raw = "I'm not able to make out any shapes in this image clearly."
        graph = _parse_graph(raw, page_index=0)
        assert graph.nodes == []
        assert graph.edges == []
        assert graph.backend == "vision"

    def test_edge_referencing_unknown_node_id_is_dropped(self):
        raw = '{"nodes": [{"id": "a", "label": "A"}], "edges": [{"source": "a", "target": "ghost", "label": ""}]}'
        graph = _parse_graph(raw, page_index=0)
        assert graph.nodes == [Node(id="a", label="A")]
        assert graph.edges == []  # "ghost" isn't a real node -- the edge is meaningless

    def test_node_missing_required_fields_is_skipped(self):
        raw = '{"nodes": [{"id": "a"}, {"id": "b", "label": "B"}], "edges": []}'
        graph = _parse_graph(raw, page_index=0)
        assert graph.nodes == [Node(id="b", label="B")]


class TestDiagramGraphToText:
    def test_empty_graph_is_empty_text(self):
        assert DiagramGraph(page=0).to_text() == ""

    def test_nodes_and_labelled_edge_flatten_to_prose(self):
        graph = DiagramGraph(
            page=0,
            nodes=[Node(id="start", label="Start"), Node(id="end", label="End")],
            edges=[Edge(source="start", target="end", label="approved")],
        )
        text = graph.to_text()
        assert "Start" in text
        assert "End" in text
        assert "Start leads to End (approved)." in text

    def test_unlabelled_edge_omits_parenthetical(self):
        graph = DiagramGraph(
            page=0,
            nodes=[Node(id="a", label="A"), Node(id="b", label="B")],
            edges=[Edge(source="a", target="b")],
        )
        assert "A leads to B." in graph.to_text()


class TestOfflineStub:
    def test_no_api_key_returns_a_labelled_stub(self, monkeypatch):
        monkeypatch.delenv("NVIDIA_API_KEY", raising=False)
        graph = extract_diagram_graph(b"fake-png-bytes", page_index=4)
        assert graph.backend == "stub"
        assert len(graph.nodes) == 1
        assert "page 5" in graph.nodes[0].label  # page_index is 0-based, label is human-facing
        assert graph.edges == []

    def test_stub_is_deterministic(self, monkeypatch):
        monkeypatch.delenv("NVIDIA_API_KEY", raising=False)
        first = extract_diagram_graph(b"fake-png-bytes", page_index=0)
        second = extract_diagram_graph(b"fake-png-bytes", page_index=0)
        assert first == second
