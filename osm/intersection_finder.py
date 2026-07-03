import json
import webbrowser
import os
import time
import threading
from http.server import HTTPServer, SimpleHTTPRequestHandler

HTML_TEMPLATE = '''<!DOCTYPE html>
<html>
<head>
    <meta charset="utf-8">
    <title>Выбери перекресток</title>
    <style>
        body {{ margin: 0; padding: 0; }}
        #map {{ height: 100vh; width: 100%; }}
        .instruction {{
            position: fixed;
            bottom: 20px;
            left: 20px;
            right: 20px;
            background: rgba(0,0,0,0.8);
            color: white;
            padding: 10px;
            border-radius: 8px;
            font-family: Arial;
            font-size: 14px;
            text-align: center;
            z-index: 1000;
            pointer-events: none;
            max-width: 280px;
            margin: 0 auto;
        }}
    </style>
    <link rel="stylesheet" href="https://unpkg.com/leaflet@1.9.4/dist/leaflet.css" />
    <script src="https://unpkg.com/leaflet@1.9.4/dist/leaflet.js"></script>
</head>
<body>
    <div class="instruction">️ Кликни на перекресток → карта закроется</div>
    <div id="map"></div>

    <script>
        var map = L.map('map').setView([{center_lat}, {center_lon}], 14);
        
        L.tileLayer('https://{{s}}.basemaps.cartocdn.com/light_all/{{z}}/{{x}}/{{y}}{{r}}.png', {{
            attribution: '&copy; OSM'
        }}).addTo(map);
        
        var marker = null;
        
        map.on('click', function(e) {{
            var lat = e.latlng.lat.toFixed(6);
            var lng = e.latlng.lng.toFixed(6);
            
            if (marker) map.removeLayer(marker);
            marker = L.marker([lat, lng]).addTo(map);
            
            fetch('/save', {{
                method: 'POST',
                headers: {{'Content-Type': 'application/json'}},
                body: JSON.stringify({{lat: parseFloat(lat), lon: parseFloat(lng)}})
            }}).then(function() {{
                window.close();
            }});
        }});
        
        // Поиск
        L.Control.Search = L.Control.extend({{
            onAdd: function(map) {{
                var div = L.DomUtil.create('div');
                div.innerHTML = '<input type="text" id="search" placeholder=" Поиск..." style="padding:6px;width:180px;border-radius:20px;border:none;">';
                div.style.position = 'absolute';
                div.style.top = '10px';
                div.style.left = '10px';
                div.style.zIndex = '1000';
                
                var input = div.querySelector('#search');
                input.addEventListener('keypress', function(e) {{
                    if (e.key === 'Enter') {{
                        var query = encodeURIComponent(input.value);
                        fetch('https://nominatim.openstreetmap.org/search?q=' + query + '&format=json&limit=1')
                            .then(r => r.json())
                            .then(data => {{
                                if (data.length > 0) {{
                                    var lat = parseFloat(data[0].lat);
                                    var lon = parseFloat(data[0].lon);
                                    map.setView([lat, lon], 17);
                                    if (marker) map.removeLayer(marker);
                                    marker = L.marker([lat, lon]).addTo(map);
                                }}
                            }});
                    }}
                }});
                return div;
            }}
        }});
        map.addControl(new L.Control.Search({{position: 'topleft'}}));
    </script>
</body>
</html>'''


class MyHandler(SimpleHTTPRequestHandler):
    saved_coords = None
    center_lat = 55.751244
    center_lon = 37.618423

    def do_GET(self):
        if self.path == '/':
            html = HTML_TEMPLATE.format(
                center_lat=self.center_lat,
                center_lon=self.center_lon
            )
            self.send_response(200)
            self.send_header('Content-type', 'text/html; charset=utf-8')
            self.end_headers()
            self.wfile.write(html.encode('utf-8'))
        else:
            self.send_response(404)
            self.end_headers()

    def do_POST(self):
        if self.path == '/save':
            length = int(self.headers['Content-Length'])
            data = json.loads(self.rfile.read(length).decode('utf-8'))
            MyHandler.saved_coords = (data['lat'], data['lon'])

            with open('clicked_coords.json', 'w', encoding='utf-8') as f:
                json.dump(data, f, indent=2)

            self.send_response(200)
            self.end_headers()
            self.wfile.write(b'OK')

            threading.Thread(target=lambda: server.shutdown(), daemon=True).start()

    def log_message(self, *args, **kwargs):
        pass


def get_city_coords(city_name):
    import requests
    url = "https://nominatim.openstreetmap.org/search"
    params = {"q": city_name, "format": "json", "limit": 1}
    headers = {"User-Agent": "MapPicker/1.0"}
    try:
        resp = requests.get(url, params=params, headers=headers, timeout=10)
        data = resp.json()
        if data:
            return float(data[0]["lat"]), float(data[0]["lon"])
    except:
        pass
    return 55.751244, 37.618423


if __name__ == "__main__":
    print("\n" + "=" * 50)
    city = input("Введите город: ").strip()
    if not city:
        city = "Москва"

    lat, lon = get_city_coords(city)
    MyHandler.center_lat = lat
    MyHandler.center_lon = lon

    server = HTTPServer(('localhost', 8888), MyHandler)

    webbrowser.open('http://localhost:8888')

    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass

    if MyHandler.saved_coords:
        lat, lon = MyHandler.saved_coords
        print(f"Перекресток на карте: https://www.google.com/maps?q={lat},{lon}")
        print("=" * 50)