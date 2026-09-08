-- ── Warehouse schema migration V1 ─────────────────────────────────────────────
SET search_path = warehouse;

CREATE TABLE IF NOT EXISTS warehouses (
    id              VARCHAR(36)     PRIMARY KEY DEFAULT gen_random_uuid()::text,
    code            VARCHAR(20)     NOT NULL UNIQUE,
    name            VARCHAR(200)    NOT NULL,
    street          VARCHAR(255),
    city            VARCHAR(100),
    state           VARCHAR(100),
    country         VARCHAR(100),
    postal_code     VARCHAR(20),
    lat             NUMERIC(9,6),
    lng             NUMERIC(9,6),
    capacity_m3     NUMERIC(12,3)   NOT NULL,
    used_m3         NUMERIC(12,3)   NOT NULL DEFAULT 0,
    active          BOOLEAN         NOT NULL DEFAULT TRUE,
    contact_email   VARCHAR(255),
    contact_phone   VARCHAR(50),
    created_at      TIMESTAMPTZ     NOT NULL DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS warehouse_capabilities (
    warehouse_id            VARCHAR(36)     NOT NULL REFERENCES warehouses(id) ON DELETE CASCADE,
    capability              VARCHAR(50)     NOT NULL,
    PRIMARY KEY (warehouse_id, capability)
);

CREATE TABLE IF NOT EXISTS dock_schedules (
    id              VARCHAR(36)     PRIMARY KEY DEFAULT gen_random_uuid()::text,
    warehouse_id    VARCHAR(36)     NOT NULL REFERENCES warehouses(id) ON DELETE CASCADE,
    dock_number     INT             NOT NULL,
    date            DATE            NOT NULL,
    start_time      TIME            NOT NULL,
    end_time        TIME            NOT NULL,
    shipment_id     VARCHAR(36),
    type            VARCHAR(20)     NOT NULL DEFAULT 'PICKUP',  -- PICKUP | DELIVERY
    status          VARCHAR(20)     NOT NULL DEFAULT 'AVAILABLE'
);

CREATE INDEX IF NOT EXISTS idx_warehouses_active        ON warehouses(active);
CREATE INDEX IF NOT EXISTS idx_dock_warehouse_date      ON dock_schedules(warehouse_id, date);
CREATE INDEX IF NOT EXISTS idx_dock_shipment            ON dock_schedules(shipment_id);

-- Seed one warehouse
INSERT INTO warehouses (id, code, name, city, state, country, postal_code, lat, lng, capacity_m3, active)
VALUES
  ('wh-001', 'CHI-01', 'Chicago Central', 'Chicago', 'IL', 'US', '60601', 41.8781, -87.6298, 50000, TRUE),
  ('wh-002', 'NYC-01', 'New York East',   'New York', 'NY', 'US', '10001', 40.7128, -74.0060, 35000, TRUE),
  ('wh-003', 'LAX-01', 'Los Angeles West','Los Angeles','CA','US', '90001', 34.0522,-118.2437, 45000, TRUE)
ON CONFLICT (id) DO NOTHING;
