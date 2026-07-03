import os, subprocess, math, tempfile, sys, io, re, xml.etree.ElementTree as ET

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')

APPROACH_LENGTH = 150.0

def transliterate(text):
    mapping = {
        'а':'a','б':'b','в':'v','г':'g','д':'d','е':'e','ё':'e','ж':'zh','з':'z',
        'и':'i','й':'y','к':'k','л':'l','м':'m','н':'n','о':'o','п':'p','р':'r',
        'с':'s','т':'t','у':'u','ф':'f','х':'h','ц':'ts','ч':'ch','ш':'sh','щ':'sch',
        'ъ':'','ы':'y','ь':'','э':'e','ю':'yu','я':'ya',' ':'_'
    }
    result = text.lower()
    for rus, lat in mapping.items():
        result = result.replace(rus, lat)
    result = re.sub(r'[^a-z0-9_]', '', result)
    return result

def add_pedestrian_phases_to_net(net_file: str):
    """
    Находит пешеходные сигналы и модифицирует tlLogic:
      - во всех существующих фазах делает пешеходные сигналы красными ('r')
      - добавляет новую пешеходную фазу в конец (пешеходы зелёные 'g')
      - добавляет короткую фазу "все красные" для очистки
    """
    try:
        tree = ET.parse(net_file)
        root = tree.getroot()

        pedestrian_indices = set()
        for conn in root.findall("connection"):
            from_edge = conn.get("from", "")
            to_edge = conn.get("to", "")
            if ("_c" in from_edge or "_c" in to_edge or
                "_w" in from_edge or "_w" in to_edge):
                link_idx = conn.get("linkIndex")
                if link_idx is not None:
                    pedestrian_indices.add(int(link_idx))
        for edge in root.findall("edge"):
            if edge.get("function") in ("crossing", "walkingarea"):
                for conn in edge.findall("connection"):
                    link_idx = conn.get("linkIndex")
                    if link_idx is not None:
                        pedestrian_indices.add(int(link_idx))

        if not pedestrian_indices:
            print("⚠ Пешеходные сигналы не найдены, пешеходные фазы не добавлены.")
            return

        print(f" Найдены пешеходные индексы: {sorted(pedestrian_indices)}")

        tl_logic = root.find("tlLogic")
        if tl_logic is None:
            print(" tlLogic не найден в сети")
            return

        phases = tl_logic.findall("phase")
        if not phases:
            print(" Нет фаз в tlLogic")
            return

        num_signals = len(phases[0].get("state"))
        print(f" Всего сигналов: {num_signals}")

        for phase in phases:
            state = list(phase.get("state"))
            for idx in pedestrian_indices:
                state[idx] = 'r'
            phase.set("state", "".join(state))

        ped_state = list("r" * num_signals)
        for i in pedestrian_indices:
            ped_state[i] = "g"
        ped_phase = ET.Element("phase", duration="15.0", state="".join(ped_state))
        all_red = ET.Element("phase", duration="1.0", state="r" * num_signals)

        tl_logic.append(ped_phase)
        tl_logic.append(all_red)

        tree.write(net_file, encoding="utf-8", xml_declaration=True)
        print(f" Пешеходные фазы успешно добавлены, исходные фазы исправлены в {net_file}")

        for i, ph in enumerate(tl_logic.findall("phase")[:4]):
            print(f"   Фаза {i+1}: dur={ph.get('duration')} state={ph.get('state')}")

    except Exception as e:
        print(f" Ошибка при добавлении пешеходных фаз: {e}")


