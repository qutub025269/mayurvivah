"""
Mayur Vivah - online store for ladies' suits (salwar suits).
Flask + SQLite. Run:  python3 app.py   (or: gunicorn app:app)
"""
import os
import re
import secrets
import sqlite3
from datetime import datetime, timedelta
from functools import wraps
from urllib.parse import quote

from flask import (
    Flask, g, render_template, request, redirect, url_for,
    session, flash, abort,
)
from werkzeug.security import generate_password_hash, check_password_hash
from werkzeug.utils import secure_filename

try:
    from PIL import Image
    HAS_PIL = True
except ImportError:  # pragma: no cover
    HAS_PIL = False

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
INSTANCE_DIR = os.path.join(BASE_DIR, "instance")
SCHEMA_PATH = os.path.join(BASE_DIR, "schema.sql")
UPLOAD_DIR = os.path.join(BASE_DIR, "static", "uploads")

ALLOWED_EXTENSIONS = {"jpg", "jpeg", "png", "webp"}
MAX_UPLOAD_BYTES = 5 * 1024 * 1024  # 5 MB

app = Flask(__name__)

_secret = os.environ.get("MV_SECRET_KEY")
if not _secret:
    _secret = "dev-only-insecure-key"
    print("WARNING: MV_SECRET_KEY is not set - using an insecure dev key. "
          "Set MV_SECRET_KEY to a long random value in production.")
app.secret_key = _secret
app.config["MAX_CONTENT_LENGTH"] = MAX_UPLOAD_BYTES


# ----------------------------------------------------------------------------
# Helpers
# ----------------------------------------------------------------------------
def inr(value):
    """Format a rupee amount with Indian digit grouping: 100000 -> 1,00,000."""
    try:
        n = int(value or 0)
    except (TypeError, ValueError):
        n = 0
    s = str(abs(n))
    if len(s) <= 3:
        grouped = s
    else:
        last3 = s[-3:]
        rest = s[:-3]
        parts = []
        while len(rest) > 2:
            parts.insert(0, rest[-2:])
            rest = rest[:-2]
        if rest:
            parts.insert(0, rest)
        grouped = ",".join(parts) + "," + last3
    return ("-" if n < 0 else "") + grouped


app.jinja_env.filters["inr"] = inr


def slugify(text):
    text = (text or "").strip().lower()
    text = re.sub(r"[^a-z0-9]+", "-", text).strip("-")
    return text or "item"


def split_csv_list(value):
    if not value:
        return []
    return [part.strip() for part in re.split(r"[,;]+", str(value)) if part and part.strip()]


def _product_value(product, key, default=""):
    if product is None:
        return default
    if isinstance(product, sqlite3.Row):
        return product[key] if key in product.keys() else default
    if hasattr(product, "get"):
        return product.get(key, default)
    return default


def get_product_images(product):
    images = []
    for key in ["images", "image"]:
        value = _product_value(product, key) or ""
        for part in re.split(r"[,;]+", value):
            candidate = part.strip()
            if candidate and candidate not in images:
                images.append(candidate)
    return images or []


def product_badges(product):
    badges = []
    if _product_value(product, "is_new"):
        badges.append("New")
    if _product_value(product, "is_best_seller"):
        badges.append("Best Seller")
    if _product_value(product, "featured"):
        badges.append("Featured")
    return badges


app.jinja_env.globals["product_badges"] = product_badges
app.jinja_env.globals["get_product_images"] = get_product_images
app.jinja_env.globals["split_csv_list"] = split_csv_list


def unique_slug(table, base):
    """Return a slug unique within `table` (catalogs or products)."""
    db = get_db()
    slug = base or "item"
    candidate, i = slug, 2
    while db.execute(f"SELECT 1 FROM {table} WHERE slug = ?", (candidate,)).fetchone():
        candidate = f"{slug}-{i}"
        i += 1
    return candidate


