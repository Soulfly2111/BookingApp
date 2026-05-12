from http import HTTPStatus
from http.server import ThreadingHTTPServer, BaseHTTPRequestHandler
from html import escape
from pathlib import Path
from urllib.parse import parse_qs, quote_plus, urlparse
import calendar
import os
import sqlite3
import webbrowser
from datetime import date, datetime


BASE_DIR = Path(__file__).resolve().parent
DB_PATH = Path(os.environ.get("BOOKING_DB_PATH", BASE_DIR / "band_concerts.db"))
LOGO_PATH = Path(
    os.environ.get(
        "BOOKING_LOGO_PATH",
        BASE_DIR / "assets" / "logo.png",
    )
)
APP_HOST = os.environ.get("BOOKING_HOST", "127.0.0.1")
APP_PORT = int(os.environ.get("BOOKING_PORT", "8000"))
MONTH_NAMES = (
    "",
    "Januar",
    "Februar",
    "März",
    "April",
    "Mai",
    "Juni",
    "Juli",
    "August",
    "September",
    "Oktober",
    "November",
    "Dezember",
)


def get_connection():
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    connection = sqlite3.connect(DB_PATH)
    connection.row_factory = sqlite3.Row
    return connection


def init_db():
    with get_connection() as connection:
        connection.execute(
            """
            CREATE TABLE IF NOT EXISTS opportunities (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                name TEXT NOT NULL,
                kind TEXT NOT NULL,
                city TEXT,
                website TEXT,
                owner TEXT,
                contact_name TEXT,
                contact_email TEXT,
                application_deadline TEXT,
                performance_date TEXT,
                status TEXT NOT NULL DEFAULT 'Recherche',
                notes TEXT,
                created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
            )
            """
        )
        columns = {
            row["name"]
            for row in connection.execute("PRAGMA table_info(opportunities)").fetchall()
        }
        if "owner" not in columns:
            connection.execute("ALTER TABLE opportunities ADD COLUMN owner TEXT")
        if "performance_date" not in columns:
            connection.execute("ALTER TABLE opportunities ADD COLUMN performance_date TEXT")
        connection.execute(
            """
            CREATE TABLE IF NOT EXISTS availability (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                owner TEXT NOT NULL,
                available_date TEXT NOT NULL,
                notes TEXT,
                created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
            )
            """
        )


def normalize_url(value):
    value = value.strip()
    if value and not value.startswith(("http://", "https://")):
        return f"https://{value}"
    return value


def field_value(form, key):
    return form.get(key, [""])[0].strip()


def form_data(form):
    return {
        "name": field_value(form, "name"),
        "kind": field_value(form, "kind") or "Location",
        "city": field_value(form, "city"),
        "website": normalize_url(field_value(form, "website")),
        "owner": field_value(form, "owner"),
        "contact_name": field_value(form, "contact_name"),
        "contact_email": field_value(form, "contact_email"),
        "application_deadline": field_value(form, "application_deadline"),
        "performance_date": field_value(form, "performance_date"),
        "status": field_value(form, "status") or "Recherche",
        "notes": field_value(form, "notes"),
    }


def save_opportunity(form):
    data = form_data(form)
    if not data["name"]:
        return False

    with get_connection() as connection:
        connection.execute(
            """
            INSERT INTO opportunities (
                name, kind, city, website, owner, contact_name, contact_email,
                application_deadline, performance_date, status, notes
            ) VALUES (
                :name, :kind, :city, :website, :owner, :contact_name, :contact_email,
                :application_deadline, :performance_date, :status, :notes
            )
            """,
            data,
        )
    return True


def update_opportunity(form):
    data = form_data(form)
    data["id"] = field_value(form, "id")
    if not data["id"].isdigit() or not data["name"]:
        return False

    with get_connection() as connection:
        cursor = connection.execute(
            """
            UPDATE opportunities
            SET name = :name,
                kind = :kind,
                city = :city,
                website = :website,
                owner = :owner,
                contact_name = :contact_name,
                contact_email = :contact_email,
                application_deadline = :application_deadline,
                performance_date = :performance_date,
                status = :status,
                notes = :notes
            WHERE id = :id
            """,
            data,
        )
    return cursor.rowcount == 1


def delete_opportunity(form):
    opportunity_id = field_value(form, "id")
    if not opportunity_id.isdigit():
        return False

    with get_connection() as connection:
        cursor = connection.execute(
            "DELETE FROM opportunities WHERE id = ?",
            (opportunity_id,),
        )
    return cursor.rowcount == 1


