from flask import Flask, render_template, request, redirect, url_for, jsonify, flash, session
import sqlite3
import datetime
import os
import json

from config import Config
from db import get_db, init_db
from ai_engine import AIEngine
from traffic_service import smart_arrival_service, SimulatedTrafficProvider

app = Flask(__name__)
app.config.from_object(Config)

# ---------------------------------------------------------
# Context Processors & Template Helpers
# ---------------------------------------------------------
@app.context_processor
def inject_global_vars():
    return {
        "categories": Config.SUPPORTED_CATEGORIES,
        "traffic_conditions": SimulatedTrafficProvider.TRAFFIC_CONDITIONS,
        "distance_presets": SimulatedTrafficProvider.DISTANCE_PRESETS,
        "now": datetime.datetime.now()
    }

# ---------------------------------------------------------
# Customer Facing Routes
# ---------------------------------------------------------

@app.route("/")
def home():
    """Homepage with hero, category selection, live preview, and AI features."""
    connection = get_db()
    # Fetch demo organization for the live hero preview
    preview_org = connection.execute("SELECT * FROM organizations WHERE slug = 'sunrise-clinic'").fetchone()
    if not preview_org:
        preview_org = connection.execute("SELECT * FROM organizations LIMIT 1").fetchone()
        
    # Get active stats for hero
    total_waiting = connection.execute("SELECT COUNT(*) as cnt FROM queue WHERE status = 'Waiting'").fetchone()["cnt"]
    total_served = connection.execute("SELECT COUNT(*) as cnt FROM queue WHERE status = 'Completed'").fetchone()["cnt"]
    total_orgs = connection.execute("SELECT COUNT(*) as cnt FROM organizations").fetchone()["cnt"]
    
    connection.close()
    return render_template(
        "index.html",
        preview_org=preview_org,
        total_waiting=total_waiting,
        total_served=total_served,
        total_orgs=total_orgs
    )

@app.route("/explore")
def explore():
    """Search & Filter registered organizations across the 6 supported categories."""
    category_filter = request.args.get("category", "").strip()
    search_query = request.args.get("q", "").strip()

    connection = get_db()
    query = "SELECT * FROM organizations WHERE 1=1"
    params = []

    if category_filter:
        query += " AND category = ?"
        params.append(category_filter)
    if search_query:
        query += " AND (name LIKE ? OR description LIKE ? OR address LIKE ?)"
        params.extend([f"%{search_query}%", f"%{search_query}%", f"%{search_query}%"])

    query += " ORDER BY id ASC"
    orgs = connection.execute(query, params).fetchall()

    # Enhance each org with live queue statistics
    enriched_orgs = []
    for org in orgs:
        waiting_cnt = connection.execute(
            "SELECT COUNT(*) as cnt FROM queue WHERE org_id = ? AND status = 'Waiting'",
            (org["id"],)
        ).fetchone()["cnt"]
        
        active_counters = connection.execute(
            "SELECT COUNT(*) as cnt FROM counters WHERE org_id = ? AND status = 'Active'",
            (org["id"],)
        ).fetchone()["cnt"]

        # AI estimated wait time for next joiner
        avg_duration = connection.execute(
            "SELECT AVG(avg_duration_min) as avg_d FROM services WHERE org_id = ?",
            (org["id"],)
        ).fetchone()["avg_d"] or 15.0

        ai_pred = AIEngine.predict_waiting_time(
            people_ahead=waiting_cnt,
            avg_service_time_min=float(avg_duration),
            active_counters=active_counters,
            priority="Normal"
        )

        org_dict = dict(org)
        org_dict["waiting_count"] = waiting_cnt
        org_dict["active_counters"] = active_counters
        org_dict["predicted_wait_min"] = ai_pred["predicted_wait_min"]
        enriched_orgs.append(org_dict)

    connection.close()
    return render_template(
        "explore.html",
        organizations=enriched_orgs,
        selected_category=category_filter,
        search_query=search_query
    )

@app.route("/join", methods=["GET", "POST"])
def join_queue():
    """Customer Join Queue Form & Service Selection."""
    connection = get_db()

    if request.method == "POST":
        org_id = request.form.get("org_id", type=int)
        service_id = request.form.get("service_id", type=int)
        name = request.form.get("name", "").strip()
        phone = request.form.get("phone", "").strip()
        priority = request.form.get("priority", "Normal")

        if not name:
            name = "Guest Customer"

        # Lookup organization & service
        org = connection.execute("SELECT * FROM organizations WHERE id = ?", (org_id,)).fetchone()
        if not org:
            # Fallback to first available organization if none specified
            org = connection.execute("SELECT * FROM organizations LIMIT 1").fetchone()
            org_id = org["id"]

        service = connection.execute("SELECT * FROM services WHERE id = ?", (service_id,)).fetchone()
        service_name = service["name"] if service else request.form.get("service", "General Service")

        # Generate unique sequential token number for this organization
        max_tok = connection.execute(
            "SELECT MAX(token) as max_t FROM queue WHERE org_id = ?",
            (org_id,)
        ).fetchone()["max_t"] or 0
        next_token = max_tok + 1
        
        # Token string prefix (e.g. H-08, C-12)
        prefix = (org["category"] or "Q")[0].upper()
        token_str = f"{prefix}-{next_token:02d}"

        # Calculate initial AI wait time
        waiting_ahead = connection.execute(
            "SELECT COUNT(*) as cnt FROM queue WHERE org_id = ? AND status = 'Waiting'",
            (org_id,)
        ).fetchone()["cnt"]

        active_counters = connection.execute(
            "SELECT COUNT(*) as cnt FROM counters WHERE org_id = ? AND status = 'Active'",
            (org_id,)
        ).fetchone()["cnt"]

        avg_duration = service["avg_duration_min"] if service else 15.0
        ai_pred = AIEngine.predict_waiting_time(
            people_ahead=waiting_ahead,
            avg_service_time_min=float(avg_duration),
            active_counters=active_counters,
            priority=priority
        )

        # Insert into queue table
        cursor = connection.cursor()
        cursor.execute("""
            INSERT INTO queue 
            (org_id, service_id, name, phone, service, priority, token, token_str, status, estimated_wait_min, created_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, 'Waiting', ?, datetime('now'))
        """, (org_id, service_id, name, phone, service_name, priority, next_token, token_str, ai_pred["predicted_wait_min"]))
        
        new_id = cursor.lastrowid
        connection.commit()
        connection.close()

        return redirect(url_for("token_view", token_id=new_id))

    # GET Request: Load organizations and initial services
    org_slug = request.args.get("org")
    selected_org = None
    if org_slug:
        selected_org = connection.execute("SELECT * FROM organizations WHERE slug = ?", (org_slug,)).fetchone()

    all_orgs = connection.execute("SELECT * FROM organizations ORDER BY category, name").fetchall()
    
    # Preload services for selected or first org
    target_org_id = selected_org["id"] if selected_org else (all_orgs[0]["id"] if all_orgs else 1)
    services = connection.execute("SELECT * FROM services WHERE org_id = ?", (target_org_id,)).fetchall()
    
    connection.close()
    return render_template(
        "join.html",
        organizations=all_orgs,
        selected_org=selected_org,
        services=services
    )

