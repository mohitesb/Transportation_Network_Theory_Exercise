"""Load a road network from OpenStreetMap or from a file a student uploads.

The graph used for centrality is an intersection graph: a node is a place
where roads meet (or a dead end), and an edge is the road between them.
Bend points along a single road are not intersections.
"""

from __future__ import annotations

import ast
import io
import json
import math
import os
import shutil
import tempfile
import uuid
import zipfile
from dataclasses import dataclass, field
from pathlib import Path

import geopandas as gpd
import networkx as nx
import osmnx as ox
import pandas as pd
from network_theory.errors import NetworkLabError

ROOT = Path(__file__).resolve().parents[1]
DATA_DIR = ROOT / "Data"
METERS_PER_MILE = 1609.344


def to_miles(kilometers: float) -> float:
    """Convert a kilometer length to miles."""
    return float(kilometers) * (1000.0 / METERS_PER_MILE)


def to_square_miles(square_kilometers: float) -> float:
    """Convert an area in square kilometers to square miles."""
    factor = 1000.0 / METERS_PER_MILE
    return float(square_kilometers) * factor * factor
CACHE_DIR = DATA_DIR / "osm_cache"
EXAMPLE_PATH = DATA_DIR / "example_newark.graphml"

ROAD_KINDS = {
    "streets": "All drivable streets",
    "main": "Main roads, including secondary",
    "highways": "Highways and primary roads only",
    "walk": "Walking network",
    "bike": "Bike network",
}

# What each menu choice actually requests from OpenStreetMap.
ROAD_KIND_DETAILS = {
    "streets": (
        "Public roads a car can use, from interstates and primary roads down through "
        "secondary roads to neighborhood streets. Driveways, parking-lot aisles, "
        "footpaths, and bike paths stay out."
    ),
    "main": (
        "Interstates, other major highways, primary roads, and secondary roads, "
        "including their ramps. Neighborhood streets stay out."
    ),
    "highways": (
        "Interstates, other major highways, and primary roads, including their ramps. "
        "Secondary roads and neighborhood streets stay out."
    ),
    "walk": "Public paths you can walk, including footpaths. Motorways stay out.",
    "bike": "Public paths you can bike. Foot-only paths and motorways stay out.",
}

# Road classes kept when a student uploads a whole-state extract.
_MAIN_ROAD_CLASSES = {
    "motorway",
    "motorway_link",
    "trunk",
    "trunk_link",
    "primary",
    "primary_link",
    "secondary",
    "secondary_link",
}

# Overpass filters. These replace OSMnx's network-type preset.
_HIGHWAY_FILTER = (
    '["highway"~"motorway|motorway_link|trunk|trunk_link|primary|primary_link"]'
)
_MAIN_FILTER = (
    '["highway"~"motorway|motorway_link|trunk|trunk_link|'
    'primary|primary_link|secondary|secondary_link"]'
)
_HEAVY_KINDS = {"streets", "walk", "bike"}
_NAME_COLUMNS = (
    "name",
    "names",
    "street",
    "road_name",
    "fullname",
    "full_name",
    "st_name",
    "street_name",
)


@dataclass
class PlaceInfo:
    query: str
    official_name: str
    area_km2: float | None
    recommended_kind: str
    message: str


@dataclass
class RoadNetwork:
    graph: nx.Graph
    title: str
    source: str
    official_name: str | None
    kind_label: str
    area_km2: float | None
    dropped_nodes: int
    geographic: bool
    has_latlon: bool
    token: str
    notes: list[str] = field(default_factory=list)
    geojson_bytes: bytes | None = None
    shapefile_bytes: bytes | None = None

    @property
    def n(self) -> int:
        return self.graph.number_of_nodes()

    @property
    def m(self) -> int:
        return self.graph.number_of_edges()

    @property
    def total_km(self) -> float:
        return sum(float(data["length"]) for *_, data in self.graph.edges(data=True)) / 1000.0


def configure_osm() -> None:
    """Point OSMnx at a local cache and identify this lab to the map servers."""
    CACHE_DIR.mkdir(parents=True, exist_ok=True)
    ox.settings.use_cache = True
    ox.settings.cache_folder = str(CACHE_DIR)
    # Same timeout OSMnx uses by default. A dead status page must not sit for five minutes.
    ox.settings.requests_timeout = 180
    ox.settings.overpass_rate_limit = False
    ox.settings.http_user_agent = (
        "NetworkTheoryExercise/1.0 (university classroom lab; educational use)"
    )
    ox.settings.http_referer = "NetworkTheoryExercise classroom lab"


def recommend_kind(area_km2: float | None) -> tuple[str, str]:
    """Suggest a road class that will finish during a class period."""
    if area_km2 is None:
        return (
            "streets",
            "Choose main roads if this place is a whole state or a large region.",
        )
    if area_km2 < 1500:
        return (
            "streets",
            f"This boundary is about {to_square_miles(area_km2):,.0f} square miles. "
            "All drivable streets are a good fit.",
        )
    if area_km2 < 80000:
        return (
            "main",
            f"This boundary is about {to_square_miles(area_km2):,.0f} square miles. "
            "Main roads will download faster and still show the regional pattern. "
            "All local streets may take a long time.",
        )
    return (
        "highways",
        f"This boundary is about {to_square_miles(area_km2):,.0f} square miles, the size of a state. "
        "Start with highways and primary roads. Main roads add secondary streets "
        "if you want more detail.",
    )


# Largest place boundary the built-in OSMnx download will accept, in square miles.
# Keeps classroom downloads small so many students can share one server.
# Override without editing code: set LAB_MAX_DOWNLOAD_SQ_MILES (e.g. in Streamlit secrets or the shell).
MAX_DOWNLOAD_SQ_MILES = float(os.environ.get("LAB_MAX_DOWNLOAD_SQ_MILES", "20"))


def download_area_blocked(area_km2: float | None) -> bool:
    """True when a place is too large (or its size is unknown) for the built-in download."""
    if area_km2 is None:
        return True
    return to_square_miles(area_km2) > MAX_DOWNLOAD_SQ_MILES


def download_area_message(area_km2: float | None) -> str:
    limit = f"{MAX_DOWNLOAD_SQ_MILES:,.0f}"
    if area_km2 is None:
        return (
            "OpenStreetMap did not return a boundary size for that place, so it cannot be downloaded here. "
            f"Try a more specific town or city name (up to {limit} square miles)."
        )
    return (
        f"This boundary is about {to_square_miles(area_km2):,.1f} square miles. "
        f"In this lab, downloads are limited to places of {limit} square miles or less "
        "so the whole class can share the server. Choose a smaller town or city, "
        "or ask your instructor for a prepared network file to upload."
    )


# Upload limits. Override with environment variables without editing code.
# Keep MAX_UPLOAD_MB in step with server.maxUploadSize in .streamlit/config.toml.
MAX_UPLOAD_MB = float(os.environ.get("LAB_MAX_UPLOAD_MB", "25"))
MAX_UNZIPPED_MB = 4 * MAX_UPLOAD_MB
MAX_UPLOAD_INTERSECTIONS = int(os.environ.get("LAB_MAX_UPLOAD_INTERSECTIONS", "20000"))