def save_availability(form):
    owner = field_value(form, "owner")
    available_date = field_value(form, "available_date")
    notes = field_value(form, "notes")
    if owner not in ("Frank", "Michael", "Heiner") or not is_valid_date(available_date):
        return False

    with get_connection() as connection:
        connection.execute(
            """
            INSERT INTO availability (owner, available_date, notes)
            VALUES (?, ?, ?)
            """,
            (owner, available_date, notes),
        )
    return True


def delete_availability(form):
    availability_id = field_value(form, "id")
    if not availability_id.isdigit():
        return False

    with get_connection() as connection:
        cursor = connection.execute(
            "DELETE FROM availability WHERE id = ?",
            (availability_id,),
        )
    return cursor.rowcount == 1


def list_availability(month_value):
    year, month = parse_month(month_value)
    start = date(year, month, 1)
    last_day = calendar.monthrange(year, month)[1]
    end = date(year, month, last_day)

    with get_connection() as connection:
        rows = connection.execute(
            """
            SELECT *
            FROM availability
            WHERE available_date BETWEEN ? AND ?
            ORDER BY available_date, owner, created_at
            """,
            (start.isoformat(), end.isoformat()),
        ).fetchall()

    by_day = {}
    for row in rows:
        by_day.setdefault(row["available_date"], []).append(row)
    return by_day


def is_valid_date(value):
    try:
        datetime.strptime(value, "%Y-%m-%d")
        return True
    except ValueError:
        return False


def parse_month(value):
    try:
        parsed = datetime.strptime(value, "%Y-%m")
        return parsed.year, parsed.month
    except (TypeError, ValueError):
        today = date.today()
        return today.year, today.month


def shift_month(year, month, offset):
    month_index = (year * 12 + month - 1) + offset
    shifted_year = month_index // 12
    shifted_month = month_index % 12 + 1
    return f"{shifted_year:04d}-{shifted_month:02d}"


def get_opportunity(opportunity_id):
    if not opportunity_id or not opportunity_id.isdigit():
        return None

    with get_connection() as connection:
        return connection.execute(
            "SELECT * FROM opportunities WHERE id = ?",
            (opportunity_id,),
        ).fetchone()


def filter_value(filters, key, default=""):
    if not filters:
        return default
    return filters.get(key, [default])[0].strip()


def has_active_filters(filters):
    return any(
        filter_value(filters, key)
        for key in ("q", "kind", "status", "owner")
    )


def list_opportunities(filters=None):
    where = []
    params = {}

    search = filter_value(filters, "q")
    if search:
        params["search"] = f"%{search}%"
        where.append(
            """
            (
                name LIKE :search
                OR city LIKE :search
                OR website LIKE :search
                OR contact_name LIKE :search
                OR contact_email LIKE :search
                OR notes LIKE :search
            )
            """
        )

    for key in ("kind", "status", "owner"):
        value = filter_value(filters, key)
        if value:
            params[key] = value
            where.append(f"{key} = :{key}")

    sort_options = {
        "priority": """
            CASE status
                WHEN 'Bewerben' THEN 1
                WHEN 'Recherche' THEN 2
                WHEN 'Kontaktiert' THEN 3
                WHEN 'Zusage' THEN 4
                WHEN 'Absage' THEN 5
                ELSE 6
            END,
            application_deadline IS NULL,
            application_deadline,
            created_at DESC
        """,
        "deadline": "application_deadline IS NULL, application_deadline, created_at DESC",
        "newest": "created_at DESC",
        "name": "LOWER(name), created_at DESC",
        "city": "LOWER(city), LOWER(name), created_at DESC",
    }
    order_by = sort_options.get(filter_value(filters, "sort", "priority"), sort_options["priority"])
    where_sql = f"WHERE {' AND '.join(where)}" if where else ""

    with get_connection() as connection:
        return connection.execute(
            f"""
            SELECT *
            FROM opportunities
            {where_sql}
            ORDER BY {order_by}
            """,
            params,
        ).fetchall()


def selected(current, value):
    return " selected" if (current or "") == value else ""


def row_field(row, key, default=""):
    if row is None:
        return default
    return row[key] or ""


def option(value, current, label=None):
    label = label or value
    return f'<option value="{escape(value)}"{selected(current, value)}>{escape(label)}</option>'


