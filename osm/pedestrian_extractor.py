import requests
import xml.etree.ElementTree as ET
import math
import json
from collections import defaultdict


def haversine(lat1, lon1, lat2, lon2):
    R = 6371000
    dlat = math.radians(lat2 - lat1)
    dlon = math.radians(lon2 - lon1)
    a = math.sin(dlat / 2) ** 2 + math.cos(math.radians(lat1)) * math.cos(math.radians(lat2)) * math.sin(dlon / 2) ** 2
    return R * 2 * math.atan2(math.sqrt(a), math.sqrt(1 - a))


try:
    with open("clicked_coords.json", "r", encoding="utf-8") as f:
        coords = json.load(f)
        my_lat = coords.get("lat")
        my_lon = coords.get("lon")
        if my_lat is None or my_lon is None:
            raise ValueError("В файле отсутствуют lat или lon")
except FileNotFoundError:
    print("Ошибка: файл clicked_coords.json не найден")
    exit(1)
except json.JSONDecodeError:
    print("Ошибка: файл clicked_coords.json содержит некорректный JSON")
    exit(1)
except Exception as e:
    print(f"Ошибка при чтении файла: {e}")
    exit(1)

print(f"Загружены координаты: {my_lat}, {my_lon}")

bbox = f"{my_lon - 0.005},{my_lat - 0.005},{my_lon + 0.005},{my_lat + 0.005}"
url = f"https://api.openstreetmap.org/api/0.6/map?bbox={bbox}"
r = requests.get(url, headers={"User-Agent": "GeoTrafficAI/1.0"}, timeout=30)
root = ET.fromstring(r.content)

nodes_coords = {}
for n in root.findall("node"):
    nodes_coords[n.get("id")] = (float(n.get("lat")), float(n.get("lon")))

all_ways = {}
for w in root.findall("way"):
    wid = w.get("id")
    nds = [nd.get("ref") for nd in w.findall("nd")]
    tags = {}
    for tag in w.findall("tag"):
        tags[tag.get("k")] = tag.get("v")
    all_ways[wid] = {"nodes": nds, "tags": tags}

nodes_to_ways = defaultdict(set)
for wid, data in all_ways.items():
    for nid in data["nodes"]:
        nodes_to_ways[nid].add(wid)

intersection_nodes = {nid for nid, ws in nodes_to_ways.items() if len(ws) >= 2}

if intersection_nodes:
    closest_node = min(
        intersection_nodes,
        key=lambda nid: haversine(my_lat, my_lon, nodes_coords[nid][0], nodes_coords[nid][1])
    )
    center_lat, center_lon = nodes_coords[closest_node]
else:
    center_lat, center_lon = my_lat, my_lon

print(f"\n{'=' * 80}")
print(f"ЦЕНТР ПЕРЕКРЁСТКА")
print(f"{'=' * 80}")
print(f"  Координаты: {center_lat:.6f}, {center_lon:.6f}")
print(f"  Радиус поиска: 50 метров")

print(f"\n{'=' * 80}")
print(f"ПЕШЕХОДНЫЕ ПЕРЕХОДЫ")
print(f"{'=' * 80}")

crossings = []
for node in root.findall("node"):
    tags = {}
    for tag in node.findall("tag"):
        tags[tag.get("k")] = tag.get("v")

    if tags.get("highway") == "crossing":
        nid = node.get("id")
        tlat = float(node.get("lat"))
        tlon = float(node.get("lon"))
        dist = haversine(center_lat, center_lon, tlat, tlon)

        if dist <= 70:
            crossing_info = {
                "id": nid,
                "lat": tlat,
                "lon": tlon,
                "distance_m": round(dist, 1),
                "tags": tags
            }
            crossings.append(crossing_info)

crossings.sort(key=lambda x: x["distance_m"])

print(f"\nНайдено переходов: {len(crossings)}")

if crossings:
    print(f"\n{'=' * 80}")
    print(f"ДЕТАЛЬНАЯ ИНФОРМАЦИЯ О ПЕРЕХОДАХ")
    print(f"{'=' * 80}")

    for i, c in enumerate(crossings, 1):
        print(f"\n--- Переход {i} (ID: {c['id']}) ---")
        print(f"  Координаты: {c['lat']:.6f}, {c['lon']:.6f}")
        print(f"  Расстояние от центра: {c['distance_m']} м")
        print(f"  ВСЕ ТЕГИ:")
        for k, v in sorted(c["tags"].items()):
            print(f"    {k} = {v}")

    print(f"\n{'=' * 80}")
    print(f"СТАТИСТИКА")
    print(f"{'=' * 80}")

    crossing_types = defaultdict(int)
    for c in crossings:
        crossing_type = c["tags"].get("crossing", "unknown")
        crossing_types[crossing_type] += 1

    print(f"  Распределение по типам:")
    for ct, count in sorted(crossing_types.items()):
        print(f"    {ct}: {count}")

    traffic_signals_count = sum(1 for c in crossings if c["tags"].get("crossing") == "traffic_signals")
    print(f"  Переходов со светофором: {traffic_signals_count}")

else:
    print(f"\n  Переходов не найдено в радиусе 70 м")

print(f"\n{'=' * 80}")
print("ГОТОВО")
print(f"{'=' * 80}")