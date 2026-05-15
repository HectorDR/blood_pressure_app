import csv
import io
import statistics
from flask import Flask, request, jsonify, render_template, Response
from database import get_db, init_db
from datetime import datetime, timedelta, date

app = Flask(__name__)


def classify_bp(systolic, diastolic):
    if systolic > 180 or diastolic > 120:
        return "Hypertensive Crisis", "#c0392b"
    if systolic >= 140 or diastolic >= 90:
        return "High - Stage 2", "#e74c3c"
    if systolic >= 130 or diastolic >= 80:
        return "High - Stage 1", "#e67e22"
    if 120 <= systolic <= 129 and diastolic < 80:
        return "Elevated", "#f39c12"
    if systolic < 90 or diastolic < 60:
        return "Low (Hypotension)", "#2980b9"
    return "Normal", "#27ae60"


def calc_age(dob_str):
    dob = date.fromisoformat(dob_str)
    today = date.today()
    return today.year - dob.year - ((today.month, today.day) < (dob.month, dob.day))


def row_to_dict(row):
    return dict(row)


# ── Users ──────────────────────────────────────────────────────────────────────

@app.route("/api/users", methods=["GET"])
def list_users():
    with get_db() as conn:
        rows = conn.execute("SELECT * FROM users ORDER BY name").fetchall()
    users = []
    for r in rows:
        u = row_to_dict(r)
        u["age"] = calc_age(u["date_of_birth"])
        users.append(u)
    return jsonify(users)


@app.route("/api/users", methods=["POST"])
def create_user():
    data = request.get_json()
    name = (data.get("name") or "").strip()
    dob = (data.get("date_of_birth") or "").strip()
    if not name or not dob:
        return jsonify({"error": "name and date_of_birth are required"}), 400
    with get_db() as conn:
        cur = conn.execute(
            "INSERT INTO users (name, date_of_birth) VALUES (?, ?)", (name, dob)
        )
        user_id = cur.lastrowid
        row = conn.execute("SELECT * FROM users WHERE id = ?", (user_id,)).fetchone()
    u = row_to_dict(row)
    u["age"] = calc_age(u["date_of_birth"])
    return jsonify(u), 201


@app.route("/api/users/<int:user_id>", methods=["GET"])
def get_user(user_id):
    with get_db() as conn:
        row = conn.execute("SELECT * FROM users WHERE id = ?", (user_id,)).fetchone()
    if not row:
        return jsonify({"error": "User not found"}), 404
    u = row_to_dict(row)
    u["age"] = calc_age(u["date_of_birth"])
    return jsonify(u)


@app.route("/api/users/<int:user_id>", methods=["DELETE"])
def delete_user(user_id):
    with get_db() as conn:
        conn.execute("DELETE FROM users WHERE id = ?", (user_id,))
    return jsonify({"ok": True})


# ── Readings ───────────────────────────────────────────────────────────────────

@app.route("/api/readings/<int:user_id>", methods=["GET"])
def list_readings(user_id):
    with get_db() as conn:
        rows = conn.execute(
            "SELECT * FROM readings WHERE user_id = ? ORDER BY reading_date DESC",
            (user_id,),
        ).fetchall()
    result = []
    for r in rows:
        rd = row_to_dict(r)
        cat, color = classify_bp(rd["systolic"], rd["diastolic"])
        rd["category"] = cat
        rd["color"] = color
        result.append(rd)
    return jsonify(result)


@app.route("/api/readings/<int:user_id>", methods=["POST"])
def add_reading(user_id):
    data = request.get_json()
    systolic = data.get("systolic")
    diastolic = data.get("diastolic")
    pulse = data.get("pulse") or None
    reading_date = data.get("reading_date") or datetime.now().strftime("%Y-%m-%dT%H:%M")
    notes = (data.get("notes") or "").strip() or None

    if systolic is None or diastolic is None:
        return jsonify({"error": "systolic and diastolic are required"}), 400

    with get_db() as conn:
        cur = conn.execute(
            "INSERT INTO readings (user_id, systolic, diastolic, pulse, reading_date, notes) VALUES (?,?,?,?,?,?)",
            (user_id, int(systolic), int(diastolic), int(pulse) if pulse else None, reading_date, notes),
        )
        reading_id = cur.lastrowid
        row = conn.execute("SELECT * FROM readings WHERE id = ?", (reading_id,)).fetchone()

    rd = row_to_dict(row)
    cat, color = classify_bp(rd["systolic"], rd["diastolic"])
    rd["category"] = cat
    rd["color"] = color
    return jsonify(rd), 201