@app.route("/token/<int:token_id>")
def token_view(token_id):
    """Digital Token & Active Queue Screen with Live AI Prediction & Smart Arrival."""
    connection = get_db()
    customer = connection.execute("SELECT * FROM queue WHERE id = ?", (token_id,)).fetchone()

    if not customer:
        connection.close()
        return render_template("404.html", message="Queue token not found."), 404

    org_id = customer["org_id"] or 1
    org = connection.execute("SELECT * FROM organizations WHERE id = ?", (org_id,)).fetchone()
    
    # Calculate current people ahead using AI prioritization order
    people_ahead = 0
    if customer["status"] == "Waiting":
        raw_waiting = connection.execute(
            "SELECT * FROM queue WHERE org_id = ? AND status = 'Waiting'",
            (org_id,)
        ).fetchall()
        waiting_list = [dict(row) for row in raw_waiting]
        prioritized_waiting = AIEngine.prioritize_queue(waiting_list)
        for idx, item in enumerate(prioritized_waiting):
            if item["id"] == customer["id"]:
                people_ahead = idx
                break
        else:
            people_ahead = len(prioritized_waiting)

    # Assigned counter info if customer is currently serving
    assigned_counter = None
    if customer["counter_id"]:
        assigned_counter = connection.execute(
            "SELECT * FROM counters WHERE id = ?",
            (customer["counter_id"],)
        ).fetchone()

    # Currently serving token
    current_serving = connection.execute("""
        SELECT * FROM queue WHERE org_id = ? AND status = 'Serving' ORDER BY served_at DESC, id DESC LIMIT 1
    """, (org_id,)).fetchone()

    # Active counters
    active_counters = connection.execute(
        "SELECT COUNT(*) as cnt FROM counters WHERE org_id = ? AND status = 'Active'",
        (org_id,)
    ).fetchone()["cnt"] or 1

    # Fetch crowd status
    crowd_snapshot = connection.execute(
        "SELECT * FROM crowd_snapshots WHERE org_id = ? ORDER BY id DESC LIMIT 1",
        (org_id,)
    ).fetchone()
    crowd_status = crowd_snapshot["density_status"] if crowd_snapshot else "Normal"

    # AI Wait Prediction
    ai_prediction = AIEngine.predict_waiting_time(
        people_ahead=people_ahead,
        avg_service_time_min=15.0,
        active_counters=active_counters,
        priority=customer["priority"],
        crowd_status=crowd_status
    )

    # Initial Smart Arrival calculation (default Moderate traffic, Mid-city distance)
    smart_arrival = smart_arrival_service.calculate_smart_arrival(
        ai_wait_minutes=ai_prediction["predicted_wait_min"],
        traffic_condition="Moderate",
        distance_preset="metro",
        destination_name=org["name"] if org else "Service Center"
    )

    connection.close()
    return render_template(
        "token.html",
        customer=customer,
        org=org,
        people_ahead=people_ahead,
        current_serving=current_serving,
        assigned_counter=assigned_counter,
        ai_prediction=ai_prediction,
        smart_arrival=smart_arrival
    )

@app.route("/live-queue/<slug>")
@app.route("/queue-status")
def live_queue(slug=None):
    """Public Display Board / Live Kiosk View for an organization."""
    connection = get_db()
    
    if not slug:
        first_org = connection.execute("SELECT slug FROM organizations LIMIT 1").fetchone()
        slug = first_org["slug"] if first_org else "metro-care-hospital"

    org = connection.execute("SELECT * FROM organizations WHERE slug = ?", (slug,)).fetchone()
    if not org:
        connection.close()
        return redirect(url_for("explore"))

    # Active Serving Customers across counters
    serving = connection.execute("""
        SELECT q.*, c.name as counter_name, c.counter_number
        FROM queue q
        LEFT JOIN counters c ON q.counter_id = c.id
        WHERE q.org_id = ? AND q.status = 'Serving'
        ORDER BY c.counter_number ASC
    """, (org["id"],)).fetchall()

    # Waiting Customers (ordered by smart priority algorithm)
    raw_waiting = connection.execute("""
        SELECT * FROM queue
        WHERE org_id = ? AND status = 'Waiting'
        ORDER BY id ASC
    """, (org["id"],)).fetchall()

    waiting_list = [dict(row) for row in raw_waiting]
    prioritized_waiting = AIEngine.prioritize_queue(waiting_list)

    # Active counters count
    counters = connection.execute("SELECT * FROM counters WHERE org_id = ? ORDER BY counter_number", (org["id"],)).fetchall()

    connection.close()
    return render_template(
        "live_queue.html",
        org=org,
        serving=serving,
        waiting=prioritized_waiting,
        counters=counters
    )

