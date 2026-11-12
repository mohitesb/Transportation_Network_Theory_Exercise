"""Road network centrality lab.

Students open this page in a browser. They download a city, county, or state
road network, or upload one, and map degree, betweenness, and closeness.
"""

from __future__ import annotations

import base64
import html
import io
import math
import zipfile

import matplotlib.pyplot as plt
import pandas as pd
import plotly.express as px
import streamlit as st

from network_theory.centrality import compute_centrality, results_table
from network_theory.errors import NetworkLabError
from network_theory.load_network import (
    EXAMPLE_PATH,
    ROAD_KIND_DETAILS,
    ROAD_KINDS,
    PlaceInfo,
    RoadNetwork,
    download_roads,
    find_place,
    load_example,
    load_uploads,
    network_to_graphml_bytes,
    streets_are_blocked,
    streets_need_confirm,
    to_miles,
    to_square_miles,
)
from network_theory.plotting import (
    centrality_figure,
    color_limits,
    figure_png,
    lesson_figure,
    preview_figure,
)

IDENTIFY_QUESTIONS = [
    (
        "q_degree",
        "Which intersection has the highest weighted degree centrality?",
    ),
    (
        "q_betweenness",
        "Which intersection has the highest weighted betweenness?",
    ),
    (
        "q_closeness",
        "Which intersection has the highest weighted closeness?",
    ),
]

QUESTIONS = [
    (
        "q_station",
        "A city can build one fire station and wants a short trip to a typical intersection. "
        "Where on your map would you put the station?",
    ),
    (
        "q_between_place",
        "A town can build one rest stop for people traveling between other places. "
        "Where on your map would you put it?",
    ),
    (
        "q_degree_place",
        "A city can build one roundabout and wants it where the most roads already meet, "
        "so each of those roads gets an entrance. Where on your map would you put it?",
    ),
]

MEASURE_TEXT = {
    "degree": (
        "Color is how many roads meet at that intersection. "
        "A dead end is dark blue. A junction where several streets come together is red."
    ),
    "betweenness": (
        "Color is how often the intersection sits on a shortest path between other places. "
        "Red marks the bridges and shortcuts of the network. A quiet street can be blue even when it is near the middle of the map."
    ),
    "closeness": (
        "Color is how near the intersection is to all the others. "
        "The middle of the network is warm. The edge of town is cool."
    ),
}


def main() -> None:
    st.set_page_config(page_title="Road network centrality", layout="wide")
    _apply_pending_query()
    _sync_network_defaults()
    if st.session_state.get("flash"):
        st.success(st.session_state.pop("flash"))

    st.title("Road network centrality")
    st.write(
        "Download the roads for a city, a county, or a state, or upload a network you already have. "
        "Then map three measures: how many roads meet, which intersections sit on the most shortcuts, "
        "and which intersections are closest to the rest of the network."
    )
    st.caption("No coding. The work happens in this page.")

    with st.expander("New to these measures? Start here."):
        _show_lesson()

    st.subheader("1. Get a road network")
    _step_load()

    network = st.session_state.get("network")
    if network is None:
        st.info("Load a network to continue. A town or a small city is a good first try.")
        _about()
        return

    _network_summary(network)

    st.subheader("2. Calculate centrality")
    _step_calculate(network)

    results = _results_if_current(network)
    if results is None:
        if st.session_state.get("results") is not None:
            st.warning("The distance or betweenness setting changed. Click Calculate to refresh the maps.")
        _about()
        return

    st.subheader("3. Read the maps")
    _step_maps(network, results)
    _about()


def _show_lesson() -> None:
    st.write(
        "An intersection is a point where roads meet, or a dead end. "
        "A road in this lab is the connection between two intersections. "
        "The same three definitions are used on the toy streets below and on a real city."
    )
    figure = lesson_figure()
    st.pyplot(figure, alt="Three small street sketches colored by degree, betweenness, and closeness.")
    plt.close(figure)
    left, right = st.columns(2)
    left.markdown(
        "**Degree** counts the roads that meet. On the sketch, 1st and 2nd are the busiest junctions.\n\n"
        "**Betweenness** counts how often an intersection is on a shortest path between other intersections. "
        "Dead-end lanes score zero: nobody passes through them to get somewhere else. "
        "2nd scores high, because trips between the west side and the east side go through it."
    )
    right.markdown(
        "**Closeness** is high where the total trip to every other intersection is short. "
        "The middle of the sketch is closer to everyone than the east or west end.\n\n"
        "**Unweighted** means every block is one step, whether it is short or long. "
        "**Length-weighted** uses the real length of the road. "
        "Degree ignores length either way."
    )


