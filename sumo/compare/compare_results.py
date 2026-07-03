import os
import sys
import shutil
import tempfile
import xml.etree.ElementTree as ET
from pathlib import Path
import traci

SCRIPT_DIR = Path(__file__).parent
SUMO_DIR = SCRIPT_DIR.parent

ORIGINAL_NET = SUMO_DIR / "test_intersection.net.xml"
OPTIMIZED_NET = SUMO_DIR / "test_intersection_optimized_ga.net.xml"
ROUTES_FILE = SUMO_DIR / "routes.rou.xml"
DETECTORS_FILE = SUMO_DIR / "detectors.add.xml"
CONFIG_FILE = SUMO_DIR / "intersection.sumocfg"

STATS_INTERVAL = 1


def get_detector_ids():
    """Извлекает ID детекторов из файла."""
    if not DETECTORS_FILE.exists():
        print(f"Файл детекторов не найден: {DETECTORS_FILE}")
        return []
    tree = ET.parse(DETECTORS_FILE)
    root = tree.getroot()
    detectors = []
    detectors.extend([elem.get("id") for elem in root.findall("e1Detector")])
    detectors.extend([elem.get("id") for elem in root.findall("inductionLoop")])
    return detectors


def get_lane_from_detector(det_id):
    """Извлекает имя полосы из ID детектора."""
    if det_id.startswith("det_"):
        return det_id.replace("det_", "")
    if det_id.startswith("e1det_"):
        return det_id.replace("e1det_", "")
    return det_id


DETECTOR_IDS = get_detector_ids()
print(f"Загружено детекторов: {len(DETECTOR_IDS)}")
for d in DETECTOR_IDS:
    print(f"  - {d}")

LANE_TO_DETECTOR = {}
for det_id in DETECTOR_IDS:
    lane = get_lane_from_detector(det_id)
    LANE_TO_DETECTOR[lane] = det_id