@app.route("/leave-queue/<int:token_id>", methods=["POST"])
def leave_queue(token_id):
    """Allow customer to leave/cancel their queue spot."""
    connection = get_db()
    connection.execute("UPDATE queue SET status = 'Cancelled' WHERE id = ?", (token_id,))
    connection.commit()
    connection.close()
    flash("You have successfully left the queue.", "info")
    return redirect(url_for("home"))

# ---------------------------------------------------------
# Customer REST APIs
# ---------------------------------------------------------

@app.route("/api/services-by-org/<int:org_id>")
def api_services_by_org(org_id):
    """API returning services for a given organization."""
    connection = get_db()
    services = connection.execute("SELECT * FROM services WHERE org_id = ?", (org_id,)).fetchall()
    connection.close()
    return jsonify([dict(s) for s in services])

@app.route("/api/token-status/<int:token_id>")
def api_token_status(token_id):
    """Live Polling endpoint for active token screen."""
    connection = get_db()
    customer = connection.execute("SELECT * FROM queue WHERE id = ?", (token_id,)).fetchone()
    if not customer:
        connection.close()
        return jsonify({"error": "Token not found"}), 404

    org_id = customer["org_id"]
    
    # Calculate current people ahead using AI prioritization order
    people_ahead = 0
    if customer["status"] == "Waiting":
        raw_waiting = connection.execute(
            "SELECT * FROM queue WHERE org_id = ? AND status = 'Waiting'",
            (org_id,)
        ).fetchall()
        waiting_list = [dict(row) for row in raw_waiting]
        prioritized_waiting = AIEngine.prioritize_queue(waiting_list)
        for idx, item in enumerate(prioritized_waiting):
            if item["id"] == customer["id"]:
                people_ahead = idx
                break
        else:
            people_ahead = len(prioritized_waiting)

    # Look up assigned counter if Serving
    assigned_counter = None
    if customer["counter_id"]:
        counter_row = connection.execute(
            "SELECT * FROM counters WHERE id = ?",
            (customer["counter_id"],)
        ).fetchone()
        if counter_row:
            assigned_counter = {
                "id": counter_row["id"],
                "counter_number": counter_row["counter_number"],
                "name": counter_row["name"],
                "staff_name": counter_row["staff_name"]
            }

    current_serving = connection.execute("""
        SELECT token_str, token FROM queue WHERE org_id = ? AND status = 'Serving' ORDER BY served_at DESC, id DESC LIMIT 1
    """, (org_id,)).fetchone()

    active_counters = connection.execute(
        "SELECT COUNT(*) as cnt FROM counters WHERE org_id = ? AND status = 'Active'",
        (org_id,)
    ).fetchone()["cnt"] or 1

    crowd_snapshot = connection.execute(
        "SELECT density_status FROM crowd_snapshots WHERE org_id = ? ORDER BY id DESC LIMIT 1",
        (org_id,)
    ).fetchone()
    crowd_status = crowd_snapshot["density_status"] if crowd_snapshot else "Normal"

    ai_prediction = AIEngine.predict_waiting_time(
        people_ahead=people_ahead,
        avg_service_time_min=15.0,
        active_counters=active_counters,
        priority=customer["priority"],
        crowd_status=crowd_status
    )

    traffic_cond = request.args.get("traffic", "Moderate")
    distance_preset = request.args.get("distance", "metro")
    
    smart_arrival = smart_arrival_service.calculate_smart_arrival(
        ai_wait_minutes=ai_prediction["predicted_wait_min"],
        traffic_condition=traffic_cond,
        distance_preset=distance_preset
    )

    connection.close()
    return jsonify({
        "status": customer["status"],
        "token_str": customer["token_str"],
        "token": customer["token"],
        "people_ahead": people_ahead,
        "current_serving": current_serving["token_str"] if current_serving else "None",
        "assigned_counter": assigned_counter,
        "is_your_turn": (customer["status"] == "Serving"),
        "ai_prediction": ai_prediction,
        "smart_arrival": smart_arrival
    })

@app.route("/api/calculate-smart-arrival", methods=["POST"])
def api_calculate_smart_arrival():
    """Recomputes Smart Arrival when user switches traffic or travel distance."""
    data = request.get_json() or {}
    ai_wait_minutes = data.get("ai_wait_minutes", 20)
    traffic_condition = data.get("traffic_condition", "Moderate")
    distance_preset = data.get("distance_preset", "metro")
    custom_travel_min = data.get("custom_travel_min")
    destination_name = data.get("destination_name", "Destination Service")

    arrival_data = smart_arrival_service.calculate_smart_arrival(
        ai_wait_minutes=ai_wait_minutes,
        traffic_condition=traffic_condition,
        distance_preset=distance_preset,
        custom_travel_min=custom_travel_min,
        destination_name=destination_name
    )
    return jsonify(arrival_data)