def render_filter_form(filters):
    q = filter_value(filters, "q")
    kind = filter_value(filters, "kind")
    status = filter_value(filters, "status")
    owner = filter_value(filters, "owner")
    sort = filter_value(filters, "sort", "priority")

    return f"""
    <form method="get" action="/" class="filter-panel">
        <label>
            Suche
            <input name="q" value="{escape(q)}" placeholder="Name, Ort, Kontakt, Notiz">
        </label>
        <label>
            Art
            <select name="kind">
                {option("", kind, "Alle Arten")}
                {option("Festival", kind)}
                {option("Kneipe", kind)}
                {option("Club", kind)}
                {option("Kulturzentrum", kind)}
                {option("Open Air", kind)}
                {option("Location", kind)}
            </select>
        </label>
        <label>
            Status
            <select name="status">
                {option("", status, "Alle Status")}
                {option("Recherche", status)}
                {option("Bewerben", status)}
                {option("Kontaktiert", status)}
                {option("Zusage", status)}
                {option("Absage", status)}
            </select>
        </label>
        <label>
            Verantwortlicher
            <select name="owner">
                {option("", owner, "Alle")}
                {option("Frank", owner)}
                {option("Michael", owner)}
                {option("Heiner", owner)}
            </select>
        </label>
        <label>
            Sortierung
            <select name="sort">
                {option("priority", sort, "Status und Frist")}
                {option("deadline", sort, "Frist zuerst")}
                {option("newest", sort, "Neueste zuerst")}
                {option("name", sort, "Name A-Z")}
                {option("city", sort, "Ort A-Z")}
            </select>
        </label>
        <div class="filter-actions">
            <button type="submit">Anwenden</button>
            <a class="cancel-link" href="/">Zurücksetzen</a>
        </div>
    </form>
    """


def render_availability_section(filters):
    month_value = filter_value(filters, "month", date.today().strftime("%Y-%m"))
    year, month = parse_month(month_value)
    month_value = f"{year:04d}-{month:02d}"
    month_name = f"{MONTH_NAMES[month]} {year}"
    availability_by_day = list_availability(month_value)
    weeks = calendar.Calendar(firstweekday=0).monthdatescalendar(year, month)

    cells = []
    for week in weeks:
        for day in week:
            day_key = day.isoformat()
            is_other_month = day.month != month
            entries = availability_by_day.get(day_key, [])
            entry_html = "\n".join(render_availability_entry(row) for row in entries)
            classes = "calendar-day"
            if is_other_month:
                classes += " muted-day"
            if entries:
                classes += " has-availability"
            cells.append(
                f"""
                <div class="{classes}">
                    <div class="day-number">{day.day}</div>
                    <div class="availability-list">{entry_html}</div>
                </div>
                """
            )

    return f"""
    <section class="panel availability-panel" aria-labelledby="availability-calendar">
        <div class="section-heading dark-heading">
            <div>
                <p class="eyebrow">Band-Kalender</p>
                <h2 id="availability-calendar">Verfügbarkeiten für Konzerte</h2>
            </div>
            <div class="calendar-nav">
                <a class="cancel-link" href="/?month={shift_month(year, month, -1)}">Zurück</a>
                <span class="calendar-month">{escape(month_name)}</span>
                <a class="cancel-link" href="/?month={shift_month(year, month, 1)}">Weiter</a>
            </div>
        </div>

        <form method="post" action="/availability/add" class="availability-form">
            <label>
                Verantwortlicher
                <select name="owner" required>
                    {option("Frank", "")}
                    {option("Michael", "")}
                    {option("Heiner", "")}
                </select>
            </label>
            <label>
                Datum
                <input name="available_date" type="date" required>
            </label>
            <label>
                Notiz
                <input name="notes" placeholder="z. B. abends, ganzer Tag, nur Nähe Duisburg">
            </label>
            <button type="submit">Zeit eintragen</button>
        </form>

        <div class="calendar-grid calendar-weekdays">
            <span>Mo</span>
            <span>Di</span>
            <span>Mi</span>
            <span>Do</span>
            <span>Fr</span>
            <span>Sa</span>
            <span>So</span>
        </div>
        <div class="calendar-grid">
            {"".join(cells)}
        </div>
    </section>
    """


def render_availability_entry(row):
    notes = escape(row["notes"] or "")
    notes_html = f'<span class="availability-note">{notes}</span>' if notes else ""
    return f"""
    <form method="post" action="/availability/delete" class="availability-entry owner-{escape(row["owner"]).lower()}">
        <input type="hidden" name="id" value="{escape(str(row["id"]))}">
        <span>{escape(row["owner"])}</span>
        {notes_html}
        <button type="submit" title="Eintrag löschen">×</button>
    </form>
    """


