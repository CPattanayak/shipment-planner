# ── Build stage ───────────────────────────────────────────────────────────────
FROM maven:3.9-eclipse-temurin-17-alpine AS build
WORKDIR /workspace

COPY pom.xml parent-pom.xml
COPY domain-services/carrier-service/pom.xml pom.xml

RUN --mount=type=cache,target=/root/.m2 \
    mvn -f parent-pom.xml install -N -q 2>/dev/null || true && \
    mvn dependency:go-offline -q 2>/dev/null || true

COPY domain-services/carrier-service/src src

RUN --mount=type=cache,target=/root/.m2 \
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
