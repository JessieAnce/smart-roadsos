from flask import Flask, request, jsonify, render_template
from flask_cors import CORS
import requests
import math
import json
from datetime import datetime
import re

app = Flask(__name__)
CORS(app)

# Cache for API responses (in-memory backend cache)
backend_cache = {}
CACHE_DURATION = 300  # 5 minutes

# OpenStreetMap Overpass API endpoint
OVERPASS_API = "https://overpass-api.de/api/interpreter"
NOMINATIM_API = "https://nominatim.openstreetmap.org/reverse"

# Country emergency numbers database
EMERGENCY_NUMBERS = {
    'IN': {'number': '112', 'name': 'India', 'secondary': '102, 108'},
    'US': {'number': '911', 'name': 'United States', 'secondary': ''},
    'GB': {'number': '999', 'name': 'United Kingdom', 'secondary': '112'},
    'CA': {'number': '911', 'name': 'Canada', 'secondary': ''},
    'AU': {'number': '000', 'name': 'Australia', 'secondary': '112'},
    'DE': {'number': '112', 'name': 'Germany', 'secondary': '110'},
    'FR': {'number': '112', 'name': 'France', 'secondary': '15'},
    'JP': {'number': '110', 'name': 'Japan', 'secondary': '119'},
    'CN': {'number': '120', 'name': 'China', 'secondary': '110'},
    'BR': {'number': '190', 'name': 'Brazil', 'secondary': '192'},
    'ZA': {'number': '10111', 'name': 'South Africa', 'secondary': '10177'},
    'RU': {'number': '112', 'name': 'Russia', 'secondary': '103'},
    'AE': {'number': '998', 'name': 'UAE', 'secondary': '999'},
    'SG': {'number': '995', 'name': 'Singapore', 'secondary': '999'},
    'MY': {'number': '999', 'name': 'Malaysia', 'secondary': '112'},
    'PK': {'number': '15', 'name': 'Pakistan', 'secondary': '1122'},
    'BD': {'number': '999', 'name': 'Bangladesh', 'secondary': ''},
    'LK': {'number': '1990', 'name': 'Sri Lanka', 'secondary': '110'},
    'NP': {'number': '100', 'name': 'Nepal', 'secondary': '102'},
    'ID': {'number': '112', 'name': 'Indonesia', 'secondary': '118'},
    'TH': {'number': '191', 'name': 'Thailand', 'secondary': '1669'},
    'VN': {'number': '113', 'name': 'Vietnam', 'secondary': '115'},
    'PH': {'number': '911', 'name': 'Philippines', 'secondary': '117'},
    'EG': {'number': '122', 'name': 'Egypt', 'secondary': '123'},
    'NG': {'number': '112', 'name': 'Nigeria', 'secondary': '199'},
    'KE': {'number': '999', 'name': 'Kenya', 'secondary': '112'},
    'MX': {'number': '911', 'name': 'Mexico', 'secondary': '066'},
    'AR': {'number': '911', 'name': 'Argentina', 'secondary': '107'},
    'CL': {'number': '133', 'name': 'Chile', 'secondary': '131'},
    'CO': {'number': '123', 'name': 'Colombia', 'secondary': '125'},
    'PE': {'number': '105', 'name': 'Peru', 'secondary': '116'},
    'NZ': {'number': '111', 'name': 'New Zealand', 'secondary': ''},
    'IE': {'number': '112', 'name': 'Ireland', 'secondary': '999'}
}

# Service queries for Overpass API
SERVICE_QUERIES = {
    "hospitals": """
        [out:json];
        (
          node["amenity"="hospital"](around:{radius},{lat},{lng});
          node["amenity"="clinic"](around:{radius},{lat},{lng});
          node["healthcare"="hospital"](around:{radius},{lat},{lng});
        );
        out body center;
    """,
    "police": """
        [out:json];
        (
          node["amenity"="police"](around:{radius},{lat},{lng});
        );
        out body center;
    """,
    "ambulance": """
        [out:json];
        (
          node["emergency"="ambulance_station"](around:{radius},{lat},{lng});
          node["amenity"="ambulance_station"](around:{radius},{lat},{lng});
        );
        out body center;
    """,
    "repair": """
        [out:json];
        (
          node["shop"="car_repair"](around:{radius},{lat},{lng});
          node["service"="vehicle"](around:{radius},{lat},{lng});
        );
        out body center;
    """
}