def render_page(message="", edit_row=None, filters=None):
    filters = filters or {}
    opportunities = list_opportunities(filters)
    cards = "\n".join(render_card(row) for row in opportunities)
    is_editing = edit_row is not None
    form_title = "Eintrag bearbeiten" if is_editing else "Neue Möglichkeit eintragen"
    form_action = "/update" if is_editing else "/add"
    submit_label = "Änderungen speichern" if is_editing else "Eintrag speichern"
    cancel_link = '<a class="cancel-link" href="/">Bearbeitung abbrechen</a>' if is_editing else ""
    hidden_id = f'<input type="hidden" name="id" value="{escape(str(edit_row["id"]))}">' if is_editing else ""

    kind = row_field(edit_row, "kind", "Festival")
    owner = row_field(edit_row, "owner")
    status = row_field(edit_row, "status", "Recherche")

    empty_state_text = (
        "Keine Einträge passen zu diesen Filtern."
        if has_active_filters(filters)
        else "Füge Festivals, Kneipen, Clubs oder Kulturorte hinzu. Die Liste bleibt in der SQLite-Datei auf deinem Rechner gespeichert."
    )
    empty_state = (
        f"""
        <section class="empty-state">
            <h2>Noch keine Konzertchancen eingetragen</h2>
            <p>{empty_state_text}</p>
        </section>
        """
        if not opportunities
        else ""
    )

    safe_message = (
        f'<p class="message">{escape(message)}</p>'
        if message
        else ""
    )

    return f"""<!doctype html>
<html lang="de">
<head>
    <meta charset="utf-8">
    <meta name="viewport" content="width=device-width, initial-scale=1">
    <title>Band Booking Planner</title>
    <link rel="stylesheet" href="/style.css">
</head>
<body>
    <header class="topbar">
        <div class="hero-inner">
            <img class="band-logo" src="/logo.png" alt="Die Bauern Logo">
            <div class="hero-copy">
            <p class="eyebrow">Die Bauern Booking</p>
            <h1>Konzerte, Festivals und Locations sammeln</h1>
            <p class="intro">Halte Links, Kontakte, Fristen und Bewerbungsstatus an einem Ort fest, damit deine nächste Anfrage nicht in losen Notizen verschwindet.</p>
            </div>
        </div>
    </header>

    <main class="layout">
        <section class="panel form-panel" aria-labelledby="new-opportunity">
            <h2 id="new-opportunity">{form_title}</h2>
            {safe_message}
            <form method="post" action="{form_action}" class="entry-form">
                {hidden_id}
                <label>
                    Name der Location oder des Festivals
                    <input name="name" required value="{escape(row_field(edit_row, "name"))}" placeholder="z. B. Hafenklang, Stadtfest, Kulturkneipe">
                </label>

                <div class="grid-two">
                    <label>
                        Art
                        <select name="kind">
                            {option("Festival", kind)}
                            {option("Kneipe", kind)}
                            {option("Club", kind)}
                            {option("Kulturzentrum", kind)}
                            {option("Open Air", kind)}
                            {option("Location", kind)}
                        </select>
                    </label>
                    <label>
                        Ort
                        <input name="city" value="{escape(row_field(edit_row, "city"))}" placeholder="Stadt oder Region">
                    </label>
                </div>

                <label>
                    Link zur Webseite oder Ausschreibung
                    <input name="website" value="{escape(row_field(edit_row, "website"))}" placeholder="https://...">
                </label>

                <label>
                    Verantwortlicher
                    <select name="owner">
                        {option("", owner, "Noch offen")}
                        {option("Frank", owner)}
                        {option("Michael", owner)}
                        {option("Heiner", owner)}
                    </select>
                </label>

                <div class="grid-two">
                    <label>
                        Kontaktperson
                        <input name="contact_name" value="{escape(row_field(edit_row, "contact_name"))}" placeholder="Name, Booking-Team, Veranstalter">
                    </label>
                    <label>
                        Kontakt-E-Mail
                        <input name="contact_email" type="email" value="{escape(row_field(edit_row, "contact_email"))}" placeholder="booking@example.de">
                    </label>
                </div>

                <div class="grid-two">
                    <label>
                        Bewerbungsfrist
                        <input name="application_deadline" type="date" value="{escape(row_field(edit_row, "application_deadline"))}">
                    </label>
                    <label>
                        Auftrittsdatum
                        <input name="performance_date" type="date" value="{escape(row_field(edit_row, "performance_date"))}">
                    </label>
                </div>

                <div class="grid-two">
                    <label>
                        Status
                        <select name="status">
                            {option("Recherche", status)}
                            {option("Bewerben", status)}
                            {option("Kontaktiert", status)}
                            {option("Zusage", status)}
                            {option("Absage", status)}
                        </select>
                    </label>
                </div>

                <label>
                    Notizen für die Bewerbung
                    <textarea name="notes" rows="5" placeholder="Genre, Bewerbungsformular, Gage, Technik, warum es passt...">{escape(row_field(edit_row, "notes"))}</textarea>
                </label>

                <div class="form-actions">
                    <button type="submit">{submit_label}</button>
                    {cancel_link}
                </div>
            </form>
        </section>

        <section class="opportunity-list" aria-labelledby="saved-opportunities">
            <div class="section-heading">
                <div>
                    <p class="eyebrow">Gespeichert</p>
                    <h2 id="saved-opportunities">Deine Konzertliste</h2>
                </div>
                <span class="counter">{len(opportunities)} Einträge</span>
            </div>
            {render_filter_form(filters)}
            {empty_state}
            <div class="cards">{cards}</div>
        </section>
        {render_availability_section(filters)}
    </main>
</body>
</html>"""