@app.route("/api/chatbot", methods=["POST"])
def api_chatbot():
    """In-app AI Assistant responding to queries about queues, tokens, priorities, and services."""
    data = request.get_json() or {}
    message = data.get("message", "").lower().strip()

    connection = get_db()
    
    # Intelligent response matching
    if "token" in message or "status" in message or "check" in message:
        # Check if user mentioned a token number
        import re
        match = re.search(r'\b\d+\b', message)
        if match:
            tok_num = int(match.group())
            cust = connection.execute("SELECT * FROM queue WHERE token = ? ORDER BY id DESC LIMIT 1", (tok_num,)).fetchone()
            if cust:
                resp = f"Token #{cust['token_str'] or cust['token']} ({cust['name']}) is currently **{cust['status']}** for {cust['service']}. Estimated wait: ~{cust['estimated_wait_min']} min."
            else:
                resp = f"I couldn't find an active token #{tok_num}. Please double-check your token number or join a new queue."
        else:
            resp = "To check your active queue status, enter your token number or click 'Check Queue Status' in the navigation."

    elif "traffic" in message or "smart arrival" in message or "leave" in message:
        resp = "🚗 **Smart Arrival** combines AI queue predictions with simulated traffic data to calculate your optimal departure time. Choose your distance and traffic condition on your Token page to see when to leave home!"

    elif "priority" in message or "senior" in message or "emergency" in message:
        resp = "⚡ **Priority Smart Routing** supports: **Emergency** (immediate fast-track), **Senior Citizens**, **Appointments**, and **Special Services**. Our AI scheduler balances priorities fairly without starving standard queues."

    elif "hospital" in message or "clinic" in message or "salon" in message or "restaurant" in message or "service" in message or "college" in message:
        resp = "We currently support 6 organization types: 🏥 **Hospitals**, 🩺 **Clinics**, 💇 **Salons**, 🔧 **Service Centers**, 🍽️ **Restaurants**, and 🎓 **Schools & Colleges**. Head to the **Explore** page to find an organization."

    elif "ai" in message or "predict" in message or "work" in message:
        resp = "🧠 Our **AI Engine** calculates wait times dynamically using active counter speeds, people ahead, weighted priority routing, and real-time crowd congestion telemetry."

    else:
        resp = "Hello! I am your **AI Queue Assistant** ✦. I can help you check your token status, explain Smart Arrival departure times, find services across our 6 supported sectors, or explain priority queueing."

    connection.close()
    return jsonify({"response": resp})

# ---------------------------------------------------------
# Organization Registration
# ---------------------------------------------------------

@app.route("/register-org", methods=["GET", "POST"])
def register_org():
    """Register a new organization across the 6 supported categories."""
    if request.method == "POST":
        name = request.form.get("name", "").strip()
        category = request.form.get("category", "").strip()
        address = request.form.get("address", "").strip()
        contact = request.form.get("contact", "").strip()
        description = request.form.get("description", "").strip()
        total_counters = request.form.get("total_counters", type=int) or 3
        service_names = request.form.getlist("service_name[]")
        service_durations = request.form.getlist("service_duration[]")

        if not name or not category:
            flash("Please provide an organization name and category.", "error")
            return redirect(url_for("register_org"))

        # Generate slug
        slug = name.lower().replace(" ", "-").replace("&", "and")
        import re
        slug = re.sub(r'[^a-z0-9\-]', '', slug)

        connection = get_db()
        cursor = connection.cursor()

        # Insert organization
        cursor.execute("""
            INSERT INTO organizations (name, slug, category, address, contact, description, total_counters)
            VALUES (?, ?, ?, ?, ?, ?, ?)
        """, (name, slug, category, address, contact, description, total_counters))
        org_id = cursor.lastrowid

        # Insert services
        for s_name, s_dur in zip(service_names, service_durations):
            if s_name.strip():
                dur = int(s_dur) if s_dur and s_dur.isdigit() else 15
                cursor.execute("""
                    INSERT INTO services (org_id, name, category, avg_duration_min, description)
                    VALUES (?, ?, ?, ?, ?)
                """, (org_id, s_name.strip(), category, dur, f"Standard {s_name.strip()} service."))

        # Create counters
        for c in range(1, total_counters + 1):
            status = "Active" if c <= 2 else "Closed"
            cursor.execute("""
                INSERT INTO counters (org_id, counter_number, name, staff_name, status)
                VALUES (?, ?, ?, ?, ?)
            """, (org_id, c, f"Counter {c}", f"Operator {c}", status))

        # Initial crowd snapshot
        cursor.execute("""
            INSERT INTO crowd_snapshots (org_id, density_status, estimated_count)
            VALUES (?, 'Normal', 5)
        """, (org_id,))

        connection.commit()
        connection.close()

        flash(f"🎉 '{name}' has been successfully registered! You can now access your organization dashboard.", "success")
        return redirect(url_for("org_dashboard", slug=slug))

    return render_template("org_register.html")

# ---------------------------------------------------------
# Organization Portal / Admin Dashboard
# ---------------------------------------------------------

@app.route("/admin")
@app.route("/admin/login")
def admin_portal():
    """Admin landing / Organization switcher."""
    connection = get_db()
    orgs = connection.execute("SELECT * FROM organizations ORDER BY category, name").fetchall()
    connection.close()
    return render_template("dashboard/admin_select.html", organizations=orgs)

