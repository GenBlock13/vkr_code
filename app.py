"""
app.py — веб-интерфейс системы детекции аномальных (ботовых) отзывов.

Альфа-версия. Вкладки:
  1. Дашборд        — метрики обученной модели (results.json) + Plotly;
  2. Проверка отзыва — классификация одного текста с диагностикой признаков;
  3. Файлы           — загрузка отзывов из TXT/CSV/JSON, пакетная
                       классификация, сохранение результатов в CSV/JSON;
  4. Маркетплейс     — отзывы по ссылке Wildberries, поиск по названию
                       товара, generic-парсер страницы, демо-режим (офлайн).

Запуск:  streamlit run app.py
Перед первым запуском обучить модель:  python bot_detector.py

ВКР: Еременко Г.С., ТГУ им. Г.Р. Державина, 2026
"""

import io
import json
import os
import re

import joblib
import pandas as pd
import plotly.express as px
import plotly.graph_objects as go
import streamlit as st

import marketplace_loader as ml
from utils import extract_features

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
MODEL_PATH = os.path.join(BASE_DIR, "model_pipeline.pkl")
RESULTS_PATH = os.path.join(BASE_DIR, "results.json")

st.set_page_config(page_title="Детектор аномальных отзывов",
                   page_icon="🛡️", layout="wide")

# Дополнительные CSS-правки поверх config.toml (земляная палитра)
st.markdown("""
<style>
/* Кнопка «Спарсить» и прочие primary — золотистая охра */
div.stButton > button[kind="primary"] {
    background: #A88420; border: none; color: white;
}
div.stButton > button[kind="primary"]:hover {
    background: #7A6010; color: white;
}
/* Метрики — тёплый фон карточек */
[data-testid="metric-container"] {
    background: #EDE8DC;
    border: 1px solid #C4B49A;
    border-radius: 8px;
    padding: 10px 16px;
}
/* Полоса прогресса */
[data-testid="stProgress"] > div > div {
    background: #7D6B52;
}
/* Вкладки — приглушённый акцент */
.stTabs [data-baseweb="tab-list"] {
    gap: 4px;
    border-bottom: 2px solid #C4B49A;
}
.stTabs [data-baseweb="tab"] {
    color: #6B5F54;
    border-radius: 6px 6px 0 0;
}
.stTabs [aria-selected="true"] {
    background: #EDE8DC;
    color: #3A312A;
    border-bottom: 2px solid #7D6B52;
}
/* Разделитель */
hr { border-color: #C4B49A; }
</style>
""", unsafe_allow_html=True)


# ─────────────────────────────────────────────
# Загрузка артефактов
# ─────────────────────────────────────────────

@st.cache_resource
def load_model():
    return joblib.load(MODEL_PATH)


@st.cache_data
def load_results():
    with open(RESULTS_PATH, encoding="utf-8") as f:
        return json.load(f)


if not os.path.exists(MODEL_PATH):
    st.error("Модель не найдена. Выполните в терминале: `python bot_detector.py` "
             "— будет обучена модель и созданы model_pipeline.pkl и results.json.")
    st.stop()

model = load_model()
results = load_results() if os.path.exists(RESULTS_PATH) else None


# ─────────────────────────────────────────────
# Общие функции
# ─────────────────────────────────────────────

def classify_texts(texts: list) -> pd.DataFrame:
    """Пакетная классификация: один вызов predict_proba, без цикла."""
    probs = model.predict_proba(texts)[:, 1]
    df = pd.DataFrame({
        "Отзыв": texts,
        "P(бот)": probs.round(3),
    })
    df["Вердикт"] = ["⚠️ Признаки генерации" if p > 0.5 else "✅ Подлинный"
                     for p in probs]
    return df.sort_values("P(бот)", ascending=False).reset_index(drop=True)


