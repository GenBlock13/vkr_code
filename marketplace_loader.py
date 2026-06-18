"""
marketplace_loader.py — получение отзывов из внешних источников.

Источники:
1. Гиперссылка Wildberries (публичный JSON-интерфейс, без авторизации);
2. Поиск товара по названию (например, «Средство от комаров детское»);
3. Произвольная веб-страница (generic-парсер на BeautifulSoup);
4. Демонстрационный режим — предзагруженные снимки в demo_data/ (офлайн).

Этические ограничения (НФТ-N3): тайм-аут 10 с, пауза >= 1 с между запросами,
без обхода средств защиты; персональные данные авторов не сохраняются.

ВКР: Еременко Г.С., ТГУ им. Г.Р. Державина, 2026
"""

import json
import os
import re
import time

import requests

try:
    from bs4 import BeautifulSoup
    _HAS_BS4 = True
except ImportError:  # generic-парсер деградирует, остальное работает
    _HAS_BS4 = False

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
DEMO_DIR = os.path.join(BASE_DIR, "demo_data")

TIMEOUT = 10
REQUEST_PAUSE = 1.0  # НФТ-N3: не чаще 1 запроса в секунду
HEADERS = {
    "User-Agent": ("Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
                   "(KHTML, like Gecko) Chrome/124.0 Safari/537.36"),
    "Accept": "application/json, text/html;q=0.9,*/*;q=0.8",
}

_WB_DEST = "-1257786"  # регион по умолчанию (Москва)

# Пороговые значения vol (nm_id // 100000) для определения номера CDN-корзины WB.
# При добавлении новых корзин WB достаточно дополнить список.
_WB_BASKET_THRESHOLDS = [
    143, 287, 431, 719, 1007, 1061, 1115, 1169,
    1313, 1601, 1655, 1919, 2045, 2189, 2405, 2621,
]


class LoaderError(Exception):
    """Ошибка получения данных из внешнего источника."""


def _get_json(url: str) -> dict:
    time.sleep(REQUEST_PAUSE)
    resp = requests.get(url, headers=HEADERS, timeout=TIMEOUT)
    resp.raise_for_status()
    return resp.json()


def _wb_basket_num(vol: int) -> str:
    """Номер CDN-корзины WB по vol = nm_id // 100000."""
    for i, threshold in enumerate(_WB_BASKET_THRESHOLDS, start=1):
        if vol <= threshold:
            return f"{i:02d}"
    return f"{len(_WB_BASKET_THRESHOLDS) + 1:02d}"


# ─────────────────────────────────────────────
# 1. WILDBERRIES: ссылка → артикул → отзывы
# ─────────────────────────────────────────────

def parse_wb_url(url: str) -> int:
    """Извлечение артикула (nm_id) из ссылки Wildberries.

    Принимает форматы вида .../catalog/123456789/detail.aspx?...,
    лишние параметры игнорируются.
    """
    m = re.search(r"wildberries\.[a-z]+/catalog/(\d{5,12})", url)
    if not m:
        m = re.search(r"/catalog/(\d{5,12})", url)
    if not m:
        raise LoaderError("Не удалось извлечь артикул из ссылки. Ожидается "
                          "формат https://www.wildberries.ru/catalog/<артикул>/detail.aspx")
    return int(m.group(1))


def _wb_card(nm_id: int) -> dict:
    """Карточка товара: название и imt_id (root) для запроса отзывов.

    Использует CDN WB (wbbasket.ru/card.json) вместо устаревшего
    /cards/v2/detail, который перестал отвечать.
    """
    vol = nm_id // 100000
    part = nm_id // 1000
    basket = _wb_basket_num(vol)
    url = (f"https://basket-{basket}.wbbasket.ru"
           f"/vol{vol}/part{part}/{nm_id}/info/ru/card.json")
    try:
        time.sleep(REQUEST_PAUSE)
        resp = requests.get(url, headers=HEADERS, timeout=TIMEOUT)
        resp.raise_for_status()
        data = resp.json()
    except Exception as e:
        raise LoaderError(f"Товар с артикулом {nm_id} не найден: {e}")
    imt_id = data.get("imt_id")
    if not imt_id:
        raise LoaderError(f"Не удалось определить imt_id для артикула {nm_id}.")
    return {"nm_id": nm_id,
            "name": data.get("imt_name", f"Артикул {nm_id}"),
            "root_id": imt_id}


def fetch_wb_reviews(nm_id: int, limit: int = 100) -> dict:
    """Получение отзывов товара WB через публичный JSON-интерфейс.

    Возвращает {"product": str, "source": str, "reviews": [{text, rating, date}]}.
    Имена авторов сознательно не сохраняются (этическое требование).
    """
    card = _wb_card(nm_id)
    root_id = card["root_id"]
    last_err = None
    for host in ("feedbacks2.wb.ru", "feedbacks1.wb.ru"):
        try:
            data = _get_json(f"https://{host}/feedbacks/v2/{root_id}")
            feedbacks = data.get("feedbacks") or []
            reviews = []
            for fb in feedbacks:
                # WB хранит текст в поле text, а плюсы/минусы — в pros/cons
                parts = [
                    (fb.get("text") or "").strip(),
                    (fb.get("pros") or "").strip(),
                    (fb.get("cons") or "").strip(),
                ]
                text = " ".join(p for p in parts if p)
                if not text:
                    continue
                reviews.append({
                    "text": text,
                    "rating": fb.get("productValuation"),
                    "date": (fb.get("createdDate") or "")[:10],
                })
                if len(reviews) >= limit:
                    break
            if reviews:
                return {"product": card["name"],
                        "source": f"wildberries:nm={nm_id}",
                        "reviews": reviews}
            last_err = LoaderError("Интерфейс ответил, но текстовых отзывов нет.")
        except Exception as e:  # пробуем следующий хост
            last_err = e
    raise LoaderError(f"Не удалось получить отзывы (root={root_id}): {last_err}")