# ----------------------------------------------------------------------------
# Database
# ----------------------------------------------------------------------------
def _ensure_product_schema(db):
    columns = [row[1] for row in db.execute("PRAGMA table_info(products)").fetchall()]
    additions = {
        "color": "TEXT NOT NULL DEFAULT ''",
        "fabric": "TEXT NOT NULL DEFAULT ''",
        "embroidery_level": "TEXT NOT NULL DEFAULT 'Light'",
        "fit_type": "TEXT NOT NULL DEFAULT 'Ready to wear'",
        "is_new": "INTEGER NOT NULL DEFAULT 0",
        "is_best_seller": "INTEGER NOT NULL DEFAULT 0",
        "popularity": "INTEGER NOT NULL DEFAULT 0",
        "images": "TEXT NOT NULL DEFAULT ''",
        "sku": "TEXT NOT NULL DEFAULT ''",
        "share_count": "INTEGER NOT NULL DEFAULT 0",
        "last_shared_at": "TEXT",
    }
    for column_name, column_sql in additions.items():
        if column_name not in columns:
            db.execute(f"ALTER TABLE products ADD COLUMN {column_name} {column_sql}")
    db.execute("UPDATE products SET sku = 'VIVAH-' || printf('%04d', id) WHERE sku = '' OR sku IS NULL")
    db.execute(
        """CREATE TABLE IF NOT EXISTS whatsapp_share_events (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            product_id INTEGER NOT NULL REFERENCES products(id) ON DELETE CASCADE,
            product_sku TEXT NOT NULL,
            shared_at TEXT NOT NULL DEFAULT (datetime('now'))
        )"""
    )
    db.execute("CREATE INDEX IF NOT EXISTS idx_whatsapp_share_events_product ON whatsapp_share_events(product_id)")


def get_db():
    if "db" not in g:
        os.makedirs(INSTANCE_DIR, exist_ok=True)
        db_path = os.path.join(INSTANCE_DIR, "store.db")
        fresh = not os.path.exists(db_path)
        g.db = sqlite3.connect(db_path)
        g.db.row_factory = sqlite3.Row
        g.db.execute("PRAGMA foreign_keys = ON")
        if fresh:
            with open(SCHEMA_PATH, "r", encoding="utf-8") as f:
                g.db.executescript(f.read())
            g.db.commit()
            from seed import run_seed
            run_seed(g.db)
        _ensure_product_schema(g.db)
        g.db.commit()
    return g.db


@app.teardown_appcontext
def close_db(exc=None):
    db = g.pop("db", None)
    if db is not None:
        db.close()


# ----------------------------------------------------------------------------
# CSRF protection (simple token in session)
# ----------------------------------------------------------------------------
def csrf_token():
    if "_csrf" not in session:
        session["_csrf"] = secrets.token_hex(16)
    return session["_csrf"]


app.jinja_env.globals["csrf_token"] = csrf_token


@app.before_request
def check_csrf():
    if request.method == "POST":
        token = request.form.get("csrf_token", "")
        if not token or token != session.get("_csrf"):
            abort(400, description="Invalid or missing CSRF token.")


# ----------------------------------------------------------------------------
# Admin auth + login rate limiting
# ----------------------------------------------------------------------------
_login_attempts = {}  # ip -> [datetime, ...]


def _prune_attempts(ip):
    now = datetime.utcnow()
    attempts = [t for t in _login_attempts.get(ip, []) if now - t < timedelta(minutes=10)]
    _login_attempts[ip] = attempts
    return attempts


def login_required(view):
    @wraps(view)
    def wrapper(*args, **kwargs):
        if not session.get("admin_id"):
            return redirect(url_for("admin_login", next=request.path))
        return view(*args, **kwargs)
    return wrapper


@app.context_processor
def inject_admin():
    admin = None
    must_change = False
    if session.get("admin_id"):
        db = get_db()
        admin = db.execute(
            "SELECT id, username, must_change FROM admin_users WHERE id = ?",
            (session["admin_id"],),
        ).fetchone()
        must_change = bool(admin and admin["must_change"])
    return {"current_admin": admin, "admin_must_change": must_change}


@app.context_processor
def inject_wishlist():
    wishlist_ids = set(session.get("wishlist", []))
    return {"wishlist_ids": wishlist_ids}


def cart_count():
    cart = session.get("cart", {})
    return sum(item.get("qty", 0) for item in cart.values())


app.jinja_env.globals["cart_count"] = cart_count