def upload_limits_text() -> str:
    return (
        f"Files up to {MAX_UPLOAD_MB:,.0f} MB in total, and networks up to "
        f"{MAX_UPLOAD_INTERSECTIONS:,} intersections (about the size of a small city)."
    )


def streets_are_blocked(kind: str, area_km2: float | None) -> bool:
    return kind in _HEAVY_KINDS and area_km2 is not None and area_km2 >= 20000


def streets_need_confirm(kind: str, area_km2: float | None) -> bool:
    return kind in _HEAVY_KINDS and area_km2 is not None and 1500 <= area_km2 < 20000


def find_place(query: str) -> PlaceInfo:
    """Look up a city, county, or state boundary without downloading roads."""
    configure_osm()
    text = query.strip()
    if not text:
        raise NetworkLabError("Type a place name, such as Portland, Oregon, USA.")
    try:
        boundary = ox.geocode_to_gdf(text)
    except Exception as exc:
        raise NetworkLabError(_geocode_message(exc)) from exc
    official = str(boundary.iloc[0].get("display_name") or text)
    area = _area_km2(boundary)
    kind, message = recommend_kind(area)
    if download_area_blocked(area):
        message = download_area_message(area)
    elif area is not None and area < 1:
        message = (
            "OpenStreetMap did not return a clear boundary for that name. "
            "Try a more specific query, such as Bend, Oregon, USA."
        )
    return PlaceInfo(
        query=text,
        official_name=official,
        area_km2=area,
        recommended_kind=kind,
        message=message,
    )


def download_roads(info: PlaceInfo, kind: str) -> RoadNetwork:
    """Download the place boundary's roads and turn them into an intersection graph."""
    configure_osm()
    if kind not in ROAD_KINDS:
        raise NetworkLabError("Choose a road type from the list.")
    if download_area_blocked(info.area_km2):
        raise NetworkLabError(download_area_message(info.area_km2))
    if streets_are_blocked(kind, info.area_km2):
        area = 0 if info.area_km2 is None else info.area_km2
        raise NetworkLabError(
            f"That boundary is about {to_square_miles(area):,.0f} square miles. Downloading every local street "
            "would be too large for this lab. Choose main roads, or highways and primary roads."
        )
    try:
        graph = _download_graph(info.query, kind)
    except NetworkLabError:
        raise
    except Exception as exc:
        raise NetworkLabError(_download_message(exc)) from exc
    if graph.number_of_nodes() == 0:
        raise NetworkLabError(
            "No roads were returned for that place and road type. "
            "Try a different road type, or a more specific place name."
        )
    network = network_from_osm_graph(
        graph,
        title=clean_title(info.query),
        official_name=info.official_name,
        kind_label=ROAD_KINDS[kind],
        area_km2=info.area_km2,
        source="OpenStreetMap",
    )
    # Same exports as edges.to_file(..., driver="GeoJSON") and driver="ESRI Shapefile".
    try:
        network.geojson_bytes = edges_geojson_bytes(graph)
        network.shapefile_bytes = edges_shapefile_zip_bytes(graph)
    except Exception as exc:
        network.notes.append(
            "The roads were downloaded, but the GeoJSON and shapefile could not be saved "
            f"({_short_error(exc)})."
        )
    return network


def load_example() -> RoadNetwork:
    if not EXAMPLE_PATH.exists():
        raise NetworkLabError(
            "The example network is not in the Data folder. Download a place instead."
        )
    network = load_graphml(EXAMPLE_PATH, source="Included example")
    network.title = network.title or "Newark, Delaware"
    return network


def load_uploads(files: list) -> RoadNetwork:
    """Read one upload, or a nodes CSV together with an edges CSV."""
    if not files:
        raise NetworkLabError("Choose a file first.")
    total_mb = sum(len(item.getvalue()) for item in files) / (1024 * 1024)
    if total_mb > MAX_UPLOAD_MB:
        raise NetworkLabError(
            f"Those files add up to {total_mb:,.1f} MB. This lab accepts up to {MAX_UPLOAD_MB:,.0f} MB. "
            "Export a smaller place (a town or small city), or only main roads."
        )
    folder = CACHE_DIR / "uploads" / uuid.uuid4().hex
    folder.mkdir(parents=True, exist_ok=True)
    paths = []
    for item in files:
        name = Path(item.name).name
        path = folder / name
        path.write_bytes(item.getvalue())
        paths.append(path)
    network = load_paths(paths)
    if network.n > MAX_UPLOAD_INTERSECTIONS:
        raise NetworkLabError(
            f"That network has {network.n:,} intersections. This lab accepts up to "
            f"{MAX_UPLOAD_INTERSECTIONS:,}, so the whole class can share the server. "
            "Export a smaller place (a town or small city), or only main roads."
        )
    return network


def load_paths(paths: list[Path]) -> RoadNetwork:
    expanded = _expand_archives(paths)
    grouped: dict[str, list[Path]] = {
        "osm": [],
        "overpass": [],
        "graphml": [],
        "table": [],
        "spatial": [],
        "pbf": [],
    }
    for path in expanded:
        grouped[_file_kind(path)].append(path)
    if grouped["pbf"] and not any(grouped[key] for key in ("osm", "overpass", "graphml", "table", "spatial")):
        raise NetworkLabError(
            "This lab cannot read a .pbf extract directly. On Geofabrik, download the "
            "shapefile (.shp.zip) instead, and upload that zip."
        )
    source_name = expanded[0].name if expanded else "upload"
    if grouped["osm"]:
        return load_osm_xml(grouped["osm"][0])
    if grouped["overpass"]:
        return load_overpass_json(grouped["overpass"][0])
    if grouped["graphml"]:
        return load_graphml(grouped["graphml"][0], source=f"Uploaded file ({grouped['graphml'][0].name})")
    if grouped["table"]:
        return _load_tables(grouped["table"])
    if grouped["spatial"]:
        return _load_spatial(_prefer_roads(grouped["spatial"]))
    raise NetworkLabError(
        f"Could not find roads in {source_name}. Upload GeoJSON or raw OSM data from Overpass Turbo, "
        "a Geofabrik shapefile zip, a GraphML file, or a CSV with columns named source and target."
    )


def load_osm_xml(path: Path) -> RoadNetwork:
    """Read an .osm file, including a raw export from Overpass Turbo or openstreetmap.org."""
    try:
        graph = ox.graph_from_xml(path, simplify=True, retain_all=True)
    except Exception as exc:
        raise NetworkLabError(
            "That OSM file could not be read. In Overpass Turbo, use Export → raw OSM data, "
            "or Export → GeoJSON."
        ) from exc
    graph = _keep_highway_edges(graph)
    if graph.number_of_nodes() == 0 or graph.number_of_edges() == 0:
        raise NetworkLabError(
            "That OSM file has no roads. In Overpass Turbo, run a highway query, then export again."
        )
    return network_from_osm_graph(
        graph,
        title=clean_title(path.stem),
        official_name=None,
        kind_label="OpenStreetMap file",
        area_km2=None,
        source=f"OpenStreetMap file ({path.name})",
    )