@app.route("/api/readings/<int:user_id>/export", methods=["GET"])
def export_readings(user_id):
    period = request.args.get("period", "all")
    now = datetime.now()

    if period == "week":
        since, label = (now - timedelta(days=7)).isoformat(), "last_week"
    elif period == "month":
        since, label = (now - timedelta(days=30)).isoformat(), "last_month"
    elif period == "year":
        since, label = (now - timedelta(days=365)).isoformat(), "last_year"
    else:
        since, label = "1900-01-01", "all_time"

    with get_db() as conn:
        user = conn.execute("SELECT name FROM users WHERE id = ?", (user_id,)).fetchone()
        rows = conn.execute(
            "SELECT reading_date, systolic, diastolic, pulse, notes FROM readings "
            "WHERE user_id = ? AND reading_date >= ? ORDER BY reading_date DESC",
            (user_id, since),
        ).fetchall()

    output = io.StringIO()
    writer = csv.writer(output)
    writer.writerow(["Date & Time", "Systolic (mmHg)", "Diastolic (mmHg)", "Pulse (bpm)", "Category", "Notes"])
    for r in rows:
        rd = row_to_dict(r)
        cat, _ = classify_bp(rd["systolic"], rd["diastolic"])
        writer.writerow([rd["reading_date"], rd["systolic"], rd["diastolic"],
                         rd["pulse"] or "", cat, rd["notes"] or ""])

    username = user["name"].replace(" ", "_") if user else "user"
    filename = f"bp_{username}_{label}.csv"
    return Response(output.getvalue(), mimetype="text/csv",
                    headers={"Content-Disposition": f"attachment; filename={filename}"})


@app.route("/api/readings/<int:reading_id>", methods=["DELETE"])
def delete_reading(reading_id):
    with get_db() as conn:
        conn.execute("DELETE FROM readings WHERE id = ?", (reading_id,))
    return jsonify({"ok": True})


@app.route("/api/readings/<int:user_id>/chart", methods=["GET"])
def chart_data(user_id):
    period = request.args.get("period", "all")
    now = datetime.now()

    if period == "week":
        since = (now - timedelta(days=7)).isoformat()
    elif period == "month":
        since = (now - timedelta(days=30)).isoformat()
    elif period == "year":
        since = (now - timedelta(days=365)).isoformat()
    else:
        since = "1900-01-01"

    with get_db() as conn:
        rows = conn.execute(
            "SELECT reading_date, systolic, diastolic, pulse FROM readings "
            "WHERE user_id = ? AND reading_date >= ? ORDER BY reading_date ASC",
            (user_id, since),
        ).fetchall()

    points = [row_to_dict(r) for r in rows]
    return jsonify(points)


# ── Report ─────────────────────────────────────────────────────────────────────

@app.route("/api/readings/<int:user_id>/report", methods=["GET"])
def report_data(user_id):
    period = request.args.get("period", "month")
    now = datetime.now()

    if period == "week":
        since = (now - timedelta(days=7)).isoformat()
    elif period == "month":
        since = (now - timedelta(days=30)).isoformat()
    elif period == "ytd":
        since = date(now.year, 1, 1).isoformat()
    elif period == "year":
        since = (now - timedelta(days=365)).isoformat()
    else:
        since = "1900-01-01"

    with get_db() as conn:
        rows = conn.execute(
            "SELECT systolic, diastolic, pulse FROM readings "
            "WHERE user_id = ? AND reading_date >= ? ORDER BY reading_date ASC",
            (user_id, since),
        ).fetchall()

    readings = [row_to_dict(r) for r in rows]

    def compute_stats(values):
        if not values:
            return None
        modes = statistics.multimode(values)
        return {
            "count": len(values),
            "mean": round(statistics.mean(values), 1),
            "mode": modes[0] if len(modes) == 1 else None,
            "stdev": round(statistics.stdev(values), 1) if len(values) > 1 else 0.0,
            "min": min(values),
            "max": max(values),
        }

    categories = {}
    for r in readings:
        cat, color = classify_bp(r["systolic"], r["diastolic"])
        if cat not in categories:
            categories[cat] = {"count": 0, "color": color}
        categories[cat]["count"] += 1

    pulse_vals = [r["pulse"] for r in readings if r["pulse"] is not None]
    return jsonify({
        "count": len(readings),
        "systolic": compute_stats([r["systolic"] for r in readings]),
        "diastolic": compute_stats([r["diastolic"] for r in readings]),
        "pulse": compute_stats(pulse_vals) if pulse_vals else None,
        "categories": categories,
    })


# ── Main ───────────────────────────────────────────────────────────────────────

@app.route("/")
def index():
    return render_template("index.html")


if __name__ == "__main__":
    init_db()
    app.run(debug=True, port=8080)
