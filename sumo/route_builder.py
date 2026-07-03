import xml.etree.ElementTree as ET
from pathlib import Path
import sys
import json
import os

PROJECT_ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from config import DEFAULT_FLOW_RATE

DEPART_STEP = 7.0

def parse_connections(net_file):
    """Извлекает все соединения in_* → out_* из SUMO сети"""
    tree = ET.parse(net_file)
    root = tree.getroot()
    connections = []
    for conn in root.findall("connection"):
        from_edge = conn.get("from")
        to_edge = conn.get("to")
        from_lane = conn.get("fromLane")
        if from_edge.startswith("in_") and to_edge.startswith("out_"):
            connections.append({
                "from": from_edge,
                "to": to_edge,
                "fromLane": int(from_lane)
            })
    return connections


def generate_detectors_manual(net_file, output_file, distance_before_stop=7):
    """
    Генерирует детекторы (индукционные петли) на въездных полосах,
    исключая дублирование ID.
    """
    tree = ET.parse(net_file)
    root = tree.getroot()

    detectors = []
    seen_ids = set()

    print(f"\n Генерация детекторов (distance_before_stop={distance_before_stop} м):")

    for conn in root.findall("connection"):
        tl = conn.get("tl")
        if tl:
            from_edge = conn.get("from")
            from_lane = conn.get("fromLane")

            if not from_edge or not from_edge.startswith("in_"):
                continue

            if from_edge and from_lane is not None:
                edge = root.find(f"./edge[@id='{from_edge}']")
                if edge is not None:
                    lane = edge.find(f"./lane[@index='{from_lane}']")
                    if lane is not None:
                        lane_length = float(lane.get("length", 0))
                        pos = max(1.0, lane_length - distance_before_stop)

                        det_id = f"det_{from_edge}_{from_lane}"
                        if det_id not in seen_ids:
                            seen_ids.add(det_id)
                            detectors.append({
                                "id": det_id,
                                "lane": f"{from_edge}_{from_lane}",
                                "pos": pos
                            })
                        else:
                            print(f"Детектор {det_id} уже добавлен, пропускаем дубликат.")

    if not detectors:
        print("Не найдено соединений для детекторов")
        return False

    add_xml = '<?xml version="1.0" encoding="UTF-8"?>\n<additional>\n'
    for d in detectors:
        add_xml += f'    <e1Detector id="{d["id"]}" lane="{d["lane"]}" pos="{d["pos"]:.1f}" period="1.0" file="detector_output.xml" friendlyPos="true"/>\n'
    add_xml += '</additional>'

    with open(output_file, "w", encoding="utf-8") as f:
        f.write(add_xml)

    print(f"Создано {len(detectors)} уникальных детекторов")
    return True