def load_overpass_json(path: Path) -> RoadNetwork:
    """Read an Overpass JSON export (elements of nodes and ways)."""
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise NetworkLabError("That JSON file could not be read.") from exc
    elements = payload.get("elements") if isinstance(payload, dict) else None
    if not isinstance(elements, list):
        raise NetworkLabError(
            "That JSON file is not an Overpass export. In Overpass Turbo, choose GeoJSON or raw OSM data."
        )
    graph = _graph_from_overpass_elements(elements)
    if graph.number_of_edges() == 0:
        raise NetworkLabError(
            "That Overpass file has no roads. Run a highway query, then export again."
        )
    return finalize_graph(
        graph,
        title=clean_title(path.stem),
        source=f"OpenStreetMap file ({path.name})",
        official_name=None,
        kind_label="OpenStreetMap file",
        area_km2=None,
        coords="lonlat",
    )


def load_graphml(path: Path, *, source: str) -> RoadNetwork:
    try:
        raw = nx.read_graphml(path)
    except Exception as exc:
        raise NetworkLabError(
            "That GraphML file could not be read. If it is a shapefile, zip it and upload the zip."
        ) from exc
    title = clean_title(str(raw.graph.get("title") or path.stem))
    kind = str(raw.graph.get("kind_label") or "Uploaded network")
    official = raw.graph.get("official_name")
    official_name = str(official) if official else None
    area = _maybe_float(raw.graph.get("area_km2"))
    return _network_from_generic(
        raw,
        title=title,
        source=source,
        official_name=official_name,
        kind_label=kind,
        area_km2=area,
    )


def network_to_graphml_bytes(network: RoadNetwork) -> bytes:
    """Save the intersection graph so another student can upload it."""
    saved = nx.Graph()
    saved.graph["lab_format"] = "road-centrality-lab"
    saved.graph["title"] = network.title
    saved.graph["kind_label"] = network.kind_label
    saved.graph["source"] = network.source
    saved.graph["geographic"] = "true" if network.geographic else "false"
    if network.official_name:
        saved.graph["official_name"] = network.official_name
    if network.area_km2 is not None:
        saved.graph["area_km2"] = float(network.area_km2)
    for node, data in network.graph.nodes(data=True):
        attrs = {
            "label": str(data.get("label") or node),
            "x": float(data["x"]),
            "y": float(data["y"]),
            "x_km": float(data["x_km"]),
            "y_km": float(data["y_km"]),
        }
        if data.get("lon") is not None:
            attrs["lon"] = float(data["lon"])
        if data.get("lat") is not None:
            attrs["lat"] = float(data["lat"])
        saved.add_node(str(node), **attrs)
    for u, v, data in network.graph.edges(data=True):
        saved.add_edge(
            str(u),
            str(v),
            length=float(data["length"]),
            names=" | ".join(data.get("names") or []),
        )
    buffer = io.BytesIO()
    nx.write_graphml(saved, buffer)
    return buffer.getvalue()


def clean_title(query: str) -> str:
    title = query.strip()
    for suffix in (", USA", ", US", ", United States", ", United States of America"):
        if title.lower().endswith(suffix.lower()):
            title = title[: -len(suffix)]
    title = title.strip(" ,")
    return title or "Road network"


def network_from_osm_graph(
    graph: nx.MultiDiGraph,
    *,
    title: str,
    official_name: str | None,
    kind_label: str,
    area_km2: float | None,
    source: str,
) -> RoadNetwork:
    longitudes = {node: float(data["x"]) for node, data in graph.nodes(data=True)}
    latitudes = {node: float(data["y"]) for node, data in graph.nodes(data=True)}
    projected = ox.project_graph(graph)
    for node, data in projected.nodes(data=True):
        data["lon"] = longitudes[node]
        data["lat"] = latitudes[node]
    simple = collapse_to_simple(ox.convert.to_undirected(projected))
    return finalize_graph(
        simple,
        title=title,
        source=source,
        official_name=official_name,
        kind_label=kind_label,
        area_km2=area_km2,
        coords="projected",
    )


def finalize_graph(
    graph: nx.Graph,
    *,
    title: str,
    source: str,
    official_name: str | None,
    kind_label: str,
    area_km2: float | None,
    coords: str,
) -> RoadNetwork:
    """Make the graph match the lab's rules and keep the largest connected piece.

    `coords` is "lonlat", "projected" (x and y in meters), or "none".
    """
    working = _fresh_copy(graph)
    _ensure_edge_attributes(working)
    notes: list[str] = []
    before_chains = working.number_of_nodes()
    working, _removed = contract_degree_two(working)
    merged = before_chains - working.number_of_nodes()
    if merged > 0:
        notes.append(
            f"Merged {merged:,} bend points into the roads between intersections."
        )
    if working.number_of_nodes() == 0:
        raise NetworkLabError("No intersections were found in that network.")

    if coords == "lonlat":
        _project_lonlat_nodes(working)
        geographic = True
    elif coords == "projected":
        missing = [
            node
            for node, data in working.nodes(data=True)
            if not _is_number(data.get("x")) or not _is_number(data.get("y"))
        ]
        if missing and len(missing) == working.number_of_nodes():
            geographic = False
            coords = "none"
        elif missing:
            working.remove_nodes_from(missing)
            notes.append(
                f"Ignored {len(missing):,} intersections that had no coordinates."
            )
            geographic = True
        else:
            geographic = True
    else:
        geographic = False

    before_component = working.number_of_nodes()
    working, dropped = largest_component(working)
    if dropped > 0:
        notes.append(
            f"Kept the largest connected road network and set aside {dropped:,} "
            f"of {before_component:,} intersections that had no path onto it."
        )
    if working.number_of_nodes() < 3:
        raise NetworkLabError(
            "The connected road network is too small. Check that the roads share intersections, "
            "or pick a larger place."
        )

    if geographic:
        _assign_kilometers(working)
    else:
        _assign_diagram_layout(working)
        notes.append(
            "This network has no map coordinates. The picture is a diagram, not a map of a place."
        )
    _assign_labels(working)
    has_latlon = all(
        _is_number(data.get("lon")) and _is_number(data.get("lat"))
        for _, data in working.nodes(data=True)
    )
    return RoadNetwork(
        graph=working,
        title=title,
        source=source,
        official_name=official_name,
        kind_label=kind_label,
        area_km2=area_km2,
        dropped_nodes=dropped,
        geographic=geographic,
        has_latlon=has_latlon,
        token=uuid.uuid4().hex[:12],
        notes=notes,
    )


