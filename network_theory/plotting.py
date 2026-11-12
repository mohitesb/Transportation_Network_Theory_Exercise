"""Figures for the lab.

The main figure follows the usual class map: every intersection is a point,
colored by a centrality measure, in miles from the center of the network.
A small inset draws the streets around the highest value.
"""

from __future__ import annotations

import io

import matplotlib

matplotlib.use("Agg", force=False)

import matplotlib.pyplot as plt
import networkx as nx
import numpy as np
from matplotlib.collections import LineCollection
from matplotlib.ticker import FormatStrFormatter, MaxNLocator

from network_theory.centrality import compute_centrality
from network_theory.load_network import RoadNetwork, to_miles


def centrality_figure(
    network: RoadNetwork,
    values: dict,
    *,
    left_label: str,
    place_name: str,
    colorbar_label: str,
    palette: str = "jet",
    vmin: float,
    vmax: float,
    show_inset: bool = True,
    point_size: float | None = None,
) -> plt.Figure:
    nodes, x, y, color = _aligned(network.graph, values)
    nodes, x, y, color = _low_to_high(nodes, x, y, color)
    size = point_size if point_size is not None else _point_size(len(nodes))
    fig, ax = plt.subplots(figsize=(6.6, 5.8), dpi=120)
    _style_map_axes(ax, network)
    _draw_edges(ax, network.graph)
    scatter = ax.scatter(
        x,
        y,
        c=color,
        s=size,
        marker="s",
        cmap=palette,
        vmin=vmin,
        vmax=vmax,
        linewidths=0,
        rasterized=True,
        zorder=3,
    )
    ax.set_aspect("equal", adjustable="datalim")
    ax.margins(0.03, 0.06)
    _room_for_titles(ax)
    _corner_titles(ax, left_label, place_name)
    colorbar = fig.colorbar(scatter, ax=ax, fraction=0.035, pad=0.02)
    _format_colorbar(colorbar, colorbar_label, vmin, vmax, integer=colorbar_label == "roads meeting")
    if show_inset:
        _draw_inset(ax, network.graph, nodes, x, y, color, palette, vmin, vmax)
    fig.tight_layout()
    return fig


def compare_figure(
    network: RoadNetwork,
    series: list[tuple[str, dict, float, float]],
    *,
    place_name: str,
    weight_label: str,
    palette: str = "jet",
) -> plt.Figure:
    """Three maps side by side. `series` is (title, values, vmin, vmax)."""
    fig, axes = plt.subplots(1, 3, figsize=(15.2, 5.1), dpi=120)
    fig.patch.set_facecolor("white")
    for ax, (title, values, vmin, vmax) in zip(axes, series, strict=True):
        _nodes, x, y, color = _aligned(network.graph, values)
        scatter = ax.scatter(
            x,
            y,
            c=color,
            s=_point_size(len(x)),
            marker="s",
            cmap=palette,
            vmin=vmin,
            vmax=vmax,
            linewidths=0,
            rasterized=True,
        )
        ax.set_aspect("equal", adjustable="datalim")
        _style_map_axes(ax, network)
        ax.set_title(title, fontsize=13, fontweight="bold", pad=8)
        colorbar = fig.colorbar(scatter, ax=ax, fraction=0.046, pad=0.03)
        _format_colorbar(
            colorbar,
            "",
            vmin,
            vmax,
            integer=title.startswith("Degree"),
        )
    fig.suptitle(f"{weight_label}    {place_name}", fontsize=15, fontweight="bold", y=1.02)
    fig.tight_layout()
    return fig


def preview_figure(network: RoadNetwork) -> plt.Figure:
    """The roads alone, before any centrality is calculated."""
    graph = network.graph
    x_of, y_of = _position_maps(graph)
    segments = [
        [(x_of[u], y_of[u]), (x_of[v], y_of[v])]
        for u, v in graph.edges
    ]
    fig, ax = plt.subplots(figsize=(8.2, 5.4), dpi=110)
    fig.patch.set_facecolor("white")
    ax.set_facecolor("white")
    width = 0.9 if graph.number_of_edges() < 2000 else 0.35 if graph.number_of_edges() < 20000 else 0.15
    if segments:
        ax.add_collection(LineCollection(segments, colors="#4a5560", linewidths=width, zorder=2))
    xs = np.fromiter(x_of.values(), dtype=float)
    ys = np.fromiter(y_of.values(), dtype=float)
    ax.scatter(xs, ys, s=1, c="#4a5560", linewidths=0, zorder=3)
    pad_x = max((xs.max() - xs.min()) * 0.04, 0.2)
    pad_y = max((ys.max() - ys.min()) * 0.04, 0.2)
    ax.set_xlim(xs.min() - pad_x, xs.max() + pad_x)
    ax.set_ylim(ys.min() - pad_y, ys.max() + pad_y)
    ax.set_aspect("equal", adjustable="box")
    _style_map_axes(ax, network)
    ax.set_title(network.title, fontsize=15, fontweight="bold", loc="left", pad=10)
    fig.tight_layout()
    return fig


