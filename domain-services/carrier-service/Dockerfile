# ── Build stage ───────────────────────────────────────────────────────────────
FROM maven:3.9-eclipse-temurin-17-alpine AS build
WORKDIR /workspace

COPY pom.xml parent-pom.xml
COPY domain-services/carrier-service/pom.xml pom.xml

# Pre-fetch dependencies. Best-effort — suppress only this step's failures.
RUN --mount=type=cache,target=/root/.m2 \
    mvn dependency:go-offline -q || true

COPY domain-services/carrier-service/src src

# Build: clear only the cached negative entry for the parent POM (stale from
# a previous failed resolution attempt), install it from the local file, then
# package. Targeted rm avoids the network storm that -U would cause.
RUN --mount=type=cache,target=/root/.m2 \
    rm -rf /root/.m2/repository/com/shipmentplanner/shipment-planner-parent && \
    mvn -f parent-pom.xml install -N -q && \
    mvn package -DskipTests -q

# ── Runtime stage ─────────────────────────────────────────────────────────────
FROM eclipse-temurin:17-jre-alpine
WORKDIR /app

RUN addgroup -S spring && adduser -S spring -G spring
USER spring:spring

COPY --from=build /workspace/target/*.jar app.jar

EXPOSE 8083
ENTRYPOINT ["java", \
  "-XX:MaxRAMPercentage=75", \
  "-Djava.security.egd=file:/dev/./urandom", \
  "-jar", "app.jar"]
