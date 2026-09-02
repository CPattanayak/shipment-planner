-- ── Carrier seed data V2 ──────────────────────────────────────────────────────
SET search_path = carrier;

INSERT INTO carriers (id, name, code, active,
                      contact_email,
                      max_weight_kg, max_volume_m3,
                      hazardous_allowed, temperature_controlled,
                      express_available, overnight_available, same_day_available,
                      tracking_available,
                      on_time_delivery_rate, average_delay_hours,
                      damage_rate, customer_satisfaction, total_shipments)
VALUES
  ('car-001', 'FastFreight USA',    'FFU',  TRUE, 'ops@fastfreight.example',
   25000, 120.0, FALSE, FALSE, TRUE,  TRUE,  FALSE, TRUE,  0.9600, 0.5,  0.00080, 4.7, 15000),

  ('car-002', 'CoolChain Express',  'CCX',  TRUE, 'ops@coolchain.example',
   10000,  50.0, FALSE, TRUE,  TRUE,  TRUE,  FALSE, TRUE,  0.9400, 1.2,  0.00050, 4.8,  8000),

  ('car-003', 'HazMat Logistics',   'HML',  TRUE, 'ops@hazmat.example',
    5000,  20.0, TRUE,  FALSE, FALSE, FALSE, FALSE, TRUE,  0.9200, 2.0,  0.00030, 4.5,  3000),

  ('car-004', 'BulkMove Inc',       'BMI',  TRUE, 'ops@bulkmove.example',
   50000, 250.0, FALSE, FALSE, FALSE, FALSE, FALSE, TRUE,  0.9300, 3.0,  0.00120, 4.3, 22000),

  ('car-005', 'SkyRush Air Cargo',  'SRC',  TRUE, 'ops@skyrush.example',
   15000,  60.0, FALSE, FALSE, TRUE,  TRUE,  TRUE,  TRUE,  0.9800, 0.2,  0.00040, 4.9,  9500)
ON CONFLICT (id) DO NOTHING;

-- Supported transport modes
INSERT INTO carrier_modes (carrier_id, mode) VALUES
  ('car-001', 'ROAD'),
  ('car-002', 'ROAD'),
  ('car-003', 'ROAD'),
  ('car-004', 'ROAD'),
  ('car-004', 'RAIL'),
  ('car-005', 'AIR')
ON CONFLICT DO NOTHING;

-- Service areas (US-wide for all carriers)
INSERT INTO carrier_service_areas (carrier_id, service_area) VALUES
  ('car-001', 'US'), ('car-001', 'CA'),
  ('car-002', 'US'), ('car-002', 'CA'),
  ('car-003', 'US'),
  ('car-004', 'US'), ('car-004', 'CA'), ('car-004', 'MX'),
  ('car-005', 'US'), ('car-005', 'CA'), ('car-005', 'GB'), ('car-005', 'DE')
ON CONFLICT DO NOTHING;
