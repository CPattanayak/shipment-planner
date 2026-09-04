# ── Build stage ───────────────────────────────────────────────────────────────
FROM eclipse-temurin:17-jdk-alpine AS build
WORKDIR /workspace

COPY pom.xml .
COPY ../../pom.xml /parent-pom.xml

# Pull dependencies first (layer cache)
RUN --mount=type=cache,target=/root/.m2 \
    mvn -f /parent-pom.xml install -N -q 2>/dev/null || true

COPY src src
RUN --mount=type=cache,target=/root/.m2 \
    mvn package -DskipTests -q

# ── Runtime stage ─────────────────────────────────────────────────────────────
FROM eclipse-temurin:17-jre-alpine
WORKDIR /app

RUN addgroup -S spring && adduser -S spring -G spring
USER spring:spring

COPY --from=build /workspace/target/*.jar app.jar

EXPOSE 8082
ENTRYPOINT ["java", \
  "-XX:MaxRAMPercentage=75", \
  "-Djava.security.egd=file:/dev/./urandom", \
  "-jar", "app.jar"]