@app.route("/org/<slug>/dashboard")
def org_dashboard(slug):
    """Organization Management Overview Dashboard."""
    connection = get_db()
    org = connection.execute("SELECT * FROM organizations WHERE slug = ?", (slug,)).fetchone()
    if not org:
        connection.close()
        flash("Organization not found.", "error")
        return redirect(url_for("admin_portal"))

    org_id = org["id"]

    # KPI Metrics
    waiting_count = connection.execute(
        "SELECT COUNT(*) as cnt FROM queue WHERE org_id = ? AND status = 'Waiting'",
        (org_id,)
    ).fetchone()["cnt"]

    serving_count = connection.execute(
        "SELECT COUNT(*) as cnt FROM queue WHERE org_id = ? AND status = 'Serving'",
        (org_id,)
    ).fetchone()["cnt"]

    served_today = connection.execute(
        "SELECT COUNT(*) as cnt FROM queue WHERE org_id = ? AND status = 'Completed'",
        (org_id,)
    ).fetchone()["cnt"]

    active_counters = connection.execute(
        "SELECT COUNT(*) as cnt FROM counters WHERE org_id = ? AND status = 'Active'",
        (org_id,)
    ).fetchone()["cnt"]

    total_counters = connection.execute(
        "SELECT COUNT(*) as cnt FROM counters WHERE org_id = ?",
        (org_id,)
    ).fetchone()["cnt"] or org["total_counters"]

    # Avg wait time
    avg_wait = connection.execute(
        "SELECT AVG(estimated_wait_min) as avg_w FROM queue WHERE org_id = ? AND status = 'Waiting'",
        (org_id,)
    ).fetchone()["avg_w"] or 18.0

    avg_service_min = connection.execute(
        "SELECT AVG(avg_duration_min) as avg_s FROM services WHERE org_id = ?",
        (org_id,)
    ).fetchone()["avg_s"] or 15.0

    # Crowd status
    crowd_snapshot = connection.execute(
        "SELECT * FROM crowd_snapshots WHERE org_id = ? ORDER BY id DESC LIMIT 1",
        (org_id,)
    ).fetchone()
    crowd_status = crowd_snapshot["density_status"] if crowd_snapshot else "Normal"

    # Priority breakdown
    priority_rows = connection.execute(
        "SELECT priority, COUNT(*) as cnt FROM queue WHERE org_id = ? AND status = 'Waiting' GROUP BY priority",
        (org_id,)
    ).fetchall()
    priority_breakdown = {r["priority"]: r["cnt"] for r in priority_rows}

    # AI Optimization Insights
    ai_insights = AIEngine.generate_optimization_insights(
        waiting_count=waiting_count,
        active_counters=active_counters,
        total_counters=total_counters,
        avg_wait_min=float(avg_wait),
        avg_service_min=float(avg_service_min),
        crowd_status=crowd_status,
        priority_breakdown=priority_breakdown
    )

    # Recent Queue Activity
    recent_queue = connection.execute("""
        SELECT * FROM queue WHERE org_id = ? ORDER BY id DESC LIMIT 6
    """, (org_id,)).fetchall()

    # Counters status
    counters = connection.execute("SELECT * FROM counters WHERE org_id = ? ORDER BY counter_number", (org_id,)).fetchall()

    connection.close()
    return render_template(
        "dashboard/overview.html",
        org=org,
        waiting_count=waiting_count,
        serving_count=serving_count,
        served_today=served_today,
        active_counters=active_counters,
        total_counters=total_counters,
        avg_wait=int(avg_wait),
        crowd_status=crowd_status,
        ai_insights=ai_insights,
        recent_queue=recent_queue,
        counters=counters
    )

@app.route("/org/<slug>/live-queue")
def org_live_queue(slug):
    """Organization Live Queue Operator Console."""
    connection = get_db()
    org = connection.execute("SELECT * FROM organizations WHERE slug = ?", (slug,)).fetchone()
    if not org:
        connection.close()
        return redirect(url_for("admin_portal"))

    org_id = org["id"]

    # Active Counters
    counters = connection.execute("SELECT * FROM counters WHERE org_id = ? ORDER BY counter_number", (org_id,)).fetchall()

    # Active Serving Items
    serving = connection.execute("""
        SELECT q.*, c.name as counter_name, c.counter_number
        FROM queue q
        JOIN counters c ON q.counter_id = c.id
        WHERE q.org_id = ? AND q.status = 'Serving'
        ORDER BY c.counter_number ASC
    """, (org_id,)).fetchall()

    # Waiting Items with Smart Priority order
    raw_waiting = connection.execute("SELECT * FROM queue WHERE org_id = ? AND status = 'Waiting'", (org_id,)).fetchall()
    waiting_list = [dict(r) for r in raw_waiting]
    prioritized_waiting = AIEngine.prioritize_queue(waiting_list)

    # Services list for walk-in form
    services = connection.execute("SELECT * FROM services WHERE org_id = ?", (org_id,)).fetchall()

    connection.close()
    return render_template(
        "dashboard/live_queue.html",
        org=org,
        counters=counters,
        serving=serving,
        waiting=prioritized_waiting,
        services=services
    )

