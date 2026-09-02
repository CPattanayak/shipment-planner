-- ── V3: Fix bad enum values written by V2 + ensure all seed rows exist ────────
-- V2 used 'GROUND' (invalid TransportMode) and 'WAYPOINT' (invalid WaypointType).
-- This migration corrects them and upserts any missing seed rows.
SET search_path = route;

-- Fix transport_mode values ───────────────────────────────────────────────────
UPDATE routes SET transport_mode = 'ROAD'
WHERE  transport_mode = 'GROUND';

-- Fix waypoint type values ────────────────────────────────────────────────────
UPDATE waypoints SET type = 'TRANSIT'
WHERE  type = 'WAYPOINT';

-- Upsert seed routes (idempotent — ON CONFLICT DO UPDATE keeps them current) ──

-- ─── From Chicago (wh-001) ───────────────────────────────────────────────────
INSERT INTO routes (id, name, origin_warehouse_id, destination_postal_code,
                    status, transport_mode,
                    total_distance_km, estimated_duration_hours,
                    cost_per_kg, max_weight_kg, max_volume_m3,
                    hazardous_allowed, temperature_controlled)
VALUES
  ('rt-001-nyc',  'CHI→NYC (road)',  'wh-001', '10001', 'ACTIVE', 'ROAD',  1370, 24, 0.0420, 20000, 80.0, FALSE, FALSE),
  ('rt-001-lax',  'CHI→LAX (road)',  'wh-001', '90001', 'ACTIVE', 'ROAD',  3240, 48, 0.0390, 20000, 80.0, FALSE, FALSE),
  ('rt-001-dal',  'CHI→DAL (road)',  'wh-001', '75201', 'ACTIVE', 'ROAD',  1500, 26, 0.0410, 18000, 72.0, FALSE, FALSE),
  ('rt-001-mia',  'CHI→MIA (road)',  'wh-001', '33101', 'ACTIVE', 'ROAD',  2200, 38, 0.0430, 18000, 72.0, FALSE, FALSE),
  ('rt-001-sea',  'CHI→SEA (road)',  'wh-001', '98101', 'ACTIVE', 'ROAD',  3300, 52, 0.0400, 18000, 72.0, FALSE, FALSE),
  ('rt-001-atl',  'CHI→ATL (road)',  'wh-001', '30301', 'ACTIVE', 'ROAD',  1150, 20, 0.0410, 18000, 72.0, FALSE, FALSE),
  ('rt-001-bos',  'CHI→BOS (road)',  'wh-001', '02101', 'ACTIVE', 'ROAD',  1670, 28, 0.0425, 18000, 72.0, FALSE, FALSE),
  ('rt-001-nyc-a','CHI→NYC (air)',   'wh-001', '10001', 'ACTIVE', 'AIR',   1370,  4, 0.1800, 10000, 40.0, FALSE, TRUE),
  ('rt-001-lax-a','CHI→LAX (air)',   'wh-001', '90001', 'ACTIVE', 'AIR',   3240,  5, 0.1750, 10000, 40.0, FALSE, TRUE)
ON CONFLICT (id) DO UPDATE SET
    transport_mode = EXCLUDED.transport_mode,
    name           = EXCLUDED.name;

-- ─── From New York (wh-002) ──────────────────────────────────────────────────
INSERT INTO routes (id, name, origin_warehouse_id, destination_postal_code,
                    status, transport_mode,
                    total_distance_km, estimated_duration_hours,
                    cost_per_kg, max_weight_kg, max_volume_m3,
                    hazardous_allowed, temperature_controlled)
VALUES
  ('rt-002-chi',  'NYC→CHI (road)',  'wh-002', '60601', 'ACTIVE', 'ROAD',  1370, 24, 0.0420, 20000, 80.0, FALSE, FALSE),
  ('rt-002-lax',  'NYC→LAX (road)',  'wh-002', '90001', 'ACTIVE', 'ROAD',  4500, 72, 0.0380, 20000, 80.0, FALSE, FALSE),
  ('rt-002-dal',  'NYC→DAL (road)',  'wh-002', '75201', 'ACTIVE', 'ROAD',  2560, 44, 0.0410, 18000, 72.0, FALSE, FALSE),
  ('rt-002-mia',  'NYC→MIA (road)',  'wh-002', '33101', 'ACTIVE', 'ROAD',  2050, 34, 0.0430, 18000, 72.0, FALSE, FALSE),
  ('rt-002-sea',  'NYC→SEA (road)',  'wh-002', '98101', 'ACTIVE', 'ROAD',  4700, 76, 0.0395, 18000, 72.0, FALSE, FALSE),
  ('rt-002-atl',  'NYC→ATL (road)',  'wh-002', '30301', 'ACTIVE', 'ROAD',  1560, 26, 0.0415, 18000, 72.0, FALSE, FALSE),
  ('rt-002-bos',  'NYC→BOS (road)',  'wh-002', '02101', 'ACTIVE', 'ROAD',   340,  6, 0.0350, 18000, 72.0, FALSE, FALSE),
  ('rt-002-chi-a','NYC→CHI (air)',   'wh-002', '60601', 'ACTIVE', 'AIR',   1370,  3, 0.1800, 10000, 40.0, FALSE, TRUE),
  ('rt-002-lax-a','NYC→LAX (air)',   'wh-002', '90001', 'ACTIVE', 'AIR',   4500,  6, 0.1750, 10000, 40.0, FALSE, TRUE)
