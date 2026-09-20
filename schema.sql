PRAGMA foreign_keys = ON;

CREATE TABLE IF NOT EXISTS catalogs (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    name TEXT NOT NULL,
    slug TEXT NOT NULL UNIQUE,
    description TEXT DEFAULT '',
    visible INTEGER NOT NULL DEFAULT 1,
    created_at TEXT NOT NULL DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS products (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    catalog_id INTEGER REFERENCES catalogs(id) ON DELETE SET NULL,
    name TEXT NOT NULL,
    slug TEXT NOT NULL UNIQUE,
    price INTEGER NOT NULL DEFAULT 0,          -- price in INR (whole rupees)
    compare_at INTEGER,                        -- optional "was" price in INR
    sizes TEXT NOT NULL DEFAULT 'S,M,L,XL',    -- comma separated
    stock INTEGER NOT NULL DEFAULT 0,
    description TEXT DEFAULT '',
    image TEXT DEFAULT '',                     -- path relative to static/
    sku TEXT NOT NULL DEFAULT '',
    share_count INTEGER NOT NULL DEFAULT 0,
    last_shared_at TEXT,
    visible INTEGER NOT NULL DEFAULT 1,
    featured INTEGER NOT NULL DEFAULT 0,
    created_at TEXT NOT NULL DEFAULT (datetime('now'))
);
CREATE INDEX IF NOT EXISTS idx_products_slug ON products(slug);
CREATE INDEX IF NOT EXISTS idx_products_catalog ON products(catalog_id);

CREATE TABLE IF NOT EXISTS whatsapp_share_events (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    product_id INTEGER NOT NULL REFERENCES products(id) ON DELETE CASCADE,
    product_sku TEXT NOT NULL,
    shared_at TEXT NOT NULL DEFAULT (datetime('now'))
);
CREATE INDEX IF NOT EXISTS idx_whatsapp_share_events_product ON whatsapp_share_events(product_id);

CREATE TABLE IF NOT EXISTS orders (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    order_no TEXT NOT NULL UNIQUE,
    name TEXT NOT NULL,
    phone TEXT NOT NULL,
    address TEXT NOT NULL,
    city TEXT NOT NULL,
    state TEXT NOT NULL,
    pincode TEXT NOT NULL,
    notes TEXT DEFAULT '',
    total INTEGER NOT NULL DEFAULT 0,          -- total in INR
    status TEXT NOT NULL DEFAULT 'pending',   -- pending/confirmed/shipped/delivered/cancelled
    created_at TEXT NOT NULL DEFAULT (datetime('now'))
);
CREATE INDEX IF NOT EXISTS idx_orders_status ON orders(status);

CREATE TABLE IF NOT EXISTS order_items (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    order_id INTEGER NOT NULL REFERENCES orders(id) ON DELETE CASCADE,
    product_id INTEGER REFERENCES products(id) ON DELETE SET NULL,
    name TEXT NOT NULL,
    size TEXT NOT NULL DEFAULT '',
    qty INTEGER NOT NULL DEFAULT 1,
    price INTEGER NOT NULL DEFAULT 0           -- unit price in INR at time of order
);

CREATE TABLE IF NOT EXISTS admin_users (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    username TEXT NOT NULL UNIQUE,
    password_hash TEXT NOT NULL,
    must_change INTEGER NOT NULL DEFAULT 1,   -- force password change on first login
    created_at TEXT NOT NULL DEFAULT (datetime('now'))
);