@app.route("/org/<slug>/ai-insights")
def org_ai_insights(slug):
    """Dedicated AI Queue Optimization & Predictive Insights screen."""
    connection = get_db()
    org = connection.execute("SELECT * FROM organizations WHERE slug = ?", (slug,)).fetchone()
    if not org:
        connection.close()
        return redirect(url_for("admin_portal"))

    org_id = org["id"]
    waiting_count = connection.execute("SELECT COUNT(*) as cnt FROM queue WHERE org_id = ? AND status = 'Waiting'", (org_id,)).fetchone()["cnt"]
    active_counters = connection.execute("SELECT COUNT(*) as cnt FROM counters WHERE org_id = ? AND status = 'Active'", (org_id,)).fetchone()["cnt"]
    total_counters = connection.execute("SELECT COUNT(*) as cnt FROM counters WHERE org_id = ?", (org_id,)).fetchone()["cnt"] or org["total_counters"]
    
    avg_wait = connection.execute("SELECT AVG(estimated_wait_min) as avg_w FROM queue WHERE org_id = ? AND status = 'Waiting'", (org_id,)).fetchone()["avg_w"] or 18.0
    avg_service = connection.execute("SELECT AVG(avg_duration_min) as avg_s FROM services WHERE org_id = ?", (org_id,)).fetchone()["avg_s"] or 15.0

    crowd_snapshot = connection.execute("SELECT * FROM crowd_snapshots WHERE org_id = ? ORDER BY id DESC LIMIT 1", (org_id,)).fetchone()
    crowd_status = crowd_snapshot["density_status"] if crowd_snapshot else "Normal"

    priority_rows = connection.execute("SELECT priority, COUNT(*) as cnt FROM queue WHERE org_id = ? AND status = 'Waiting' GROUP BY priority", (org_id,)).fetchall()
    priority_breakdown = {r["priority"]: r["cnt"] for r in priority_rows}

    insights = AIEngine.generate_optimization_insights(
        waiting_count=waiting_count,
        active_counters=active_counters,
        total_counters=total_counters,
        avg_wait_min=float(avg_wait),
        avg_service_min=float(avg_service),
        crowd_status=crowd_status,
        priority_breakdown=priority_breakdown
    )

    connection.close()
    return render_template(
        "dashboard/ai_insights.html",
        org=org,
        insights=insights,
        waiting_count=waiting_count,
        active_counters=active_counters,
        total_counters=total_counters,
        avg_wait=int(avg_wait),
        crowd_status=crowd_status
    )

@app.route("/org/<slug>/crowd-monitor")
def org_crowd_monitor(slug):
    """AI Crowd Monitor with visual density telemetry & zone map."""
    connection = get_db()
    org = connection.execute("SELECT * FROM organizations WHERE slug = ?", (slug,)).fetchone()
    if not org:
        connection.close()
        return redirect(url_for("admin_portal"))

    org_id = org["id"]
    waiting_count = connection.execute("SELECT COUNT(*) as cnt FROM queue WHERE org_id = ? AND status = 'Waiting'", (org_id,)).fetchone()["cnt"]

    telemetry = AIEngine.get_crowd_telemetry(slug, waiting_count)
    connection.close()

    return render_template(
        "dashboard/crowd_monitor.html",
        org=org,
        telemetry=telemetry,
        waiting_count=waiting_count
    )

@app.route("/org/<slug>/analytics")
def org_analytics(slug):
    """Organization Queue Analytics & Performance Metrics."""
    connection = get_db()
    org = connection.execute("SELECT * FROM organizations WHERE slug = ?", (slug,)).fetchone()
    if not org:
        connection.close()
        return redirect(url_for("admin_portal"))

    org_id = org["id"]

    # Hourly served analytics
    hourly_rows = connection.execute("""
        SELECT time_of_day, COUNT(*) as count, AVG(wait_time_min) as avg_wait
        FROM analytics_history
        WHERE org_id = ?
        GROUP BY time_of_day
        ORDER BY time_of_day ASC
    """, (org_id,)).fetchall()

    # Priority distribution
    priority_stats = connection.execute("""
        SELECT priority_type, COUNT(*) as count
        FROM analytics_history
        WHERE org_id = ?
        GROUP BY priority_type
    """, (org_id,)).fetchall()

    # Service volume
    service_stats = connection.execute("""
        SELECT service_name, COUNT(*) as count, AVG(service_duration_min) as avg_dur
        FROM analytics_history
        WHERE org_id = ?
        GROUP BY service_name
    """, (org_id,)).fetchall()

    connection.close()
    return render_template(
        "dashboard/analytics.html",
        org=org,
        hourly_data=[dict(r) for r in hourly_rows],
        priority_data=[dict(r) for r in priority_stats],
        service_data=[dict(r) for r in service_stats]
    )

@app.route("/org/<slug>/services", methods=["GET", "POST"])
def org_services(slug):
    """Manage Organization Services & Counters."""
    connection = get_db()
    org = connection.execute("SELECT * FROM organizations WHERE slug = ?", (slug,)).fetchone()
    if not org:
        connection.close()
        return redirect(url_for("admin_portal"))

    org_id = org["id"]

    if request.method == "POST":
        action = request.form.get("action")
        cursor = connection.cursor()
        
        if action == "add_service":
            s_name = request.form.get("name", "").strip()
            s_dur = request.form.get("duration", type=int) or 15
            s_desc = request.form.get("description", "").strip()
            if s_name:
                cursor.execute("""
                    INSERT INTO services (org_id, name, category, avg_duration_min, description)
                    VALUES (?, ?, ?, ?, ?)
                """, (org_id, s_name, org["category"], s_dur, s_desc))
                flash(f"Service '{s_name}' added.", "success")
                
        elif action == "add_counter":
            c_name = request.form.get("name", "").strip()
            staff = request.form.get("staff_name", "").strip()
            current_max = connection.execute("SELECT MAX(counter_number) as max_c FROM counters WHERE org_id = ?", (org_id,)).fetchone()["max_c"] or 0
            new_num = current_max + 1
            cursor.execute("""
                INSERT INTO counters (org_id, counter_number, name, staff_name, status)
                VALUES (?, ?, ?, ?, 'Active')
            """, (org_id, new_num, c_name or f"Counter {new_num}", staff))
            flash(f"Counter #{new_num} created.", "success")

        connection.commit()

    services = connection.execute("SELECT * FROM services WHERE org_id = ?", (org_id,)).fetchall()
    counters = connection.execute("SELECT * FROM counters WHERE org_id = ? ORDER BY counter_number", (org_id,)).fetchall()
    connection.close()

    return render_template(
        "dashboard/services.html",
        org=org,
        services=services,
        counters=counters
    )