ON CONFLICT (id) DO UPDATE SET
    transport_mode = EXCLUDED.transport_mode,
    name           = EXCLUDED.name;

-- ─── From Los Angeles (wh-003) ───────────────────────────────────────────────
INSERT INTO routes (id, name, origin_warehouse_id, destination_postal_code,
                    status, transport_mode,
                    total_distance_km, estimated_duration_hours,
                    cost_per_kg, max_weight_kg, max_volume_m3,
                    hazardous_allowed, temperature_controlled)
VALUES
  ('rt-003-chi',  'LAX→CHI (road)',  'wh-003', '60601', 'ACTIVE', 'ROAD',  3240, 48, 0.0390, 20000, 80.0, FALSE, FALSE),
  ('rt-003-nyc',  'LAX→NYC (road)',  'wh-003', '10001', 'ACTIVE', 'ROAD',  4500, 72, 0.0380, 20000, 80.0, FALSE, FALSE),
  ('rt-003-dal',  'LAX→DAL (road)',  'wh-003', '75201', 'ACTIVE', 'ROAD',  2430, 40, 0.0400, 18000, 72.0, FALSE, FALSE),
  ('rt-003-mia',  'LAX→MIA (road)',  'wh-003', '33101', 'ACTIVE', 'ROAD',  4380, 70, 0.0410, 18000, 72.0, FALSE, FALSE),
  ('rt-003-sea',  'LAX→SEA (road)',  'wh-003', '98101', 'ACTIVE', 'ROAD',  1760, 28, 0.0360, 18000, 72.0, FALSE, FALSE),
  ('rt-003-atl',  'LAX→ATL (road)',  'wh-003', '30301', 'ACTIVE', 'ROAD',  3540, 58, 0.0405, 18000, 72.0, FALSE, FALSE),
  ('rt-003-bos',  'LAX→BOS (road)',  'wh-003', '02101', 'ACTIVE', 'ROAD',  4820, 78, 0.0400, 18000, 72.0, FALSE, FALSE),
  ('rt-003-chi-a','LAX→CHI (air)',   'wh-003', '60601', 'ACTIVE', 'AIR',   3240,  5, 0.1750, 10000, 40.0, FALSE, TRUE),
  ('rt-003-nyc-a','LAX→NYC (air)',   'wh-003', '10001', 'ACTIVE', 'AIR',   4500,  6, 0.1800, 10000, 40.0, FALSE, TRUE)
ON CONFLICT (id) DO UPDATE SET
    transport_mode = EXCLUDED.transport_mode,
    name           = EXCLUDED.name;

-- Upsert waypoints (fixed IDs so ON CONFLICT works) ───────────────────────────
INSERT INTO waypoints (id, route_id, sequence, location, lat, lng, estimated_arrival, type) VALUES
  ('wp-001-nyc-1', 'rt-001-nyc', 1, 'Chicago, IL',     41.878113, -87.629799, NULL,        'ORIGIN'),
  ('wp-001-nyc-2', 'rt-001-nyc', 2, 'Cleveland, OH',   41.499320, -81.694361, '+8 hours',  'TRANSIT'),
  ('wp-001-nyc-3', 'rt-001-nyc', 3, 'New York, NY',    40.712776, -74.005974, '+24 hours', 'DESTINATION'),

  ('wp-001-lax-1', 'rt-001-lax', 1, 'Chicago, IL',     41.878113, -87.629799, NULL,        'ORIGIN'),
  ('wp-001-lax-2', 'rt-001-lax', 2, 'Kansas City, MO', 39.099728, -94.578568, '+10 hours', 'TRANSIT'),
  ('wp-001-lax-3', 'rt-001-lax', 3, 'Los Angeles, CA', 34.052235,-118.243683, '+48 hours', 'DESTINATION'),

  ('wp-002-chi-1', 'rt-002-chi', 1, 'New York, NY',    40.712776, -74.005974, NULL,        'ORIGIN'),
  ('wp-002-chi-2', 'rt-002-chi', 2, 'Cleveland, OH',   41.499320, -81.694361, '+8 hours',  'TRANSIT'),
  ('wp-002-chi-3', 'rt-002-chi', 3, 'Chicago, IL',     41.878113, -87.629799, '+24 hours', 'DESTINATION'),

  ('wp-003-chi-1', 'rt-003-chi', 1, 'Los Angeles, CA', 34.052235,-118.243683, NULL,        'ORIGIN'),
  ('wp-003-chi-2', 'rt-003-chi', 2, 'Kansas City, MO', 39.099728, -94.578568, '+24 hours', 'TRANSIT'),
  ('wp-003-chi-3', 'rt-003-chi', 3, 'Chicago, IL',     41.878113, -87.629799, '+48 hours', 'DESTINATION'),

  ('wp-003-nyc-1', 'rt-003-nyc', 1, 'Los Angeles, CA', 34.052235,-118.243683, NULL,        'ORIGIN'),
  ('wp-003-nyc-2', 'rt-003-nyc', 2, 'Chicago, IL',     41.878113, -87.629799, '+36 hours', 'TRANSIT'),
  ('wp-003-nyc-3', 'rt-003-nyc', 3, 'New York, NY',    40.712776, -74.005974, '+72 hours', 'DESTINATION')
ON CONFLICT (id) DO UPDATE SET type = EXCLUDED.type;