def render_card(row):
    website = escape(row["website"] or "")
    website_link = (
        f'<a class="link-button" href="{website}" target="_blank" rel="noreferrer">Link öffnen</a>'
        if website
        else ""
    )
    email = escape(row["contact_email"] or "")
    email_link = (
        f'<a class="link-button muted" href="mailto:{email}">E-Mail</a>'
        if email
        else ""
    )
    deadline = escape(row["application_deadline"] or "Keine Frist")
    performance_date = escape(row["performance_date"] or "Noch offen")
    notes = escape(row["notes"] or "Noch keine Notizen")
    contact = escape(row["contact_name"] or "Kontakt offen")
    city_value = row["city"] or ""
    city = escape(city_value or "Ort offen")
    maps_link = (
        f'<a class="text-link" href="https://www.google.com/maps/search/?api=1&query={quote_plus(city_value)}" target="_blank" rel="noreferrer">In Maps öffnen</a>'
        if city_value
        else ""
    )
    owner = escape(row["owner"] or "Noch offen")
    row_id = escape(str(row["id"]))

    return f"""
    <article class="card">
        <div class="card-header">
            <div>
                <p class="type">{escape(row["kind"])}</p>
                <h3>{escape(row["name"])}</h3>
            </div>
            <span class="status">{escape(row["status"])}</span>
        </div>
        <dl class="meta">
            <div><dt>Ort</dt><dd>{city}{maps_link}</dd></div>
            <div><dt>Frist</dt><dd>{deadline}</dd></div>
            <div><dt>Auftritt</dt><dd>{performance_date}</dd></div>
            <div><dt>Verantwortlich</dt><dd>{owner}</dd></div>
            <div><dt>Kontakt</dt><dd>{contact}</dd></div>
        </dl>
        <p class="notes">{notes}</p>
        <div class="actions">
            {website_link}
            {email_link}
            <a class="link-button muted" href="/edit?id={row_id}">Bearbeiten</a>
            <form method="post" action="/delete" class="inline-form">
                <input type="hidden" name="id" value="{row_id}">
                <button type="submit" class="danger-button" onclick="return confirm('Diesen Eintrag wirklich löschen?')">Löschen</button>
            </form>
        </div>
    </article>
    """


class BookingHandler(BaseHTTPRequestHandler):
    def do_GET(self):
        parsed = urlparse(self.path)
        path = parsed.path
        query = parse_qs(parsed.query)
        if path == "/style.css":
            self.respond(CSS, "text/css; charset=utf-8")
            return
        if path == "/logo.png":
            self.respond_file(LOGO_PATH, "image/png")
            return
        if path == "/":
            messages = {
                "1": "Eintrag gespeichert.",
                "updated": "Eintrag aktualisiert.",
                "deleted": "Eintrag gelöscht.",
                "availability": "Verfügbarkeit eingetragen.",
                "availability-deleted": "Verfügbarkeit gelöscht.",
            }
            message = messages.get(query.get("saved", [""])[0], "")
            self.respond(render_page(message, filters=query), "text/html; charset=utf-8")
            return
        if path == "/edit":
            edit_row = get_opportunity(query.get("id", [""])[0])
            if edit_row is None:
                self.respond(render_page("Eintrag wurde nicht gefunden."), "text/html; charset=utf-8")
                return
            self.respond(render_page("Du bearbeitest diesen Eintrag.", edit_row), "text/html; charset=utf-8")
            return
        self.send_error(HTTPStatus.NOT_FOUND)

    def do_POST(self):
        path = urlparse(self.path).path
        length = int(self.headers.get("Content-Length", 0))
        body = self.rfile.read(length).decode("utf-8")
        form = parse_qs(body)

        if path == "/add":
            if save_opportunity(form):
                self.redirect("/?saved=1")
                return
            self.respond(render_page("Bitte mindestens einen Namen eintragen."), "text/html; charset=utf-8")
            return

        if path == "/update":
            if update_opportunity(form):
                self.redirect("/?saved=updated")
                return
            self.respond(render_page("Der Eintrag konnte nicht aktualisiert werden."), "text/html; charset=utf-8")
            return

        if path == "/delete":
            if delete_opportunity(form):
                self.redirect("/?saved=deleted")
                return
            self.respond(render_page("Der Eintrag konnte nicht gelöscht werden."), "text/html; charset=utf-8")
            return

        if path == "/availability/add":
            if save_availability(form):
                month = field_value(form, "available_date")[:7]
                self.redirect(f"/?saved=availability&month={month}")
                return
            self.respond(render_page("Die Verfügbarkeit konnte nicht gespeichert werden."), "text/html; charset=utf-8")
            return

        if path == "/availability/delete":
            if delete_availability(form):
                self.redirect("/?saved=availability-deleted")
                return
            self.respond(render_page("Die Verfügbarkeit konnte nicht gelöscht werden."), "text/html; charset=utf-8")
            return

        self.send_error(HTTPStatus.NOT_FOUND)

    def respond(self, body, content_type):
        encoded = body.encode("utf-8")
        self.send_response(HTTPStatus.OK)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(encoded)))
        self.end_headers()
        self.wfile.write(encoded)

    def respond_file(self, path, content_type):
        if not path.exists():
            self.send_error(HTTPStatus.NOT_FOUND)
            return

        data = path.read_bytes()
        self.send_response(HTTPStatus.OK)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(data)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(data)

    def redirect(self, location):
        self.send_response(HTTPStatus.SEE_OTHER)
        self.send_header("Location", location)
        self.end_headers()

    def log_message(self, format, *args):
        return