def _step_load() -> None:
    mode = st.radio(
        "Where should the roads come from?",
        ["Download with OSMnx", "Load a file from OpenStreetMap"],
        horizontal=True,
    )
    if mode == "Download with OSMnx":
        _download_form()
    else:
        _upload_form()
    if EXAMPLE_PATH.exists():
        if st.button("Load the included example (Newark, Delaware, USA)"):
            try:
                network = load_example()
            except NetworkLabError as exc:
                st.error(str(exc))
            else:
                _store_network(network, "Loaded the Newark, Delaware example.")
                st.rerun()


def _download_form() -> None:
    st.text_input(
        "City, county, or state",
        key="place_query",
        placeholder="Lewes, Delaware, USA",
    )
    example_cols = st.columns(3)
    examples = ("Newark, Delaware, USA", "Lewes, Delaware, USA", "Delaware, USA")
    for column, name in zip(example_cols, examples, strict=True):
        column.button(name, on_click=_queue_query, args=(name,), width="stretch")

    if st.button("Find this place", type="primary"):
        query = st.session_state.get("place_query", "").strip()
        try:
            info = find_place(query)
        except NetworkLabError as exc:
            st.session_state.pop("place_info", None)
            st.error(str(exc))
        else:
            st.session_state["place_info"] = info
            st.session_state["road_kind"] = info.recommended_kind

    info = st.session_state.get("place_info")
    query = st.session_state.get("place_query", "").strip()
    if not isinstance(info, PlaceInfo) or info.query != query:
        st.caption("Find the place first. You will see the area and a suggested road type before anything downloads.")
        return

    st.info(f"OpenStreetMap calls this: {info.official_name}\n\n{info.message}")
    st.selectbox(
        "Which roads?",
        list(ROAD_KINDS),
        format_func=lambda key: ROAD_KINDS[key],
        key="road_kind",
    )
    kind = st.session_state["road_kind"]
    choice_lines = []
    for key in ("streets", "main", "highways"):
        marker = " (this download)" if key == kind else ""
        choice_lines.append(f"- **{ROAD_KINDS[key]}**{marker}. {ROAD_KIND_DETAILS[key]}")
    st.markdown("\n".join(choice_lines))
    if kind in {"walk", "bike"}:
        st.caption(f"**{ROAD_KINDS[kind]}.** {ROAD_KIND_DETAILS[kind]}")
    blocked = streets_are_blocked(kind, info.area_km2)
    needs_confirm = streets_need_confirm(kind, info.area_km2)
    confirmed = True
    if blocked:
        st.error(
            "That area is too large for every local street. "
            "Choose main roads, or highways and primary roads."
        )
    elif needs_confirm:
        st.warning(
            "All local streets in an area this large can take several minutes and a lot of memory. "
            "Main roads are the better classroom choice."
        )
        confirmed = st.checkbox("Download all local streets anyway")
    elif kind == "streets":
        st.caption(
            'All drivable streets uses graph_from_place(place, network_type="drive"). '
            "A city usually takes a minute or two. If one OpenStreetMap server times out, the next one is tried."
        )

    if st.button("Download roads", type="primary", disabled=blocked or not confirmed):
        try:
            with st.spinner(
                "Downloading the selected roads with OSMnx. "
                "A city takes a minute or two. Leave this tab open."
            ):
                network = download_roads(info, kind)
        except NetworkLabError as exc:
            st.error(str(exc))
        else:
            _store_network(network, f"Loaded {network.title}: {network.n:,} intersections.")
            st.rerun()