# ---------------------------------------------------------
# Organization Management REST APIs
# ---------------------------------------------------------

@app.route("/api/org/<slug>/call-next", methods=["POST"])
def api_org_call_next(slug):
    """Calls next customer in line according to AI priority order (or specific token if requested), assigning them to a counter."""
    connection = get_db()
    org = connection.execute("SELECT id FROM organizations WHERE slug = ?", (slug,)).fetchone()
    if not org:
        connection.close()
        return jsonify({"error": "Organization not found"}), 404

    org_id = org["id"]
    data = request.get_json() or {}
    counter_id = data.get("counter_id")
    specific_token_id = data.get("specific_token_id")

    cursor = connection.cursor()

    # Find and validate operating counter
    target_counter = None
    if counter_id:
        target_counter = connection.execute(
            "SELECT * FROM counters WHERE id = ? AND org_id = ?",
            (counter_id, org_id)
        ).fetchone()

    # If counter not provided, not found, or not active, find the first Active counter
    if not target_counter or target_counter["status"] != "Active":
        target_counter = connection.execute(
            "SELECT * FROM counters WHERE org_id = ? AND status = 'Active' ORDER BY counter_number ASC LIMIT 1",
            (org_id,)
        ).fetchone()

    if not target_counter:
        connection.close()
        return jsonify({"error": "No active counter available. Please open or resume a counter first."}), 400

    active_counter_id = target_counter["id"]

    # 1. Complete any current token at this counter & log to analytics history
    prev_serving = connection.execute("""
        SELECT * FROM queue
        WHERE org_id = ? AND counter_id = ? AND status = 'Serving'
    """, (org_id, active_counter_id)).fetchall()

    for ps in prev_serving:
        cursor.execute("""
            UPDATE queue SET status = 'Completed', completed_at = datetime('now')
            WHERE id = ?
        """, (ps["id"],))
        cursor.execute("""
            INSERT INTO analytics_history (org_id, token_number, service_name, wait_time_min, service_duration_min, priority_type, time_of_day)
            VALUES (?, ?, ?, ?, ?, ?, ?)
        """, (ps["org_id"], ps["token"], ps["service"], ps["estimated_wait_min"] or 15, 14.5, ps["priority"], datetime.datetime.now().strftime("%H:00")))

    # 2. Determine next customer
    next_customer = None
    if specific_token_id:
        # "Serve Now" for a specific waiting token
        specific_cust = connection.execute(
            "SELECT * FROM queue WHERE id = ? AND org_id = ? AND status = 'Waiting'",
            (specific_token_id, org_id)
        ).fetchone()
        if specific_cust:
            next_customer = dict(specific_cust)

    if not next_customer:
        # "Call Next Customer (AI Priority)"
        waiting_rows = connection.execute(
            "SELECT * FROM queue WHERE org_id = ? AND status = 'Waiting'",
            (org_id,)
        ).fetchall()
        waiting_list = [dict(r) for r in waiting_rows]

        if not waiting_list:
            cursor.execute("UPDATE counters SET current_token_id = NULL WHERE id = ?", (active_counter_id,))
            connection.commit()
            connection.close()
            return jsonify({"message": "Waiting queue is currently empty. No waiting customers.", "token": None})

        prioritized = AIEngine.prioritize_queue(waiting_list)
        next_customer = prioritized[0]

    # 3. Mark next customer as Serving at this counter
    cursor.execute("""
        UPDATE queue 
        SET status = 'Serving', counter_id = ?, served_at = datetime('now')
        WHERE id = ?
    """, (active_counter_id, next_customer["id"]))

    cursor.execute(
        "UPDATE counters SET current_token_id = ? WHERE id = ?",
        (next_customer["id"], active_counter_id)
    )

    connection.commit()

    # Re-fetch customer and counter to return fresh values
    updated_cust = connection.execute("SELECT * FROM queue WHERE id = ?", (next_customer["id"],)).fetchone()
    counter_info = {
        "id": target_counter["id"],
        "counter_number": target_counter["counter_number"],
        "name": target_counter["name"],
        "staff_name": target_counter["staff_name"]
    }

    connection.close()

    return jsonify({
        "success": True,
        "message": f"Called next token: #{updated_cust['token_str'] or updated_cust['token']}",
        "token": dict(updated_cust),
        "counter": counter_info
    })

@app.route("/api/org/<slug>/complete-token", methods=["POST"])
def api_org_complete_token(slug):
    """Mark a customer's token completed."""
    data = request.get_json() or {}
    token_id = data.get("token_id")

    connection = get_db()
    cursor = connection.cursor()

    cust = connection.execute("SELECT * FROM queue WHERE id = ?", (token_id,)).fetchone()
    if cust:
        cursor.execute("UPDATE queue SET status = 'Completed', completed_at = datetime('now') WHERE id = ?", (token_id,))
        if cust["counter_id"]:
            cursor.execute("UPDATE counters SET current_token_id = NULL WHERE id = ?", (cust["counter_id"],))
            
        # Log to analytics history
        cursor.execute("""
            INSERT INTO analytics_history (org_id, token_number, service_name, wait_time_min, service_duration_min, priority_type, time_of_day)
            VALUES (?, ?, ?, ?, ?, ?, ?)
        """, (cust["org_id"], cust["token"], cust["service"], cust["estimated_wait_min"] or 15, 14.5, cust["priority"], datetime.datetime.now().strftime("%H:00")))

        connection.commit()

    connection.close()
    return jsonify({"success": True})