def save_upload(file_storage):
    """Validate and store an uploaded product image. Returns path relative to static/."""
    if not file_storage or not file_storage.filename:
        return None
    filename = secure_filename(file_storage.filename)
    ext = filename.rsplit(".", 1)[-1].lower() if "." in filename else ""
    if ext not in ALLOWED_EXTENSIONS:
        raise ValueError("Only JPG, PNG or WebP images are allowed.")
    # Verify it is really an image (guards against renamed scripts).
    file_storage.stream.seek(0)
    if HAS_PIL:
        try:
            img = Image.open(file_storage.stream)
            img.verify()
        except Exception:
            raise ValueError("The uploaded file is not a valid image.")
        file_storage.stream.seek(0)
    new_name = secrets.token_hex(12) + "." + ext
    os.makedirs(UPLOAD_DIR, exist_ok=True)
    file_storage.save(os.path.join(UPLOAD_DIR, new_name))
    return "uploads/" + new_name


# ----------------------------------------------------------------------------
# Public storefront
# ----------------------------------------------------------------------------
@app.route("/")
def index():
    db = get_db()
    q = (request.args.get("q") or "").strip()
    catalog_slug = (request.args.get("catalog") or "").strip()
    size = (request.args.get("size") or "").strip()
    color = (request.args.get("color") or "").strip()
    fabric = (request.args.get("fabric") or "").strip()
    embroidery = (request.args.get("embroidery") or "").strip()
    fit_type = (request.args.get("fit_type") or "").strip()
    price_max = request.args.get("price_max") or ""
    sort = (request.args.get("sort") or "newest").strip()

    catalogs = db.execute(
        "SELECT * FROM catalogs WHERE visible = 1 ORDER BY name"
    ).fetchall()

    sql = ("SELECT p.*, c.name AS catalog_name FROM products p "
           "LEFT JOIN catalogs c ON c.id = p.catalog_id "
           "WHERE p.visible = 1")
    params = []
    if catalog_slug:
        sql += " AND c.slug = ?"
        params.append(catalog_slug)
    if q:
        sql += " AND (p.name LIKE ? OR p.description LIKE ? OR p.color LIKE ? OR p.fabric LIKE ?)"
        params += [f"%{q}%", f"%{q}%", f"%{q}%", f"%{q}%"]
    if size:
        sql += " AND p.sizes LIKE ?"
        params.append(f"%{size}%")
    if color:
        sql += " AND p.color = ?"
        params.append(color)
    if fabric:
        sql += " AND p.fabric = ?"
        params.append(fabric)
    if embroidery:
        sql += " AND p.embroidery_level = ?"
        params.append(embroidery)
    if fit_type:
        sql += " AND p.fit_type = ?"
        params.append(fit_type)
    if price_max and price_max.isdigit():
        sql += " AND p.price <= ?"
        params.append(int(price_max))

    sort_map = {
        "newest": "p.created_at DESC, p.featured DESC, p.popularity DESC",
        "price_asc": "p.price ASC, p.created_at DESC",
        "price_desc": "p.price DESC, p.created_at DESC",
        "popularity": "p.popularity DESC, p.featured DESC, p.created_at DESC",
    }
    sql += " ORDER BY " + sort_map.get(sort, sort_map["newest"])
    products = db.execute(sql, params).fetchall()

    filter_values = {
        "sizes": sorted({item for row in db.execute("SELECT sizes FROM products WHERE visible = 1").fetchall() for item in split_csv_list(row["sizes"])}),
        "colors": [row["color"] for row in db.execute("SELECT DISTINCT color FROM products WHERE visible = 1 AND color != '' ORDER BY color").fetchall() if row["color"]],
        "fabrics": [row["fabric"] for row in db.execute("SELECT DISTINCT fabric FROM products WHERE visible = 1 AND fabric != '' ORDER BY fabric").fetchall() if row["fabric"]],
        "embroidery_levels": [row["embroidery_level"] for row in db.execute("SELECT DISTINCT embroidery_level FROM products WHERE visible = 1 AND embroidery_level != '' ORDER BY embroidery_level").fetchall() if row["embroidery_level"]],
        "fit_types": [row["fit_type"] for row in db.execute("SELECT DISTINCT fit_type FROM products WHERE visible = 1 AND fit_type != '' ORDER BY fit_type").fetchall() if row["fit_type"]],
    }

    return render_template(
        "index.html",
        products=products,
        catalogs=catalogs,
        active_catalog=catalog_slug,
        q=q,
        size=size,
        color=color,
        fabric=fabric,
        embroidery=embroidery,
        fit_type=fit_type,
        price_max=price_max,
        sort=sort,
        filters=filter_values,
    )


