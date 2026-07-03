import io
import os
import sys
import openai
import json
import subprocess
from pathlib import Path
from dotenv import load_dotenv
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')

PROJECT_ROOT = Path(__file__).parent.parent
load_dotenv(PROJECT_ROOT / '.env')

API_KEY = os.getenv("YANDEX_API_KEY")
FOLDER_ID = os.getenv("YANDEX_FOLDER_ID")
AGENT_ID = os.getenv("YANDEX_AGENT_ID")

COORDS_FILE = PROJECT_ROOT / "clicked_coords.json"
OUTPUT_FILE = PROJECT_ROOT / "osm" / "geometry.json"
NETWORK_FILE = PROJECT_ROOT / "sumo" / "test_intersection.net.xml"
ROUTES_FILE = PROJECT_ROOT / "sumo" / "routes.rou.xml"
CONFIG_FILE = PROJECT_ROOT / "sumo" / "intersection.sumocfg"


def run_intersection_finder():
    """Запускает intersection_finder, получает координаты"""
    result = subprocess.run(
        ["python", str(PROJECT_ROOT / "osm" / "intersection_finder.py")],
        cwd=str(PROJECT_ROOT)
    )

    if result.returncode != 0:
        raise RuntimeError("intersection_finder завершился с ошибкой")

    if not COORDS_FILE.exists():
        raise RuntimeError("Файл с координатами не создан")

    with open(COORDS_FILE, "r", encoding="utf-8") as f:
        coords = json.load(f)
    return coords


def run_osm_extractor() -> str:
    """Запускает text_geometry_extractor и возвращает его вывод"""
    print("\n" + "=" * 50)
    print("ШАГ 2: ИЗВЛЕЧЕНИЕ ДАННЫХ OSM")
    print("=" * 50)

    result = subprocess.run(
        ["python", str(PROJECT_ROOT / "osm" / "text_geometry_extractor.py")],
        capture_output=True,
        text=True,
        encoding='utf-8',
        errors='replace',
        cwd=str(PROJECT_ROOT)
    )

    if result.returncode != 0:
        raise RuntimeError(f"Ошибка OSM экстрактора: {result.stderr}")

    print(f"Получено {len(result.stdout)} символов")
    return result.stdout


def call_agent(prompt: str) -> str:
    """Вызывает агента и возвращает ответ"""
    print("\n" + "=" * 50)
    print("ШАГ 3: ВЫЗОВ АГЕНТА Yandex AI Studio")
    print("=" * 50)

    client = openai.OpenAI(
        api_key=API_KEY,
        base_url="https://ai.api.cloud.yandex.net/v1",
        project=FOLDER_ID
    )

    response = client.responses.create(
        prompt={"id": AGENT_ID},
        input=prompt,
        temperature=0.1
    )

    print(f"Получен ответ ({len(response.output_text)} символов)")
    return response.output_text


def extract_json(text: str) -> list:
    """Извлекает JSON из ответа агента"""
    text = text.strip()

    if "```json" in text:
        text = text.split("```json")[1].split("```")[0]
    elif "```" in text:
        text = text.split("```")[1].split("```")[0]

    start = text.find("[")
    end = text.rfind("]") + 1

    if start == -1 or end == 0:
        raise ValueError("JSON массив не найден в ответе агента")

    json_text = text[start:end]
    return json.loads(json_text)


def build_network():
    """Запускает net_builder для создания SUMO сети"""
    print("\n" + "=" * 50)
    print("ШАГ 4: ПОСТРОЕНИЕ SUMO СЕТИ")
    print("=" * 50)

    result = subprocess.run(
        ["python", str(PROJECT_ROOT / "sumo" / "net_builder.py")],
        cwd=str(PROJECT_ROOT),
        capture_output=True,
        text=True,
        encoding='utf-8',
        errors='replace'
    )

    if result.returncode != 0:
        print(f"STDERR: {result.stderr}")
        raise RuntimeError("net_builder завершился с ошибкой")

    print(result.stdout)
    print(f"✅ Сеть сохранена в {NETWORK_FILE}")


def build_routes():
    """Запускает route_builder для создания маршрутов и детекторов"""
    print("\n" + "=" * 50)
    print("ШАГ 5: ГЕНЕРАЦИЯ МАРШРУТОВ И ДЕТЕКТОРОВ")
    print("=" * 50)

    result = subprocess.run(
        ["python", str(PROJECT_ROOT / "sumo" / "route_builder.py")],
        cwd=str(PROJECT_ROOT),
        capture_output=True,
        text=True,
        encoding='utf-8',
        errors='replace'
    )

    if result.returncode != 0:
        print(f"STDERR: {result.stderr}")
        raise RuntimeError("route_builder завершился с ошибкой")

    print(result.stdout)
    print(f"✅ Маршруты сохранены в {ROUTES_FILE}")
    print(f"✅ Конфиг сохранён в {CONFIG_FILE}")


def main():
    try:
        run_intersection_finder()

        osm_data = run_osm_extractor()

        response = call_agent(osm_data)
        approaches = extract_json(response)

        with open(OUTPUT_FILE, "w", encoding="utf-8") as f:
            json.dump(approaches, f, ensure_ascii=False, indent=2)
        print(f"\n✅ JSON сохранён: {OUTPUT_FILE}")
        print(f"   Найдено подходов: {len(approaches)}")

        build_network()

        build_routes()

        print("\n" + "=" * 60)
        print("ВСЕ ШАГИ ВЫПОЛНЕНЫ УСПЕШНО!")
        print(f"   Файл сети: {NETWORK_FILE}")
        print(f"   Файл маршрутов: {ROUTES_FILE}")
        print(f"   Файл конфига: {CONFIG_FILE}")
        print("=" * 60)

    except Exception as e:
        print(f"\n❌ ОШИБКА: {e}")
        import traceback
        traceback.print_exc()
        return 1


if __name__ == "__main__":
    main()