def _upload_form() -> None:
    st.write(
        "Download the roads in your browser, then upload the file here. "
        "That avoids the server timeout from the built-in download."
    )
    st.link_button("Open Overpass Turbo", "https://overpass-turbo.eu")
    st.markdown(
        "1. Click **Wizard**.\n"
        "2. Paste one of these lines and click **build and run**.\n"
        "3. When the roads appear, click **Export**.\n"
        "4. Choose **GeoJSON** or **raw OSM data**, then upload that file below."
    )
    st.caption("A town or city — every street")
    st.code('highway=* in "Newark, Delaware"', language=None)
    st.caption("A big city or a state — main roads only")
    st.code('highway~"motorway|trunk|primary|secondary" in "Delaware"', language=None)
    with st.expander("Whole state from Geofabrik, or another file you already have"):
        st.markdown(
            "For a state, you can also open [Geofabrik](https://download.geofabrik.de/), "
            "choose the state, and download the **shapefile** (`.shp.zip`). Upload that zip. "
            "A full state of local streets is too large, so the lab keeps main roads.\n\n"
            "Other files that work: GeoJSON, `.osm`, GraphML, GeoPackage, "
            "or a CSV with columns `source` and `target`."
        )
        st.write(
            "Intersections are where roads share a point. Bend points along one road are merged. "
            "A bridge drawn across another road, without a shared point, stays unconnected."
        )
    uploads = st.file_uploader(
        "Road file from OpenStreetMap",
        type=["osm", "geojson", "json", "xml", "graphml", "gpkg", "zip", "csv"],
        accept_multiple_files=True,
    )
    if st.button("Use this file", type="primary", disabled=not uploads):
        try:
            with st.spinner("Reading the road network…"):
                network = load_uploads(uploads)
        except NetworkLabError as exc:
            st.error(str(exc))
        else:
            _store_network(network, f"Loaded {network.title}: {network.n:,} intersections.")
            st.rerun()


def _network_summary(network: RoadNetwork) -> None:
    st.markdown(f"**{network.title}**  \n{network.kind_label} · {network.source}")
    if network.official_name:
        st.caption(network.official_name)
    intersections, segments, length, dropped = st.columns(4)
    intersections.metric("Intersections", f"{network.n:,}")
    segments.metric("Road segments", f"{network.m:,}")
    length.metric("Total road length", f"{to_miles(network.total_km):,.0f} mi")
    typical = (2 * network.m / network.n) if network.n else 0
    dropped.metric("Roads meeting, typical", f"{typical:.1f}")
    for note in network.notes:
        st.caption(note)
    with st.expander("Preview the roads", expanded=True):
        figure = preview_figure(network)
        _fit_image(
            figure_png(figure),
            f"Map of the road network for {network.title}, before centrality is calculated.",
        )
        plt.close(figure)
        if network.geographic:
            st.caption(
                "Each line is a road and each endpoint is an intersection. "
                "The axes are miles from the center of this network."
            )
        else:
            st.caption("These positions are a diagram. They are not miles on a map.")
    graphml = _graphml_bytes(network)
    file_cols = st.columns(3)
    file_cols[0].download_button(
        "Download this network (GraphML)",
        data=graphml,
        file_name=f"{_slug(network.title)}.graphml",
        mime="application/graphml+xml",
        help="Another student can upload this file instead of downloading the same place again.",
    )
    if network.geojson_bytes:
        file_cols[1].download_button(
            "Download roads (GeoJSON)",
            data=network.geojson_bytes,
            file_name="roads.geojson",
            mime="application/geo+json",
            help="The road edges, from graph_to_gdfs, saved as GeoJSON.",
        )
    if network.shapefile_bytes:
        file_cols[2].download_button(
            "Download roads (shapefile)",
            data=network.shapefile_bytes,
            file_name="roads_shapefile.zip",
            mime="application/zip",
            help="The road edges as a zipped shapefile. Unzip to get roads.shp.",
        )


def _step_calculate(network: RoadNetwork) -> None:
    st.radio(
        "How should distance be measured?",
        ["Unweighted", "Length-weighted"],
        horizontal=True,
        key="weight_choice",
        help="Unweighted: every road between intersections is one step. Length-weighted: distance is the road length in miles.",
    )
    weighted = st.session_state["weight_choice"] == "Length-weighted"
    if weighted:
        st.caption("Shortest paths will follow miles of road. A long highway counts as a long trip.")
    else:
        st.caption("Shortest paths count intersections. A long highway and a short block both count as one step.")

    mode = "exact"
    sample_size = 400
    if network.n > 8000:
        st.radio(
            "Betweenness calculation",
            ["Exact", "Faster estimate"],
            horizontal=True,
            key="between_mode",
        )
        mode = "estimate" if st.session_state["between_mode"] == "Faster estimate" else "exact"
        if mode == "estimate":
            upper = max(50, network.n - 1)
            st.slider(
                "Starting intersections in the estimate",
                min_value=50,
                max_value=min(2000, upper),
                step=50,
                key="sample_k",
                help="More starting intersections make a steadier estimate and take longer.",
            )
            sample_size = int(st.session_state["sample_k"])
            st.caption(
                f"The estimate uses {sample_size:,} random starting intersections and stays fixed "
                f"until you draw a new sample (sample {int(st.session_state['sample_seed'])}). "
                "Closeness and degree are always exact."
            )
            if st.button("Draw a new estimate sample"):
                st.session_state["sample_seed"] = int(st.session_state["sample_seed"]) + 1
                st.rerun()
        elif network.n > 40000:
            st.warning(
                "Exact betweenness on a network this large can take several minutes. "
                "The faster estimate is enough to see the pattern."
            )
        else:
            st.caption("Exact betweenness on this network usually takes under a minute.")
    else:
        st.caption("This network is small enough for an exact calculation. It usually takes a few seconds.")

    if st.button("Calculate degree, betweenness, and closeness", type="primary"):
        try:
            with st.spinner("Calculating centrality. Leave this tab open."):
                results = compute_centrality(
                    network.graph,
                    weighted=weighted,
                    betweenness_mode=mode,
                    sample_size=sample_size,
                    sample_seed=int(st.session_state["sample_seed"]),
                )
                frame = results_table(network.graph, results)
        except NetworkLabError as exc:
            st.error(str(exc))
        else:
            st.session_state["results"] = results
            st.session_state["frame"] = frame
            st.session_state["result_signature"] = _signature(
                network, weighted, mode, sample_size, int(st.session_state["sample_seed"])
            )