@app.route("/product/<slug>")
def product_detail(slug):
    db = get_db()
    product = db.execute(
        "SELECT p.*, c.name AS catalog_name FROM products p "
        "LEFT JOIN catalogs c ON c.id = p.catalog_id "
        "WHERE p.slug = ? AND p.visible = 1",
        (slug,),
    ).fetchone()
    if not product:
        abort(404)
    related = db.execute(
        "SELECT * FROM products WHERE visible = 1 AND id != ? "
        "AND catalog_id = ? ORDER BY featured DESC, popularity DESC LIMIT 4",
        (product["id"], product["catalog_id"]),
    ).fetchall()
    sizes = split_csv_list(product["sizes"])
    images = get_product_images(product)
    return render_template("product.html", product=product, related=related, sizes=sizes, images=images)


@app.route("/product/<int:pid>/share-whatsapp")
def share_product_whatsapp(pid):
    db = get_db()
    product = db.execute(
        "SELECT * FROM products WHERE id = ? AND visible = 1", (pid,)
    ).fetchone()
    if not product:
        abort(404)
    product_url = url_for("product_detail", slug=product["slug"], _external=True)
    description = (product["description"] or "Elegant ladies' suit from the VIVAH collection.").strip()
    description = description[:180] + ("..." if len(description) > 180 else "")
    message = (
        "Check out this beautiful suit from VIVAH 👗\n\n"
        f"✨ Product: {product['name']}\n"
        f"💰 Price: ₹{inr(product['price'])}\n"
        f"🏷️ SKU: {product['sku']}\n"
        f"📝 {description}\n\n"
        f"View the product:\n{product_url}\n\n"
        "Shop more beautiful ladies suits at VIVAH."
    )
    now = datetime.utcnow().strftime("%Y-%m-%d %H:%M:%S")
    db.execute(
        "UPDATE products SET share_count = share_count + 1, last_shared_at = ? WHERE id = ?",
        (now, pid),
    )
    db.execute(
        "INSERT INTO whatsapp_share_events (product_id, product_sku, shared_at) VALUES (?, ?, ?)",
        (pid, product["sku"], now),
    )
    db.commit()
    return redirect("https://wa.me/?text=" + quote(message))


def _get_cart():
    return session.get("cart", {})


def _save_cart(cart):
    session["cart"] = cart
    session.modified = True


@app.route("/cart/add", methods=["POST"])
def cart_add():
    db = get_db()
    try:
        product_id = int(request.form.get("product_id", 0))
    except (TypeError, ValueError):
        product_id = 0
    size = (request.form.get("size") or "").strip()
    try:
        qty = max(1, min(10, int(request.form.get("qty", 1))))
    except (TypeError, ValueError):
        qty = 1
    product = db.execute(
        "SELECT * FROM products WHERE id = ? AND visible = 1", (product_id,)
    ).fetchone()
    if not product:
        flash("That product is no longer available.", "error")
        return redirect(url_for("index"))
    sizes = split_csv_list(product["sizes"])
    if sizes and size not in sizes:
        size = sizes[0]
    key = f"{product_id}:{size}"
    cart = _get_cart()
    existing = cart.get(key, {}).get("qty", 0)
    cart[key] = {
        "product_id": product_id,
        "name": product["name"],
        "image": product["image"] or (get_product_images(product)[0] if get_product_images(product) else ""),
        "price": product["price"],
        "size": size,
        "qty": min(existing + qty, product["stock"] if product["stock"] else 10),
    }
    _save_cart(cart)
    flash(f"Added to bag: {product['name']}", "success")
    return redirect(request.form.get("next") or url_for("cart_view"))


@app.route("/wishlist/toggle/<int:pid>", methods=["POST"])
def wishlist_toggle(pid):
    wishlist = session.get("wishlist", [])
    if pid in wishlist:
        wishlist = [item for item in wishlist if item != pid]
    else:
        wishlist.append(pid)
    session["wishlist"] = wishlist
    session.modified = True
    return redirect(request.referrer or url_for("index"))