def build_network(approaches: list, output_file: str = "intersection.net.xml", debug: bool = True) -> str:
    has_lights = any(a.get("traffic_lights") for a in approaches)

    grouped = {}
    for app in approaches:
        name = app["street_name"]
        angle = app["angle_deg"]
        key = (name, round(angle))
        if key not in grouped:
            grouped[key] = {
                "street_name": name,
                "angle_deg": angle,
                "lanes_in": 0,
                "lanes_out": 0,
                "turn_lanes_in": [],
                "traffic_lights": [],
                "has_in": False,
                "has_out": False
            }
        if app["direction"] == "ВЪЕЗД":
            grouped[key]["lanes_in"] = app["lanes"]
            grouped[key]["turn_lanes_in"] = app.get("turn_lanes", [])
            grouped[key]["has_in"] = True
        elif app["direction"] == "ВЫЕЗД":
            grouped[key]["lanes_out"] = app["lanes"]
            grouped[key]["has_out"] = True
        if app.get("traffic_lights"):
            grouped[key]["traffic_lights"].extend(app["traffic_lights"])

    sorted_approaches = sorted(grouped.values(), key=lambda x: x["angle_deg"])

    nod_xml = '<?xml version="1.0" encoding="UTF-8"?>\n<nodes>\n'
    nod_xml += '    <node id="center" x="0.0" y="0.0" type="traffic_light"/>\n'
    for app in sorted_approaches:
        name = app["street_name"]
        angle = app["angle_deg"]
        bid = f"{transliterate(name)}_{angle:.0f}"
        if app["has_in"]:
            rad = math.radians(angle)
            x, y = -APPROACH_LENGTH * math.sin(rad), -APPROACH_LENGTH * math.cos(rad)
            nod_xml += f'    <node id="in_{bid}" x="{x:.2f}" y="{y:.2f}"/>\n'
        if app["has_out"]:
            rad = math.radians(angle + 180)
            x, y = -APPROACH_LENGTH * math.sin(rad), -APPROACH_LENGTH * math.cos(rad)
            nod_xml += f'    <node id="out_{bid}" x="{x:.2f}" y="{y:.2f}"/>\n'
    nod_xml += '</nodes>\n'

    edg_xml = '<?xml version="1.0" encoding="UTF-8"?>\n<edges>\n'
    for app in sorted_approaches:
        name = app["street_name"]
        angle = app["angle_deg"]
        bid = f"{transliterate(name)}_{angle:.0f}"
        speed = 13.89
        if app["has_in"]:
            edg_xml += f'    <edge from="in_{bid}" to="center" id="in_{bid}" numLanes="{app["lanes_in"]}" speed="{speed:.2f}"/>\n'
        if app["has_out"]:
            edg_xml += f'    <edge from="center" to="out_{bid}" id="out_{bid}" numLanes="{app["lanes_out"]}" speed="{speed:.2f}"/>\n'
    edg_xml += '</edges>\n'

    con_xml = '<?xml version="1.0" encoding="UTF-8"?>\n<connections>\n'
    dir_map = {"through": "s", "left": "l", "right": "r", "slight_right": "r", "UNK": "s"}

    for app in sorted_approaches:
        if not app["has_in"]:
            continue
        name = app["street_name"]
        angle = app["angle_deg"]
        bid = f"{transliterate(name)}_{angle:.0f}"
        in_edge = f"in_{bid}"
        lanes_in = app["lanes_in"]
        turn_lanes = app["turn_lanes_in"] if app["turn_lanes_in"] else [["UNK"]] * lanes_in

        turn_lanes = turn_lanes[:lanes_in]

        for lane_idx, maneuvers in enumerate(turn_lanes):
            sumo_lane = lanes_in - 1 - lane_idx

            for m in maneuvers:
                target = None
                to_lane = 0
                dir_attr = dir_map.get(m, "s")

                if m in ("through", "UNK"):
                    for other in sorted_approaches:
                        if not other["has_out"] or other["street_name"] != name:
                            continue
                        other_angle = (other["angle_deg"] + 180) % 360
                        target_angle = (angle + 180) % 360
                        if abs(other_angle - target_angle) < 30:
                            other_bid = f"{transliterate(other['street_name'])}_{other['angle_deg']:.0f}"
                            target = f"out_{other_bid}"
                            to_lane = min(sumo_lane, other["lanes_out"] - 1)
                            con_xml += f'    <connection from="{in_edge}" to="{target}" fromLane="{sumo_lane}" toLane="{to_lane}" dir="s"/>\n'
                            break

                elif m == "left":
                    target_exit_angle = (angle + 90) % 360
                    best = None
                    best_diff = 50
                    for other in sorted_approaches:
                        if not other["has_out"] or other["street_name"] == name:
                            continue
                        other_exit_angle = (other["angle_deg"] + 180) % 360
                        diff = abs((other_exit_angle - target_exit_angle + 180) % 360 - 180)
                        if diff < best_diff:
                            best_diff = diff
                            other_bid = f"{transliterate(other['street_name'])}_{other['angle_deg']:.0f}"
                            best = (f"out_{other_bid}", other["lanes_out"])
                    if best:
                        target, exit_lanes = best
                        to_lane = exit_lanes - 1
                        con_xml += f'    <connection from="{in_edge}" to="{target}" fromLane="{sumo_lane}" toLane="{to_lane}" dir="l"/>\n'

                elif m in ("right", "slight_right"):
                    target_exit_angle = (angle - 90) % 360
                    best = None
                    best_diff = 50
                    for other in sorted_approaches:
                        if not other["has_out"] or other["street_name"] == name:
                            continue
                        other_exit_angle = (other["angle_deg"] + 180) % 360
                        diff = abs((other_exit_angle - target_exit_angle + 180) % 360 - 180)
                        if diff < best_diff:
                            best_diff = diff
                            other_bid = f"{transliterate(other['street_name'])}_{other['angle_deg']:.0f}"
                            best = (f"out_{other_bid}", other["lanes_out"])
                    if best:
                        target, exit_lanes = best
                        to_lane = 0
                        con_xml += f'    <connection from="{in_edge}" to="{target}" fromLane="{sumo_lane}" toLane="{to_lane}" dir="r"/>\n'

    con_xml += '</connections>\n'

    with tempfile.TemporaryDirectory() as tmpdir:
        for name, content in [("nod.xml", nod_xml), ("edg.xml", edg_xml), ("con.xml", con_xml)]:
            with open(os.path.join(tmpdir, f"intersection.{name}"), "w", encoding="utf-8") as f:
                f.write(content)

        cmd = [
            "netconvert",
            "--node-files", os.path.join(tmpdir, "intersection.nod.xml"),
            "--edge-files", os.path.join(tmpdir, "intersection.edg.xml"),
            "--connection-files", os.path.join(tmpdir, "intersection.con.xml"),
            "--output-file", output_file,
            "--no-turnarounds",
            "--junctions.corner-detail", "0",
            "--sidewalks.guess",
            "--crossings.guess",
            "--default.sidewalk-width", "2.0",
        ]
        if has_lights:
            cmd += ["--tls.guess", "--tls.green.time=30", "--tls.yellow.time=3"]

        print(f"Запуск: {' '.join(cmd)}")
        result = subprocess.run(cmd, capture_output=True, text=True)
        if result.returncode != 0:
            print("STDERR:", result.stderr)
            raise RuntimeError(f"netconvert error: {result.stderr}")

    add_pedestrian_phases_to_net(output_file)

    return output_file