def _step_maps(network: RoadNetwork, results) -> None:
    frame: pd.DataFrame = st.session_state["frame"]
    distance, elapsed, mode = st.columns(3)
    unit = "miles along the shortest roads" if results.distance_unit == "miles" else "hops (one hop is one road segment)"
    distance.metric("Average shortest-path distance", f"{results.mean_distance:.1f}")
    distance.caption(unit)
    elapsed.metric("Calculation time", "<0.1 s" if results.seconds < 0.05 else f"{results.seconds:.1f} s")
    mode.metric(
        "Betweenness",
        "Estimate" if results.betweenness_mode == "estimate" else "Exact",
    )
    for note in results.notes:
        st.caption(note)

    place = network.title
    weight = _weight_label(results.weighted)
    figure_columns = st.columns(3)
    softened = False
    for column, measure in zip(figure_columns, ("closeness", "betweenness", "degree"), strict=True):
        with column:
            softened = _show_png(network, results, measure, place, weight) or softened
    if results.weighted:
        st.caption("These maps are length-weighted: distance is miles of road, not a count of blocks.")
    else:
        st.caption("These maps are unweighted: every road between two intersections is one step. Degree ignores length.")
    if softened:
        st.caption(
            "On the betweenness map, extreme highs were pulled in so the rest of the pattern is visible. "
            "Anything above the top of the color bar is drawn in the same red."
        )
    st.caption("Gray lines are the roads. Road geometries © OpenStreetMap contributors.")

    _explore_map(network, frame, results)
    _top_table(frame, st.session_state.get("measure", "closeness"), network.has_latlon)
    _lab_sheet(network, results, frame)


def _fit_image(png: bytes, alt: str) -> None:
    """Show a figure at its own shape, limited so the whole image stays on screen."""
    encoded = base64.b64encode(png).decode("ascii")
    st.markdown(
        f'<img alt="{html.escape(alt)}" src="data:image/png;base64,{encoded}" '
        'style="display:block;max-width:100%;max-height:46vh;width:auto;height:auto;margin:0 auto;" />',
        unsafe_allow_html=True,
    )


def _show_png(network: RoadNetwork, results, measure: str, place: str, weight: str) -> bool:
    values, left, colorbar, _column = _measure_bundle(results, measure, weight)
    vmin, vmax, softened = color_limits(values, "auto", measure)
    figure = centrality_figure(
        network,
        values,
        left_label=left,
        place_name=place,
        colorbar_label=colorbar,
        palette="jet",
        vmin=vmin,
        vmax=vmax,
        show_inset=False,
    )
    png = figure_png(figure)
    plt.close(figure)
    st.image(png, width="stretch")
    st.caption(MEASURE_TEXT[measure])
    st.download_button(
        f"Download {measure} (PNG)",
        data=png,
        file_name=f"{_slug(place)}_{measure}.png",
        mime="image/png",
        key=f"png_{measure}",
    )
    return softened


def _rank_column(measure: str) -> str:
    return {"degree": "roads_meeting", "betweenness": "betweenness", "closeness": "closeness"}[measure]


def _table_key(measure: str) -> str:
    return f"top_table_{measure}"