def collapse_to_simple(graph: nx.Graph) -> nx.Graph:
    """Drop parallel and one-way duplicates. Keep the shorter road and every street name."""
    simple = nx.Graph()
    for node, data in graph.nodes(data=True):
        attrs = {}
        for key in ("x", "y", "lon", "lat", "label"):
            if key in data and data[key] is not None and str(data[key]).strip() != "":
                number = _maybe_float(data[key]) if key != "label" else None
                attrs[key] = data[key] if key == "label" else number
        simple.add_node(node, **{key: value for key, value in attrs.items() if value is not None or key == "label"})
    for u, v, data in graph.edges(data=True):
        if u == v or u not in simple or v not in simple:
            continue
        length = _maybe_float(data.get("length"))
        names = names_from_attr(data.get("names", data.get("name")))
        if simple.has_edge(u, v):
            current = simple[u][v]["length"]
            if length is not None and (current is None or length < current):
                simple[u][v]["length"] = length
            simple[u][v]["names"] = merge_names(simple[u][v]["names"], names)
        else:
            simple.add_edge(u, v, length=length, names=names)
    return simple


def _same_road(left_names: list[str], right_names: list[str]) -> bool:
    """A bend continues one road. Two different street names are an intersection."""
    left = {name for name in left_names or [] if name}
    right = {name for name in right_names or [] if name}
    if not left or not right:
        return True
    return bool(left & right)


def contract_degree_two(graph: nx.Graph) -> tuple[nx.Graph, int]:
    """Replace chains of bend points with one road between real intersections.

    A node with two neighbors is removed only when both roads share a name, or
    a name is missing. A corner where Main meets Oak stays. A pure loop of
    degree-2 nodes is left as it is.
    """
    original_n = graph.number_of_nodes()
    anchors = [node for node, degree in graph.degree() if degree != 2]
    if not anchors or original_n == 0:
        return graph, 0
    visited: set[frozenset] = set()
    additions: list[tuple[object, object, float, list[str]]] = []
    remove: set[object] = set()
    for anchor in anchors:
        if anchor not in graph:
            continue
        for neighbor in list(graph.neighbors(anchor)):
            key = frozenset((anchor, neighbor))
            if key in visited or neighbor not in graph:
                continue
            if graph.degree(neighbor) != 2:
                visited.add(key)
                continue
            side_a, side_b = list(graph.neighbors(neighbor))
            if not _same_road(graph[neighbor][side_a]["names"], graph[neighbor][side_b]["names"]):
                visited.add(key)
                continue
            length = float(graph[anchor][neighbor]["length"])
            names = list(graph[anchor][neighbor]["names"])
            prev, curr = anchor, neighbor
            chain: list[object] = []
            cyclic = False
            while graph.degree(curr) == 2:
                left, right = list(graph.neighbors(curr))
                if not _same_road(graph[curr][left]["names"], graph[curr][right]["names"]):
                    break
                chain.append(curr)
                nxt = left if right == prev else right
                visited.add(frozenset((prev, curr)))
                length += float(graph[curr][nxt]["length"])
                names.extend(graph[curr][nxt]["names"])
                prev, curr = curr, nxt
                if curr == anchor or curr in chain:
                    cyclic = True
                    break
            if cyclic or not chain:
                continue
            visited.add(frozenset((prev, curr)))
            additions.append((anchor, curr, length, merge_names(names)))
            remove.update(chain)
    if not remove:
        return graph, 0
    graph.remove_nodes_from(remove)
    for left, right, length, names in additions:
        if left not in graph or right not in graph or left == right:
            continue
        if graph.has_edge(left, right):
            if length < graph[left][right]["length"]:
                graph[left][right]["length"] = length
            graph[left][right]["names"] = merge_names(graph[left][right]["names"], names)
        else:
            graph.add_edge(left, right, length=length, names=names)
    return graph, original_n - graph.number_of_nodes()


def largest_component(graph: nx.Graph) -> tuple[nx.Graph, int]:
    if graph.number_of_nodes() == 0 or nx.is_connected(graph):
        return graph, 0
    largest = max(nx.connected_components(graph), key=len)
    dropped = graph.number_of_nodes() - len(largest)
    return graph.subgraph(largest).copy(), dropped


def names_from_attr(value) -> list[str]:
    if value is None:
        return []
    if isinstance(value, (list, tuple, set)):
        found: list[str] = []
        for item in value:
            found.extend(names_from_attr(item))
        return merge_names(found)
    text = str(value).strip()
    if not text or text.lower() in {"nan", "none", "null"}:
        return []
    if text.startswith("[") and text.endswith("]"):
        try:
            parsed = ast.literal_eval(text)
        except (SyntaxError, ValueError):
            parsed = None
        if isinstance(parsed, (list, tuple)):
            return names_from_attr(list(parsed))
    if "|" in text:
        return [part.strip() for part in text.split("|") if part.strip()]
    return [text]


def merge_names(*groups: list[str]) -> list[str]:
    merged: list[str] = []
    seen: set[str] = set()
    for group in groups:
        for name in group or []:
            cleaned = str(name).strip()
            if cleaned and cleaned not in seen:
                seen.add(cleaned)
                merged.append(cleaned)
            if len(merged) >= 12:
                return merged
    return merged


# Public Overpass servers. The first two answered quickly; the others are backups.
_OVERPASS_SERVERS = (
    "https://overpass.osm.ch/api",
    "https://overpass.openstreetmap.fr/api",
    "https://overpass-api.de/api",
    "https://overpass.kumi.systems/api",
    "https://overpass.private.coffee/api",
)


def edges_geojson_bytes(graph: nx.MultiDiGraph) -> bytes:
    """GeoJSON of the road edges, as `edges.to_file(..., driver='GeoJSON')` would write."""
    edges = _edge_frame(graph)
    return edges.to_json().encode("utf-8")


def edges_shapefile_zip_bytes(graph: nx.MultiDiGraph) -> bytes:
    """Zipped shapefile of the road edges, as `edges.to_file(..., driver='ESRI Shapefile')`."""
    edges = _shapefile_frame(_edge_frame(graph))
    folder = Path(tempfile.mkdtemp(prefix="roads_shp_"))
    try:
        target = folder / "roads.shp"
        edges.to_file(target, driver="ESRI Shapefile")
        buffer = io.BytesIO()
        with zipfile.ZipFile(buffer, "w", compression=zipfile.ZIP_DEFLATED) as archive:
            for path in folder.iterdir():
                archive.write(path, arcname=f"roads_shapefile/{path.name}")
        return buffer.getvalue()
    finally:
        shutil.rmtree(folder, ignore_errors=True)


def _download_graph(query: str, kind: str) -> nx.MultiDiGraph:
    # Drivable streets use the same call as ox.graph_from_place(place, network_type="drive").
    if kind == "streets":
        kwargs = {"network_type": "drive"}
    elif kind == "walk":
        kwargs = {"network_type": "walk"}
    elif kind == "bike":
        kwargs = {"network_type": "bike"}
    else:
        custom = _HIGHWAY_FILTER if kind == "highways" else _MAIN_FILTER
        kwargs = {"custom_filter": custom}
    return _graph_from_place(query, **kwargs)


