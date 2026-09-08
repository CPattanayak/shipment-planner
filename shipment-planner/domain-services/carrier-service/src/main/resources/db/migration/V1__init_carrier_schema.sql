-- ── Carrier schema migration V1 ───────────────────────────────────────────────
SET search_path = carrier;

CREATE TABLE IF NOT EXISTS carriers (
    id                      VARCHAR(36)     PRIMARY KEY DEFAULT gen_random_uuid()::text,
    name                    VARCHAR(200)    NOT NULL,
    code                    VARCHAR(20)     NOT NULL UNIQUE,
    active                  BOOLEAN         NOT NULL DEFAULT TRUE,
    contact_email           VARCHAR(255),
    api_endpoint            VARCHAR(500),
    max_weight_kg           NUMERIC(10,2)   NOT NULL DEFAULT 1000,
    max_volume_m3           NUMERIC(10,3)   NOT NULL DEFAULT 10,
    hazardous_allowed       BOOLEAN         NOT NULL DEFAULT FALSE,
    temperature_controlled  BOOLEAN         NOT NULL DEFAULT FALSE,
    express_available       BOOLEAN         NOT NULL DEFAULT FALSE,
    overnight_available     BOOLEAN         NOT NULL DEFAULT FALSE,
    same_day_available      BOOLEAN         NOT NULL DEFAULT FALSE,
    tracking_available      BOOLEAN         NOT NULL DEFAULT TRUE,
    on_time_delivery_rate   NUMERIC(5,4)    NOT NULL DEFAULT 0.95,
    average_delay_hours     NUMERIC(6,2)    NOT NULL DEFAULT 0,
    damage_rate             NUMERIC(6,5)    NOT NULL DEFAULT 0.001,
    customer_satisfaction   NUMERIC(3,2)    NOT NULL DEFAULT 4.5,
    total_shipments         INT             NOT NULL DEFAULT 0,
    created_at              TIMESTAMPTZ     NOT NULL DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS carrier_modes (
    carrier_id  VARCHAR(36)     NOT NULL REFERENCES carriers(id) ON DELETE CASCADE,
    mode        VARCHAR(20)     NOT NULL,
    PRIMARY KEY (carrier_id, mode)
);

CREATE TABLE IF NOT EXISTS carrier_service_areas (
    carrier_id      VARCHAR(36)     NOT NULL REFERENCES carriers(id) ON DELETE CASCADE,
    service_area    VARCHAR(100)    NOT NULL,
    PRIMARY KEY (carrier_id, service_area)
);

CREATE TABLE IF NOT EXISTS carrier_bookings (
    id                  VARCHAR(36)     PRIMARY KEY DEFAULT gen_random_uuid()::text,
    carrier_id          VARCHAR(36)     NOT NULL REFERENCES carriers(id),
    shipment_id         VARCHAR(36)     NOT NULL,
    confirmed_at        TIMESTAMPTZ     NOT NULL DEFAULT NOW(),
    pickup_window       VARCHAR(100),
    estimated_delivery  TIMESTAMPTZ,
    tracking_number     VARCHAR(100),
    service_level       VARCHAR(30)
);

CREATE INDEX IF NOT EXISTS idx_carriers_active      ON carriers(active);
CREATE INDEX IF NOT EXISTS idx_bookings_shipment    ON carrier_bookings(shipment_id);
CREATE INDEX IF NOT EXISTS idx_bookings_carrier     ON carrier_bookings(carrier_id);