def _ranked_intersections(frame: pd.DataFrame, measure: str) -> pd.DataFrame:
    """Top intersections for the table. Row order is what a click selects."""
    column = _rank_column(measure)
    ranked = frame.sort_values(column, ascending=False).head(12).reset_index(drop=True)
    ranked.insert(0, "Rank", ranked.index + 1)
    return ranked.rename(
        columns={
            "intersection": "Intersection",
            "roads_meeting": "Roads meeting",
            "degree_centrality": "Degree centrality",
            "betweenness": "Betweenness",
            "closeness": "Closeness",
        }
    )


def _selected_intersection(ranked: pd.DataFrame, measure: str) -> dict | None:
    """The table row the student clicked, if that intersection can be mapped."""
    state = st.session_state.get(_table_key(measure))
    if not isinstance(state, dict):
        return None
    rows = (state.get("selection") or {}).get("rows") or []
    if not rows:
        return None
    index = int(rows[0])
    if index < 0 or index >= len(ranked):
        return None
    row = ranked.iloc[index]
    if pd.isna(row["latitude"]) or pd.isna(row["longitude"]):
        return None
    return {
        "node_id": row["node_id"],
        "name": str(row["Intersection"]),
        "lat": float(row["latitude"]),
        "lon": float(row["longitude"]),
    }


def _note_focus(focus: dict | None) -> None:
    """Tell the student when the map has moved to a newly selected intersection."""
    focus_id = None if focus is None else str(focus["node_id"])
    if focus_id == st.session_state.get("map_focus"):
        return
    st.session_state["map_focus"] = focus_id
    st.session_state["flash_left"] = 8 if focus is not None else 0
    if focus is not None:
        st.toast(f"The street map zoomed to {focus['name']}.")


def _top_table(frame: pd.DataFrame, measure: str, can_map: bool) -> None:
    ranked = _ranked_intersections(frame, measure)
    st.markdown("**Highest intersections**")
    if can_map:
        st.caption(
            "Click a row. The street map above zooms to that intersection and the point flashes for a few seconds. "
            "The flash uses the point's own centrality color."
        )
    if can_map and _selected_intersection(ranked, measure) is not None:
        if st.button("Show the whole network on the map"):
            st.session_state[_table_key(measure)] = {"selection": {"rows": []}}
            st.session_state["map_focus"] = None
            st.session_state["flash_left"] = 0
            st.rerun()
    st.dataframe(
        ranked,
        hide_index=True,
        width="stretch",
        on_select="rerun",
        selection_mode="single-row",
        key=_table_key(measure),
        column_order=[
            "Rank",
            "Intersection",
            "Roads meeting",
            "Degree centrality",
            "Betweenness",
            "Closeness",
        ],
        column_config={
            "Degree centrality": st.column_config.NumberColumn(format="%.4f"),
            "Betweenness": st.column_config.NumberColumn(format="%.4f"),
            "Closeness": st.column_config.NumberColumn(format="%.4f"),
        },
    )
    st.caption("Street names come from OpenStreetMap when the road has one.")
    csv = frame.sort_values(_rank_column(measure), ascending=False).to_csv(index=False)
    st.download_button(
        "Download the full table (CSV)",
        data=csv,
        file_name="centrality.csv",
        mime="text/csv",
    )


_MAP_CONFIG = {"scrollZoom": True, "displaylogo": False}


def _explore_map(network: RoadNetwork, frame: pd.DataFrame, results) -> None:
    st.selectbox(
        "Centrality",
        ["closeness", "betweenness", "degree"],
        format_func=lambda key: key.capitalize(),
        key="measure",
    )
    st.markdown("**Explore on a street map**")
    if not network.has_latlon:
        st.caption("This network has no longitude and latitude, so it cannot be placed on a street map.")
        return
    measure = st.session_state["measure"]
    _values, _left, colorbar, column = _measure_bundle(results, measure, _weight_label(results.weighted))
    ranked = _ranked_intersections(frame, measure)
    focus = _selected_intersection(ranked, measure)
    _note_focus(focus)
    plot_frame = frame.dropna(subset=["latitude", "longitude"]).copy()
    sampled = False
    if len(plot_frame) > 25000:
        keep = set()
        for col in ("roads_meeting", "betweenness", "closeness"):
            keep.update(plot_frame.nlargest(200, col).index)
        rest = plot_frame.index.difference(keep)
        need = 25000 - len(keep)
        chosen = rest.to_series().sample(need, random_state=0).index
        plot_frame = plot_frame.loc[list(keep) + list(chosen)]
        sampled = True
    center, zoom = _map_view(plot_frame)
    # Low values are drawn first. High values are drawn last, so they stay on top.
    plot_frame = plot_frame.sort_values(column, ascending=True, na_position="first")
    if focus is not None and int(st.session_state.get("flash_left", 0)) > 0:
        _flashing_map(plot_frame, column, colorbar, center, zoom, focus, sampled)
    else:
        _draw_street_map(plot_frame, column, colorbar, center, zoom, focus, sampled, pulse=False)