@app.route("/wishlist")
def wishlist_view():
    db = get_db()
    wishlist_ids = session.get("wishlist", [])
    products = []
    if wishlist_ids:
        placeholders = ",".join("?" for _ in wishlist_ids)
        products = db.execute(
            f"SELECT p.*, c.name AS catalog_name FROM products p LEFT JOIN catalogs c ON c.id = p.catalog_id WHERE p.visible = 1 AND p.id IN ({placeholders}) ORDER BY p.created_at DESC",
            wishlist_ids,
        ).fetchall()
    return render_template("wishlist.html", products=products)


@app.route("/cart")
def cart_view():
    items = []
    total = 0
    for key, item in _get_cart().items():
        line = item["price"] * item["qty"]
        total += line
        items.append({"key": key, **item, "line_total": line})
    return render_template("cart.html", items=items, total=total)


@app.route("/cart/update", methods=["POST"])
def cart_update():
    key = request.form.get("key", "")
    action = request.form.get("action", "")
    cart = _get_cart()
    if key in cart:
        if action == "remove":
            cart.pop(key, None)
        elif action == "inc":
            cart[key]["qty"] = min(cart[key]["qty"] + 1, 10)
        elif action == "dec":
            cart[key]["qty"] -= 1
            if cart[key]["qty"] <= 0:
                cart.pop(key, None)
    _save_cart(cart)
    return redirect(url_for("cart_view"))


@app.route("/checkout", methods=["GET", "POST"])
def checkout():
    cart = _get_cart()
    if not cart:
        flash("Your bag is empty.", "error")
        return redirect(url_for("index"))

    db = get_db()
    # Re-validate prices/stock from the database at checkout time.
    items, total = [], 0
    for key, item in list(cart.items()):
        product = db.execute(
            "SELECT * FROM products WHERE id = ? AND visible = 1",
            (item["product_id"],),
        ).fetchone()
        if not product or product["stock"] < item["qty"]:
            flash(f"Sorry, '{item['name']}' is out of stock now.", "error")
            cart.pop(key, None)
            _save_cart(cart)
            return redirect(url_for("cart_view"))
        line = product["price"] * item["qty"]
        total += line
        items.append({
            "key": key, "product_id": product["id"], "name": product["name"],
            "size": item["size"], "qty": item["qty"],
            "price": product["price"], "line_total": line,
        })

    if request.method == "POST":
        name = (request.form.get("name") or "").strip()
        phone = re.sub(r"\D", "", request.form.get("phone") or "")
        address = (request.form.get("address") or "").strip()
        city = (request.form.get("city") or "").strip()
        state = (request.form.get("state") or "").strip()
        pincode = re.sub(r"\D", "", request.form.get("pincode") or "")
        notes = (request.form.get("notes") or "").strip()

        errors = []
        if len(name) < 2:
            errors.append("Please enter your full name.")
        if len(phone) < 10:
            errors.append("Please enter a valid 10-digit phone number.")
        if len(address) < 5:
            errors.append("Please enter your full address.")
        if len(city) < 2:
            errors.append("Please enter your city.")
        if len(state) < 2:
            errors.append("Please enter your state.")
        if len(pincode) != 6:
            errors.append("Please enter a valid 6-digit pincode.")
        if errors:
            for e in errors:
                flash(e, "error")
        else:
            order_no = "MV-" + datetime.now().strftime("%Y%m%d") + "-" + secrets.token_hex(3).upper()
            cur = db.execute(
                "INSERT INTO orders (order_no, name, phone, address, city, state, pincode, notes, total, status)"
                " VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, 'pending')",
                (order_no, name, phone, address, city, state, pincode, notes, total),
            )
            order_id = cur.lastrowid
            for it in items:
                db.execute(
                    "INSERT INTO order_items (order_id, product_id, name, size, qty, price)"
                    " VALUES (?, ?, ?, ?, ?, ?)",
                    (order_id, it["product_id"], it["name"], it["size"], it["qty"], it["price"]),
                )
                db.execute(
                    "UPDATE products SET stock = stock - ? WHERE id = ?",
                    (it["qty"], it["product_id"]),
                )
            db.commit()
            session.pop("cart", None)
            return render_template("order_success.html", order_no=order_no,
                                   name=name, total=total, items=items)

    return render_template("checkout.html", items=items, total=total)