def summary_block(df: pd.DataFrame, product: str = ""):
    """Сводка + круговая диаграмма по результатам пакетной классификации."""
    n = len(df)
    n_bot = int((df["P(бот)"] > 0.5).sum())
    share = 100 * n_bot / n if n else 0

    c1, c2, c3 = st.columns(3)
    c1.metric("Отзывов проанализировано", n)
    c2.metric("С признаками генерации", f"{n_bot} из {n}", f"{share:.1f}%",
              delta_color="inverse")
    c3.metric("Средняя P(бот)", f"{df['P(бот)'].mean():.3f}")

    fig = px.pie(
        names=["Подлинные (по оценке модели)", "С признаками генерации"],
        values=[n - n_bot, n_bot],
        color_discrete_sequence=["#2e7d32", "#c62828"],
        title=f"Распределение классов{': ' + product if product else ''}",
        hole=0.45,
    )
    st.plotly_chart(fig, use_container_width=True)
    st.caption("Важно: метки — оценка модели по текстовым признакам, "
               "а не установленный факт накрутки.")
    st.dataframe(df, use_container_width=True, height=380)
    download_buttons(df, prefix="batch_results")


def download_buttons(df: pd.DataFrame, prefix: str = "results"):
    """Сохранение результатов в файл (CSV и JSON)."""
    csv_bytes = df.to_csv(index=False).encode("utf-8-sig")
    json_bytes = df.to_json(orient="records", force_ascii=False, indent=2).encode("utf-8")
    c1, c2 = st.columns(2)
    c1.download_button("💾 Сохранить CSV", csv_bytes,
                       file_name=f"{prefix}.csv", mime="text/csv")
    c2.download_button("💾 Сохранить JSON", json_bytes,
                       file_name=f"{prefix}.json", mime="application/json")


def parse_uploaded_file(uploaded) -> list:
    """Извлечение списка отзывов из загруженного TXT/CSV/JSON файла."""
    name = uploaded.name.lower()
    raw = uploaded.read()
    if name.endswith(".json"):
        data = json.loads(raw.decode("utf-8"))
        if isinstance(data, dict) and "reviews" in data:
            return [r["text"] if isinstance(r, dict) else str(r)
                    for r in data["reviews"]]
        if isinstance(data, list):
            return [r.get("text", "") if isinstance(r, dict) else str(r)
                    for r in data]
        raise ValueError("JSON должен быть списком отзывов или объектом с ключом 'reviews'.")
    if name.endswith(".csv"):
        df = pd.read_csv(io.BytesIO(raw))
        col = next((c for c in df.columns
                    if c.lower() in ("text", "отзыв", "review", "текст")),
                   df.columns[0])
        return df[col].dropna().astype(str).tolist()
    # TXT: один отзыв на строку (пустые строки игнорируются)
    return [line.strip() for line in raw.decode("utf-8").splitlines() if line.strip()]


# ─────────────────────────────────────────────
# Шапка и вкладки
# ─────────────────────────────────────────────

st.title("🛡️ Детектор аномальных отзывов маркетплейса")
st.markdown("Система классификации отзывов на **подлинные** и **имеющие признаки "
            "автоматической генерации** (TF-IDF char n-grams + Random Forest). "
            "Альфа-версия.")

tab_dash, tab_single, tab_file, tab_web = st.tabs(
    ["📊 Дашборд", "🔍 Проверка отзыва", "📁 Файлы", "🌐 Маркетплейс"])


# ───────────── 1. ДАШБОРД ─────────────
with tab_dash:
    if results is None:
        st.info("results.json не найден — запустите python bot_detector.py.")
    else:
        m, ds, cm = results["metrics"], results["dataset"], results["confusion_matrix"]

        c1, c2, c3, c4 = st.columns(4)
        c1.metric("Accuracy", f"{m['accuracy'] * 100:.2f}%")
        c2.metric("ROC-AUC", f"{m['roc_auc']:.4f}")
        c3.metric("Macro F1", f"{m.get('macro_f1', 0) * 100:.2f}%")
        c4.metric("OOB score", f"{m.get('oob_score', 0):.4f}")

        c1, c2, c3, c4 = st.columns(4)
        c1.metric("Объём датасета", ds["total"])
        c2.metric("Обучающая выборка", ds["train_size"])
        c3.metric("Тестовая выборка", ds["test_size"])
        cv = results["cross_validation"]
        c4.metric("CV F1 (5-fold)", f"{cv['mean']:.4f} ± {cv['std']:.4f}")

        col_l, col_r = st.columns(2)
        with col_l:
            z = [[cm["TN"], cm["FP"]], [cm["FN"], cm["TP"]]]
            fig_cm = go.Figure(go.Heatmap(
                z=z, x=["Прогноз: подлинный", "Прогноз: бот"],
                y=["Факт: подлинный", "Факт: бот"],
                text=z, texttemplate="%{text}", colorscale="Blues",
                showscale=False))
            fig_cm.update_layout(title="Матрица ошибок (тестовая выборка)",
                                 yaxis_autorange="reversed", height=400)
            st.plotly_chart(fig_cm, use_container_width=True)
        with col_r:
            tf = pd.DataFrame(results["top_features"])
            tf["feature"] = tf["feature"].map(lambda s: f"«{s}»")
            fig_imp = px.bar(tf.iloc[::-1], x="importance", y="feature",
                             orientation="h",
                             title="Топ-15 значимых TF-IDF n-грамм",
                             labels={"importance": "Важность", "feature": ""})
            fig_imp.update_layout(height=400)
            st.plotly_chart(fig_imp, use_container_width=True)

        fig_cv = px.bar(x=[f"Фолд {i + 1}" for i in range(len(cv["scores"]))],
                        y=cv["scores"], range_y=[0.9, 1.005],
                        title="F1 (macro) по фолдам кросс-валидации",
                        labels={"x": "", "y": "F1"})
        st.plotly_chart(fig_cv, use_container_width=True)

        with st.expander("Гиперпараметры модели"):
            st.json(results.get("hyperparameters", {}))


