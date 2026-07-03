import requests, xml.etree.ElementTree as ET, math, json
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
    print(f" Ошибка при чтении файла: {e}")
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
    tags.pop("oneway", None)
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

print(f"Центр перекрёстка: {center_lat:.6f}, {center_lon:.6f}")

traffic_lights = []
for n in root.findall("node"):
    tags = {}
    for tag in n.findall("tag"):
        tags[tag.get("k")] = tag.get("v")
    if tags.get("highway") == "traffic_signals":
        tlat, tlon = float(n.get("lat")), float(n.get("lon"))
        if haversine(center_lat, center_lon, tlat, tlon) <= 70:
            traffic_lights.append(n.get("id"))

print(f"Светофоров в радиусе 70 м: {len(traffic_lights)}")

neighbors = defaultdict(set)
for wid1, data1 in all_ways.items():
    for wid2, data2 in all_ways.items():
        if wid1 >= wid2:
            continue
        if set(data1["nodes"]) & set(data2["nodes"]):
            neighbors[wid1].add(wid2)
            neighbors[wid2].add(wid1)

def way_angle(wid):
    nds = all_ways[wid]["nodes"]
    if len(nds) < 2:
        return None
    p1 = nodes_coords.get(nds[0])
    p2 = nodes_coords.get(nds[-1])
    if not p1 or not p2:
        return None
    dx = p2[1] - p1[1]
    dy = p2[0] - p1[0]
    return round(math.degrees(math.atan2(dx, dy)) % 360, 1)

print("\n" + "=" * 80)
print("DFS ОБХОД ДОРОГ ВОКРУГ СВЕТОФОРОВ")
print("=" * 80)

for tl_id in traffic_lights:
    print(f"\n{'=' * 60}")
    print(f"СВЕТОФОР {tl_id}")
    print(f"  Координаты: {nodes_coords[tl_id][0]:.6f}, {nodes_coords[tl_id][1]:.6f}")
    print(f"{'=' * 60}")

    seed_ways = [wid for wid in all_ways if tl_id in all_ways[wid]["nodes"]]
    print(f"Связан с way: {seed_ways}")

    visited = set()
    for seed in seed_ways:
        if seed in visited:
            continue
        visited.add(seed)

        tags = all_ways[seed]["tags"]
        name = tags.get("name", "без названия")
        nodes = all_ways[seed]["nodes"]
        angle = way_angle(seed)

        if nodes[0] == tl_id and nodes[-1] == tl_id:
            direction = "СВЕТОФОР ОДИН УЗЕЛ"
        elif nodes[0] == tl_id:
            direction = "ВЫЕЗД (первый узел)"
        elif nodes[-1] == tl_id:
            direction = "ВЪЕЗД (последний узел)"
        else:
            direction = "ВНУТРИ"

        print(f"\n  Way {seed}:")
        print(f"    Название: {name}")
        print(f"    Угол: {angle}°")
        print(f"    Направление: {direction}")
        print(f"    ВСЕ ТЕГИ:")
        for k, v in sorted(tags.items()):
            print(f"      {k} = {v}")

        stack = [(seed, 0)]
        while stack:
            wid, depth = stack.pop()
            if depth >= 2:
                continue

            for nb in sorted(neighbors[wid]):
                if nb in visited:
                    continue
                visited.add(nb)

                nb_tags = all_ways[nb]["tags"]
                nb_name = nb_tags.get("name", "без названия")
                nb_nodes = all_ways[nb]["nodes"]
                nb_angle = way_angle(nb)

                if nb_nodes[0] == tl_id and nb_nodes[-1] == tl_id:
                    nb_direction = "СВЕТОФОР ОДИН УЗЕЛ"
                elif nb_nodes[0] == tl_id:
                    nb_direction = "ВЫЕЗД (первый узел)"
                elif nb_nodes[-1] == tl_id:
                    nb_direction = "ВЪЕЗД (последний узел)"
                else:
                    nb_direction = "—"

                indent = "    " * (depth + 1)
                print(f"\n{indent}Way {nb} (глуб {depth + 1}):")
                print(f"{indent}  Название: {nb_name}")
                print(f"{indent}  Угол: {nb_angle}°")
                print(f"{indent}  Направление: {nb_direction}")
                print(f"{indent}  ВСЕ ТЕГИ:")
                for k, v in sorted(nb_tags.items()):
                    print(f"{indent}    {k} = {v}")

                stack.append((nb, depth + 1))

print("\nГОТОВО")