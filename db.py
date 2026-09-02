import sqlite3
import os
import datetime
from config import Config

DATABASE = Config.DATABASE_PATH

def get_db():
    connection = sqlite3.connect(DATABASE)
    connection.row_factory = sqlite3.Row
    # Enable foreign keys
    connection.execute("PRAGMA foreign_keys = ON")
    return connection

def init_db():
    connection = get_db()
    cursor = connection.cursor()

    # 1. Organizations Table
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS organizations (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT NOT NULL,
            slug TEXT UNIQUE NOT NULL,
            category TEXT NOT NULL,
            address TEXT,
            contact TEXT,
            description TEXT,
            total_counters INTEGER DEFAULT 3,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    """)

    # 2. Services Table
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS services (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            org_id INTEGER NOT NULL,
            name TEXT NOT NULL,
            category TEXT NOT NULL,
            avg_duration_min INTEGER DEFAULT 15,
            description TEXT,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (org_id) REFERENCES organizations(id) ON DELETE CASCADE
        )
    """)

    # 3. Counters Table
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS counters (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            org_id INTEGER NOT NULL,
            counter_number INTEGER NOT NULL,
            name TEXT NOT NULL,
            staff_name TEXT,
            status TEXT DEFAULT 'Active', -- 'Active', 'Paused', 'Closed'
            current_token_id INTEGER,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (org_id) REFERENCES organizations(id) ON DELETE CASCADE
        )
    """)

    # 4. Queue Table (Upgraded schema & migration)
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS queue (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            org_id INTEGER,
            service_id INTEGER,
            counter_id INTEGER,
            name TEXT NOT NULL,
            phone TEXT,
            service TEXT NOT NULL,
            priority TEXT DEFAULT 'Normal',
            token INTEGER NOT NULL,
            token_str TEXT,
            status TEXT DEFAULT 'Waiting',
            estimated_wait_min INTEGER DEFAULT 15,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            served_at TIMESTAMP,
            completed_at TIMESTAMP,
            notes TEXT
        )
    """)

    # Check existing columns in queue and alter if needed
    existing_cols = [row[1] for row in cursor.execute("PRAGMA table_info(queue)").fetchall()]
    new_cols = [
        ("org_id", "INTEGER"),
        ("service_id", "INTEGER"),
        ("counter_id", "INTEGER"),
        ("phone", "TEXT"),
        ("token_str", "TEXT"),
        ("estimated_wait_min", "INTEGER DEFAULT 15"),
        ("created_at", "TIMESTAMP"),
        ("served_at", "TIMESTAMP"),
        ("completed_at", "TIMESTAMP"),
        ("notes", "TEXT")
    ]
    for col_name, col_type in new_cols:
        if col_name not in existing_cols:
            cursor.execute(f"ALTER TABLE queue ADD COLUMN {col_name} {col_type}")

    # 5. Crowd Snapshots Table
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS crowd_snapshots (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            org_id INTEGER NOT NULL,
            density_status TEXT DEFAULT 'Normal', -- 'Normal', 'Building', 'Congested'
            estimated_count INTEGER DEFAULT 10,
            active_area TEXT DEFAULT 'Waiting Lounge',
            timestamp TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (org_id) REFERENCES organizations(id) ON DELETE CASCADE
        )
    """)

    # 6. Analytics History Table
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS analytics_history (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            org_id INTEGER NOT NULL,
            token_number INTEGER,
            service_name TEXT,
            wait_time_min REAL,
            service_duration_min REAL,
            priority_type TEXT,
            time_of_day TEXT,
            date_recorded DATE DEFAULT CURRENT_DATE,
            FOREIGN KEY (org_id) REFERENCES organizations(id) ON DELETE CASCADE
        )
    """)

    connection.commit()
    connection.close()

    # Seed demo organizations and initial data if database is new or empty
    seed_demo_data()