# ----------------------------------------------------------------------------
# Admin panel
# ----------------------------------------------------------------------------
@app.route("/admin/login", methods=["GET", "POST"])
def admin_login():
    if session.get("admin_id"):
        return redirect(url_for("admin_dashboard"))
    ip = request.remote_addr or "unknown"
    if request.method == "POST":
        attempts = _prune_attempts(ip)
        if len(attempts) >= 10:
            flash("Too many failed attempts. Please wait 10 minutes.", "error")
            return render_template("admin/login.html")
        username = (request.form.get("username") or "").strip()
        password = request.form.get("password") or ""
        db = get_db()
        user = db.execute(
            "SELECT * FROM admin_users WHERE username = ?", (username,)
        ).fetchone()
        if user and check_password_hash(user["password_hash"], password):
            _login_attempts.pop(ip, None)
            session.clear()
            session["admin_id"] = user["id"]
            session["_csrf"] = secrets.token_hex(16)  # fresh CSRF token after login
            if user["must_change"]:
                flash("Please change the default password before continuing.", "warning")
                return redirect(url_for("admin_change_password"))
            nxt = request.args.get("next") or url_for("admin_dashboard")
            return redirect(nxt if nxt.startswith("/admin") else url_for("admin_dashboard"))
        _login_attempts.setdefault(ip, []).append(datetime.utcnow())
        flash("Invalid username or password.", "error")
    return render_template("admin/login.html")


@app.route("/admin/logout")
@login_required
def admin_logout():
    session.clear()
    flash("You have been signed out.", "success")
    return redirect(url_for("admin_login"))


@app.route("/admin/")
@login_required
def admin_dashboard():
    db = get_db()
    stats = {
        "products": db.execute("SELECT COUNT(*) c FROM products").fetchone()["c"],
        "catalogs": db.execute("SELECT COUNT(*) c FROM catalogs").fetchone()["c"],
        "pending_orders": db.execute(
            "SELECT COUNT(*) c FROM orders WHERE status = 'pending'").fetchone()["c"],
        "revenue": db.execute(
            "SELECT COALESCE(SUM(total),0) t FROM orders WHERE status != 'cancelled'"
        ).fetchone()["t"],
    }
    recent = db.execute(
        "SELECT * FROM orders ORDER BY created_at DESC LIMIT 8").fetchall()
    low_stock = db.execute(
        "SELECT * FROM products WHERE stock <= 5 AND visible = 1 ORDER BY stock LIMIT 8"
    ).fetchall()
    most_shared = db.execute(
        "SELECT * FROM products WHERE visible = 1 AND share_count > 0 "
        "ORDER BY share_count DESC, last_shared_at DESC LIMIT 8"
    ).fetchall()
    return render_template("admin/dashboard.html", stats=stats,
                           recent=recent, low_stock=low_stock,
                           most_shared=most_shared)


# ---- Products ----
@app.route("/admin/products")
@login_required
def admin_products():
    db = get_db()
    products = db.execute(
        "SELECT p.*, c.name AS catalog_name FROM products p "
        "LEFT JOIN catalogs c ON c.id = p.catalog_id ORDER BY p.created_at DESC"
    ).fetchall()
    return render_template("admin/products.html", products=products)


@app.route("/admin/products/new", methods=["GET", "POST"])
@login_required
def admin_product_new():
    return _product_form(None)


@app.route("/admin/products/<int:pid>/edit", methods=["GET", "POST"])
@login_required
def admin_product_edit(pid):
    db = get_db()
    product = db.execute("SELECT * FROM products WHERE id = ?", (pid,)).fetchone()
    if not product:
        abort(404)
    return _product_form(product)