def _street_figure(plot_frame, column, colorbar, center, zoom, focus, pulse: bool):
    view_center = center
    view_zoom = zoom
    drawing = plot_frame
    if focus is not None:
        view_center = {"lat": focus["lat"], "lon": focus["lon"]}
        view_zoom = 16
        # Draw the selected intersection last so a neighbor does not cover its color.
        if "node_id" in plot_frame.columns:
            chosen = plot_frame["node_id"].astype(str) == str(focus["node_id"])
            if chosen.any():
                drawing = pd.concat([plot_frame.loc[~chosen], plot_frame.loc[chosen]])
    figure = px.scatter_map(
        drawing,
        lat="latitude",
        lon="longitude",
        color=column,
        hover_name="intersection",
        hover_data={
            "degree_centrality": ":.4f",
            "roads_meeting": True,
            "betweenness": ":.4f",
            "closeness": ":.4f",
            "latitude": False,
            "longitude": False,
            "node_id": False,
        },
        color_continuous_scale="Jet",
        center=view_center,
        zoom=view_zoom,
        height=640,
        map_style="open-street-map",
        labels={
            column: colorbar,
            "degree_centrality": "Degree centrality",
            "roads_meeting": "Roads meeting",
            "betweenness": "Betweenness",
            "closeness": "Closeness",
        },
    )
    figure.update_layout(
        margin={"l": 0, "r": 0, "t": 0, "b": 0},
        map={"center": view_center, "zoom": view_zoom, "bearing": 0, "pitch": 0},
        coloraxis_colorbar={"yanchor": "middle", "y": 0.5, "len": 0.7, "x": 1.01},
    )
    base = 7 if len(drawing) < 3000 else 4
    if focus is not None and pulse and "node_id" in drawing.columns:
        chosen = str(focus["node_id"])
        sizes = [base * 3 if str(node) == chosen else base for node in drawing["node_id"]]
        figure.update_traces(marker={"size": sizes})
    else:
        figure.update_traces(marker={"size": base})
    return figure


def _map_notes(sampled: bool, focus: dict | None) -> None:
    if focus is not None:
        st.caption(
            f"Centered on {focus['name']}. Drag to move the map. Scroll, or use the buttons at the top right, to zoom."
        )
    elif sampled:
        st.caption(
            "The street map shows a sample of intersections so the page stays responsive. "
            "Drag to move it, and scroll to zoom. Click a row in the table below to jump to that intersection."
        )
    else:
        st.caption(
            "Drag to move the map, and scroll to zoom. Hover a point to read its scores. "
            "Click a row in the table below and the map zooms to that intersection. The point flashes for a few seconds."
        )


def _draw_street_map(plot_frame, column, colorbar, center, zoom, focus, sampled: bool, pulse: bool) -> None:
    figure = _street_figure(plot_frame, column, colorbar, center, zoom, focus, pulse)
    st.plotly_chart(figure, width="stretch", config=_MAP_CONFIG, key="street_map")
    _map_notes(sampled, focus)


@st.fragment(run_every=0.4)
def _flashing_map(plot_frame, column, colorbar, center, zoom, focus, sampled: bool) -> None:
    """Pulse the selected point's own color, then leave the zoomed map still."""
    left = int(st.session_state.get("flash_left", 0))
    figure = _street_figure(
        plot_frame,
        column,
        colorbar,
        center,
        zoom,
        focus,
        pulse=left % 2 == 0,
    )
    st.plotly_chart(figure, width="stretch", config=_MAP_CONFIG, key="street_map_live")
    _map_notes(sampled, focus)
    if left <= 1:
        st.session_state["flash_left"] = 0
        st.rerun()
    st.session_state["flash_left"] = left - 1