def _graph_from_place(query: str, **kwargs) -> nx.MultiDiGraph:
    """Call graph_from_place, and try another Overpass server if one times out."""
    configure_osm()
    failures: list[Exception] = []
    for server in _OVERPASS_SERVERS:
        ox.settings.overpass_url = server
        try:
            return ox.graph_from_place(query, **kwargs)
        except Exception as exc:
            if _is_place_error(exc):
                raise
            failures.append(exc)
    if failures:
        raise failures[-1]
    raise NetworkLabError("No OpenStreetMap server is configured.")


def _edge_frame(graph: nx.MultiDiGraph):
    _nodes, edges = ox.graph_to_gdfs(graph, nodes=True, edges=True)
    return edges.reset_index()


def _shapefile_frame(edges):
    """Shapefiles cannot store lists or field names longer than 10 characters."""
    frame = edges.copy()
    used: set[str] = set()
    rename: dict[str, str] = {}
    for column in list(frame.columns):
        if column == "geometry":
            continue
        if frame[column].dtype == object:
            frame[column] = frame[column].map(_shapefile_value)
        short = column[:10]
        number = 1
        while short.lower() in used:
            short = f"{column[:8]}{number}"[:10]
            number += 1
        used.add(short.lower())
        if short != column:
            rename[column] = short
    return frame.rename(columns=rename)


def _shapefile_value(value):
    if value is None:
        return ""
    if isinstance(value, float) and math.isnan(value):
        return ""
    if isinstance(value, (list, tuple, dict)):
        return json.dumps(value, default=str)
    return str(value)


def _is_place_error(exc: Exception) -> bool:
    text = str(exc).lower()
    return any(
        token in text
        for token in (
            "nominatim",
            "geocod",
            "no polygon",
            "found no graph",
            "no matching",
        )
    )


def _network_from_generic(
    graph: nx.Graph,
    *,
    title: str,
    source: str,
    official_name: str | None,
    kind_label: str,
    area_km2: float | None,
) -> RoadNetwork:
    simple = collapse_to_simple(graph)
    longitudes = []
    latitudes = []
    xs = []
    ys = []
    for _, data in simple.nodes(data=True):
        lon = _maybe_float(data.get("lon"))
        lat = _maybe_float(data.get("lat"))
        x = _maybe_float(data.get("x"))
        y = _maybe_float(data.get("y"))
        if lon is not None and lat is not None:
            longitudes.append(lon)
            latitudes.append(lat)
        if x is not None and y is not None:
            xs.append(x)
            ys.append(y)
    flagged = str(graph.graph.get("geographic", "")).lower()
    if flagged == "false":
        coords = "none"
    elif longitudes and len(longitudes) == simple.number_of_nodes() and _looks_geographic(longitudes, latitudes):
        for node, data in simple.nodes(data=True):
            data["x"] = float(data["lon"])
            data["y"] = float(data["lat"])
        coords = "lonlat"
    elif xs and _looks_geographic(xs, ys):
        coords = "lonlat"
    elif xs:
        coords = "projected"
    else:
        coords = "none"
    return finalize_graph(
        simple,
        title=title,
        source=source,
        official_name=official_name,
        kind_label=kind_label,
        area_km2=area_km2,
        coords=coords,
    )


def _load_tables(paths: list[Path]) -> RoadNetwork:
    frames = [(path, pd.read_csv(path)) for path in paths]
    edges = None
    nodes = None
    edge_name = "edges.csv"
    for path, frame in frames:
        role = _csv_role(frame)
        if role == "edges" and edges is None:
            edges = frame
            edge_name = path.name
        elif role == "nodes" and nodes is None:
            nodes = frame
    if edges is None:
        raise NetworkLabError(
            "The CSV needs columns named source and target. "
            "Optional columns are length (meters) and name. "
            "A second CSV can list each intersection as id, longitude, latitude."
        )
    graph = _graph_from_edge_table(edges, nodes)
    return finalize_graph(
        graph,
        title=clean_title(Path(edge_name).stem),
        source=f"Uploaded file ({edge_name})",
        official_name=None,
        kind_label="Uploaded network",
        area_km2=None,
        coords=_coordinate_mode(graph),
    )


def _load_spatial(path: Path) -> RoadNetwork:
    frame = _read_lines(path)
    if frame.empty:
        raise NetworkLabError(
            "No road lines were found in that file. "
            "The lab needs line features, not points or area boundaries."
        )
    frame, filter_note = _limit_huge_extract(frame)
    frame = _with_crs(frame)
    graph, coords = _graph_from_lines(frame)
    network = finalize_graph(
        graph,
        title=clean_title(path.stem),
        source=f"OpenStreetMap file ({path.name})",
        official_name=None,
        kind_label="OpenStreetMap file",
        area_km2=None,
        coords=coords,
    )
    if filter_note:
        network.notes.insert(0, filter_note)
    return network


def _read_lines(path: Path) -> gpd.GeoDataFrame:
    try:
        layers = gpd.list_layers(path)
    except Exception:
        layers = None
    if layers is not None and len(layers) > 1:
        best = None
        best_count = -1
        name_column = "name" if "name" in layers.columns else layers.columns[0]
        for layer in layers[name_column].tolist():
            frame = gpd.read_file(path, layer=layer)
            count = int(frame.geometry.geom_type.isin(["LineString", "MultiLineString"]).sum())
            if count > best_count:
                best = frame
                best_count = count
        frame = best if best is not None else gpd.read_file(path)
    else:
        try:
            frame = gpd.read_file(path)
        except Exception as exc:
            raise NetworkLabError(
                "That spatial file could not be read. GeoJSON, GeoPackage, and zipped shapefiles work. "
                "A shapefile has to be zipped with its .shp, .dbf, .shx, and .prj files."
            ) from exc
    lines = frame[frame.geometry.geom_type.isin(["LineString", "MultiLineString"])].copy()
    return lines


def _with_crs(frame: gpd.GeoDataFrame) -> gpd.GeoDataFrame:
    if frame.crs is not None:
        return frame
    minx, miny, maxx, maxy = frame.total_bounds
    if max(abs(minx), abs(maxx)) <= 180 and max(abs(miny), abs(maxy)) <= 90:
        return frame.set_crs(4326)
    raise NetworkLabError(
        "This file has coordinates but no coordinate system. "
        "Export it again with a CRS, or use longitude and latitude."
    )


