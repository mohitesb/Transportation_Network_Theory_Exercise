# Road network centrality lab

A browser exercise for students who are not writing code. They download a city, county, or state road network — or upload one — and map **degree**, **betweenness**, and **closeness**.

The map matches the usual class figure: every intersection is a point colored by the measure, gray lines are the roads, and the axes are miles from the center of the network.

## Start the lab

**New computer, nothing installed?** Follow [SETUP.md](SETUP.md). It covers installing Python, getting the files, creating a virtual environment, and installing the libraries on Windows, macOS, and Linux.

If you already have Python 3.11 or 3.12:

```bash
python -m venv .venv
source .venv/bin/activate        # Windows: .venv\Scripts\Activate.ps1
python -m pip install -r requirements.txt
python -m streamlit run app.py
```

Open the address it prints, usually http://localhost:8501. Students only use that page.

`scripts/start_lab.sh` (macOS/Linux) and `scripts/start_lab.bat` (Windows) do the same thing.

To confirm the install without opening the browser:

```bash
python scripts/check_lab.py
```

## What students do

1. Choose **Download with OSMnx**. Type a place, for example Newark, Delaware, USA, and download. That call is `graph_from_place(place, network_type="drive")`. The page then offers the roads as GeoJSON and as a zipped shapefile.
2. If that download times out, choose **Load a file from OpenStreetMap**. In [Overpass Turbo](https://overpass-turbo.eu), use the Wizard (`highway=* in "Newark, Delaware"` for a city, or main roads only for Delaware), then **Export → GeoJSON** or **raw OSM data**, and upload the file. A Geofabrik `.shp.zip` works too; a huge state extract is reduced to main roads.
3. Leave distance on **Unweighted** for the first map. Calculate. The closeness map is the one that looks like a warm center and a cool edge.
4. The page shows the closeness, betweenness, and degree figures. Switch distance to **Length-weighted** and calculate again. Above the street map, choose which centrality to explore. Drag to pan and scroll to zoom. Clicking a row in the table under the map zooms to that intersection and flashes the point for a few seconds, still in its centrality color. Hovering a point lists degree centrality as well as the other scores.
5. Answer the questions on the page and download the submission package (three PNGs, the table, and the answers). Students name the intersections with the highest degree centrality, betweenness, and closeness, then say where they would put a fire station, a rest stop for people traveling between other places, and a roundabout where the most roads already meet.

Hand out [STUDENT_GUIDE.md](STUDENT_GUIDE.md) if you want the questions on paper.

## Road class and network size

| Place | Use | What is downloaded |
| --- | --- | --- |
| Town or city, under about 580 square miles | All drivable streets | Public roads a car can use, from interstates down to neighborhood streets (`network_type="drive"`). Driveways, parking-lot aisles, footpaths, and bike paths stay out. |
| County or large metro | Main roads, including secondary | Interstates, other major highways, primary roads, and secondary roads, including ramps. |
| State | Highways and primary roads | Interstates, other major highways, and primary roads, including ramps. Choose main roads when you also want secondary streets. |

Local streets for a whole state are blocked. A state download can take several minutes. The roads are cached in `Data/osm_cache`, so the next request for the same place on that computer is much faster.

Exact betweenness is used up to about 40,000 intersections. Above that, the page estimates betweenness from a fixed sample of starting intersections and says so on the figure page. Closeness and degree stay exact. The sample does not change until the student asks for a new one, so a write-up does not flicker between refreshes.

An instructor can download once, click **Download this network (GraphML)**, and have the class upload that file. That avoids thirty identical requests to the OpenStreetMap servers.

## What the numbers mean

The graph is undirected. A node is an intersection or a dead end, not every bend in a road. One-way streets are ignored.

- **Degree** is the number of roads that meet. Degree centrality divides that count by (intersections − 1). The map colors the count, because 3 or 4 is easier to read than 0.0002.
- **Betweenness** and **closeness** use the standard normalized definitions (the same ones NetworkX documents). Unweighted distance counts each road segment as one step. Length-weighted distance uses miles along the roads. Scaling every length leaves the shortest paths in the same order, so betweenness stays on the same 0–1 scale. Closeness uses those lengths, so its numbers are in miles.
- The average shortest-path distance on the page is the mean, over intersections, of the mean distance to the others.

## Credits

Road geometries are © OpenStreetMap contributors, retrieved with [OSMnx](https://osmnx.readthedocs.io/). Calculations use igraph and NetworkX.
