"""
Smart Arrival System & Traffic Simulation Provider
Calculates recommended departure times by combining:
1. Current Time
2. AI Predicted Turn/Service Time
3. Simulated or Real Traffic Conditions
4. Travel Duration with Traffic Multiplier
5. Safety Arrival Buffer
"""

import datetime
from abc import ABC, abstractmethod
from typing import Dict, Any

class BaseTrafficProvider(ABC):
    @abstractmethod
    def get_traffic_data(self, origin: str, destination: str, baseline_min: int, condition: str = "Moderate") -> Dict[str, Any]:
        pass

class SimulatedTrafficProvider(BaseTrafficProvider):
    """
    Simulated Traffic Provider for Demo & Viva Presentations.
    Architecture allows zero-code switch to Google Maps Distance Matrix or TomTom API.
    """
    TRAFFIC_CONDITIONS = {
        "Light": {
            "name": "Light Traffic",
            "icon": "🟢",
            "color": "sage",
            "multiplier": 1.0,
            "description": "Smooth road conditions with zero congestion bottlenecks."
        },
        "Moderate": {
            "name": "Moderate Traffic",
            "icon": "🟡",
            "color": "peach",
            "multiplier": 1.45,
            "description": "Normal urban flow with minor intersection delays."
        },
        "Heavy": {
            "name": "Heavy Traffic",
            "icon": "🔴",
            "color": "blush",
            "multiplier": 2.10,
            "description": "Peak-hour congestion detected along primary corridors."
        }
    }

    DISTANCE_PRESETS = {
        "nearby": {"label": "Nearby (approx. 2-3 km)", "base_min": 10},
        "metro": {"label": "Mid-City (approx. 7-10 km)", "base_min": 18},
        "suburb": {"label": "Suburban / Outer (approx. 15-20 km)", "base_min": 30}
    }

    def get_traffic_data(
        self,
        origin: str = "Current Location",
        destination: str = "Organization",
        baseline_min: int = 16,
        condition: str = "Moderate"
    ) -> Dict[str, Any]:
        cond_data = self.TRAFFIC_CONDITIONS.get(condition, self.TRAFFIC_CONDITIONS["Moderate"])
        travel_duration_min = max(5, int(round(baseline_min * cond_data["multiplier"])))
        
        return {
            "origin": origin,
            "destination": destination,
            "condition": condition,
            "condition_name": cond_data["name"],
            "condition_icon": cond_data["icon"],
            "condition_color": cond_data["color"],
            "condition_description": cond_data["description"],
            "baseline_min": baseline_min,
            "travel_time_min": travel_duration_min,
            "is_simulated": True,
            "disclaimer": "Traffic conditions are simulated for this demo. A real-time traffic API can be integrated in the future."
        }

class SmartArrivalService:
    def __init__(self, provider: BaseTrafficProvider = None):
        self.provider = provider or SimulatedTrafficProvider()

    def calculate_smart_arrival(
        self,
        ai_wait_minutes: int,
        traffic_condition: str = "Moderate",
        distance_preset: str = "metro",
        custom_travel_min: int = None,
        safety_buffer_min: int = 8,
        destination_name: str = "Destination Service"
    ) -> Dict[str, Any]:
        """
        Calculates dynamic Smart Arrival recommendation:
        - Estimated Service Turn Time
        - Travel Duration under Traffic
        - Recommended Leave Time
        """
        now = datetime.datetime.now()
        
        # 1. Base travel duration
        if custom_travel_min and custom_travel_min > 0:
            base_min = custom_travel_min
        else:
            base_min = SimulatedTrafficProvider.DISTANCE_PRESETS.get(distance_preset, {}).get("base_min", 16)
            
        # 2. Get traffic data
        traffic_info = self.provider.get_traffic_data(
            origin="Customer Location",
            destination=destination_name,
            baseline_min=base_min,
            condition=traffic_condition
        )
        travel_time_min = traffic_info["travel_time_min"]
        
        # 3. Compute times
        estimated_turn_dt = now + datetime.timedelta(minutes=ai_wait_minutes)
        
        # Total needed time before turn = Travel time + Safety arrival buffer
        prep_and_travel_min = travel_time_min + safety_buffer_min
        
        # Recommended departure timestamp
        recommended_leave_dt = estimated_turn_dt - datetime.timedelta(minutes=prep_and_travel_min)
        
        # Check if customer should leave right away
        is_leave_now = recommended_leave_dt <= now
        
        # Formatted human-readable strings
        def fmt_time(dt: datetime.datetime) -> str:
            # Example: "4:45 PM"
            return dt.strftime("%I:%M %p").lstrip("0")

        return {
            "current_time": fmt_time(now),
            "estimated_turn_time": fmt_time(estimated_turn_dt),
            "estimated_turn_raw": estimated_turn_dt.isoformat(),
            "recommended_leave_time": fmt_time(recommended_leave_dt) if not is_leave_now else "Leave Now",
            "recommended_leave_raw": recommended_leave_dt.isoformat(),
            "is_leave_now": is_leave_now,
            "travel_time_min": travel_time_min,
            "safety_buffer_min": safety_buffer_min,
            "traffic_condition": traffic_info["condition"],
            "traffic_icon": traffic_info["condition_icon"],
            "traffic_name": traffic_info["condition_name"],
            "traffic_color": traffic_info["condition_color"],
            "traffic_description": traffic_info["condition_description"],
            "disclaimer": traffic_info["disclaimer"],
            "distance_preset": distance_preset,
            "presets": SimulatedTrafficProvider.DISTANCE_PRESETS
        }

# Global singleton instance
smart_arrival_service = SmartArrivalService()