def _map_view(frame: pd.DataFrame) -> tuple[dict[str, float], float]:
    """Center the camera on the road bounding box and zoom so those roads fill the map."""
    lat_min = float(frame["latitude"].min())
    lat_max = float(frame["latitude"].max())
    lon_min = float(frame["longitude"].min())
    lon_max = float(frame["longitude"].max())
    center = {"lat": (lat_min + lat_max) / 2.0, "lon": (lon_min + lon_max) / 2.0}
    lat_pad = max(lat_max - lat_min, 1e-4) * 0.08
    lon_pad = max(lon_max - lon_min, 1e-4) * 0.08
    lat_min -= lat_pad
    lat_max += lat_pad
    lon_min -= lon_pad
    lon_max += lon_pad

    def _lat_rad(lat: float) -> float:
        sine = min(max(math.sin(math.radians(lat)), -0.9999), 0.9999)
        return math.log((1.0 + sine) / (1.0 - sine)) / 2.0

    lat_fraction = max((_lat_rad(lat_max) - _lat_rad(lat_min)) / math.pi, 1e-9)
    lon_fraction = max((lon_max - lon_min) / 360.0, 1e-9)
    # The map is wide, and the color bar sits on the right of the drawing area.
    map_height = 600.0
    map_width = 1000.0

    def _zoom(pixels: float, fraction: float) -> float:
        return math.log2(pixels / 256.0 / fraction)

    zoom = min(_zoom(map_height, lat_fraction), _zoom(map_width, lon_fraction))
    return center, float(min(15.0, max(3.0, zoom)))


def _lab_sheet(network: RoadNetwork, results, frame: pd.DataFrame) -> None:
    st.markdown("**Lab answers**")
    st.write("Answer in your own words. Then download the package and turn it in.")
    st.text_input("Your name", key="student_name")
    st.markdown("**Name the top intersection**")
    st.caption(
        "Use the Degree centrality, Betweenness, and Closeness columns in the table above. "
        "If several intersections tie, name atleast one"
    )
    for key, prompt in IDENTIFY_QUESTIONS:
        st.text_input(prompt, key=key)
    st.markdown("**Where would you build it?**")
    for key, prompt in QUESTIONS:
        st.text_input(prompt, key=key)

    if st.button("Build the submission package"):
        with st.spinner("Drawing the three maps for the package…"):
            blob = _submission_zip(network, results, frame)
        st.session_state["bundle"] = blob
        st.session_state["bundle_for"] = network.token

    if st.session_state.get("bundle_for") == network.token and st.session_state.get("bundle"):
        st.download_button(
            "Download figures, table, and answers",
            data=st.session_state["bundle"],
            file_name=f"{_slug(network.title)}_lab.zip",
            mime="application/zip",
        )


def _submission_zip(network: RoadNetwork, results, frame: pd.DataFrame) -> bytes:
    place = network.title
    weight = _weight_label(results.weighted)
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        for measure in ("closeness", "betweenness", "degree"):
            values, left, colorbar, _column = _measure_bundle(results, measure, weight)
            vmin, vmax, _softened = color_limits(values, "auto", measure)
            figure = centrality_figure(
                network,
                values,
                left_label=left,
                place_name=place,
                colorbar_label=colorbar,
                palette="jet",
                vmin=vmin,
                vmax=vmax,
                show_inset=False,
            )
            archive.writestr(f"{measure}.png", figure_png(figure))
            plt.close(figure)
        archive.writestr("centrality.csv", frame.to_csv(index=False))
        archive.writestr("lab_report.txt", _report_text(network, results, frame))
        archive.writestr(f"{_slug(network.title)}.graphml", _graphml_bytes(network))
    return buffer.getvalue()


def _report_text(network: RoadNetwork, results, frame: pd.DataFrame) -> str:
    lines = [
        "Road network centrality lab",
        f"Student: {st.session_state.get('student_name', '').strip() or '(name not entered)'}",
        f"Place on the figure: {network.title}",
        f"Source: {network.source}",
        f"Roads: {network.kind_label}",
    ]
    if network.official_name:
        lines.append(f"OpenStreetMap boundary: {network.official_name}")
    if network.area_km2 is not None:
        lines.append(f"Boundary area: {to_square_miles(network.area_km2):,.0f} square miles")
    lines.extend(
        [
            f"Intersections: {network.n:,}",
            f"Road segments: {network.m:,}",
            f"Total road length: {to_miles(network.total_km):,.1f} miles",
            f"Disconnected intersections set aside: {network.dropped_nodes:,}",
            f"Distance: {_weight_label(results.weighted)}",
            f"Betweenness: {results.betweenness_mode}",
        ]
    )
    if results.sample_size:
        lines.append(f"Betweenness sample: {results.sample_size} starts, seed {results.sample_seed}")
    lines.append(
        f"Average shortest-path distance: {results.mean_distance:.2f} {results.distance_unit}"
    )
    lines.append("")
    lines.append("Highest intersections by closeness")
    top = frame.sort_values("closeness", ascending=False).head(8)
    for rank, row in enumerate(top.itertuples(index=False), start=1):
        lines.append(
            f"{rank}. {row.intersection}  "
            f"closeness {row.closeness:.4f}  betweenness {row.betweenness:.4f}  "
            f"roads meeting {row.roads_meeting}"
        )
    lines.append("")
    lines.append("Answers")
    numbered = list(enumerate(IDENTIFY_QUESTIONS + QUESTIONS, start=1))
    for number, (key, prompt) in numbered:
        lines.append(f"{number}. {prompt}")
        lines.append(st.session_state.get(key, "").strip() or "(blank)")
        lines.append("")
    return "\n".join(lines)