# ─────────────────────────────────────────────
# 2. ПОИСК ТОВАРА ПО НАЗВАНИЮ
# ─────────────────────────────────────────────

def search_wb_products(query: str, limit: int = 8) -> list:
    """Поиск товаров WB по текстовому запросу (фильтр по наименованию).

    Пример запроса: «Средство от комаров детское».
    Возвращает [{nm_id, name, brand, rating, feedbacks}] для выбора пользователем.
    """
    q = requests.utils.quote(query.strip())
    url = (f"https://search.wb.ru/exactmatch/ru/common/v5/search?appType=1"
           f"&curr=rub&dest={_WB_DEST}&query={q}&resultset=catalog"
           f"&sort=popular&page=1")
    try:
        data = _get_json(url)
    except Exception as e:
        raise LoaderError(f"Поиск недоступен: {e}")
    # Начиная с 2024 г. WB возвращает products на верхнем уровне, без data.data
    products = data.get("products") or (data.get("data") or {}).get("products") or []
    out = []
    for p in products[:limit]:
        out.append({
            "nm_id": p.get("id"),
            "name": p.get("name", ""),
            "brand": p.get("brand", ""),
            "rating": p.get("reviewRating") or p.get("rating"),
            "feedbacks": p.get("feedbacks", 0),
        })
    if not out:
        raise LoaderError(f"По запросу «{query}» товары не найдены.")
    return out


def fetch_reviews_by_query(query: str, limit: int = 100) -> dict:
    """Поиск по названию + автоматический выбор товара с наибольшим числом отзывов."""
    products = search_wb_products(query)
    best = max(products, key=lambda p: p.get("feedbacks") or 0)
    return fetch_wb_reviews(best["nm_id"], limit=limit)


# ─────────────────────────────────────────────
# 3. GENERIC-ПАРСЕР ПРОИЗВОЛЬНОЙ СТРАНИЦЫ
# ─────────────────────────────────────────────

def fetch_generic_page(url: str, min_len: int = 40, limit: int = 100) -> dict:
    """Извлечение текстовых блоков, похожих на отзывы, с произвольной HTML-страницы.

    Эвристика: элементы с классами/атрибутами, содержащими review|feedback|comment;
    при их отсутствии — абзацы <p> длиной не менее min_len символов.
    Не работает для страниц, формируемых JavaScript (SPA) — для них
    предусмотрены загрузка из файла и демо-режим.
    """
    if not _HAS_BS4:
        raise LoaderError("Библиотека beautifulsoup4 не установлена.")
    time.sleep(REQUEST_PAUSE)
    resp = requests.get(url, headers=HEADERS, timeout=TIMEOUT)
    resp.raise_for_status()
    soup = BeautifulSoup(resp.text, "html.parser")

    blocks = soup.find_all(attrs={"class": re.compile(r"review|feedback|comment", re.I)})
    texts = []
    for b in blocks:
        t = b.get_text(" ", strip=True)
        if len(t) >= min_len:
            texts.append(t)
    if not texts:  # запасная эвристика — длинные абзацы
        for p in soup.find_all("p"):
            t = p.get_text(" ", strip=True)
            if len(t) >= min_len:
                texts.append(t)

    # дедупликация с сохранением порядка
    seen, reviews = set(), []
    for t in texts:
        if t not in seen:
            seen.add(t)
            reviews.append({"text": t, "rating": None, "date": None})
        if len(reviews) >= limit:
            break
    if not reviews:
        raise LoaderError("На странице не найдено текстовых блоков, похожих на отзывы. "
                          "Возможно, контент формируется JavaScript — используйте "
                          "загрузку из файла или демо-режим.")
    title = soup.title.get_text(strip=True) if soup.title else url
    return {"product": title, "source": url, "reviews": reviews}


# ─────────────────────────────────────────────
# 4. ДЕМОНСТРАЦИОННЫЙ РЕЖИМ (офлайн)
# ─────────────────────────────────────────────

def list_demo_products() -> list:
    """Список доступных демо-наборов: [{file, product, date, count}]."""
    out = []
    if not os.path.isdir(DEMO_DIR):
        return out
    for fn in sorted(os.listdir(DEMO_DIR)):
        if not fn.endswith(".json"):
            continue
        try:
            with open(os.path.join(DEMO_DIR, fn), encoding="utf-8") as f:
                data = json.load(f)
            out.append({"file": fn,
                        "product": data.get("product", fn),
                        "date": data.get("snapshot_date", ""),
                        "count": len(data.get("reviews", []))})
        except (json.JSONDecodeError, OSError):
            continue
    return out


def load_cached(name: str) -> dict:
    """Чтение предзагруженного снимка отзывов из demo_data/."""
    path = os.path.join(DEMO_DIR, name)
    if not os.path.isfile(path):
        raise LoaderError(f"Демо-набор {name} не найден.")
    with open(path, encoding="utf-8") as f:
        return json.load(f)
