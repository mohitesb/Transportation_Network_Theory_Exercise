"""Degree, betweenness, and closeness on an intersection graph.

Betweenness and closeness use the same definitions as NetworkX, including
normalization, so the numbers match a standard network-science course.
igraph does the heavy calculation. On a large network, betweenness can be
estimated from a fixed sample of starting intersections.
"""

from __future__ import annotations

import math
import time
from dataclasses import dataclass

import igraph as ig
import networkx as nx
import numpy as np
import pandas as pd

from network_theory.errors import NetworkLabError
from network_theory.load_network import METERS_PER_MILE


@dataclass
class CentralityResults:
    degree_count: dict
    degree_centrality: dict
    betweenness: dict
    closeness: dict
    weighted: bool
    betweenness_mode: str
    sample_size: int | None
    sample_seed: int | None
    mean_distance: float
    distance_unit: str
    notes: list[str]
    seconds: float


def compute_centrality(
    graph: nx.Graph,
    *,
    weighted: bool,
    betweenness_mode: str = "exact",
    sample_size: int = 400,
    sample_seed: int = 42,
) -> CentralityResults:
    """Calculate the three measures on a connected undirected graph.

    `weighted=False` treats every road between two intersections as one step.
    `weighted=True` uses the `length` attribute, in meters, as distance.
    Degree never uses length. It is the number of roads that meet.
    """
    started = time.perf_counter()
    n = graph.number_of_nodes()
    if n < 3 or graph.number_of_edges() < 2:
        raise NetworkLabError(
            "This network is too small to measure centrality. "
            "It needs at least a few connected intersections."
        )
    if not nx.is_connected(graph):
        raise NetworkLabError(
            "Centrality is calculated on one connected piece of the network. "
            "The loaded network is still disconnected."
        )

    igraph, nodes = _to_igraph(graph, weighted=weighted)
    if igraph.ecount() != graph.number_of_edges():
        raise NetworkLabError("The network could not be prepared for the calculation.")

    degree_count = {node: int(degree) for node, degree in graph.degree()}
    degree_centrality = {node: degree_count[node] / (n - 1) for node in nodes}

    weight = "length" if weighted else None
    notes = [
        "Degree counts roads meeting at an intersection. It does not use length."
    ]
    if weighted:
        notes.append(
            "Betweenness and closeness measure distance in miles, along the roads."
        )
    else:
        notes.append(
            "Betweenness and closeness count each road between intersections as one step."
        )

    mode = "exact"
    used_k: int | None = None
    used_seed: int | None = None
    exact_scale = 2.0 / ((n - 1) * (n - 2))
    if betweenness_mode == "estimate" and sample_size < n:
        k = max(2, min(int(sample_size), n - 1))
        rng = np.random.default_rng(sample_seed)
        sources = rng.choice(n, size=k, replace=False).tolist()
        raw = np.asarray(
            igraph.betweenness(directed=False, weights=weight, sources=sources),
            dtype=float,
        )
        # Inflate the sample so the result is on the same 0–1 scale as the exact measure.
        scale = (n / k) * exact_scale
        betweenness = {node: float(raw[i] * scale) for i, node in enumerate(nodes)}
        mode = "estimate"
        used_k = k
        used_seed = int(sample_seed)
        notes.append(
            f"Betweenness is an estimate from {k:,} random starting intersections "
            f"(sample {used_seed}). The main hubs usually stay put. "
            "Closeness and degree are exact."
        )
    else:
        raw = np.asarray(igraph.betweenness(directed=False, weights=weight), dtype=float)
        betweenness = {node: float(raw[i] * exact_scale) for i, node in enumerate(nodes)}
        notes.append("Betweenness is exact: every intersection was used as a starting point.")

    raw_close = np.asarray(igraph.closeness(weights=weight, normalized=True), dtype=float)
    closeness: dict[object, float] = {}
    for i, node in enumerate(nodes):
        value = float(raw_close[i])
        closeness[node] = value if math.isfinite(value) else 0.0

    positive = np.array([value for value in closeness.values() if value > 0.0])
    if positive.size == 0:
        raise NetworkLabError("Closeness could not be calculated for this network.")
    # Normalized closeness is (n - 1) / total distance, so 1 / closeness is the
    # mean distance from that intersection to the others. Weighted edges are
    # miles, so this mean is already in miles.
    mean_distance = float(np.mean(1.0 / positive))
    unit = "miles" if weighted else "hops"

    return CentralityResults(
        degree_count=degree_count,
        degree_centrality=degree_centrality,
        betweenness=betweenness,
        closeness=closeness,
        weighted=weighted,
        betweenness_mode=mode,
        sample_size=used_k,
        sample_seed=used_seed,
        mean_distance=mean_distance,
        distance_unit=unit,
        notes=notes,
        seconds=time.perf_counter() - started,
    )


def results_table(graph: nx.Graph, results: CentralityResults) -> pd.DataFrame:
    """One row per intersection, ready to show or download."""
    rows = []
    for node, data in graph.nodes(data=True):
        rows.append(
            {
                "node_id": node,
                "intersection": data.get("label") or str(node),
                "roads_meeting": results.degree_count[node],
                "degree_centrality": results.degree_centrality[node],
                "betweenness": results.betweenness[node],
                "closeness": results.closeness[node],
                "longitude": data.get("lon"),
                "latitude": data.get("lat"),
            }
        )
    frame = pd.DataFrame(rows)
    return frame


def _to_igraph(graph: nx.Graph, *, weighted: bool) -> tuple[ig.Graph, list]:
    nodes = list(graph.nodes)
    index = {node: i for i, node in enumerate(nodes)}
    edges: list[tuple[int, int]] = []
    weights: list[float] = []
    for u, v, data in graph.edges(data=True):
        edges.append((index[u], index[v]))
        if weighted:
            # Miles, not meters. Shortest paths are unchanged by the unit,
            # and closeness stays a readable number (about 1 / mean miles).
            length_m = float(data.get("length", 1.0))
            length_mi = length_m / METERS_PER_MILE
            if not math.isfinite(length_mi) or length_mi <= 0:
                length_mi = 0.001
            weights.append(length_mi)
    igraph = ig.Graph(n=len(nodes), edges=edges, directed=False)
    if weighted:
        igraph.es["length"] = weights
    return igraph, nodes