def haversine_distance(lat1, lon1, lat2, lon2):
    """Calculate distance between two points in km"""
    R = 6371
    lat1_rad = math.radians(lat1)
    lat2_rad = math.radians(lat2)
    delta_lat = math.radians(lat2 - lat1)
    delta_lon = math.radians(lon2 - lon1)
    
    a = math.sin(delta_lat/2)**2 + math.cos(lat1_rad) * math.cos(lat2_rad) * math.sin(delta_lon/2)**2
    c = 2 * math.asin(math.sqrt(a))
    return round(R * c, 2)

def search_nearby(lat, lng, service_type, radius=5000):
    """Search for nearby services using Overpass API"""
    cache_key = f"{service_type}_{lat}_{lng}_{radius}"
    
    # Check backend cache
    if cache_key in backend_cache and (datetime.now() - backend_cache[cache_key]['timestamp']).seconds < CACHE_DURATION:
        return backend_cache[cache_key]['data']
    
    query = SERVICE_QUERIES.get(service_type, SERVICE_QUERIES["hospitals"])
    query = query.format(lat=lat, lng=lng, radius=radius)
    
    try:
        response = requests.post(OVERPASS_API, data=query, headers={'Content-Type': 'application/x-www-form-urlencoded'}, timeout=10)
        response.raise_for_status()
        data = response.json()
        
        results = []
        for element in data.get('elements', [])[:15]:
            lat_val = element.get('lat', element.get('center', {}).get('lat', 0))
            lon_val = element.get('lon', element.get('center', {}).get('lon', 0))
            
            if lat_val and lon_val:
                distance = haversine_distance(lat, lng, lat_val, lon_val)
                name = element.get('tags', {}).get('name', f"{service_type.replace('_', ' ').title()} #{len(results)+1}")
                
                results.append({
                    'name': name,
                    'address': element.get('tags', {}).get('addr:street', 'Address not available'),
                    'lat': lat_val,
                    'lng': lon_val,
                    'distance': distance,
                    'phone': element.get('tags', {}).get('phone', 'Not available'),
                    'type': service_type
                })
        
        results.sort(key=lambda x: x['distance'])
        results = results[:7]  # Get top 7 for better offline cache
        
        # Cache results
        backend_cache[cache_key] = {
            'data': results,
            'timestamp': datetime.now()
        }
        
        return results
    except Exception as e:
        print(f"Error searching {service_type}: {e}")
        return []

@app.route('/')
def index():
    return render_template('index.html')

@app.route('/api/search', methods=['POST'])
def search():
    """Main search endpoint - returns all services"""
    data = request.json
    lat = data.get('lat')
    lng = data.get('lng')
    
    if not lat or not lng:
        return jsonify({'error': 'Location required'}), 400
    
    services = {}
    for service in SERVICE_QUERIES.keys():
        services[service] = search_nearby(lat, lng, service)
    
    # Prepare golden hour data (prioritized hospitals)
    golden_hour_hospitals = services.get('hospitals', [])[:5]
    for idx, hospital in enumerate(golden_hour_hospitals):
        hospital['priority'] = idx + 1
        hospital['eta_minutes'] = int(hospital['distance'] * 2 + 1)
    
    return jsonify({
        'services': services,
        'golden_hour': {
            'enabled': True,
            'hospitals': golden_hour_hospitals,
            'message': 'Golden Hour Mode: Prioritizing nearest hospitals for critical care'
        },
        'timestamp': datetime.now().isoformat()
    })

@app.route('/api/geocode', methods=['POST'])
def geocode():
    """Reverse geocoding to get address from coordinates"""
    data = request.json
    lat = data.get('lat')
    lng = data.get('lng')
    
    if not lat or not lng:
        return jsonify({'error': 'Location required'}), 400
    
    try:
        response = requests.get(
            NOMINATIM_API,
            params={'lat': lat, 'lon': lng, 'format': 'json'},
            headers={'User-Agent': 'SmartRoadSOS/1.0'},
            timeout=10
        )
        response.raise_for_status()
        data = response.json()
        address = data.get('display_name', 'Address not found')
        
        # Extract country code
        country_code = data.get('address', {}).get('country_code', '').upper()
        
        return jsonify({
            'address': address,
            'country_code': country_code
        })
    except Exception as e:
        print(f"Geocoding error: {e}")
        return jsonify({'address': 'Location captured', 'country_code': 'IN'})

@app.route('/api/emergency_number', methods=['POST'])
def get_emergency_number():
    """Get emergency number based on country code"""
    data = request.json
    country_code = data.get('country_code', 'IN').upper()
    
    emergency_info = EMERGENCY_NUMBERS.get(country_code, EMERGENCY_NUMBERS['IN'])
    return jsonify(emergency_info)