def lesson_figure() -> plt.Figure:
    """A seven-intersection street sketch colored by the three measures."""
    graph, positions, labels = _lesson_graph()
    results = compute_centrality(graph, weighted=False, betweenness_mode="exact")
    panels = (
        ("Degree\nroads meeting", results.degree_count),
        ("Betweenness", results.betweenness),
        ("Closeness", results.closeness),
    )
    fig, axes = plt.subplots(1, 3, figsize=(10.6, 3.6), dpi=120)
    fig.patch.set_facecolor("white")
    for ax, (title, values) in zip(axes, panels, strict=True):
        ax.set_facecolor("white")
        nx.draw_networkx_edges(graph, positions, ax=ax, edge_color="#9aa3ad", width=2.2)
        colors = [values[node] for node in graph.nodes]
        nx.draw_networkx_nodes(
            graph,
            positions,
            ax=ax,
            node_color=colors,
            cmap="jet",
            node_size=480,
            linewidths=0.6,
            edgecolors="#222222",
        )
        label_pos = {
            node: (xy[0], xy[1] - 0.32 if xy[1] < 0 else xy[1] + 0.32)
            for node, xy in positions.items()
        }
        nx.draw_networkx_labels(
            graph, label_pos, labels=labels, ax=ax, font_size=8, font_color="#1a1a1a"
        )
        ax.set_title(title, fontsize=11, fontweight="bold")
        ax.set_axis_off()
        ax.margins(0.15)
    fig.tight_layout()
    return fig


def color_limits(values: dict, scale_mode: str, measure: str) -> tuple[float, float, bool]:
    """Return vmin, vmax, and whether extreme highs were softened.

    Betweenness is usually a few very large intersections and a lot of near-zeros.
    Softening those peaks lets the rest of the map show a pattern. Closeness is
    already a smooth range, so it keeps the full scale.
    """
    array = np.array([float(value) for value in values.values() if np.isfinite(value)], dtype=float)
    if array.size == 0:
        return 0.0, 1.0, False
    vmin = float(array.min())
    vmax = float(array.max())
    soften = scale_mode == "soften" or (scale_mode == "auto" and measure == "betweenness")
    softened = False
    if soften and array.size >= 20:
        low = float(np.percentile(array, 2))
        high = float(np.percentile(array, 98))
        if high > low:
            vmin, vmax = low, high
            softened = True
    if vmax <= vmin:
        vmax = vmin + 1.0
    return vmin, vmax, softened


def figure_png(fig: plt.Figure) -> bytes:
    buffer = io.BytesIO()
    fig.savefig(buffer, format="png", dpi=200, bbox_inches="tight", facecolor="white")
    return buffer.getvalue()


def _draw_inset(ax, graph, nodes, x, y, color, palette, vmin, vmax) -> None:
    x_of = {node: float(x[i]) for i, node in enumerate(nodes)}
    y_of = {node: float(y[i]) for i, node in enumerate(nodes)}
    value_of = {node: float(color[i]) for i, node in enumerate(nodes)}
    peak = int(np.nanargmax(color))
    center_x = float(x[peak])
    center_y = float(y[peak])
    span = max(float(np.ptp(x)), float(np.ptp(y)), 1.0)
    base = max(0.6, 0.12 * span)
    cap = max(base, 0.22 * span)
    segments: list = []
    edge_values: list[float] = []
    window = (center_x, center_y, base)
    for factor in (1.0, 1.5, 2.0):
        radius = min(base * factor, cap)
        segments, edge_values = _window_edges(
            graph, x_of, y_of, value_of, center_x, center_y, radius
        )
        window = (center_x, center_y, radius)
        if len(segments) >= 12:
            break
    if len(segments) < 8:
        return
    inset = ax.inset_axes([0.02, 0.07, 0.34, 0.38])
    inset.set_facecolor("white")
    norm = plt.Normalize(vmin=vmin, vmax=vmax)
    inset.add_collection(
        LineCollection(
            segments,
            colors=plt.get_cmap(palette)(norm(edge_values)),
            linewidths=0.8,
            capstyle="round",
            zorder=2,
        )
    )
    half = window[2]
    inset.set_xlim(window[0] - half, window[0] + half)
    inset.set_ylim(window[1] - half, window[1] + half)
    inset.set_aspect("equal", adjustable="box")
    inset.set_xticks([])
    inset.set_yticks([])
    for spine in inset.spines.values():
        spine.set_color("#111111")
        spine.set_linewidth(1.0)
    inset.set_zorder(5)


def _window_edges(graph, x_of, y_of, value_of, center_x, center_y, radius):
    segments = []
    values = []
    minx, maxx = center_x - radius, center_x + radius
    miny, maxy = center_y - radius, center_y + radius
    for u, v in graph.edges:
        x1, y1, x2, y2 = x_of[u], y_of[u], x_of[v], y_of[v]
        if minx <= x1 <= maxx and minx <= x2 <= maxx and miny <= y1 <= maxy and miny <= y2 <= maxy:
            segments.append([(x1, y1), (x2, y2)])
            values.append(0.5 * (value_of[u] + value_of[v]))
    return segments, values


