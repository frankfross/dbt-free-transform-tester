-- Per-order totals for completed orders only.
-- Seeds: orders, order_lines.
SELECT
    o.order_id,
    o.customer_id,
    SUM(l.qty * l.unit_price) AS total,
    COUNT(*) AS line_count
FROM orders o
JOIN order_lines l ON l.order_id = o.order_id
WHERE o.status = 'completed'
GROUP BY o.order_id, o.customer_id