@app.route('/api/emergency_alert', methods=['POST'])
def emergency_alert():
    """Generate emergency alert message"""
    data = request.json
    lat = data.get('lat')
    lng = data.get('lng')
    location_name = data.get('location_name', 'Unknown location')
    
    google_maps_link = f"https://www.google.com/maps?q={lat},{lng}"
    
    alert_message = f"""🚨 EMERGENCY ALERT - ROAD ACCIDENT 🚨

📍 Location: {location_name}
🗺️ Google Maps: {google_maps_link}
📅 Time: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}
📌 Coordinates: {lat}, {lng}

⚠️ IMMEDIATE ASSISTANCE REQUIRED!

First Aid Instructions:
1. Check if victim is conscious and breathing
2. Do not move victim unless in immediate danger
3. Stop any bleeding with clean cloth
4. Keep victim warm and comfortable
5. Wait for professional medical help

Call emergency services immediately!"""
    
    return jsonify({
        'message': alert_message,
        'maps_link': google_maps_link,
        'whatsapp_link': f"https://wa.me/?text={requests.utils.quote(alert_message)}"
    })

@app.route('/api/ai_guide', methods=['POST'])
def ai_emergency_guide():
    """AI Emergency Guide - Rule-based medical advice"""
    data = request.json
    query = data.get('query', '').lower()
    
    responses = {
        'accident': """🚨 ACCIDENT EMERGENCY GUIDE:
1. STOP - Ensure scene safety
2. CHECK - Are victims conscious?
3. CALL - Emergency services immediately
4. CARE - Provide basic first aid if trained
5. CONTROL - Bleeding with direct pressure
6. COMFORT - Keep victims warm and calm
7. WAIT - Don't move injured persons unless necessary""",

        'injury': """⚠️ INJURY ASSESSMENT:
1. Check responsiveness (tap and shout)
2. Look for obvious bleeding or deformity
3. Check breathing (look, listen, feel)
4. Keep neck stabilized if spinal injury suspected
5. Don't give food or drink
6. Monitor consciousness level
7. Reassure the person while waiting for help""",

        'bleeding': """🩸 BLEEDING CONTROL:
1. Apply direct pressure with clean cloth
2. Elevate injured area if possible
3. Apply pressure bandage
4. Don't remove embedded objects
5. Use tourniquet only for severe limb bleeding
6. Keep person lying down if bleeding heavily
7. Monitor for shock symptoms""",

        'breathing': """🫁 BREATHING CHECK:
1. Tilt head back slightly
2. Look, listen, feel for breath (5-10 seconds)
3. If not breathing, start CPR immediately
4. Push hard and fast in center of chest
5. 100-120 compressions per minute
6. Continue until help arrives
7. Use AED if available""",

        'shock': """⚠️ SHOCK TREATMENT:
1. Lay person down with feet elevated
2. Keep warm with blanket or jacket
3. Loosen tight clothing
4. Don't give food or drink
5. Turn on side if vomiting
6. Monitor breathing and consciousness
7. Treat any obvious injuries""",

        'default': """🏥 GENERAL EMERGENCY ADVICE:
• Stay calm and assess the situation
• Call emergency services immediately
• Don't move injured persons unless in danger
• Provide basic first aid if qualified
• Keep victims warm and comfortable
• Wait for professional medical help
• Preserve evidence if legal matter"""
    }
    
    for keyword in responses:
        if keyword in query:
            return jsonify({'guide': responses[keyword]})
    
    return jsonify({'guide': responses['default']})

if __name__ == '__main__':
    print("\n" + "="*60)
    print("🚑 SMART ROADSOS - EMERGENCY RESPONSE SYSTEM")
    print("="*60)
    print("\n✅ Server running at: http://localhost:5000")
    print("📱 Access from phone: http://<your-ip>:5000")
    print("\n🚨 FEATURES ACTIVE:")
    print("   • Offline Mode (localStorage cache)")
    print("   • Golden Hour Mode (prioritized hospitals)")
    print("   • Voice Activation (say 'help' or 'accident')")
    print("   • AI Emergency Guide")
    print("   • Map Integration")
    print("   • Global Emergency Numbers")
    print("\n⚠️  Press CTRL+C to stop server")
    print("="*60 + "\n")
    
    app.run(debug=True, host='0.0.0.0', port=5000)