def _aligned(graph: nx.Graph, values: dict):
    nodes = list(graph.nodes)
    x = np.array([to_miles(graph.nodes[node]["x_km"]) for node in nodes])
    y = np.array([to_miles(graph.nodes[node]["y_km"]) for node in nodes])
    color = np.array([float(values[node]) for node in nodes])
    return nodes, x, y, color


def _low_to_high(nodes, x, y, color):
    """Draw faint intersections first so the high values stay visible on top."""
    rank = np.where(np.isfinite(color), color, -np.inf)
    order = np.argsort(rank, kind="mergesort")
    ordered_nodes = [nodes[int(index)] for index in order]
    return ordered_nodes, x[order], y[order], color[order]


def _draw_edges(ax, graph: nx.Graph) -> None:
    x_of, y_of = _position_maps(graph)
    segments = [[(x_of[u], y_of[u]), (x_of[v], y_of[v])] for u, v in graph.edges]
    if not segments:
        return
    count = len(segments)
    width = 0.55 if count < 2500 else 0.28 if count < 20000 else 0.12
    ax.add_collection(
        LineCollection(
            segments,
            colors="#7d8794",
            linewidths=width,
            capstyle="round",
            zorder=1,
        )
    )


def _position_maps(graph: nx.Graph) -> tuple[dict, dict]:
    x_of = {node: to_miles(data["x_km"]) for node, data in graph.nodes(data=True)}
    y_of = {node: to_miles(data["y_km"]) for node, data in graph.nodes(data=True)}
    return x_of, y_of


def _style_map_axes(ax, network: RoadNetwork) -> None:
    ax.set_facecolor("white")
    ax.grid(True, color="#e3e3e3", linewidth=0.6, zorder=0)
    ax.set_axisbelow(True)
    ax.tick_params(labelsize=10, colors="#222222")
    for spine in ax.spines.values():
        spine.set_color("#222222")
        spine.set_linewidth(0.8)
    if network.geographic:
        # ax.set_xlabel("miles east of center", fontsize=11)
        # ax.set_ylabel("miles north of center", fontsize=11)
        pass
    else:
        # ax.set_xlabel("diagram position (not a map)", fontsize=11)
        # ax.set_ylabel("diagram position (not a map)", fontsize=11)
        pass
    ax.set_axis_off()


def _corner_titles(ax, left_label: str, place_name: str) -> None:
    backing = {"facecolor": "white", "edgecolor": "none", "alpha": 0.82, "pad": 1.5}
    ax.text(
        0.012,
        0.975,
        left_label,
        transform=ax.transAxes,
        fontsize=_title_size(left_label),
        fontweight="bold",
        ha="left",
        va="top",
        color="black",
        zorder=6,
        bbox=backing,
    )
    ax.text(
        0.988,
        0.975,
        place_name,
        transform=ax.transAxes,
        fontsize=_title_size(place_name),
        fontweight="bold",
        ha="right",
        va="top",
        color="black",
        zorder=6,
        bbox=backing,
    )


def _room_for_titles(ax) -> None:
    y0, y1 = ax.get_ylim()
    span = y1 - y0
    if span <= 0:
        return
    ax.set_ylim(y0, y1 + span * 0.08)


def _format_colorbar(colorbar, label: str, vmin: float, vmax: float, *, integer: bool) -> None:
    if label:
        colorbar.set_label(label, fontsize=11)
    colorbar.ax.tick_params(labelsize=9)
    if integer:
        colorbar.ax.yaxis.set_major_locator(MaxNLocator(integer=True))
        return
    span = abs(vmax - vmin)
    if 0 < span < 0.2:
        decimals = min(4, max(3, int(-np.log10(span)) + 1))
        colorbar.ax.yaxis.set_major_formatter(FormatStrFormatter(f"%.{decimals}f"))


def _title_size(text: str) -> int:
    if len(text) > 34:
        return 12
    if len(text) > 24:
        return 13
    return 16


def _point_size(n: int) -> float:
    if n < 400:
        return 16
    if n < 2000:
        return 7
    if n < 8000:
        return 3.5
    if n < 20000:
        return 2.0
    return 1.2


def _lesson_graph():
    positions = {
        "W": (0, 0),
        "B": (1, 0),
        "C": (2, 0),
        "D": (3, 0),
        "E": (4, 0),
        "F": (1, -1),
        "G": (2, -1),
    }
    labels = {
        "W": "West",
        "B": "1st",
        "C": "2nd",
        "D": "3rd",
        "E": "East",
        "F": "lane",
        "G": "lane",
    }
    graph = nx.Graph()
    graph.add_nodes_from(positions)
    graph.add_edges_from(
        [("W", "B"), ("B", "C"), ("C", "D"), ("D", "E"), ("B", "F"), ("C", "G")],
    )
    for u, v in graph.edges:
        graph.edges[u, v]["length"] = 100.0
    return graph, positions, labels