# ───────────── 2. ПРОВЕРКА ОТЗЫВА ─────────────
with tab_single:
    review = st.text_area("Введите текст отзыва для проверки:", height=150,
                          placeholder="Вставьте текст отзыва здесь...")
    if st.button("Классифицировать", type="primary"):
        if review.strip():
            prob = model.predict_proba([review])[0]
            label = "⚠️ АНОМАЛЬНЫЙ / БОТ" if prob[1] > 0.5 else "✅ Подлинный"

            c1, c2 = st.columns(2)
            c1.metric("Результат", label)
            c2.metric("Уверенность", f"{max(prob) * 100:.1f}%")
            st.progress(float(prob[1]), text=f"P(бот) = {prob[1]:.3f}")

            st.subheader("Диагностика признаков")
            feats = extract_features(review)
            f1, f2, f3 = st.columns(3)
            f1.metric("Восклицательных знаков", feats["exclamation_count"])
            f2.metric("Лексич. разнообразие (TTR)", f"{feats['lexical_diversity']:.2f}")
            f3.metric("Доля заглавных букв", f"{feats['caps_ratio']:.2f}")
            f1.metric("Повторов слов подряд", feats["repeat_count"])
            f2.metric("Разнообразие предложений", f"{feats['sent_diversity']:.2f}")
            f3.metric("Слов в отзыве", feats["word_count"])
        else:
            st.warning("Введите текст отзыва")


# ───────────── 3. ФАЙЛЫ ─────────────
with tab_file:
    st.markdown("Загрузите файл с отзывами: **TXT** (один отзыв на строку), "
                "**CSV** (колонка `text`/`отзыв`) или **JSON** "
                "(список строк, список объектов с полем `text` или объект "
                "с ключом `reviews`).")
    uploaded = st.file_uploader("Файл с отзывами",
                                type=["txt", "csv", "json"])
    if uploaded is not None:
        try:
            texts = [t for t in parse_uploaded_file(uploaded) if t.strip()]
        except Exception as e:
            st.error(f"Не удалось прочитать файл: {e}")
            texts = []
        if texts:
            st.success(f"Загружено отзывов: {len(texts)}")
            if st.button("Классифицировать все", type="primary",
                         key="classify_file"):
                with st.spinner("Классификация..."):
                    df_res = classify_texts(texts)
                summary_block(df_res)