def seed_demo_data():
    connection = get_db()
    cursor = connection.cursor()

    # Check if organizations exist
    org_count = cursor.execute("SELECT COUNT(*) as count FROM organizations").fetchone()["count"]
    if org_count > 0:
        connection.close()
        return

    # Seed 6 standard organizations across the required categories
    demo_orgs = [
        {
            "name": "Metro Care General Hospital",
            "slug": "metro-care-hospital",
            "category": "Hospital",
            "address": "452 Medical Enclave, Central Ave",
            "contact": "+1 (555) 234-5678",
            "description": "24/7 tertiary healthcare, outpatient triage, and specialist consultations with AI queue routing.",
            "total_counters": 4,
            "services": [
                {"name": "Emergency Triage", "duration": 10, "desc": "Priority trauma, acute distress, and critical evaluation."},
                {"name": "General OPD Consultation", "duration": 20, "desc": "Comprehensive medical checkup with resident physician."},
                {"name": "Specialist Clinic", "duration": 25, "desc": "Cardiology, Orthopedics, and Neurology consultations."},
                {"name": "Diagnostic & Lab Services", "duration": 12, "desc": "Blood tests, radiology, and specimen collections."}
            ],
            "counters": [
                {"num": 1, "name": "Counter 1 (Fast-Track)", "staff": "Dr. Sarah Adams", "status": "Active"},
                {"num": 2, "name": "Counter 2 (OPD)", "staff": "Dr. Rajiv Mehta", "status": "Active"},
                {"num": 3, "name": "Counter 3 (Specialist)", "staff": "Dr. Elena Rostov", "status": "Active"},
                {"num": 4, "name": "Counter 4 (Overflow / Triage)", "staff": "Staff Nurse Kevin", "status": "Closed"}
            ],
            "crowd": {"status": "Building", "count": 18}
        },
        {
            "name": "Sunrise Family Clinic",
            "slug": "sunrise-clinic",
            "category": "Clinic",
            "address": "12 Bloom Street, West Valley",
            "contact": "+1 (555) 345-6789",
            "description": "Neighborhood clinic for pediatrics, wellness checkups, and prescription renewals.",
            "total_counters": 3,
            "services": [
                {"name": "General Consultation", "duration": 15, "desc": "Standard general practice doctor visit."},
                {"name": "Pediatric Wellness Check", "duration": 20, "desc": "Child immunizations and growth assessments."},
                {"name": "Vaccination & Flu Shot", "duration": 8, "desc": "Express immunization and preventive care."}
            ],
            "counters": [
                {"num": 1, "name": "Desk 1 (Consultation)", "staff": "Dr. Claire Evans", "status": "Active"},
                {"num": 2, "name": "Desk 2 (Express & Vax)", "staff": "Nurse Hannah", "status": "Active"},
                {"num": 3, "name": "Desk 3 (Pediatrics)", "staff": "Dr. Marcus Vance", "status": "Closed"}
            ],
            "crowd": {"status": "Normal", "count": 9}
        },
        {
            "name": "Lumière Style & Beauty Lounge",
            "slug": "lumiere-salon",
            "category": "Salon",
            "address": "88 Haute Boulevard, Fashion Row",
            "contact": "+1 (555) 456-7890",
            "description": "Bespoke hair design, skincare therapy, and premium grooming services.",
            "total_counters": 3,
            "services": [
                {"name": "Precision Haircut & Styling", "duration": 30, "desc": "Custom wash, cut, blowdry, and styling consultation."},
                {"name": "Express Blowout & Wash", "duration": 20, "desc": "Fast wash and blowout for immediate events."},
                {"name": "Luxury Spa & Facial", "duration": 45, "desc": "Deep hydration facial and relaxing scalp therapy."}
            ],
            "counters": [
                {"num": 1, "name": "Chair 1 (Hair Styling)", "staff": "Stylist Julian", "status": "Active"},
                {"num": 2, "name": "Chair 2 (Color & Cut)", "staff": "Stylist Maya", "status": "Active"},
                {"num": 3, "name": "Station 3 (Spa / Grooming)", "staff": "Therapist Noah", "status": "Paused"}
            ],
            "crowd": {"status": "Normal", "count": 6}
        },
        {
            "name": "TechFix Authorized Service Hub",
            "slug": "techfix-service",
            "category": "Service Center",
            "address": "204 Silicon Park, Tech Corridor",
            "contact": "+1 (555) 567-8901",
            "description": "Rapid diagnostics, warranty repairs, and device support for laptops, phones, and wearables.",
            "total_counters": 4,
            "services": [
                {"name": "Quick Diagnostic & Drop-off", "duration": 10, "desc": "Fast hardware inspection and job sheet creation."},
                {"name": "Screen & Battery Replacement", "duration": 25, "desc": "On-spot module swaps and component testing."},
                {"name": "Software & OS Troubleshooting", "duration": 20, "desc": "Firmware restoration, data recovery, and backup."}
            ],
            "counters": [
                {"num": 1, "name": "Counter 1 (Intake & Drop)", "staff": "Tech Alex Chen", "status": "Active"},
                {"num": 2, "name": "Counter 2 (Repairs)", "staff": "Tech Samira Patel", "status": "Active"},
                {"num": 3, "name": "Counter 3 (Collection)", "staff": "Tech Daniel Kim", "status": "Active"},
                {"num": 4, "name": "Counter 4 (Express Lane)", "staff": "Tech Liam Brooks", "status": "Closed"}
            ],
            "crowd": {"status": "Building", "count": 14}
        },
        {
            "name": "The Olive Table Modern Bistro",
            "slug": "olive-table-bistro",
            "category": "Restaurant",
            "address": "77 Gourmet Way, Riverwalk",
            "contact": "+1 (555) 678-9012",
            "description": "Farm-to-table dining with digital party waitlisting and arrival coordination.",
            "total_counters": 3,
            "services": [
                {"name": "Table for 1-2 Guests", "duration": 15, "desc": "Cozy dining table for small parties and couples."},
                {"name": "Table for 3-5 Guests", "duration": 25, "desc": "Family table dining in main dining hall."},
                {"name": "Large Group / Party Table (6+)", "duration": 40, "desc": "Spacious banquette or private dining area."}
            ],
            "counters": [
                {"num": 1, "name": "Host Stand 1 (Indoor Dining)", "staff": "Hostess Olivia", "status": "Active"},
                {"num": 2, "name": "Host Stand 2 (Patio / Terrace)", "staff": "Host Ethan", "status": "Active"},
                {"num": 3, "name": "Host Stand 3 (Private Dining)", "staff": "Host Mason", "status": "Closed"}
            ],
            "crowd": {"status": "Congested", "count": 24}
        },
        {
            "name": "Horizon College Student Services",
            "slug": "horizon-college-services",
            "category": "School / College",
            "address": "100 Academic Circle, Campus Plaza",
            "contact": "+1 (555) 789-0123",
            "description": "Unified student desk for admissions, fee verification, student ID issuance, and career counseling.",
            "total_counters": 4,
            "services": [
                {"name": "Admissions & Document Verification", "duration": 15, "desc": "Submission of certificates, transcripts, and enrollment forms."},
                {"name": "Fee Payments & Financial Aid", "duration": 10, "desc": "Tuition processing, scholarship aid clearance."},
                {"name": "Academic & Career Counseling", "duration": 30, "desc": "One-on-one session with academic advisors."}
            ],
            "counters": [
                {"num": 1, "name": "Desk A (Admissions)", "staff": "Officer Linda Bell", "status": "Active"},
                {"num": 2, "name": "Desk B (Finance)", "staff": "Officer Robert Diaz", "status": "Active"},
                {"num": 3, "name": "Desk C (Counseling)", "staff": "Advisor Priya Sen", "status": "Active"},
                {"num": 4, "name": "Desk D (Student IDs & Fast-Lane)", "staff": "Staff Assistant Jay", "status": "Closed"}
            ],
            "crowd": {"status": "Building", "count": 16}
        }
    ]

    for org_data in demo_orgs:
        cursor.execute("""
            INSERT INTO organizations (name, slug, category, address, contact, description, total_counters)
            VALUES (?, ?, ?, ?, ?, ?, ?)
        """, (org_data["name"], org_data["slug"], org_data["category"], org_data["address"], org_data["contact"], org_data["description"], org_data["total_counters"]))
        org_id = cursor.lastrowid

        # Insert services
        service_map = {}
        for s in org_data["services"]:
            cursor.execute("""
                INSERT INTO services (org_id, name, category, avg_duration_min, description)
                VALUES (?, ?, ?, ?, ?)
            """, (org_id, s["name"], org_data["category"], s["duration"], s["desc"]))
            service_map[s["name"]] = cursor.lastrowid

        # Insert counters
        counter_map = {}
        for c in org_data["counters"]:
            cursor.execute("""
                INSERT INTO counters (org_id, counter_number, name, staff_name, status)
                VALUES (?, ?, ?, ?, ?)
            """, (org_id, c["num"], c["name"], c["staff"], c["status"]))
            counter_map[c["num"]] = cursor.lastrowid

        # Insert crowd snapshot
        cursor.execute("""
            INSERT INTO crowd_snapshots (org_id, density_status, estimated_count)
            VALUES (?, ?, ?)
        """, (org_id, org_data["crowd"]["status"], org_data["crowd"]["count"]))

        # Seed realistic initial queue items
        prefix = org_data["category"][0].upper()
        
        # Add 1 serving customer and 4-6 waiting customers
        serv_service = list(service_map.keys())[0]
        cursor.execute("""
            INSERT INTO queue (org_id, service_id, counter_id, name, phone, service, priority, token, token_str, status, estimated_wait_min, created_at, served_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, 'Serving', 0, datetime('now', '-12 minutes'), datetime('now', '-5 minutes'))
        """, (org_id, service_map[serv_service], counter_map[1], "Emma Watson", "+1-555-0101", serv_service, "Normal", 1, f"{prefix}-01"))
        
        # Update counter 1 with current token
        cursor.execute("UPDATE counters SET current_token_id = ? WHERE id = ?", (cursor.lastrowid, counter_map[1]))

        demo_customers = [
            ("Marcus Aurelius", "Senior Citizen", 2, 8, "Emergency Triage" if org_data["category"] == "Hospital" else list(service_map.keys())[0]),
            ("Sophia Taylor", "Appointment", 3, 14, list(service_map.keys())[min(1, len(service_map)-1)]),
            ("Liam Henderson", "Emergency" if org_data["category"] == "Hospital" else "Normal", 4, 18, list(service_map.keys())[0]),
            ("Priya Sharma", "Normal", 5, 26, list(service_map.keys())[min(2, len(service_map)-1)]),
            ("David Miller", "Special Service", 6, 34, list(service_map.keys())[0]),
            ("Chloe Bennett", "Normal", 7, 42, list(service_map.keys())[min(1, len(service_map)-1)])
        ]

        for cust_name, priority, tok_num, est_wait, s_name in demo_customers:
            cursor.execute("""
                INSERT INTO queue (org_id, service_id, name, phone, service, priority, token, token_str, status, estimated_wait_min, created_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, 'Waiting', ?, datetime('now', '-{} minutes'))
            """.format(35 - tok_num * 3), (org_id, service_map.get(s_name, list(service_map.values())[0]), cust_name, f"+1-555-010{tok_num}", s_name, priority, tok_num, f"{prefix}-{tok_num:02d}", est_wait))

        # Seed analytics history for charts
        now = datetime.datetime.now()
        for h in range(8, 17):
            served_count = 3 + (h % 4) * 2
            for i in range(served_count):
                cursor.execute("""
                    INSERT INTO analytics_history (org_id, token_number, service_name, wait_time_min, service_duration_min, priority_type, time_of_day, date_recorded)
                    VALUES (?, ?, ?, ?, ?, ?, ?, date('now'))
                """, (org_id, 100 + h*10 + i, list(service_map.keys())[i % len(service_map)], 12.0 + (h%3)*4.5 + (i%2)*2, 14.0 + (i%3)*3, "Normal" if i%3 != 0 else "Appointment", f"{h:02d}:00"))

    connection.commit()
    connection.close()

if __name__ == "__main__":
    init_db()
    print("Database initialized and demo data seeded successfully.")
