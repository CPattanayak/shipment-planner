-- ── Route schema migration V1 ─────────────────────────────────────────────────
SET search_path = route;

CREATE TABLE IF NOT EXISTS routes (
    id                      VARCHAR(36)     PRIMARY KEY DEFAULT gen_random_uuid()::text,
    name                    VARCHAR(200)    NOT NULL,
    origin_warehouse_id     VARCHAR(36)     NOT NULL,
    destination_postal_code VARCHAR(20)     NOT NULL,
    status                  VARCHAR(20)     NOT NULL DEFAULT 'ACTIVE',
    transport_mode          VARCHAR(20)     NOT NULL,
    total_distance_km       NUMERIC(10,2)   NOT NULL,
    estimated_duration_hours NUMERIC(8,2)   NOT NULL,
    cost_per_kg             NUMERIC(10,4)   NOT NULL,
    max_weight_kg           NUMERIC(10,2)   NOT NULL,
    max_volume_m3           NUMERIC(10,3)   NOT NULL,
    hazardous_allowed       BOOLEAN         NOT NULL DEFAULT FALSE,
    temperature_controlled  BOOLEAN         NOT NULL DEFAULT FALSE,
    max_item_value_usd      NUMERIC(14,2),
    created_at              TIMESTAMPTZ     NOT NULL DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS route_countries (
    route_id    VARCHAR(36)     NOT NULL REFERENCES routes(id) ON DELETE CASCADE,
    country     VARCHAR(10)     NOT NULL,
    PRIMARY KEY (route_id, country)
);

CREATE TABLE IF NOT EXISTS route_carriers (
    route_id    VARCHAR(36)     NOT NULL REFERENCES routes(id) ON DELETE CASCADE,
    carrier_id  VARCHAR(36)     NOT NULL,
    PRIMARY KEY (route_id, carrier_id)
);

CREATE TABLE IF NOT EXISTS waypoints (
    id                  VARCHAR(36)     PRIMARY KEY DEFAULT gen_random_uuid()::text,
    route_id            VARCHAR(36)     NOT NULL REFERENCES routes(id) ON DELETE CASCADE,
    sequence            INT             NOT NULL,
    location            VARCHAR(255)    NOT NULL,
    lat                 NUMERIC(9,6),
    lng                 NUMERIC(9,6),
    estimated_arrival   VARCHAR(50),
    type                VARCHAR(20)     NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_routes_warehouse   ON routes(origin_warehouse_id);
CREATE INDEX IF NOT EXISTS idx_routes_postal      ON routes(destination_postal_code);
CREATE INDEX IF NOT EXISTS idx_routes_status      ON routes(status);
CREATE INDEX IF NOT EXISTS idx_waypoints_route    ON waypoints(route_id, sequence);