CSS = """
:root {
    color-scheme: light;
    --ink: #f5f5f0;
    --panel-ink: #191816;
    --muted: #756f68;
    --line: #ded6c9;
    --panel: #fffdf7;
    --paper: #0a0a0a;
    --accent: #b91c1c;
    --accent-dark: #8f1717;
    --accent-soft: #f8dfd7;
    --danger: #111111;
    --danger-dark: #3b0a0a;
    --warn: #b91c1c;
    --shadow: 0 18px 46px rgba(0, 0, 0, 0.34);
}

* {
    box-sizing: border-box;
}

body {
    margin: 0;
    min-height: 100vh;
    color: var(--ink);
    background:
        radial-gradient(circle at top left, rgba(185, 28, 28, 0.30), transparent 34rem),
        linear-gradient(180deg, #000000 0%, #17130f 58%, #0a0a0a 100%),
        var(--paper);
    font-family: Inter, ui-sans-serif, system-ui, -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif;
}

.topbar {
    padding: 34px clamp(18px, 5vw, 72px) 28px;
    background: #000000;
    color: #f9fbfc;
    border-bottom: 1px solid rgba(255, 255, 255, 0.16);
}

.topbar > div,
.hero-inner {
    max-width: 1180px;
    margin: 0 auto;
}

.hero-inner {
    display: grid;
    grid-template-columns: minmax(130px, 220px) minmax(0, 1fr);
    gap: clamp(22px, 4vw, 48px);
    align-items: center;
}

.band-logo {
    display: block;
    width: min(220px, 42vw);
    aspect-ratio: 1;
    object-fit: contain;
    border: 1px solid rgba(255, 255, 255, 0.20);
    border-radius: 8px;
    background: #000000;
    box-shadow: 0 18px 34px rgba(0, 0, 0, 0.5);
}

.eyebrow {
    margin: 0 0 8px;
    color: var(--accent);
    font-size: 0.78rem;
    font-weight: 800;
    letter-spacing: 0;
    text-transform: uppercase;
}

.topbar .eyebrow {
    color: #ffffff;
}

h1,
h2,
h3,
p {
    overflow-wrap: anywhere;
}

h1 {
    max-width: 760px;
    margin: 0;
    font-size: clamp(2rem, 5vw, 4.4rem);
    line-height: 1.02;
    letter-spacing: 0;
}

.intro {
    max-width: 740px;
    margin: 18px 0 0;
    color: #d8d1c7;
    font-size: 1.08rem;
    line-height: 1.65;
}

.layout {
    display: grid;
    grid-template-columns: minmax(300px, 430px) minmax(0, 1fr);
    gap: 28px;
    width: min(1180px, calc(100% - 32px));
    margin: 28px auto 52px;
    align-items: start;
}

.panel,
.card,
.empty-state {
    color: var(--panel-ink);
    background: var(--panel);
    border: 1px solid var(--line);
    border-radius: 8px;
    box-shadow: var(--shadow);
}

.form-panel {
    padding: 24px;
    position: sticky;
    top: 18px;
}

h2 {
    margin: 0;
    font-size: 1.3rem;
}

.entry-form {
    display: grid;
    gap: 16px;
    margin-top: 20px;
}

label {
    display: grid;
    gap: 7px;
    color: #344451;
    font-size: 0.92rem;
    font-weight: 700;
}

input,
select,
textarea {
    width: 100%;
    min-height: 44px;
    border: 1px solid #bdc8d3;
    border-radius: 6px;
    padding: 11px 12px;
    color: var(--panel-ink);
    background: #fbfdfe;
    font: inherit;
}

input::placeholder,
textarea::placeholder {
    color: #6f6a64;
    opacity: 1;
}

textarea {
    min-height: 118px;
    resize: vertical;
}

input:focus,
select:focus,
textarea:focus {
    border-color: var(--accent);
    outline: 3px solid rgba(185, 28, 28, 0.18);
}

.grid-two {
    display: grid;
    grid-template-columns: 1fr 1fr;
    gap: 14px;
}

button,
.link-button,
.cancel-link {
    display: inline-flex;
    align-items: center;
    justify-content: center;
    min-height: 42px;
    border: 0;
    border-radius: 6px;
    padding: 10px 14px;
    background: var(--accent);
    color: #ffffff;
    font: inherit;
    font-weight: 800;
    text-decoration: none;
    cursor: pointer;
}

button:hover,
.link-button:hover {
    background: var(--accent-dark);
}

.link-button.muted,
.cancel-link {
    background: #e8eef2;
    color: #20313b;
}

.link-button.muted:hover,
.cancel-link:hover {
    background: #d8e2e8;
}

.danger-button {
    background: var(--danger);
}

.danger-button:hover {
    background: var(--danger-dark);
}

.message {
    margin: 14px 0 0;
    border-left: 4px solid var(--accent);
    padding: 10px 12px;
    background: var(--accent-soft);
    color: #17423f;
    font-weight: 700;
}

.opportunity-list {
    min-width: 0;
}

.opportunity-list .section-heading h2 {
    color: #fffdf7;
}

.availability-panel {
    grid-column: 1 / -1;
    padding: 22px;
}

.availability-panel .section-heading {
    margin-bottom: 18px;
}

.availability-panel .section-heading h2 {
    color: var(--panel-ink);
}

.calendar-nav {
    display: flex;
    align-items: center;
    flex-wrap: wrap;
    gap: 10px;
}

.calendar-month {
    min-width: 150px;
    color: var(--panel-ink);
    font-weight: 900;
    text-align: center;
}

.availability-form {
    display: grid;
    grid-template-columns: minmax(140px, 0.8fr) minmax(150px, 0.8fr) minmax(220px, 1.4fr) auto;
    gap: 12px;
    align-items: end;
    margin-bottom: 18px;
}

.calendar-grid {
    display: grid;
    grid-template-columns: repeat(7, minmax(0, 1fr));
}

.calendar-weekdays {
    overflow: hidden;
    border: 1px solid #27221d;
    border-bottom: 0;
    border-radius: 8px 8px 0 0;
    background: #111111;
    color: #fffdf7;
    font-size: 0.78rem;
    font-weight: 900;
    text-transform: uppercase;
}

.calendar-weekdays span {
    padding: 10px;
    text-align: center;
}

.calendar-day {
    min-height: 122px;
    border-right: 1px solid var(--line);
    border-bottom: 1px solid var(--line);
    padding: 9px;
    background: #fffdf7;
}

.calendar-day:nth-child(7n + 1) {
    border-left: 1px solid var(--line);
}

.muted-day {
    background: #eee8de;
    color: #8a8076;
}

.has-availability {
    background: #fff8ef;
}

.day-number {
    margin-bottom: 7px;
    font-size: 0.82rem;
    font-weight: 900;
}

.availability-list {
    display: grid;
    gap: 6px;
}

.availability-entry {
    display: grid;
    grid-template-columns: minmax(0, 1fr) auto;
    gap: 4px 6px;
    align-items: center;
    margin: 0;
    border-radius: 6px;
    padding: 7px;
    color: #ffffff;
    font-size: 0.78rem;
    font-weight: 900;
}

.availability-entry button {
    min-width: 24px;
    min-height: 24px;
    padding: 0;
    background: rgba(0, 0, 0, 0.28);
}

.availability-entry button:hover {
    background: rgba(0, 0, 0, 0.46);
}

.availability-note {
    grid-column: 1 / -1;
    font-size: 0.74rem;
    font-weight: 700;
    opacity: 0.88;
}

.owner-frank {
    background: #9f1239;
}

.owner-michael {
    background: #1d4ed8;
}

.owner-heiner {
    background: #166534;
}

.section-heading {
    display: flex;
    align-items: center;
    justify-content: space-between;
    gap: 16px;
    margin-bottom: 16px;
}

.filter-panel {
    display: grid;
    grid-template-columns: minmax(160px, 1.3fr) repeat(4, minmax(130px, 1fr));
    gap: 12px;
    align-items: end;
    margin-bottom: 16px;
    padding: 16px;
    color: var(--panel-ink);
    background: var(--panel);
    border: 1px solid var(--line);
    border-radius: 8px;
    box-shadow: var(--shadow);
}

.filter-actions {
    display: flex;
    gap: 10px;
}

.filter-actions button,
.filter-actions .cancel-link {
    width: 100%;
}

.counter,
.status {
    flex: 0 0 auto;
    border-radius: 999px;
    padding: 7px 10px;
    background: var(--accent-soft);
    color: #611111;
    font-size: 0.82rem;
    font-weight: 800;
}

.cards {
    display: grid;
    gap: 16px;
}

.card {
    padding: 20px;
}

.card-header {
    display: flex;
    justify-content: space-between;
    gap: 16px;
}

.type {
    margin: 0 0 6px;
    color: var(--warn);
    font-size: 0.8rem;
    font-weight: 800;
    text-transform: uppercase;
}

h3 {
    margin: 0;
    font-size: 1.25rem;
}

.meta {
    display: grid;
    grid-template-columns: repeat(5, minmax(0, 1fr));
    gap: 12px;
    margin: 18px 0;
}

.meta div {
    min-width: 0;
    border-top: 1px solid var(--line);
    padding-top: 10px;
}

dt {
    color: var(--muted);
    font-size: 0.78rem;
    font-weight: 800;
    text-transform: uppercase;
}

dd {
    margin: 4px 0 0;
    overflow-wrap: anywhere;
}

.text-link {
    display: block;
    width: fit-content;
    margin-top: 6px;
    color: var(--accent);
    font-size: 0.88rem;
    font-weight: 800;
    text-decoration: none;
}

.text-link:hover {
    color: var(--accent-dark);
    text-decoration: underline;
}

.notes {
    margin: 0;
    color: #3d4d59;
    line-height: 1.55;
    white-space: pre-wrap;
}

.actions,
.form-actions {
    display: flex;
    flex-wrap: wrap;
    gap: 10px;
    margin-top: 18px;
}

.form-actions {
    margin-top: 0;
}

.inline-form {
    margin: 0;
}

.empty-state {
    padding: 26px;
}

.empty-state p {
    margin-bottom: 0;
    color: var(--muted);
    line-height: 1.6;
}

@media (max-width: 920px) {
    .layout {
        grid-template-columns: 1fr;
    }

    .form-panel {
        position: static;
    }

    .hero-inner {
        grid-template-columns: minmax(100px, 160px) minmax(0, 1fr);
    }

    .filter-panel {
        grid-template-columns: 1fr 1fr;
    }

    .filter-actions {
        grid-column: 1 / -1;
    }

    .availability-form {
        grid-template-columns: 1fr 1fr;
    }

    .availability-form button {
        grid-column: 1 / -1;
    }
}

@media (max-width: 780px) {
    .meta {
        grid-template-columns: repeat(2, minmax(0, 1fr));
    }
}

@media (max-width: 620px) {
    .topbar {
        padding-top: 32px;
    }

    .hero-inner {
        grid-template-columns: 1fr;
    }

    .band-logo {
        width: min(180px, 58vw);
    }

    .layout {
        width: min(100% - 22px, 1180px);
        margin-top: 18px;
    }

    .grid-two,
    .meta,
    .filter-panel {
        grid-template-columns: 1fr;
    }

    .filter-actions {
        flex-direction: column;
    }

    .availability-form,
    .calendar-grid {
        grid-template-columns: 1fr;
    }

    .calendar-weekdays {
        display: none;
    }

    .calendar-day {
        min-height: auto;
        border-left: 1px solid var(--line);
    }

    .section-heading,
    .card-header {
        align-items: flex-start;
        flex-direction: column;
    }

    .form-panel,
    .card,
    .empty-state {
        padding: 18px;
    }
}
"""


def main():
    init_db()
    server = ThreadingHTTPServer((APP_HOST, APP_PORT), BookingHandler)
    print(f"Band Booking Planner läuft auf http://{APP_HOST}:{APP_PORT}")
    if os.environ.get("BOOKING_OPEN_BROWSER", "1") == "1":
        try:
            webbrowser.open(f"http://{APP_HOST}:{APP_PORT}")
        except Exception:
            pass
    server.serve_forever()


if __name__ == "__main__":
    main()
