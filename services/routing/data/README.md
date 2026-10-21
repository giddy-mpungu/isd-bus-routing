# Map data

`demo-houston.osm.pbf` holds the drivable roads and turn restrictions within
about 12 km of the fictional demo district, in central Houston (latitude
29.65 to 29.865, longitude -95.50 to -95.27), as they were in OpenStreetMap
on 21 October 2026.

Map data © OpenStreetMap contributors, available under the Open Database
License (ODbL) 1.0: https://www.openstreetmap.org/copyright. This extract
is a Derivative Database under the ODbL and is shared under the same
licence. Editors' names, ids and edit history were left out.

How it was made: `../tools/overpass.ql` downloaded with the Overpass API,
then `python -P ../tools/make_extract.py demo.osm demo-houston.osm.pbf`.

A real district uses its own region's extract, for example a state file
from https://download.geofabrik.de, mounted into the routing container
(docs/routing-engine.md).