def _graph_from_lines(frame: gpd.GeoDataFrame) -> tuple[nx.Graph, str]:
    """Build an intersection graph from road centerlines.

    If the file already names the intersections (columns u and v, or source and
    target), each feature is one road between those intersections. Otherwise
    every shared endpoint becomes an intersection, and later steps merge bend points.
    """
    columns = {str(column).lower(): column for column in frame.columns}
    named = _edge_id_columns(columns)
    geographic = bool(frame.crs.is_geographic)
    projected = frame.to_crs(frame.estimate_utm_crs()) if geographic else frame
    graph = nx.Graph()
    if named is not None:
        source_col, target_col = named
        for idx in frame.index:
            geometry = projected.geometry.loc[idx]
            if geometry is None or geometry.is_empty:
                continue
            row = frame.loc[idx]
            u = row[source_col]
            v = row[target_col]
            if pd.isna(u) or pd.isna(v) or u == v:
                continue
            start, end = _line_ends(geometry)
            _put_xy(graph, u, start)
            _put_xy(graph, v, end)
            if geographic:
                lonlat_start, lonlat_end = _line_ends(frame.geometry.loc[idx])
                _put_lonlat_once(graph, u, lonlat_start)
                _put_lonlat_once(graph, v, lonlat_end)
            _add_road(graph, u, v, float(geometry.length), _row_names(row, columns))
        return graph, "projected"

    for idx in projected.index:
        names = _row_names(projected.loc[idx], columns)
        for part in _iter_lines(projected.geometry.loc[idx]):
            points = [(round(x, 1), round(y, 1)) for x, y, *_rest in part.coords]
            for start, end in zip(points, points[1:]):
                if start == end:
                    continue
                _add_xy_node(graph, start)
                _add_xy_node(graph, end)
                _add_road(graph, start, end, math.hypot(end[0] - start[0], end[1] - start[1]), names)
    if geographic and graph.number_of_nodes():
        _attach_lonlat_from_projected(graph, projected.crs)
    return graph, "projected"


def _graph_from_edge_table(edges: pd.DataFrame, nodes: pd.DataFrame | None) -> nx.Graph:
    columns = {str(column).lower().strip(): column for column in edges.columns}
    source_col, target_col = _require_edge_columns(columns)
    length_col = _first_column(columns, ("length", "distance", "meters", "weight", "length_m"))
    km_col = _first_column(columns, ("length_km", "km"))
    miles_col = _first_column(columns, ("length_mi", "miles"))
    name_col = _first_column(columns, _NAME_COLUMNS)
    positions = _node_positions(nodes) if nodes is not None else {}
    graph = nx.Graph()
    for _, row in edges.iterrows():
        u = _as_id(row[source_col])
        v = _as_id(row[target_col])
        if u is None or v is None or u == v:
            continue
        names = names_from_attr(row[name_col]) if name_col else []
        length = None
        if length_col:
            length = _maybe_float(row[length_col])
        elif km_col:
            km = _maybe_float(row[km_col])
            length = None if km is None else km * 1000.0
        elif miles_col:
            miles = _maybe_float(row[miles_col])
            length = None if miles is None else miles * 1609.344
        for node in (u, v):
            if node not in graph:
                graph.add_node(node)
            if node in positions:
                lon_or_x, lat_or_y, kind = positions[node]
                if kind == "lonlat":
                    graph.nodes[node]["lon"] = lon_or_x
                    graph.nodes[node]["lat"] = lat_or_y
                    graph.nodes[node]["x"] = lon_or_x
                    graph.nodes[node]["y"] = lat_or_y
                else:
                    graph.nodes[node]["x"] = lon_or_x
                    graph.nodes[node]["y"] = lat_or_y
        if length is None:
            length = _length_from_nodes(graph, u, v)
        graph.add_edge(u, v, length=length, names=names)
    return graph


def _node_positions(nodes: pd.DataFrame) -> dict:
    columns = {str(column).lower().strip(): column for column in nodes.columns}
    id_col = _first_column(columns, ("id", "node", "node_id", "osmid", "intersection"))
    if id_col is None:
        raise NetworkLabError("The nodes CSV needs an id column that matches source and target.")
    lon_col = _first_column(columns, ("lon", "longitude", "lng", "x"))
    lat_col = _first_column(columns, ("lat", "latitude", "y"))
    if lon_col is None or lat_col is None:
        raise NetworkLabError("The nodes CSV needs longitude and latitude, or x and y columns.")
    kind = "lonlat" if lon_col.lower() in {"lon", "longitude", "lng"} or lat_col.lower() in {"lat", "latitude"} else "xy"
    # A column named x/y can still be longitude/latitude. Detect from the values.
    sample_x = pd.to_numeric(nodes[lon_col], errors="coerce")
    sample_y = pd.to_numeric(nodes[lat_col], errors="coerce")
    if _looks_geographic(sample_x.dropna().tolist(), sample_y.dropna().tolist()):
        kind = "lonlat"
    positions = {}
    for _, row in nodes.iterrows():
        x = _maybe_float(row[lon_col])
        y = _maybe_float(row[lat_col])
        if x is None or y is None or pd.isna(row[id_col]):
            continue
        positions[_as_id(row[id_col])] = (x, y, kind)
    return positions


def _coordinate_mode(graph: nx.Graph) -> str:
    xs = []
    ys = []
    lons = []
    lats = []
    for _, data in graph.nodes(data=True):
        if _is_number(data.get("lon")) and _is_number(data.get("lat")):
            lons.append(float(data["lon"]))
            lats.append(float(data["lat"]))
        if _is_number(data.get("x")) and _is_number(data.get("y")):
            xs.append(float(data["x"]))
            ys.append(float(data["y"]))
    if lons and len(lons) == graph.number_of_nodes():
        return "lonlat"
    if xs and _looks_geographic(xs, ys):
        return "lonlat"
    if len(xs) == graph.number_of_nodes() and xs:
        return "projected"
    return "none"


def _put_xy(graph: nx.Graph, node, coord) -> None:
    if node not in graph:
        graph.add_node(node, x=float(coord[0]), y=float(coord[1]))


def _put_lonlat_once(graph: nx.Graph, node, coord) -> None:
    data = graph.nodes[node]
    if not _is_number(data.get("lon")):
        data["lon"] = float(coord[0])
        data["lat"] = float(coord[1])


def _line_ends(geometry) -> tuple[tuple[float, float], tuple[float, float]]:
    parts = list(_iter_lines(geometry))
    if not parts:
        return (0.0, 0.0), (0.0, 0.0)
    return parts[0].coords[0][:2], parts[-1].coords[-1][:2]


def _iter_lines(geometry):
    if geometry is None or geometry.is_empty:
        return
    if geometry.geom_type == "LineString":
        yield geometry
    elif geometry.geom_type == "MultiLineString":
        yield from geometry.geoms


def _as_id(value):
    if value is None or (isinstance(value, float) and math.isnan(value)):
        return None
    try:
        if pd.isna(value):
            return None
    except (TypeError, ValueError):
        pass
    if isinstance(value, float) and value.is_integer():
        return str(int(value))
    if isinstance(value, int) and not isinstance(value, bool):
        return str(value)
    text = str(value).strip()
    return text or None


def _add_xy_node(graph: nx.Graph, coord: tuple[float, float]) -> None:
    if coord not in graph:
        graph.add_node(coord, x=float(coord[0]), y=float(coord[1]))


def _add_road(graph: nx.Graph, u, v, length: float, names: list[str]) -> None:
    if graph.has_edge(u, v):
        if length < graph[u][v]["length"]:
            graph[u][v]["length"] = length
        graph[u][v]["names"] = merge_names(graph[u][v]["names"], names)
    else:
        graph.add_edge(u, v, length=length, names=list(names))