def _product_form(product):
    db = get_db()
    catalogs = db.execute("SELECT * FROM catalogs ORDER BY name").fetchall()
    if request.method == "POST":
        name = (request.form.get("name") or "").strip()
        catalog_id = request.form.get("catalog_id") or None
        try:
            price = int(request.form.get("price") or 0)
        except ValueError:
            price = -1
        compare_raw = (request.form.get("compare_at") or "").strip()
        try:
            compare_at = int(compare_raw) if compare_raw else None
        except ValueError:
            compare_at = -1
        sizes = (request.form.get("sizes") or "").strip()
        color = (request.form.get("color") or "").strip()
        fabric = (request.form.get("fabric") or "").strip()
        embroidery_level = (request.form.get("embroidery_level") or "Light").strip() or "Light"
        fit_type = (request.form.get("fit_type") or "Ready to wear").strip() or "Ready to wear"
        try:
            stock = int(request.form.get("stock") or 0)
        except ValueError:
            stock = -1
        description = (request.form.get("description") or "").strip()
        visible = 1 if request.form.get("visible") else 0
        featured = 1 if request.form.get("featured") else 0
        is_new = 1 if request.form.get("is_new") else 0
        is_best_seller = 1 if request.form.get("is_best_seller") else 0
        sku = (request.form.get("sku") or "").strip().upper()

        errors = []
        if len(name) < 2:
            errors.append("Product name is required.")
        if price < 0:
            errors.append("Price must be a whole number of rupees.")
        if compare_at is not None and compare_at < 0:
            errors.append("Compare-at price must be a whole number of rupees.")
        if stock < 0:
            errors.append("Stock must be a whole number.")
        if not sku:
            sku = f"VIVAH-{slugify(name).upper()}"
        if catalog_id:
            try:
                catalog_id = int(catalog_id)
            except ValueError:
                catalog_id = None
                errors.append("Invalid catalog selected.")

        image_path = product["image"] if product else ""
        upload = request.files.get("image")
        if upload and upload.filename:
            try:
                image_path = save_upload(upload)
            except ValueError as e:
                errors.append(str(e))

        if errors:
            for e in errors:
                flash(e, "error")
        else:
            if product:
                db.execute(
                    "UPDATE products SET name=?, sku=?, catalog_id=?, price=?, compare_at=?, sizes=?, color=?, fabric=?, embroidery_level=?, fit_type=?, stock=?, description=?, image=?, visible=?, featured=?, is_new=?, is_best_seller=? WHERE id=?",
                    (name, sku, catalog_id, price, compare_at, sizes or "S,M,L,XL",
                     color, fabric, embroidery_level, fit_type, stock, description,
                     image_path, visible, featured, is_new, is_best_seller, product["id"]),
                )
                flash("Product updated.", "success")
            else:
                slug = unique_slug("products", slugify(name))
                db.execute(
                    "INSERT INTO products (catalog_id, name, slug, sku, price, compare_at, sizes, color, fabric, embroidery_level, fit_type, stock, description, image, visible, featured, is_new, is_best_seller)"
                    " VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                    (catalog_id, name, slug, sku, price, compare_at, sizes or "S,M,L,XL",
                     color, fabric, embroidery_level, fit_type, stock, description,
                     image_path or "placeholders/suit-1.svg", visible, featured, is_new, is_best_seller),
                )
                flash("Product added.", "success")
            db.commit()
            return redirect(url_for("admin_products"))
    return render_template("admin/product_form.html", product=product, catalogs=catalogs)


@app.route("/admin/products/<int:pid>/delete", methods=["POST"])
@login_required
def admin_product_delete(pid):
    db = get_db()
    db.execute("DELETE FROM products WHERE id = ?", (pid,))
    db.commit()
    flash("Product deleted.", "success")
    return redirect(url_for("admin_products"))


# ---- Catalogs ----
@app.route("/admin/catalogs")
@login_required
def admin_catalogs():
    db = get_db()
    catalogs = db.execute(
        "SELECT c.*, (SELECT COUNT(*) FROM products p WHERE p.catalog_id = c.id) AS product_count"
        " FROM catalogs c ORDER BY c.name"
    ).fetchall()
    return render_template("admin/catalogs.html", catalogs=catalogs)


@app.route("/admin/catalogs/new", methods=["GET", "POST"])
@login_required
def admin_catalog_new():
    return _catalog_form(None)


