-- ── Dock slot seed data V2 ────────────────────────────────────────────────────
-- Generates AVAILABLE PICKUP slots for all 3 warehouses for the next 90 days.
-- 4 docks per warehouse × 4 time windows × 90 days = 1080 slots per warehouse.
-- generate_series avoids hardcoding dates so slots are always in the future.
SET search_path = warehouse;

INSERT INTO dock_schedules (
    id, warehouse_id, dock_number, date, start_time, end_time, type, status
)
SELECT
    gen_random_uuid()::text,
    wh.id,
    dock.n,
    d.day::DATE,
    slot.start_t::TIME,
    slot.end_t::TIME,
    'PICKUP',
    'AVAILABLE'
FROM
    warehouses wh
    CROSS JOIN (VALUES (1),(2),(3),(4))          AS dock(n)
    CROSS JOIN generate_series(
        CURRENT_DATE,
        CURRENT_DATE + INTERVAL '90 days',
        INTERVAL '1 day'
    )                                             AS d(day)
    CROSS JOIN (
        VALUES
            ('08:00','10:00'),
            ('10:00','12:00'),
            ('13:00','15:00'),
            ('15:00','17:00')
    )                                             AS slot(start_t, end_t)
WHERE
    wh.active = TRUE
ON CONFLICT DO NOTHING;