def _attach_lonlat_from_projected(graph: nx.Graph, crs) -> None:
    if graph.number_of_nodes() == 0:
        return
    nodes = list(graph.nodes)
    points = gpd.GeoDataFrame(
        geometry=gpd.points_from_xy(
            [graph.nodes[node]["x"] for node in nodes],
            [graph.nodes[node]["y"] for node in nodes],
        ),
        crs=crs,
    ).to_crs(4326)
    for node, geom in zip(nodes, points.geometry, strict=True):
        graph.nodes[node]["lon"] = float(geom.x)
        graph.nodes[node]["lat"] = float(geom.y)


def _row_names(row, columns: dict) -> list[str]:
    for candidate in _NAME_COLUMNS:
        if candidate in columns:
            return names_from_attr(row[columns[candidate]])
    return []


def _edge_id_columns(columns: dict) -> tuple[str, str] | None:
    pairs = (("u", "v"), ("source", "target"), ("from", "to"), ("from_id", "to_id"))
    for left, right in pairs:
        if left in columns and right in columns:
            return columns[left], columns[right]
    return None


def _require_edge_columns(columns: dict) -> tuple[str, str]:
    found = _edge_id_columns(columns)
    if found is None:
        raise NetworkLabError("The CSV needs columns named source and target.")
    return found


def _first_column(columns: dict, names: tuple[str, ...]) -> str | None:
    for name in names:
        if name in columns:
            return columns[name]
    return None


def _csv_role(frame: pd.DataFrame) -> str | None:
    columns = {str(column).lower().strip() for column in frame.columns}
    if columns & {"source", "u", "from", "from_id"} and columns & {"target", "v", "to", "to_id"}:
        return "edges"
    if columns & {"lon", "longitude", "lng", "lat", "latitude", "x", "y"}:
        return "nodes"
    return None


def _expand_archives(paths: list[Path]) -> list[Path]:
    expanded: list[Path] = []
    for path in paths:
        if path.suffix.lower() != ".zip":
            expanded.append(path)
            continue
        destination = path.parent / f"{path.stem}_unzipped"
        destination.mkdir(parents=True, exist_ok=True)
        try:
            with zipfile.ZipFile(path) as archive:
                _safe_extract(archive, destination)
        except zipfile.BadZipFile as exc:
            raise NetworkLabError("That zip file could not be opened.") from exc
        for child in destination.rglob("*"):
            if child.is_file() and _is_network_file(child):
                expanded.append(child)
    if not expanded:
        raise NetworkLabError("The zip file did not contain a road network.")
    return expanded


def _safe_extract(archive: zipfile.ZipFile, destination: Path) -> None:
    root = destination.resolve()
    unzipped_mb = sum(member.file_size for member in archive.infolist()) / (1024 * 1024)
    if unzipped_mb > MAX_UNZIPPED_MB:
        raise NetworkLabError(
            f"That zip unpacks to {unzipped_mb:,.0f} MB, more than this lab accepts "
            f"({MAX_UNZIPPED_MB:,.0f} MB). Export a smaller place, or only main roads."
        )
    for member in archive.infolist():
        target = (destination / member.filename).resolve()
        if root != target and root not in target.parents:
            raise NetworkLabError("That zip file contains an unsafe path and was not opened.")
        archive.extract(member, destination)


def _is_network_file(path: Path) -> bool:
    name = path.name.lower()
    return name.endswith(
        (".graphml", ".xml", ".osm", ".geojson", ".json", ".gpkg", ".shp", ".csv", ".pbf")
    )


def _file_kind(path: Path) -> str:
    name = path.name.lower()
    if name.endswith(".pbf"):
        return "pbf"
    if name.endswith(".geojson"):
        return "spatial"
    if name.endswith(".csv"):
        return "table"
    if name.endswith((".gpkg", ".shp")):
        return "spatial"
    if name.endswith(".json"):
        head = _head_text(path)
        if '"elements"' in head:
            return "overpass"
        return "spatial"
    if name.endswith(".graphml"):
        return "graphml"
    if name.endswith((".osm", ".xml")):
        head = _head_text(path)
        if "<osm" in head:
            return "osm"
        return "graphml"
    return "spatial"


def _head_text(path: Path) -> str:
    try:
        return path.read_bytes()[:800].decode("utf-8", errors="ignore").lower()
    except OSError:
        return ""


def _prefer_roads(paths: list[Path]) -> Path:
    named = [path for path in paths if "road" in path.name.lower()]
    return named[0] if named else paths[0]


def _keep_highway_edges(graph: nx.MultiDiGraph) -> nx.MultiDiGraph:
    """Drop buildings and other non-roads when the file mixed them in with streets."""
    tagged = [(*edge[:3],) for edge in graph.edges(keys=True, data=True) if edge[3].get("highway")]
    if not tagged or len(tagged) == graph.number_of_edges():
        return graph
    keep = set(tagged)
    drop = [edge for edge in graph.edges(keys=True) if edge not in keep]
    graph.remove_edges_from(drop)
    graph.remove_nodes_from([node for node, degree in graph.degree() if degree == 0])
    return graph


def _graph_from_overpass_elements(elements: list) -> nx.Graph:
    locations: dict = {}
    for element in elements:
        if element.get("type") == "node" and "lat" in element and "lon" in element:
            locations[element["id"]] = (float(element["lon"]), float(element["lat"]))
    graph = nx.Graph()
    saw_highway_tag = any((element.get("tags") or {}).get("highway") for element in elements)
    for element in elements:
        if element.get("type") != "way":
            continue
        tags = element.get("tags") or {}
        if saw_highway_tag and not tags.get("highway"):
            continue
        names = names_from_attr(tags.get("name"))
        if element.get("nodes") and all(node_id in locations for node_id in element["nodes"]):
            points = [(node_id, locations[node_id]) for node_id in element["nodes"]]
        elif element.get("geometry"):
            points = [
                ((round(float(point["lon"]), 6), round(float(point["lat"]), 6)), (float(point["lon"]), float(point["lat"])))
                for point in element["geometry"]
                if "lon" in point and "lat" in point
            ]
        else:
            continue
        for (left_id, left_xy), (right_id, right_xy) in zip(points, points[1:]):
            if left_id == right_id:
                continue
            for node_id, (lon, lat) in ((left_id, left_xy), (right_id, right_xy)):
                if node_id not in graph:
                    graph.add_node(node_id, x=lon, y=lat, lon=lon, lat=lat)
            _add_road(graph, left_id, right_id, _haversine_m(*left_xy, *right_xy), names)
    return graph


def _limit_huge_extract(frame: gpd.GeoDataFrame) -> tuple[gpd.GeoDataFrame, str | None]:
    """A full state of local streets will not finish in class. Keep main roads."""
    if len(frame) < 80000:
        return frame, None
    columns = {str(column).lower(): column for column in frame.columns}
    column = columns.get("highway") or columns.get("fclass")
    if column is None:
        return frame, None
    classes = frame[column].astype(str).str.lower()
    kept = frame[classes.isin(_MAIN_ROAD_CLASSES)]
    if len(kept) < 50:
        return frame, None
    note = (
        f"This file has {len(frame):,} road lines. "
        f"Kept {len(kept):,} main roads, from motorways through secondary streets, "
        "so the calculation can finish."
    )
    return kept, note


