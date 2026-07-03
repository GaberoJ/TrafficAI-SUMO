# Traffic Intersection Simulator with AI & SUMO

Проект для автоматического построения и оптимизации дорожной сети на основе данных OpenStreetMap (OSM) с использованием Yandex AI Studio (агент) и симулятора SUMO.  
Позволяет:
- выбирать перекрёсток на интерактивной карте;
- извлекать геометрию дорог и светофоров из OSM;
- с помощью AI-агента определять полосы и разрешённые манёвры;
- строить сеть SUMO, генерировать маршруты и индукционные петли;
- редактировать полосы и интенсивность через графический интерфейс;
- оптимизировать длительности фаз светофоров генетическим алгоритмом;
- сравнивать результаты оптимизации.

---

## Требования

- **Python 3.8+**
- **SUMO** (Simulation of Urban MObility) – установите с [официального сайта](https://sumo.dlr.de/docs/Downloads.php) и добавьте `bin` в `PATH`
- **Аккаунт Yandex Cloud** с доступом к AI Studio (для работы агента)

---

## Запуск проекта:

Скопировать пример окружения и изменить в .env YANDEX_API_KEY:

- cp .env.example .env


Из корня проекта:

- python .\agent\llm_client.py - Автоматическое построение сети
- sumo-gui -c .\sumo\intersection.sumocfg - Проверка построенной сети и маршрутов в симуляции
- python .\ui\main.py - Корректировка движения по полосам и интенсивности
- python .\sumo\optimize_traffic_lights.py - Оптимизация построенной сети
- sumo-gui -c .\sumo\test_intersection_optimized_ga.sumo.cfg - Проверка построенной оптимизированной сети и маршрутов в симуляции
- python .\sumo\compare\compare_results.py - Сравнение результатов (появятся файлы в папке sumo\compare)

## Презентация проекта:

https://disk.yandex.ru/d/QlE4gSzGdoZSuA