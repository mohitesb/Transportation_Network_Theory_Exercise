"""Offline checks for the centrality lab. Run from the project folder:

    python scripts/check_lab.py
"""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

import networkx as nx
import pandas as pd

from network_theory.centrality import compute_centrality
from network_theory.load_network import (
    collapse_to_simple,
    contract_degree_two,
    finalize_graph,
    names_from_attr,
)
from network_theory.plotting import centrality_figure, color_limits, figure_png, lesson_figure


def _path(names=("A", "b", "c", "d", "E")) -> nx.Graph:
    graph = nx.Graph()
    for name in names:
        graph.add_node(name, x=0.0, y=0.0)
    for left, right, length in zip(names, names[1:], (10, 20, 30, 40)):
        graph.add_edge(left, right, length=float(length), names=["Main"])
    return graph


def check_contract() -> None:
    graph, _removed = contract_degree_two(_path())
    assert set(graph.nodes) == {"A", "E"}, set(graph.nodes)
    assert graph["A"]["E"]["length"] == 100
    assert graph["A"]["E"]["names"] == ["Main"]

    tee = nx.Graph()
    tee.add_edge("A", "B", length=1.0, names=["a"])
    tee.add_edge("B", "C", length=1.0, names=["c"])
    tee.add_edge("B", "D", length=1.0, names=["d"])
    same, removed = contract_degree_two(tee)
    assert removed == 0
    assert same.number_of_edges() == 3

    cycle = nx.cycle_graph(5)
    for u, v in cycle.edges:
        cycle.edges[u, v]["length"] = 1.0
        cycle.edges[u, v]["names"] = []
    kept, removed = contract_degree_two(cycle)
    assert removed == 0
    assert kept.number_of_nodes() == 5

    corner = nx.Graph()
    corner.add_edge("A", "B", length=1.0, names=["Main"])
    corner.add_edge("B", "C", length=1.0, names=["Oak"])
    kept, removed = contract_degree_two(corner)
    assert removed == 0
    assert kept.number_of_nodes() == 3
    print("contract ok")


def check_centrality_matches_networkx() -> None:
    karate = nx.karate_club_graph()
    for u, v in karate.edges:
        karate.edges[u, v]["length"] = float(1 + (u + v) % 5)
    ours = compute_centrality(karate, weighted=False, betweenness_mode="exact")
    reference = nx.betweenness_centrality(karate, normalized=True)
    closeness = nx.closeness_centrality(karate)
    for node in karate.nodes:
        assert abs(ours.betweenness[node] - reference[node]) < 1e-9
        assert abs(ours.closeness[node] - closeness[node]) < 1e-9
        assert abs(ours.degree_centrality[node] - nx.degree_centrality(karate)[node]) < 1e-12
    weighted = compute_centrality(karate, weighted=True, betweenness_mode="exact")
    reference_w = nx.betweenness_centrality(karate, normalized=True, weight="length")
    for node in karate.nodes:
        assert abs(weighted.betweenness[node] - reference_w[node]) < 1e-9
    print("centrality ok", "mean hops", round(ours.mean_distance, 3))


def check_names() -> None:
    assert names_from_attr(["Burnside", "Couch"]) == ["Burnside", "Couch"]
    assert names_from_attr("A | B") == ["A", "B"]
    assert names_from_attr("['Main', 'Oak']") == ["Main", "Oak"]
    print("names ok")


def check_figure_pipeline() -> None:
    graph = nx.grid_2d_graph(12, 8)
    relabeled = nx.Graph()
    for (col, row) in graph.nodes:
        lon = -123.2 + col * 0.01
        lat = 44.6 + row * 0.008
        relabeled.add_node((col, row), x=lon, y=lat, lon=lon, lat=lat)
    for (col1, row1), (col2, row2) in graph.edges:
        street = "East-West" if row1 == row2 else "North-South"
        relabeled.add_edge((col1, row1), (col2, row2), length=800.0, names=[street])
    simple = collapse_to_simple(relabeled)
    network = finalize_graph(
        simple,
        title="Gridville, Oregon",
        source="Test",
        official_name=None,
        kind_label="Test",
        area_km2=None,
        coords="lonlat",
    )
    assert network.geographic
    assert network.has_latlon
    assert network.n == 12 * 8
    results = compute_centrality(network.graph, weighted=False)
    vmin, vmax, softened = color_limits(results.closeness, "auto", "closeness")
    assert not softened
    figure = centrality_figure(
        network,
        results.closeness,
        left_label="Unweighted",
        place_name="Gridville, Oregon",
        colorbar_label="closeness",
        vmin=vmin,
        vmax=vmax,
        show_inset=True,
    )
    png = figure_png(figure)
    assert png[:8] == b"\x89PNG\r\n\x1a\n"
    lesson = lesson_figure()
    assert figure_png(lesson)[:8] == b"\x89PNG\r\n\x1a\n"
    print("figure ok", "bytes", len(png))

    # CSV upload path: write nodes and edges and read them back through finalize.
    nodes = pd.DataFrame(
        {
            "id": [f"{col}-{row}" for col, row in network.graph.nodes],
            "longitude": [network.graph.nodes[node]["lon"] for node in network.graph.nodes],
            "latitude": [network.graph.nodes[node]["lat"] for node in network.graph.nodes],
        }
    )
    edges = pd.DataFrame(
        [
            {
                "source": f"{u[0]}-{u[1]}",
                "target": f"{v[0]}-{v[1]}",
                "length": data["length"],
                "name": (data["names"] or ["Grid"])[0],
            }
            for u, v, data in network.graph.edges(data=True)
        ]
    )
    node_path = ROOT / "Data" / "osm_cache" / "_nodes_check.csv"
    edge_path = ROOT / "Data" / "osm_cache" / "_edges_check.csv"
    node_path.parent.mkdir(parents=True, exist_ok=True)
    nodes.to_csv(node_path, index=False)
    edges.to_csv(edge_path, index=False)
    from network_theory.load_network import load_paths

    loaded = load_paths([node_path, edge_path])
    assert loaded.n == network.n
    assert loaded.m == network.m
    assert loaded.has_latlon
    print("csv reload ok", loaded.n, "intersections")


if __name__ == "__main__":
    check_contract()
    check_names()
    check_centrality_matches_networkx()
    check_figure_pipeline()
    print("all checks passed")