def generate_pedestrians_add(approaches: list, output_file: str = "pedestrians.add.xml") -> str:
    """Генерирует отдельный файл с пешеходными переходами (с привязкой к светофору)"""
    add_xml = '<?xml version="1.0" encoding="UTF-8"?>\n<additional>\n'
    add_xml += '    <pedestrianCrossing id="pc_center" edges=":center_0_0 :center_0_1" />\n'

    for app in approaches:
        if app["direction"] != "ВЪЕЗД":
            continue
        name = app["street_name"]
        angle = app["angle_deg"]
        bid = f"{transliterate(name)}_{angle:.0f}"
        edge_id = f"in_{bid}"
        lanes = app["lanes"]
        for lane in range(lanes):
            to_lane = lanes - 1 - lane
            add_xml += f'    <crossing id="cross_{edge_id}_{lane}" edge="{edge_id}" fromLane="{lane}" toLane="{to_lane}" priority="true" width="3.0" trafficLight="true"/>\n'

    add_xml += '</additional>\n'
    with open(output_file, "w", encoding="utf-8") as f:
        f.write(add_xml)
    return output_file


def generate_tls_with_pedestrian_phases(approaches: list, net_file: str, output_file: str = "tls_pedestrians.add.xml") -> str:
    """
    Добавляет пешеходную фазу в конец существующего цикла светофора.
    Использует programID="1", чтобы не конфликтовать с исходным tlLogic.
    """
    try:
        tree = ET.parse(net_file)
        root = tree.getroot()

        pedestrian_indices = set()
        for conn in root.findall("connection"):
            from_edge = conn.get("from", "")
            to_edge = conn.get("to", "")
            if ("_c" in from_edge or "_c" in to_edge or
                "_w" in from_edge or "_w" in to_edge):
                link_idx = conn.get("linkIndex")
                if link_idx is not None:
                    pedestrian_indices.add(int(link_idx))
        for edge in root.findall("edge"):
            if edge.get("function") in ("crossing", "walkingarea"):
                for conn in edge.findall("connection"):
                    link_idx = conn.get("linkIndex")
                    if link_idx is not None:
                        pedestrian_indices.add(int(link_idx))

        if not pedestrian_indices:
            print(" Не найдено пешеходных сигналов, пропускаем генерацию")
            return output_file

        tl_logic = root.find("tlLogic")
        if tl_logic is None:
            print(" tlLogic не найден")
            return output_file

        phases = []
        for phase in tl_logic.findall("phase"):
            phases.append({
                "duration": float(phase.get("duration")),
                "state": phase.get("state")
            })
        if not phases:
            return output_file

        num_signals = len(phases[0]["state"])

        ped_state = list("r" * num_signals)
        for i in pedestrian_indices:
            ped_state[i] = "g"
        ped_phase = {"duration": 15.0, "state": "".join(ped_state)}
        all_red = {"duration": 1.0, "state": "r" * num_signals}

        phases.append(ped_phase)
        phases.append(all_red)

        tl_id = tl_logic.get("id")
        tls_xml = f'''<?xml version="1.0" encoding="UTF-8"?>
<additional>
    <tlLogic id="{tl_id}" type="static" programID="1" offset="0">
'''
        for ph in phases:
            tls_xml += f'        <phase duration="{ph["duration"]}" state="{ph["state"]}"/>\n'
        tls_xml += '    </tlLogic>\n</additional>'

        with open(output_file, "w", encoding="utf-8") as f:
            f.write(tls_xml)
        print(f" Светофор с пешеходными фазами (programID=1): {output_file}")
        return output_file

    except Exception as e:
        print(f" Ошибка: {e}")
        return output_file


if __name__ == "__main__":
    import json
    from pathlib import Path

    script_dir = Path(__file__).parent.parent
    json_path = script_dir / "osm" / "geometry.json"

    if not json_path.exists():
        print(f" Файл {json_path} не найден!")
        exit(1)

    with open(json_path, 'r', encoding='utf-8') as f:
        data = json.load(f)

    if isinstance(data, list):
        test_approaches = data
    elif isinstance(data, dict) and "approaches" in data:
        test_approaches = data["approaches"]
    else:
        print(" Неподдерживаемый формат geometry.json")
        exit(1)

    print(f"Загружено {len(test_approaches)} подходов из {json_path}")

    output_file = script_dir / "sumo" / "test_intersection.net.xml"
    build_network(test_approaches, str(output_file))

    ped_file = script_dir / "sumo" / "pedestrians.add.xml"
    generate_pedestrians_add(test_approaches, str(ped_file))

    print(f" Готово! Сеть сохранена в {output_file}")
    print(f" Пешеходные переходы (привязаны к светофору): {ped_file}")
    print("\n Запусти симуляцию:")
    print(f"   sumo-gui -c sumo/intersection.sumocfg -a sumo/pedestrians.add.xml")