def _fresh_copy(graph: nx.Graph) -> nx.Graph:
    fresh = nx.Graph()
    for node, data in graph.nodes(data=True):
        fresh.add_node(node, **{key: value for key, value in data.items()})
    for u, v, data in graph.edges(data=True):
        fresh.add_edge(
            u,
            v,
            length=_maybe_float(data.get("length")),
            names=list(data.get("names") or []),
        )
    return fresh


def _ensure_edge_attributes(graph: nx.Graph) -> None:
    for u, v, data in graph.edges(data=True):
        data["names"] = merge_names(names_from_attr(data.get("names")))
        length = _maybe_float(data.get("length"))
        if length is None or length <= 0:
            length = _length_from_nodes(graph, u, v)
        data["length"] = 1.0 if length is None or length <= 0 else float(length)


def _length_from_nodes(graph: nx.Graph, u, v) -> float | None:
    left = graph.nodes[u]
    right = graph.nodes[v]
    if _is_number(left.get("lon")) and _is_number(right.get("lon")):
        return _haversine_m(left["lon"], left["lat"], right["lon"], right["lat"])
    if _is_number(left.get("x")) and _is_number(right.get("x")):
        x1, y1 = float(left["x"]), float(left["y"])
        x2, y2 = float(right["x"]), float(right["y"])
        if _looks_geographic([x1, x2], [y1, y2]):
            return _haversine_m(x1, y1, x2, y2)
        return math.hypot(x2 - x1, y2 - y1)
    return None


def _project_lonlat_nodes(graph: nx.Graph) -> None:
    nodes = list(graph.nodes)
    longitudes = []
    latitudes = []
    for node in nodes:
        data = graph.nodes[node]
        lon = _maybe_float(data.get("lon"))
        lat = _maybe_float(data.get("lat"))
        if lon is None:
            lon = _maybe_float(data.get("x"))
            lat = _maybe_float(data.get("y"))
        if lon is None or lat is None:
            raise NetworkLabError(
                "Some intersections are missing longitude and latitude, so the network cannot be mapped."
            )
        data["lon"] = float(lon)
        data["lat"] = float(lat)
        longitudes.append(float(lon))
        latitudes.append(float(lat))
    points = gpd.GeoDataFrame(
        geometry=gpd.points_from_xy(longitudes, latitudes),
        crs="EPSG:4326",
    )
    projected = points.to_crs(points.estimate_utm_crs())
    for node, geom in zip(nodes, projected.geometry, strict=True):
        graph.nodes[node]["x"] = float(geom.x)
        graph.nodes[node]["y"] = float(geom.y)
    # Lengths that were left as 1 (no length column, no geometry) get replaced
    # only when they were a placeholder. Edges that already have a real length stay.
    for u, v, data in graph.edges(data=True):
        if data["length"] == 1.0:
            guessed = math.hypot(
                graph.nodes[u]["x"] - graph.nodes[v]["x"],
                graph.nodes[u]["y"] - graph.nodes[v]["y"],
            )
            if guessed > 1.0:
                data["length"] = float(guessed)


def _assign_kilometers(graph: nx.Graph) -> None:
    xs = [float(data["x"]) for _, data in graph.nodes(data=True)]
    ys = [float(data["y"]) for _, data in graph.nodes(data=True)]
    origin_x = sum(xs) / len(xs)
    origin_y = sum(ys) / len(ys)
    for _, data in graph.nodes(data=True):
        data["x_km"] = (float(data["x"]) - origin_x) / 1000.0
        data["y_km"] = (float(data["y"]) - origin_y) / 1000.0


def _assign_diagram_layout(graph: nx.Graph) -> None:
    positions = nx.spring_layout(graph, seed=7)
    for node, (x, y) in positions.items():
        graph.nodes[node]["x_km"] = float(x) * 10.0
        graph.nodes[node]["y_km"] = float(y) * 10.0
        graph.nodes[node]["x"] = float(x) * 10000.0
        graph.nodes[node]["y"] = float(y) * 10000.0


def _assign_labels(graph: nx.Graph) -> None:
    for node, data in graph.nodes(data=True):
        existing = data.get("label")
        if existing and not str(existing).startswith("Unnamed"):
            # Keep a label that came from a file when it is a real street name.
            # Node ids copied into the label field are replaced below when we
            # can build a better one from the street names.
            if str(existing) != str(node):
                data["label"] = str(existing)
                continue
        names: list[str] = []
        seen: set[str] = set()
        for _, _, edge in graph.edges(node, data=True):
            for name in edge.get("names") or []:
                if name not in seen:
                    seen.add(name)
                    names.append(name)
                if len(names) >= 3:
                    break
            if len(names) >= 3:
                break
        data["label"] = " & ".join(names) if names else f"Intersection {node}"


def _area_km2(boundary: gpd.GeoDataFrame) -> float | None:
    try:
        projected = boundary.to_crs(boundary.estimate_utm_crs())
        return float(projected.geometry.area.iloc[0]) / 1_000_000.0
    except Exception:
        return None


def _looks_geographic(xs, ys) -> bool:
    if len(xs) == 0 or len(ys) == 0:
        return False
    return max(abs(float(x)) for x in xs) <= 180 and max(abs(float(y)) for y in ys) <= 90


def _haversine_m(lon1, lat1, lon2, lat2) -> float:
    radius = 6_371_000.0
    phi1, phi2 = math.radians(float(lat1)), math.radians(float(lat2))
    dphi = math.radians(float(lat2) - float(lat1))
    dlambda = math.radians(float(lon2) - float(lon1))
    a = math.sin(dphi / 2) ** 2 + math.cos(phi1) * math.cos(phi2) * math.sin(dlambda / 2) ** 2
    return 2 * radius * math.asin(math.sqrt(a))


def _maybe_float(value):
    if value is None or isinstance(value, (list, tuple, dict)):
        return None
    try:
        if pd.isna(value):
            return None
    except (TypeError, ValueError):
        pass
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    if not math.isfinite(number):
        return None
    return number


def _is_number(value) -> bool:
    return _maybe_float(value) is not None


def _geocode_message(exc: Exception) -> str:
    return (
        "No boundary was found for that name. Try City, State, USA, "
        "for example Portland, Oregon, USA. "
        f"({_short_error(exc)})"
    )


def _download_message(exc: Exception) -> str:
    text = str(exc).lower()
    if "timed out" in text or "timeout" in text or "504" in text or "429" in text:
        return (
            "The OpenStreetMap servers timed out. "
            "Choose “Load a file from OpenStreetMap,” export the roads from Overpass Turbo, "
            "and upload that file."
        )
    return (
        "The road download did not finish. Check the place name and your connection, then try again. "
        f"({_short_error(exc)})"
    )


def _short_error(exc: Exception) -> str:
    text = " ".join(str(exc).split())
    return text[:240] if text else exc.__class__.__name__