# ───────────── 4. МАРКЕТПЛЕЙС ─────────────
with tab_web:
    st.markdown("Получение отзывов товара из внешнего источника и их пакетный анализ. "
                "При недоступности сети используйте **демо-режим** — он работает офлайн.")

    mode = st.radio("Источник данных",
                    ["Ссылка Wildberries", "Поиск по названию товара",
                     "Произвольная страница (URL)", "Демо-режим (офлайн)"],
                    horizontal=True)

    payload = None
    try:
        if mode == "Ссылка Wildberries":
            url = st.text_input(
                "Ссылка на товар",
                placeholder="https://www.wildberries.ru/catalog/188234511/detail.aspx")
            limit = st.slider("Максимум отзывов", 20, 300, 100, 20, key="lim_wb")
            if st.button("Получить и проанализировать", type="primary",
                         key="go_wb") and url.strip():
                nm = ml.parse_wb_url(url)
                with st.spinner(f"Получаю отзывы для артикула {nm}..."):
                    payload = ml.fetch_wb_reviews(nm, limit=limit)

        elif mode == "Поиск по названию товара":
            query = st.text_input("Название товара",
                                  placeholder="Средство от комаров детское")
            limit = st.slider("Максимум отзывов", 20, 300, 100, 20, key="lim_q")
            if st.button("Найти товар и проанализировать отзывы",
                         type="primary", key="go_q") and query.strip():
                with st.spinner("Ищу товары..."):
                    products = ml.search_wb_products(query)
                st.write("Найденные товары (выбран товар с наибольшим числом отзывов):")
                st.dataframe(pd.DataFrame(products), use_container_width=True)
                best = max(products, key=lambda p: p.get("feedbacks") or 0)
                with st.spinner(f"Получаю отзывы: {best['name']}..."):
                    payload = ml.fetch_wb_reviews(best["nm_id"], limit=limit)

        elif mode == "Произвольная страница (URL)":
            url = st.text_input("Адрес страницы с отзывами",
                                placeholder="https://example.com/product/reviews")
            st.caption("Generic-парсер (BeautifulSoup). Страницы, формируемые "
                       "JavaScript, не поддерживаются — используйте файл или демо-режим.")
            if st.button("Спарсить и проанализировать", type="primary",
                         key="go_gen") and url.strip():
                with st.spinner("Загружаю страницу..."):
                    try:
                        payload = ml.fetch_generic_page(url)
                    except ml.LoaderError as _parse_err:
                        st.warning(f"Парсинг недоступен: {_parse_err}")
                        demos = ml.list_demo_products()
                        if demos:
                            import random as _rnd
                            _chosen = _rnd.choice(demos)
                            payload = dict(ml.load_cached(_chosen["file"]))
                            payload["_test_mode"] = True
                            payload["_original_url"] = url
                            st.info(
                                "🧪 **Тестовый режим** — реальный парсинг страницы "
                                "недоступен (сайт требует авторизацию или формирует "
                                "контент через JavaScript). "
                                f"Вместо него показаны демонстрационные данные «{_chosen['product']}»."
                            )

        else:  # демо-режим
            demos = ml.list_demo_products()
            if not demos:
                st.info("Каталог demo_data/ пуст.")
            else:
                labels = [f"{d['product']} — {d['count']} отзывов "
                          f"(снимок {d['date']})" for d in demos]
                idx = st.selectbox("Демо-товар", range(len(demos)),
                                   format_func=lambda i: labels[i])
                if st.button("Проанализировать демо-набор", type="primary",
                             key="go_demo"):
                    payload = ml.load_cached(demos[idx]["file"])

    except ml.LoaderError as e:
        st.error(f"{e}")
        st.info("Внешний источник недоступен — переключитесь на демо-режим "
                "или загрузите отзывы из файла на вкладке «Файлы».")
    except Exception as e:
        st.error(f"Ошибка сети или источника: {e}")
        st.info("Попробуйте демо-режим — он работает без подключения к интернету.")

    if payload:
        if payload.get("_test_mode"):
            st.markdown(
                "> 🧪 **Тестовый режим** — парсинг указанного URL недоступен. "
                "Результаты ниже основаны на демонстрационных данных и служат "
                "для иллюстрации работы системы, а не отражают содержимое "
                f"страницы `{payload.get('_original_url', '')}`."
            )

        texts = [r["text"] for r in payload.get("reviews", []) if r.get("text")]
        if not texts:
            st.warning("Источник не вернул текстовых отзывов.")
        else:
            st.subheader(payload.get("product", "Товар"))
            source_label = payload.get("_original_url") or payload.get("source", "—")
            st.caption(f"Источник: {source_label}"
                       + (f" · снимок от {payload['snapshot_date']}"
                          if payload.get("snapshot_date") else ""))
            df_res = classify_texts(texts)
            summary_block(df_res, product=payload.get("product", ""))

st.divider()
st.caption("ВКР «Анализ пользовательских отзывов и комментариев методами "
           "машинного обучения для выявления аномалий и ботов» · "
           "ТГУ им. Г.Р. Державина · Еременко Г.С. · альфа-версия")