def generate_routes_from_network(net_file, output_routes, output_config, geometry_file=None):
    """Генерирует routes.rou.xml с потоками на основе интенсивности каждой полосы из geometry.json"""

    print("\n" + "=" * 70)
    print(" ОТЛАДКА: generate_routes_from_network")
    print(f"   geometry_file = {geometry_file}")
    print(f"   файл существует = {os.path.exists(geometry_file) if geometry_file else False}")
    print("=" * 70)

    lane_flow_rates = {}

    try:
        from sumo.net_builder import transliterate
    except ImportError:
        def transliterate(text):
            mapping = {
                'а': 'a', 'б': 'b', 'в': 'v', 'г': 'g', 'д': 'd', 'е': 'e', 'ё': 'e', 'ж': 'zh', 'з': 'z',
                'и': 'i', 'й': 'y', 'к': 'k', 'л': 'l', 'м': 'm', 'н': 'n', 'о': 'o', 'п': 'p', 'р': 'r',
                'с': 's', 'т': 't', 'у': 'u', 'ф': 'f', 'х': 'h', 'ц': 'ts', 'ч': 'ch', 'ш': 'sh', 'щ': 'sch',
                'ъ': '', 'ы': 'y', 'ь': '', 'э': 'e', 'ю': 'yu', 'я': 'ya', ' ': '_'
            }
            result = text.lower()
            for rus, lat in mapping.items():
                result = result.replace(rus, lat)
            import re
            result = re.sub(r'[^a-z0-9_]', '', result)
            return result

    if geometry_file and os.path.exists(geometry_file):
        with open(geometry_file, "r", encoding="utf-8") as f:
            geo_data = json.load(f)
        print(f"Загружено {len(geo_data)} записей из geometry.json")
        for app in geo_data:
            if app.get("direction") == "ВЪЕЗД":
                name = app.get("street_name", "")
                angle = app.get("angle_deg", 0)
                lanes = app.get("lanes", 0)
                flow_rates = app.get("lane_flow_rates", [DEFAULT_FLOW_RATE] * lanes)
                print(f" {name} угол {angle}: {flow_rates}")

                bid = f"{transliterate(name)}_{angle:.0f}"
                from_edge = f"in_{bid}"
                for lane_idx in range(lanes):
                    flow = flow_rates[lane_idx] if lane_idx < len(flow_rates) else DEFAULT_FLOW_RATE
                    sumo_lane = lanes - 1 - lane_idx
                    lane_flow_rates[(from_edge, sumo_lane)] = flow
                    print(f"      Полоса {lane_idx + 1} (ваша нумерация) -> SUMO-полоса {sumo_lane}: {flow} авто/час")
    else:
        print(" geometry_file не передан или не существует!")

    print("\n lane_flow_rates (все значения):")
    for (edge, lane), flow in sorted(lane_flow_rates.items()):
        print(f"   {edge} полоса {lane}: {flow} авто/час")

    conns = parse_connections(net_file)
    if not conns:
        raise RuntimeError("Нет соединений in_* → out_* в сети")

    groups = {}
    for c in conns:
        key = (c["from"], c["to"])
        if key not in groups:
            groups[key] = {"from": c["from"], "to": c["to"], "lanes": set()}
        groups[key]["lanes"].add(c["fromLane"])

    print("\n groups (маршруты и полосы):")
    for (from_edge, to_edge), data in groups.items():
        print(f"   {from_edge} -> {to_edge}: полосы {sorted(data['lanes'])}")

    routes_xml = '<?xml version="1.0" encoding="UTF-8"?>\n'
    routes_xml += '<routes>\n'
    routes_xml += '    <vType id="car" type="passenger" accel="2.6" decel="4.5" sigma="0.5" length="5" maxSpeed="13.89"/>\n\n'

    route_id = 1
    for (from_edge, to_edge), data in groups.items():
        edges = f"{from_edge} {to_edge}"
        routes_xml += f'    <route id="route_{route_id}" edges="{edges}"/>\n'

        for lane in sorted(data["lanes"]):
            flow_rate = lane_flow_rates.get((from_edge, lane), DEFAULT_FLOW_RATE)
            if flow_rate > 0:
                period = 3600.0 / flow_rate
                routes_xml += f'    <flow id="flow_{route_id}_lane_{lane}" type="car" route="route_{route_id}" begin="0" end="360" period="{period:.2f}" departLane="{lane}"/>\n'
                print(
                    f"    Маршрут {route_id}, SUMO-полоса {lane}: период {period:.2f} сек (интенсивность {flow_rate} авто/час)")
            else:
                print(f"    Маршрут {route_id}, SUMO-полоса {lane}: интенсивность 0, поток не создан")

        route_id += 1

    routes_xml += '</routes>\n'
    with open(output_routes, "w", encoding="utf-8") as f:
        f.write(routes_xml)

    net_dir = Path(net_file).parent
    detectors_file = net_dir / "detectors.add.xml"
    print("\n Генерация детекторов...")
    generate_detectors_manual(net_file, str(detectors_file), distance_before_stop=7)

    additional_files = []
    if (net_dir / "pedestrians.add.xml").exists():
        additional_files.append("pedestrians.add.xml")
    if (net_dir / "detectors.add.xml").exists():
        additional_files.append("detectors.add.xml")
    if (net_dir / "tls_pedestrians.add.xml").exists():
        additional_files.append("tls_pedestrians.add.xml")

    additional_str = ",".join(additional_files) if additional_files else ""

    sim_end = 360

    config_xml = f'''<?xml version="1.0" encoding="UTF-8"?>
    <configuration>
        <input>
            <net-file value="{net_file}"/>
            <route-files value="{output_routes}"/>
            <additional-files value="{additional_str}"/>
        </input>
        <time>
            <begin value="0"/>
            <end value="{sim_end}"/>
        </time>
        <processing>
            <time-to-teleport value="-1"/>
        </processing>
    </configuration>'''

    with open(output_config, "w", encoding="utf-8") as f:
        f.write(config_xml)

    print(f"\n Сгенерировано {len(groups)} маршрутов с потоками по полосам")
    print(f"   Файл маршрутов: {output_routes}")
    print(f"   Файл конфига: {output_config}")
    print(f"   Время симуляции: до {sim_end} секунд")
    print(f"   Подключены доп. файлы: {additional_str if additional_str else '(нет)'}")
    print("=" * 70 + "\n")


if __name__ == "__main__":
    net_file = Path(__file__).parent / "test_intersection.net.xml"
    routes_file = Path(__file__).parent / "routes.rou.xml"
    config_file = Path(__file__).parent / "intersection.sumocfg"
    geometry_file = Path(__file__).parent.parent / "osm" / "geometry.json"

    if not net_file.exists():
        print(f" Сеть {net_file} не найдена. Сначала запусти net_builder.py")
        exit(1)

    generate_routes_from_network(str(net_file), str(routes_file), str(config_file), str(geometry_file))
    print("\nЗапусти симуляцию:\n  sumo-gui -c intersection.sumocfg")