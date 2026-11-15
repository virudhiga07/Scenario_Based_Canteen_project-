# SQL reporting queries

The executable schema and seed data are in `database/schema.sql` and `database/seed.json`. All amounts are integer paise. Divide by 100.0 only for presentation. SQLite and Cloudflare D1 share these relational queries.

## Retrieve individual sale lines for preprocessing

```sql
SELECT o.id AS order_id, o.created_at, o.customer_name,
       o.order_type, o.payment_method, o.is_demo,
       oi.item_id, oi.item_name, oi.quantity, oi.unit_price_paise,
       oi.quantity * oi.unit_price_paise AS line_total_paise
FROM orders AS o
JOIN order_items AS oi ON oi.order_id = o.id
ORDER BY o.created_at, o.id, oi.item_id;
```

## Daily revenue and order count in India

```sql
SELECT date(created_at, '+5 hours', '+30 minutes') AS sale_date,
       COUNT(*) AS orders,
       SUM(total_paise) / 100.0 AS revenue_inr
FROM orders
GROUP BY sale_date
ORDER BY sale_date;
```

India currently has a fixed UTC+05:30 offset. The Python implementation uses the named `Asia/Kolkata` zone for explicit timezone handling.

## Item-wise sales and popular items

```sql
SELECT oi.item_id, m.name AS current_name,
       SUM(oi.quantity) AS units_sold,
       SUM(oi.quantity * oi.unit_price_paise) / 100.0 AS revenue_inr
FROM order_items AS oi
JOIN menu_items AS m ON m.id = oi.item_id
GROUP BY oi.item_id, m.name
ORDER BY units_sold DESC, revenue_inr DESC;
```

This SQL labels items using their current menu names. The Python report instead uses their latest historical name within the selected period; both group by stable item ID. Revenue always uses the price stored on each sale line.

## Low stock

```sql
SELECT id, name, stock
FROM menu_items
WHERE active = 1 AND stock <= 10
ORDER BY stock, name;
```

## Check total consistency

```sql
SELECT o.id, o.total_paise, SUM(oi.quantity * oi.unit_price_paise) AS calculated_paise
FROM orders AS o JOIN order_items AS oi ON oi.order_id = o.id
GROUP BY o.id, o.total_paise
HAVING o.total_paise <> SUM(oi.quantity * oi.unit_price_paise);
```

A consistent database returns no rows. To exclude demonstrations in sales queries add `WHERE o.is_demo = 0` before `GROUP BY` (use `is_demo` on an unaliased `orders` query).