def collect_statistics(net_path, output_prefix, label="Сеть"):
    """
    Запускает симуляцию и собирает ДВА типа данных:
      1. Задержки и очереди (через TraCI) -> {output_prefix}_delays.txt
      2. Данные с петель (пропускная способность) -> {output_prefix}_detectors.txt
    """
    print(f"\n{'=' * 60}")
    print(f" Сбор статистики для: {label}")
    print(f"   Сеть: {net_path.name}")
    print(f"{'=' * 60}")

    if not net_path.exists():
        print(f" Файл сети не найден: {net_path}")
        return False

    if not DETECTOR_IDS:
        print(" Нет детекторов для сбора данных")
        return False

    temp_net = Path(tempfile.mktemp(suffix=".net.xml"))
    shutil.copy(net_path, temp_net)

    temp_cfg = Path(tempfile.mktemp(suffix=".sumocfg"))
    cfg_content = f'''<?xml version="1.0" encoding="UTF-8"?>
<configuration>
    <input>
        <net-file value="{temp_net}"/>
        <route-files value="{ROUTES_FILE}"/>
        <additional-files value="{DETECTORS_FILE}"/>
    </input>
    <time>
        <begin value="0"/>
        <end value="360"/>
    </time>
    <processing>
        <time-to-teleport value="-1"/>
    </processing>
</configuration>'''
    with open(temp_cfg, "w", encoding="utf-8") as f:
        f.write(cfg_content)

    total_delay = {det_id: 0.0 for det_id in DETECTOR_IDS}
    count_delay = {det_id: 0 for det_id in DETECTOR_IDS}
    queue_sum = {det_id: 0.0 for det_id in DETECTOR_IDS}
    queue_count = {det_id: 0 for det_id in DETECTOR_IDS}
    queue_max = {det_id: 0 for det_id in DETECTOR_IDS}
    unique_vehicles = {det_id: set() for det_id in DETECTOR_IDS}

    all_vehicles = set()

    prev_wait = {}
    veh_lane = {}

    detector_passed = {det_id: 0 for det_id in DETECTOR_IDS}
    detector_speed_sum = {det_id: 0.0 for det_id in DETECTOR_IDS}
    detector_speed_count = {det_id: 0 for det_id in DETECTOR_IDS}
    detector_occupancy_sum = {det_id: 0.0 for det_id in DETECTOR_IDS}
    detector_occupancy_count = {det_id: 0 for det_id in DETECTOR_IDS}

    last_active_time = 0
    sumo_cmd = ["sumo", "-c", str(temp_cfg), "--start", "--no-step-log"]

    try:
        traci.start(sumo_cmd)
        step = 0
        last_snapshot = 0

        while step < 360:
            traci.simulationStep()
            step += 1
            current_time = traci.simulation.getTime()

            active_vehicles = traci.vehicle.getIDList()
            if active_vehicles:
                last_active_time = current_time

            for veh_id in active_vehicles:
                all_vehicles.add(veh_id)

            if not active_vehicles and current_time > 30 and current_time - last_active_time > 30:
                print(f"   Машины закончились на {last_active_time:.0f} сек")
                break

            for veh_id in active_vehicles:
                current_wait = traci.vehicle.getWaitingTime(veh_id)
                try:
                    lane_id = traci.vehicle.getLaneID(veh_id)
                except:
                    lane_id = None

                if veh_id not in prev_wait:
                    prev_wait[veh_id] = current_wait
                    if lane_id is not None:
                        veh_lane[veh_id] = lane_id
                    continue

                delta = current_wait - prev_wait[veh_id]
                if delta > 0:
                    lane = veh_lane.get(veh_id)
                    if lane is not None and lane in LANE_TO_DETECTOR:
                        det_id = LANE_TO_DETECTOR[lane]
                        total_delay[det_id] += delta
                        count_delay[det_id] += 1

                prev_wait[veh_id] = current_wait
                if lane_id is not None:
                    veh_lane[veh_id] = lane_id

            if current_time - last_snapshot >= STATS_INTERVAL:
                last_snapshot = current_time

                for det_id in DETECTOR_IDS:
                    lane = get_lane_from_detector(det_id)
                    try:
                        vehicles = traci.lane.getLastStepVehicleIDs(lane)
                        for veh in vehicles:
                            unique_vehicles[det_id].add(veh)

                        halted = traci.lane.getLastStepHaltingNumber(lane)
                        queue_sum[det_id] += halted
                        queue_count[det_id] += 1
                        if halted > queue_max[det_id]:
                            queue_max[det_id] = halted
                    except:
                        pass

                for det_id in DETECTOR_IDS:
                    try:
                        n_vehicles = traci.inductionloop.getLastStepVehicleNumber(det_id)
                        if n_vehicles > 0:
                            detector_passed[det_id] += n_vehicles
                            speed = traci.inductionloop.getLastStepMeanSpeed(det_id)
                            if speed >= 0:
                                detector_speed_sum[det_id] += speed
                                detector_speed_count[det_id] += 1
                            occupancy = traci.inductionloop.getLastStepOccupancy(det_id)
                            if occupancy >= 0:
                                detector_occupancy_sum[det_id] += occupancy
                                detector_occupancy_count[det_id] += 1
                    except:
                        pass

        print(f" Симуляция завершена. Собрано {step} шагов.")

    except Exception as e:
        print(f" Ошибка во время симуляции: {e}")
        return False
    finally:
        try:
            traci.close()
        except:
            pass
        try:
            temp_net.unlink()
        except:
            pass
        try:
            temp_cfg.unlink()
        except:
            pass

    total_vehicles_seen = len(all_vehicles)

    all_detected_vehicles = set()
    for det_id in DETECTOR_IDS:
        all_detected_vehicles.update(unique_vehicles[det_id])
    total_detected_vehicles = len(all_detected_vehicles)

    delays_file = f"{output_prefix}_delays.txt"
    with open(delays_file, "w", encoding='utf-8') as f:
        f.write(f"ОТЧЁТ О ЗАДЕРЖКАХ И ОЧЕРЕДЯХ (ЧЕРЕЗ TraCI)\n")
        f.write(f"Сеть: {net_path.name}\n")
        f.write(f"Время сбора данных: до {last_active_time:.0f} сек\n")
        f.write("=" * 80 + "\n\n")

        total_wait_all = 0.0
        total_vehicles_all = 0

        for det_id in DETECTOR_IDS:
            lane = get_lane_from_detector(det_id)
            delay_sum = total_delay[det_id]
            count_delay_det = count_delay[det_id]
            avg_delay = delay_sum / count_delay_det if count_delay_det > 0 else 0.0
            avg_queue = queue_sum[det_id] / queue_count[det_id] if queue_count[det_id] > 0 else 0.0
            max_queue = queue_max[det_id]
            unique_cnt = len(unique_vehicles[det_id])
            stops_per_vehicle = count_delay_det / unique_cnt if unique_cnt > 0 else 0.0

            total_wait_all += delay_sum
            total_vehicles_all += unique_cnt

            f.write(f"Полоса '{lane}':\n")
            f.write(f"  - Суммарное время задержек: {delay_sum:.2f} сек\n")
            f.write(f"  - Количество зарегистрированных задержек (прирост): {count_delay_det}\n")
            f.write(f"  - СРЕДНЯЯ ЗАДЕРЖКА НА МАШИНУ: {avg_delay:.2f} сек\n")
            f.write(f"  - Количество уникальных машин: {unique_cnt}\n")
            f.write(f"  - Среднее количество остановок на машину: {stops_per_vehicle:.2f}\n")
            f.write(f"  - СРЕДНЯЯ ДЛИНА ОЧЕРЕДИ: {avg_queue:.2f}\n")
            f.write(f"  - МАКСИМАЛЬНАЯ ДЛИНА ОЧЕРЕДИ: {max_queue}\n\n")

        if DETECTOR_IDS:
            avg_wait_all = total_wait_all / len(DETECTOR_IDS) if DETECTOR_IDS else 0
            f.write("=" * 80 + "\n")
            f.write("СВОДКА ПО ВСЕМ ДЕТЕКТОРАМ:\n")
            f.write(f"  - Общее время задержек (сумма по полосам): {total_wait_all:.2f} сек\n")
            f.write(f"  - Среднее время задержек на детектор: {avg_wait_all:.2f} сек\n")
            f.write(f"  - Всего уникальных машин (сумма по полосам): {total_vehicles_all}\n")
            f.write(f"  - Всего уникальных машин (по всем детекторам): {total_detected_vehicles}\n")
            f.write(f"  - Всего машин, появившихся в симуляции: {total_vehicles_seen}\n")

    print(f" Отчёт о задержках: {delays_file}")

    detectors_file = f"{output_prefix}_detectors.txt"
    with open(detectors_file, "w", encoding='utf-8') as f:
        f.write(f"ОТЧЁТ С ИНДУКЦИОННЫХ ПЕТЕЛЬ\n")
        f.write(f"Сеть: {net_path.name}\n")
        f.write(f"Время сбора данных: до {last_active_time:.0f} сек\n")
        f.write("=" * 80 + "\n\n")

        for det_id in DETECTOR_IDS:
            lane = get_lane_from_detector(det_id)
            passed = detector_passed[det_id]
            avg_speed = detector_speed_sum[det_id] / detector_speed_count[det_id] if detector_speed_count[det_id] > 0 else 0.0
            avg_occupancy = detector_occupancy_sum[det_id] / detector_occupancy_count[det_id] if detector_occupancy_count[det_id] > 0 else 0.0

            f.write(f"Петля '{det_id}' (полоса '{lane}'):\n")
            f.write(f"  - Количество проехавших машин (по петле): {passed}\n")
            f.write(f"  - Средняя скорость: {avg_speed:.2f} м/с\n")
            f.write(f"  - Средняя занятость: {avg_occupancy:.2f}%\n\n")

        if DETECTOR_IDS:
            f.write("=" * 80 + "\n")
            f.write("СВОДКА ПО ВСЕМ ПЕТЛЯМ:\n")
            f.write(f"  - Всего проехало машин (по петлям, может быть завышено): {sum(detector_passed.values())}\n")
            avg_speed_all = sum(detector_speed_sum[d] / detector_speed_count[d] if detector_speed_count[d] > 0 else 0 for d in DETECTOR_IDS) / len(DETECTOR_IDS) if DETECTOR_IDS else 0
            avg_occupancy_all = sum(detector_occupancy_sum[d] / detector_occupancy_count[d] if detector_occupancy_count[d] > 0 else 0 for d in DETECTOR_IDS) / len(DETECTOR_IDS) if DETECTOR_IDS else 0
            f.write(f"  - Средняя скорость по всем петлям: {avg_speed_all:.2f} м/с\n")
            f.write(f"  - Средняя занятость по всем петлям: {avg_occupancy_all:.2f}%\n")

    print(f" Отчёт с петель: {detectors_file}")

    return True


def main():
    print("=" * 60)
    print("УНИВЕРСАЛЬНОЕ СРАВНЕНИЕ СЕТЕЙ (ДВА ТИПА ДАННЫХ)")
    print("=" * 60)

    for f in [ORIGINAL_NET, OPTIMIZED_NET, ROUTES_FILE, DETECTORS_FILE]:
        if not f.exists():
            print(f" Файл не найден: {f}")
            return

    print(f"\n Исходная сеть: {ORIGINAL_NET.name}")
    print(f" Оптимизированная сеть: {OPTIMIZED_NET.name}")
    print(f" Детекторов: {len(DETECTOR_IDS)}")

    collect_statistics(ORIGINAL_NET, str(SCRIPT_DIR / "original"), label="Исходная сеть")
    collect_statistics(OPTIMIZED_NET, str(SCRIPT_DIR / "optimized"), label="Оптимизированная сеть")

    print("\n" + "=" * 60)
    print(" Сравнение завершено!")
    print(f"   Файлы для исходной сети: original_delays.txt, original_detectors.txt")
    print(f"   Файлы для оптимизированной сети: optimized_delays.txt, optimized_detectors.txt")
    print("=" * 60)


if __name__ == "__main__":
    main()