@app.route("/admin/catalogs/<int:cid>/edit", methods=["GET", "POST"])
@login_required
def admin_catalog_edit(cid):
    db = get_db()
    catalog = db.execute("SELECT * FROM catalogs WHERE id = ?", (cid,)).fetchone()
    if not catalog:
        abort(404)
    return _catalog_form(catalog)


def _catalog_form(catalog):
    db = get_db()
    if request.method == "POST":
        name = (request.form.get("name") or "").strip()
        description = (request.form.get("description") or "").strip()
        visible = 1 if request.form.get("visible") else 0
        if len(name) < 2:
            flash("Catalog name is required.", "error")
        else:
            if catalog:
                db.execute(
                    "UPDATE catalogs SET name=?, description=?, visible=? WHERE id=?",
                    (name, description, visible, catalog["id"]),
                )
                flash("Catalog updated.", "success")
            else:
                db.execute(
                    "INSERT INTO catalogs (name, slug, description, visible) VALUES (?, ?, ?, ?)",
                    (name, unique_slug("catalogs", slugify(name)), description, visible),
                )
                flash("Catalog created.", "success")
            db.commit()
            return redirect(url_for("admin_catalogs"))
    return render_template("admin/catalog_form.html", catalog=catalog)


@app.route("/admin/catalogs/<int:cid>/delete", methods=["POST"])
@login_required
def admin_catalog_delete(cid):
    db = get_db()
    db.execute("DELETE FROM catalogs WHERE id = ?", (cid,))
    db.commit()
    flash("Catalog deleted. Its products were kept but unassigned.", "success")
    return redirect(url_for("admin_catalogs"))


# ---- Orders ----
ORDER_STATUSES = ["pending", "confirmed", "shipped", "delivered", "cancelled"]


@app.route("/admin/orders")
@login_required
def admin_orders():
    db = get_db()
    status = (request.args.get("status") or "").strip()
    if status in ORDER_STATUSES:
        orders = db.execute(
            "SELECT * FROM orders WHERE status = ? ORDER BY created_at DESC", (status,)
        ).fetchall()
    else:
        status = ""
        orders = db.execute("SELECT * FROM orders ORDER BY created_at DESC").fetchall()
    return render_template("admin/orders.html", orders=orders,
                           active_status=status, statuses=ORDER_STATUSES)


@app.route("/admin/orders/<int:oid>", methods=["GET", "POST"])
@login_required
def admin_order_detail(oid):
    db = get_db()
    order = db.execute("SELECT * FROM orders WHERE id = ?", (oid,)).fetchone()
    if not order:
        abort(404)
    if request.method == "POST":
        status = (request.form.get("status") or "").strip()
        if status in ORDER_STATUSES:
            db.execute("UPDATE orders SET status = ? WHERE id = ?", (status, oid))
            db.commit()
            flash(f"Order marked as {status}.", "success")
            return redirect(url_for("admin_order_detail", oid=oid))
        flash("Invalid status.", "error")
    items = db.execute(
        "SELECT * FROM order_items WHERE order_id = ?", (oid,)
    ).fetchall()
    return render_template("admin/order_detail.html", order=order, items=items,
                           statuses=ORDER_STATUSES)


@app.route("/admin/change-password", methods=["GET", "POST"])
@login_required
def admin_change_password():
    if request.method == "POST":
        current = request.form.get("current_password") or ""
        new = request.form.get("new_password") or ""
        confirm = request.form.get("confirm_password") or ""
        db = get_db()
        user = db.execute("SELECT * FROM admin_users WHERE id = ?",
                          (session["admin_id"],)).fetchone()
        if not check_password_hash(user["password_hash"], current):
            flash("Current password is incorrect.", "error")
        elif len(new) < 8:
            flash("New password must be at least 8 characters.", "error")
        elif new != confirm:
            flash("New passwords do not match.", "error")
        else:
            db.execute(
                "UPDATE admin_users SET password_hash = ?, must_change = 0 WHERE id = ?",
                (generate_password_hash(new), user["id"]),
            )
            db.commit()
            flash("Password changed.", "success")
            return redirect(url_for("admin_dashboard"))
    return render_template("admin/change_password.html")


if __name__ == "__main__":
    # Ensure the DB exists before serving.
    with app.app_context():
        get_db()
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", 5000)), debug=False)
