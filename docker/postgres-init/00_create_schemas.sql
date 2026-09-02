-- ─────────────────────────────────────────────────────────────────────────────
-- One PostgreSQL database, four isolated schemas – one per domain service.
-- Each service connects with its own user scoped to its own schema.
-- ─────────────────────────────────────────────────────────────────────────────

-- ── Schemas ──────────────────────────────────────────────────────────────────
CREATE SCHEMA IF NOT EXISTS shipment;
CREATE SCHEMA IF NOT EXISTS route;
CREATE SCHEMA IF NOT EXISTS carrier;
CREATE SCHEMA IF NOT EXISTS warehouse;

-- ── Per-service roles ─────────────────────────────────────────────────────────
DO $$
BEGIN
  -- shipment_svc
  IF NOT EXISTS (SELECT FROM pg_roles WHERE rolname = 'shipment_svc') THEN
    CREATE ROLE shipment_svc LOGIN PASSWORD 'shipment_pass';
  END IF;
  -- route_svc
  IF NOT EXISTS (SELECT FROM pg_roles WHERE rolname = 'route_svc') THEN
    CREATE ROLE route_svc LOGIN PASSWORD 'route_pass';
  END IF;
  -- carrier_svc
  IF NOT EXISTS (SELECT FROM pg_roles WHERE rolname = 'carrier_svc') THEN
    CREATE ROLE carrier_svc LOGIN PASSWORD 'carrier_pass';
  END IF;
  -- warehouse_svc
  IF NOT EXISTS (SELECT FROM pg_roles WHERE rolname = 'warehouse_svc') THEN
    CREATE ROLE warehouse_svc LOGIN PASSWORD 'warehouse_pass';
  END IF;
END
$$;

-- ── Grant privileges ──────────────────────────────────────────────────────────
-- shipment
GRANT USAGE, CREATE ON SCHEMA shipment TO shipment_svc;
ALTER ROLE shipment_svc SET search_path = shipment;

-- route
GRANT USAGE, CREATE ON SCHEMA route TO route_svc;
ALTER ROLE route_svc SET search_path = route;

-- carrier
GRANT USAGE, CREATE ON SCHEMA carrier TO carrier_svc;
ALTER ROLE carrier_svc SET search_path = carrier;

-- warehouse
GRANT USAGE, CREATE ON SCHEMA warehouse TO warehouse_svc;
ALTER ROLE warehouse_svc SET search_path = warehouse;