def _about() -> None:
    with st.expander("About this lab"):
        st.write(
            "Place names and road geometries come from OpenStreetMap, fetched with OSMnx. "
            "The calculation uses an undirected intersection graph: one-way restrictions are ignored, "
            "and a node exists where roads meet rather than at every bend. "
            "Degree, betweenness, and closeness use the standard normalized definitions. "
            "On a very large network, betweenness is estimated from a sample of starting intersections. "
            "Closeness and degree are still exact."
        )
        st.caption("Road data © OpenStreetMap contributors.")


def _measure_bundle(results, measure: str, weight: str):
    if measure == "degree":
        return results.degree_count, "Degree", "roads meeting", "roads_meeting"
    if measure == "betweenness":
        return results.betweenness, weight, "betweenness", "betweenness"
    return results.closeness, weight, "closeness", "closeness"


def _results_if_current(network: RoadNetwork):
    results = st.session_state.get("results")
    signature = st.session_state.get("result_signature")
    if results is None or signature is None:
        return None
    weighted = st.session_state.get("weight_choice", "Unweighted") == "Length-weighted"
    if network.n > 8000:
        mode = "estimate" if st.session_state.get("between_mode") == "Faster estimate" else "exact"
        sample_size = int(st.session_state.get("sample_k", 400))
    else:
        mode = "exact"
        sample_size = 400
    expected = _signature(
        network, weighted, mode, sample_size, int(st.session_state.get("sample_seed", 42))
    )
    if signature != expected:
        return None
    return results


def _signature(network, weighted: bool, mode: str, sample_size: int, seed: int):
    if mode != "estimate":
        return (network.token, bool(weighted), "exact")
    return (network.token, bool(weighted), "estimate", int(sample_size), int(seed))


def _store_network(network: RoadNetwork, message: str) -> None:
    st.session_state["network"] = network
    st.session_state["results"] = None
    st.session_state["frame"] = None
    st.session_state["result_signature"] = None
    st.session_state.pop("bundle", None)
    st.session_state.pop("bundle_for", None)
    st.session_state["flash"] = message


def _sync_network_defaults() -> None:
    if "place_query" not in st.session_state:
        st.session_state["place_query"] = ""
    if "sample_seed" not in st.session_state:
        st.session_state["sample_seed"] = 42
    if "weight_choice" not in st.session_state:
        st.session_state["weight_choice"] = "Unweighted"
    if "measure" not in st.session_state:
        st.session_state["measure"] = "closeness"
    network = st.session_state.get("network")
    if network is None or st.session_state.get("title_for") == network.token:
        return
    st.session_state["figure_title"] = network.title
    st.session_state["title_for"] = network.token
    st.session_state["between_mode"] = "Exact" if network.n <= 40000 else "Faster estimate"
    st.session_state["sample_k"] = int(min(400, max(50, network.n // 10)))


def _apply_pending_query() -> None:
    pending = st.session_state.pop("pending_query", None)
    if pending:
        st.session_state["place_query"] = pending
        st.session_state.pop("place_info", None)


def _queue_query(name: str) -> None:
    st.session_state["pending_query"] = name


def _graphml_bytes(network: RoadNetwork) -> bytes:
    cache = st.session_state.setdefault("graphml_cache", {})
    if network.token not in cache:
        cache.clear()
        cache[network.token] = network_to_graphml_bytes(network)
    return cache[network.token]


def _weight_label(weighted: bool) -> str:
    return "Length-weighted" if weighted else "Unweighted"


def _slug(text: str) -> str:
    cleaned = "".join(character.lower() if character.isalnum() else "_" for character in text)
    parts = [part for part in cleaned.split("_") if part]
    return "_".join(parts)[:60] or "network"


if __name__ == "__main__":
    main()
