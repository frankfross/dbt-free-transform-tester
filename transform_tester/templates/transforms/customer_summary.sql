-- Lifetime value per customer, built on top of order_totals.
-- Demonstrates {{ ref() }}: order_totals is run first and materialized
-- as a temporary table, then this transform reads from it.
SELECT
    customer_id,
    COUNT(*) AS completed_orders,
    SUM(total) AS lifetime_value
FROM {{ ref("order_totals") }}
GROUP BY customer_id
