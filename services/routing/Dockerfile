# The district's own routing engine (spec sections 6 and 7): GraphHopper,
# with a school-bus profile whose turn costs prefer right turns over lefts
# and never U-turn outside an approved turnaround. See docs/routing-engine.md.
FROM eclipse-temurin:21.0.12_8-jre-noble

ARG GRAPHHOPPER_VERSION=11.1
# Maven Central's published SHA-256 for that jar; the build fails on any other.
ADD --checksum=sha256:8462f758d9ea49edaded557cec5c687a0a24f004ec371cd4daaeb0534824ea33 \
    https://repo1.maven.org/maven2/com/graphhopper/graphhopper-web/${GRAPHHOPPER_VERSION}/graphhopper-web-${GRAPHHOPPER_VERSION}.jar \
    /opt/graphhopper/graphhopper-web.jar

COPY config.yml /opt/graphhopper/config.yml
COPY custom_models/ /opt/graphhopper/custom_models/
# The demo district's roads (© OpenStreetMap contributors, ODbL; see
# data/README.md). A real district mounts its own region's extract and
# points GH_MAP_FILE at it.
COPY data/demo-houston.osm.pbf /opt/graphhopper/maps/demo-houston.osm.pbf

RUN useradd --system --home-dir /var/lib/graphhopper --create-home graphhopper \
    && chmod a+r /opt/graphhopper/graphhopper-web.jar
USER graphhopper
WORKDIR /var/lib/graphhopper

ENV GH_MAP_FILE=/opt/graphhopper/maps/demo-houston.osm.pbf \
    GH_GRAPH_DIR=/var/lib/graphhopper/graph-cache \
    JAVA_OPTS="-Xms256m -Xmx1g"

EXPOSE 8989
# The graph is built from the map on first start (about a minute for the
# demo area) and kept in GH_GRAPH_DIR; delete that folder after changing
# the map.
ENTRYPOINT ["sh", "-c", "exec java $JAVA_OPTS -Ddw.graphhopper.datareader.file=\"$GH_MAP_FILE\" -Ddw.graphhopper.graph.location=\"$GH_GRAPH_DIR\" -jar /opt/graphhopper/graphhopper-web.jar server /opt/graphhopper/config.yml"]
