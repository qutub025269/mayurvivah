# Mayur Vivah — Online Store for Ladies' Suits

A complete, ready-to-deploy Python web store built with **Flask + SQLite**:
customer storefront (browse, search, bag, pay-on-delivery checkout) plus a
password-protected **admin panel** for uploading suits, creating catalogs,
managing stock and processing orders. Works on mobile and desktop.

## Quick start (on your own computer)

```bash
cd mayur-vivah-server
python3 -m venv venv && source venv/bin/activate
pip install -r requirements.txt
# optional but recommended:
export MV_SECRET_KEY="$(python3 -c 'import secrets; print(secrets.token_hex(32))')"
python3 app.py
```

Open http://127.0.0.1:5000 — the store.
Admin panel: http://127.0.0.1:5000/admin/ — login `admin` / `changeme123`.
**Change the admin password immediately** (the panel warns you until you do).

The SQLite database is created automatically on first run at
`instance/store.db`, seeded with 2 sample catalogs and 4 sample suits
(clearly labelled "(Sample)") that you can delete or replace.

## Deploy option A — PythonAnywhere (free tier, recommended for a real store)

PythonAnywhere's free tier keeps your files and SQLite database permanently,
so products, photos and orders survive restarts. Steps:

1. Sign up at pythonanywhere.com (free "Beginner" account).
2. Open **Files**, upload the contents of this folder (or `git clone` it in a
   **Bash** console).
3. In a Bash console:
   ```bash
   mkvirtualenv --python=/usr/bin/python3.12 mayurvivah
   pip install -r requirements.txt
   ```
4. Go to the **Web** tab → *Add a new web app* → **Manual configuration** →
   Python 3.12.
5. In the *Virtualenv* section, enter `/home/YOURNAME/.virtualenvs/mayurvivah`.
6. Edit the **WSGI configuration file** to:
   ```python
   import sys
   sys.path.insert(0, '/home/YOURNAME/mayur-vivah-server')
   from app import app as application
   ```
7. Add an environment variable (Web tab → *Environment variables*):
   `MV_SECRET_KEY` = a long random string (generate with
   `python3 -c "import secrets; print(secrets.token_hex(32))"`).
8. Set **Static files**: URL `/static/` → path
   `/home/YOURNAME/mayur-vivah-server/static/`.
9. Hit **Reload**, visit your `YOURNAME.pythonanywhere.com` site.
10. Log in at `/admin/` (`admin` / `changeme123`) and change the password.
11. (Optional) Point your own domain at it via the Web tab.

Uploads go to `static/uploads/` and the database to `instance/store.db` —
both live on PythonAnywhere's persistent disk.

## Deploy option B — Render

1. Push this folder to a GitHub repo.
2. On render.com: **New → Web Service** → connect the repo.
   - Build command: `pip install -r requirements.txt`
   - Start command: `gunicorn app:app` (the `Procfile` already does this)
   - Environment variable: `MV_SECRET_KEY` = a long random string.
3. Deploy and open the given URL.

> ⚠️ **Important:** Render's free tier has an *ephemeral* disk — every deploy
> or restart wipes `instance/store.db` and `static/uploads/`, so products,
> photos and orders would be lost. For a real store either add a paid
> **Persistent Disk** (mount at `/opt/render/project/src/instance` and point
> uploads there), or prefer **PythonAnywhere** / a VPS where files persist.

## Deploy option C — any VPS (Ubuntu) with gunicorn + nginx (sketch)

```bash
sudo apt install python3-venv python3-pip nginx
cd /var/www && git clone <your-repo> mayur-vivah-server && cd mayur-vivah-server
python3 -m venv venv && ./venv/bin/pip install -r requirements.txt
# systemd service /etc/systemd/system/mayurvivah.service:
#   [Service] WorkingDirectory=/var/www/mayur-vivah-server
#   Environment="MV_SECRET_KEY=<long random>"
#   ExecStart=/var/www/mayur-vivah-server/venv/bin/gunicorn app:app -w 3 -b 127.0.0.1:8000
sudo systemctl enable --now mayurvivah
# nginx: reverse-proxy port 80/443 to 127.0.0.1:8000; serve /static/ directly.
# Add HTTPS with: sudo certbot --nginx
```

## Admin guide

- **Products** (`/admin/products`): add/edit/delete suits — name, catalog,
  price (₹), compare-at price, sizes, stock, description, photo upload
  (JPG/PNG/WebP, max 5 MB), visible/featured flags.
- **Catalogs** (`/admin/catalogs`): create collections like "Festive
  Collection" that appear as filter chips in the store.
- **Orders** (`/admin/orders`): view customer details + items, update status
  through pending → confirmed → shipped → delivered (or cancelled).
- Checkout is **pay-on-delivery only**; no payment gateway is connected.

## Security notes

- Set `MV_SECRET_KEY` in production (the app warns and uses an insecure dev
  key otherwise).
- Change the default admin password on first login (forced reminder banner).
- All admin/product/order forms carry CSRF tokens; uploads are validated as
  real images with randomised filenames; login is rate-limited
  (10 failed attempts / 10 min per IP); all SQL uses parameterised queries;
  templates auto-escape output.
- For production, serve behind HTTPS (Render/PythonAnywhere do this for you;
  on a VPS use certbot as sketched above).

## Project layout

```
app.py                 Flask app: storefront + admin routes
schema.sql             SQLite schema
seed.py                sample catalogs/products + default admin user
templates/             Jinja templates (store + admin/)
static/style.css       all styles (storefront + admin, responsive)
static/app.js          mobile menu + image preview
static/placeholders/   sample SVG product images
static/uploads/        admin-uploaded product photos (created at runtime)
instance/store.db      SQLite database (created on first run)
requirements.txt Procfile runtime.txt .python-version
```
