# Road network centrality

You will not write code. Open the lab page your instructor gives you (it looks like a normal website).

You are going to download a real road network and make three maps. Each map colors intersections by a different idea of "important."

## Steps

1. Under **Get a road network**, leave the choice on **Download with OSMnx**.
2. Type a place, for example `Newark, Delaware, USA`, click **Find this place**, then choose **Which roads?** The page lists what each choice downloads:
   - **All drivable streets** — public roads a car can use, from interstates down to neighborhood streets. This is `graph_from_place(place, network_type="drive")`.
   - **Main roads, including secondary** — interstates, other major highways, primary roads, and secondary roads, including ramps.
   - **Highways and primary roads only** — interstates, other major highways, and primary roads, including ramps.
   Then click **Download roads**.
3. After it loads, you can save **roads.geojson** and the zipped shapefile (`roads.shp` inside the zip).
4. If the download times out, switch to **Load a file from OpenStreetMap**. Open [Overpass Turbo](https://overpass-turbo.eu), click **Wizard**, paste a line, and click **build and run**.
   - A town or city: `highway=* in "Newark, Delaware"`
   - A big city or a state: `highway~"motorway|trunk|primary|secondary" in "Delaware"`
   Then **Export → GeoJSON** or **raw OSM data**, upload that file, and click **Use this file**.
5. Look at the preview. Lines are roads. Ends of lines are intersections. The axes are miles from the center of the network.
6. Leave distance on **Unweighted** and click **Calculate**.
7. Three maps appear in one row: closeness, betweenness, and degree. Warm colors are high. Cool colors are low. Gray lines are the roads.
8. Switch distance to **Length-weighted**, calculate again, and compare the closeness map.
9. Above **Explore on a street map**, choose a centrality and hover an intersection to read its name. Drag the map to move it, and scroll to zoom. In the table under the map, click a row: the map zooms to that intersection and the point flashes for a few seconds. The point keeps its color. Hover a point to read degree centrality, betweenness, and closeness.
10. Answer the questions, then download the submission package.

A whole state can also come from [Geofabrik](https://download.geofabrik.de/) as a shapefile zip. Upload the zip. The lab keeps main roads when the file is huge.

## The three measures

**Degree.** How many roads meet at this intersection. A dead end is low. A junction of several streets is high. Length does not matter.

**Betweenness.** How often this intersection is on a shortest path between other intersections. Bridges and the only road between two neighborhoods score high. A cul-de-sac scores near zero, because almost nobody has to pass through it.

**Closeness.** How near this intersection is to all the others. The middle of the network scores high. The edge of town scores low.

**Unweighted** pretends every block is one step. **Length-weighted** uses the real length of the road. Degree is the same either way.

Bigger networks have smaller closeness numbers, because a typical trip passes more intersections. Compare the pattern (where the warm colors are), not the raw number, when you look at two cities of different sizes.

## Questions

1. Which intersection has the highest degree centrality?
2. Which intersection has the highest betweenness?
3. Which intersection has the highest closeness?
4. A city can build one fire station and wants a short trip to a typical intersection. Where on your map would you put the station?
5. A town can build one rest stop for people traveling between other places. Where on your map would you put it?
6. A city can build one roundabout and wants it where the most roads already meet, so each of those roads gets an entrance. Where on your map would you put it?

For questions 1–3, use the table on the page. If several intersections tie, name one and say that others tie.

## What to turn in

The zip from **Download figures, table, and answers**. It contains the three maps, the table of scores, and your answers.