@app.route("/api/org/<slug>/skip-token", methods=["POST"])
def api_org_skip_token(slug):
    """Mark token as Skipped."""
    data = request.get_json() or {}
    token_id = data.get("token_id")

    connection = get_db()
    cursor = connection.cursor()
    cust = connection.execute("SELECT * FROM queue WHERE id = ?", (token_id,)).fetchone()
    if cust:
        cursor.execute("UPDATE queue SET status = 'Skipped' WHERE id = ?", (token_id,))
        if cust["counter_id"]:
            cursor.execute("UPDATE counters SET current_token_id = NULL WHERE id = ?", (cust["counter_id"],))
        cursor.execute("UPDATE counters SET current_token_id = NULL WHERE current_token_id = ?", (token_id,))
        connection.commit()
    connection.close()
    return jsonify({"success": True})

@app.route("/api/org/<slug>/add-walkin", methods=["POST"])
def api_org_add_walkin(slug):
    """Add a direct walk-in customer from operator console."""
    connection = get_db()
    org = connection.execute("SELECT id, category FROM organizations WHERE slug = ?", (slug,)).fetchone()
    if not org:
        connection.close()
        return jsonify({"error": "Organization not found"}), 404

    data = request.get_json() or {}
    name = data.get("name", "Walk-in Guest").strip()
    service_id = data.get("service_id")
    priority = data.get("priority", "Normal")

    service = connection.execute("SELECT * FROM services WHERE id = ?", (service_id,)).fetchone()
    s_name = service["name"] if service else "General Service"

    max_tok = connection.execute("SELECT MAX(token) as max_t FROM queue WHERE org_id = ?", (org["id"],)).fetchone()["max_t"] or 0
    next_tok = max_tok + 1
    prefix = (org["category"] or "Q")[0].upper()
    tok_str = f"{prefix}-{next_tok:02d}"

    cursor = connection.cursor()
    cursor.execute("""
        INSERT INTO queue (org_id, service_id, name, service, priority, token, token_str, status, estimated_wait_min, created_at)
        VALUES (?, ?, ?, ?, ?, ?, ?, 'Waiting', 15, datetime('now'))
    """, (org["id"], service_id, name, s_name, priority, next_tok, tok_str))
    
    new_id = cursor.lastrowid
    connection.commit()
    connection.close()

    return jsonify({"success": True, "token_id": new_id, "token_str": tok_str})

@app.route("/api/org/<slug>/toggle-counter", methods=["POST"])
def api_org_toggle_counter(slug):
    """Open, pause, or close a counter."""
    data = request.get_json() or {}
    counter_id = data.get("counter_id")
    new_status = data.get("status", "Active") # 'Active', 'Paused', 'Closed'

    connection = get_db()
    cursor = connection.cursor()
    cursor.execute("UPDATE counters SET status = ? WHERE id = ?", (new_status, counter_id))
    connection.commit()
    connection.close()

    return jsonify({"success": True, "new_status": new_status})

@app.route("/api/org/<slug>/apply-ai-rec", methods=["POST"])
def api_org_apply_ai_rec(slug):
    """Executes AI recommendation, such as activating the next counter."""
    connection = get_db()
    org = connection.execute("SELECT id FROM organizations WHERE slug = ?", (slug,)).fetchone()
    if not org:
        connection.close()
        return jsonify({"error": "Organization not found"}), 404

    data = request.get_json() or {}
    action_type = data.get("action_type")
    target_counter_num = data.get("target_counter")

    cursor = connection.cursor()
    if action_type == "open_counter" and target_counter_num:
        cursor.execute("UPDATE counters SET status = 'Active' WHERE org_id = ? AND counter_number = ?", (org["id"], target_counter_num))
        connection.commit()
        connection.close()
        return jsonify({"success": True, "message": f"Counter {target_counter_num} activated successfully."})
        
    connection.close()
    return jsonify({"success": True, "message": "Recommendation applied."})

@app.route("/api/org/<slug>/update-crowd", methods=["POST"])
def api_org_update_crowd(slug):
    """Allows demo operator to adjust simulated crowd density level."""
    data = request.get_json() or {}
    status = data.get("status", "Normal") # 'Normal', 'Building', 'Congested'
    
    counts = {"Normal": 8, "Building": 16, "Congested": 28}
    est_count = counts.get(status, 10)

    connection = get_db()
    org = connection.execute("SELECT id FROM organizations WHERE slug = ?", (slug,)).fetchone()
    if org:
        cursor = connection.cursor()
        cursor.execute("""
            INSERT INTO crowd_snapshots (org_id, density_status, estimated_count)
            VALUES (?, ?, ?)
        """, (org["id"], status, est_count))
        connection.commit()
    connection.close()

    return jsonify({"success": True, "new_status": status, "count": est_count})

# ---------------------------------------------------------
# Health Check
# ---------------------------------------------------------
@app.route("/health")
def health():
    return {
        "status": "success",
        "message": "AI-Powered Smart Queue Management System SaaS is running smoothly.",
        "ai_engine": "Active (Prediction + Optimizer + Priority + Crowd)",
        "smart_arrival": "Active (Simulated Traffic Provider)"
    }

# ---------------------------------------------------------
# Application Entrypoint
# ---------------------------------------------------------
if __name__ == "__main__":
    init_db()
    app.run(
        host="127.0.0.1",
        port=5000,
        debug=True
    )