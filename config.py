import os

BASE_DIR = os.path.abspath(os.path.dirname(__file__))

class Config:
    SECRET_KEY = os.environ.get("SECRET_KEY", "smart-queue-ai-secret-key-2026")
    DATABASE_PATH = os.path.join(BASE_DIR, "queue.db")
    DEBUG = True
    
    # AI Engine Settings
    AI_DEFAULT_COUNTER_EFFICIENCY = 1.0
    AI_CONFIDENCE_BASELINE = 0.94
    AI_HIGH_WAIT_THRESHOLD_MIN = 25
    
    # Smart Arrival & Traffic Simulation Settings
    TRAFFIC_SIMULATION_ENABLED = True
    DEFAULT_TRAVEL_TIME_MIN = 15
    DEFAULT_BUFFER_MIN = 8
    
    # Supported Organization Categories (Strictly restricted to 6)
    SUPPORTED_CATEGORIES = [
        {"id": "Hospital", "name": "Hospitals", "icon": "🏥", "color": "blush", "desc": "Manage patient queues, emergency triaging, and department routing."},
        {"id": "Clinic", "name": "Clinics", "icon": "🩺", "color": "lavender", "desc": "Give patients digital tokens, consultation slots, and live wait estimates."},
        {"id": "Salon", "name": "Salons", "icon": "💇", "color": "peach", "desc": "Organize appointments, walk-ins, styling stations, and personalized care."},
        {"id": "Service Center", "name": "Service Centers", "icon": "🔧", "color": "sage", "desc": "Keep device repairs, vehicle maintenance, and customer desks flowing seamlessly."},
        {"id": "Restaurant", "name": "Restaurants", "icon": "🍽️", "color": "amber", "desc": "Manage table waitlists, guest parties, and dining turnarounds effortlessly."},
        {"id": "School / College", "name": "Schools & Colleges", "icon": "🎓", "color": "purple", "desc": "Streamline student admissions, fee desks, documentation, and counseling."}
    ]
