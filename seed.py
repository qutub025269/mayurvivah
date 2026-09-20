"""Seed the Mayur Vivah database with sample catalogs, products and an admin user."""
from werkzeug.security import generate_password_hash


SAMPLE_PRODUCTS = [
    {
        "name": "Gulnaar Festive Anarkali Suit (Sample)",
        "price": 2499,
        "compare_at": 3299,
        "sizes": "S,M,L,XL",
        "stock": 12,
        "description": "Sample product - replace with your own catalog. Elegant maroon Anarkali suit with golden embroidery, paired with a net dupatta. Perfect for festive occasions and weddings.",
        "image": "placeholders/suit-1.svg",
        "featured": 1,
    },
    {
        "name": "Meher Banarasi Silk Suit (Sample)",
        "price": 4999,
        "compare_at": 6499,
        "sizes": "M,L,XL",
        "stock": 8,
        "description": "Sample product - replace with your own catalog. Rich Banarasi silk straight-cut suit with zari work and silk dupatta. A timeless wedding wardrobe piece.",
        "image": "placeholders/suit-2.svg",
        "featured": 1,
    },
    {
        "name": "Noor Cotton Daily Suit (Sample)",
        "price": 899,
        "compare_at": 1199,
        "sizes": "S,M,L,XL,XXL",
        "stock": 25,
        "description": "Sample product - replace with your own catalog. Breathable cotton straight suit with printed palazzo and dupatta - comfortable for everyday wear.",
        "image": "placeholders/suit-3.svg",
        "featured": 0,
    },
    {
        "name": "Zeenat Rayon Straight Suit (Sample)",
        "price": 1299,
        "compare_at": 1699,
        "sizes": "S,M,L,XL",
        "stock": 15,
        "description": "Sample product - replace with your own catalog. Soft rayon straight suit with subtle foil print and matching dupatta - graceful office and outing wear.",
        "image": "placeholders/suit-4.svg",
        "featured": 0,
    },
]


def _slug(text):
    import re
    return re.sub(r"[^a-z0-9]+", "-", text.strip().lower()).strip("-") or "item"


def run_seed(db):
    """Insert sample data into a freshly-created database."""
    import sqlite3  # noqa: F401  (kept explicit for clarity)
    db.execute(
        "INSERT INTO admin_users (username, password_hash, must_change) VALUES (?, ?, 1)",
        ("admin", generate_password_hash("changeme123")),
    )
    catalogs = [
        ("Festive Collection", "Suits for weddings, festivals and special occasions."),
        ("Daily Wear", "Comfortable cotton and rayon suits for everyday wear."),
    ]
    cat_ids = {}
    for name, desc in catalogs:
        cur = db.execute(
            "INSERT INTO catalogs (name, slug, description, visible) VALUES (?, ?, ?, 1)",
            (name, _slug(name), desc),
        )
        cat_ids[name] = cur.lastrowid

    festive = ["Gulnaar", "Meher"]
    for p in SAMPLE_PRODUCTS:
        catalog_name = "Festive Collection" if any(k in p["name"] for k in festive) else "Daily Wear"
        db.execute(
            """INSERT INTO products
               (catalog_id, name, slug, price, compare_at, sizes, stock, description, image, visible, featured)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, 1, ?)""",
            (cat_ids[catalog_name], p["name"], _slug(p["name"]), p["price"],
             p["compare_at"], p["sizes"], p["stock"], p["description"],
             p["image"], p["featured"]),
        )
    db.commit()
