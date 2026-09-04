-- ── Shipment schema migration V1 ──────────────────────────────────────────────
SET search_path = shipment;

CREATE TABLE IF NOT EXISTS shipments (
    id                  VARCHAR(36)     PRIMARY KEY DEFAULT gen_random_uuid()::text,
    tracking_number     VARCHAR(50)     NOT NULL UNIQUE,
    status              VARCHAR(30)     NOT NULL,
    priority            VARCHAR(20)     NOT NULL,
    origin_warehouse_id VARCHAR(36)     NOT NULL,
    dest_street         VARCHAR(255),
    dest_city           VARCHAR(100),
    dest_state          VARCHAR(100),
    dest_country        VARCHAR(100),
    dest_postal_code    VARCHAR(20),
    dest_lat            NUMERIC(9,6),
    dest_lng            NUMERIC(9,6),
    total_weight        NUMERIC(12,3),
    total_volume        NUMERIC(12,3),
    total_value         NUMERIC(14,2),
    carrier_id          VARCHAR(36),
    route_id            VARCHAR(36),
    estimated_delivery  TIMESTAMPTZ,
    actual_delivery     TIMESTAMPTZ,
    scheduled_pickup    TIMESTAMPTZ,
    special_instructions TEXT,
    created_at          TIMESTAMPTZ     NOT NULL DEFAULT NOW(),
    updated_at          TIMESTAMPTZ     NOT NULL DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS shipment_items (
    id                      VARCHAR(36)     PRIMARY KEY DEFAULT gen_random_uuid()::text,
    shipment_id             VARCHAR(36)     NOT NULL REFERENCES shipments(id) ON DELETE CASCADE,
    sku                     VARCHAR(100)    NOT NULL,
    description             VARCHAR(255),
    quantity                INT             NOT NULL CHECK (quantity > 0),
    weight                  NUMERIC(10,3)   NOT NULL,
    volume                  NUMERIC(10,3)   NOT NULL,
    value                   NUMERIC(12,2)   NOT NULL,
    hazardous               BOOLEAN         NOT NULL DEFAULT FALSE,
    temperature_controlled  BOOLEAN         NOT NULL DEFAULT FALSE,
    fragile                 BOOLEAN         NOT NULL DEFAULT FALSE
);

CREATE TABLE IF NOT EXISTS status_events (
    id          VARCHAR(36)     PRIMARY KEY DEFAULT gen_random_uuid()::text,
    shipment_id VARCHAR(36)     NOT NULL REFERENCES shipments(id) ON DELETE CASCADE,
    status      VARCHAR(30)     NOT NULL,
    timestamp   TIMESTAMPTZ     NOT NULL DEFAULT NOW(),
    location    VARCHAR(255),
    notes       VARCHAR(1000)
);

CREATE INDEX IF NOT EXISTS idx_shipments_status         ON shipments(status);
CREATE INDEX IF NOT EXISTS idx_shipments_carrier        ON shipments(carrier_id);
CREATE INDEX IF NOT EXISTS idx_shipments_warehouse      ON shipments(origin_warehouse_id);
CREATE INDEX IF NOT EXISTS idx_shipment_items_shipment  ON shipment_items(shipment_id);
CREATE INDEX IF NOT EXISTS idx_status_events_shipment   ON status_events(shipment_id);
