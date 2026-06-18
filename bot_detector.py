"""
bot_detector.py — обучение модели детекции аномальных (ботовых) отзывов.

Гиперпараметры синхронизированы с текстом ВКР (этап 0 плана доработок):
TF-IDF: analyzer='char_wb', ngram_range=(2,4), max_features=5000, sublinear_tf=True
RF:     n_estimators=200, max_depth=None, max_features='sqrt',
        class_weight='balanced', oob_score=True, random_state=42
Разбиение: test_size=0.20, stratify, random_state=42.

Артефакты: model_pipeline.pkl (joblib), results.json.

ВКР: Еременко Г.С., ТГУ им. Г.Р. Державина, 2026
"""

import json
import os

import joblib
import numpy as np
from sklearn.ensemble import RandomForestClassifier
from sklearn.feature_extraction.text import TfidfVectorizer
from sklearn.metrics import (accuracy_score, classification_report,
                             confusion_matrix, roc_auc_score)
from sklearn.model_selection import cross_val_score, train_test_split
from sklearn.pipeline import Pipeline

from utils import RANDOM_SEED, generate_dataset

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
MODEL_PATH = os.path.join(BASE_DIR, "model_pipeline.pkl")
RESULTS_PATH = os.path.join(BASE_DIR, "results.json")


def build_pipeline() -> Pipeline:
    return Pipeline([
        ("tfidf", TfidfVectorizer(
            analyzer="char_wb",
            ngram_range=(2, 4),
            max_features=5000,
            sublinear_tf=True,
        )),
        ("clf", RandomForestClassifier(
            n_estimators=200,
            max_depth=None,
            max_features="sqrt",
            class_weight="balanced",
            oob_score=True,
            random_state=RANDOM_SEED,
            n_jobs=1,   # multiprocessing ломает PyInstaller-сборку
        )),
    ])


def main() -> None:
    # 1. Датасет: 800 сбалансированных синтетических отзывов (400 + 400)
    df = generate_dataset(n_per_class=400, seed=RANDOM_SEED)
    print("=" * 60)
    print("ДАТАСЕТ")
    print("=" * 60)
    print(f"Всего отзывов: {len(df)} | подлинных: {(df.label == 0).sum()} | "
          f"ботовых: {(df.label == 1).sum()}")

    X_text, y = df["text"], df["label"]
    X_train, X_test, y_train, y_test = train_test_split(
        X_text, y, test_size=0.20, random_state=RANDOM_SEED, stratify=y)

    # 2. Обучение
    pipeline = build_pipeline()
    pipeline.fit(X_train, y_train)
    y_pred = pipeline.predict(X_test)
    y_prob = pipeline.predict_proba(X_test)[:, 1]

    # 3. Метрики
    acc = accuracy_score(y_test, y_pred)
    auc = roc_auc_score(y_test, y_prob)
    cm = confusion_matrix(y_test, y_pred)
    report = classification_report(
        y_test, y_pred, target_names=["подлинный", "бот"], output_dict=True)
    oob = pipeline.named_steps["clf"].oob_score_

    print("\n" + "=" * 60)
    print("РЕЗУЛЬТАТЫ КЛАССИФИКАЦИИ")
    print("=" * 60)
    print(f"Accuracy: {acc:.4f} | ROC-AUC: {auc:.4f} | OOB: {oob:.4f}")
    print("Confusion matrix [[TN FP],[FN TP]]:")
    print(cm)
    print(classification_report(y_test, y_pred, target_names=["подлинный", "бот"]))

    cv_scores = cross_val_score(build_pipeline(), X_text, y, cv=5,
                                scoring="f1_macro", n_jobs=1)
    print(f"5-fold CV F1(macro): {cv_scores.round(4)} | "
          f"среднее {cv_scores.mean():.4f} ± {cv_scores.std():.4f}")

    # 4. Важность признаков
    feature_names = pipeline.named_steps["tfidf"].get_feature_names_out()
    importances = pipeline.named_steps["clf"].feature_importances_
    top_idx = np.argsort(importances)[::-1][:15]

    # 5. Сохранение артефактов
    joblib.dump(pipeline, MODEL_PATH)

    results = {
        "dataset": {
            "total": len(df),
            "real": int((df.label == 0).sum()),
            "bot": int((df.label == 1).sum()),
            "train_size": len(X_train),
            "test_size": len(X_test),
        },
        "hyperparameters": {
            "tfidf": {"analyzer": "char_wb", "ngram_range": [2, 4],
                      "max_features": 5000, "sublinear_tf": True},
            "random_forest": {"n_estimators": 200, "max_depth": None,
                              "max_features": "sqrt",
                              "class_weight": "balanced", "oob_score": True},
            "split": {"test_size": 0.20, "random_state": RANDOM_SEED},
        },
        "metrics": {
            "accuracy": round(acc, 4),
            "roc_auc": round(auc, 4),
            "oob_score": round(oob, 4),
            "macro_f1": round(report["macro avg"]["f1-score"], 4),
            "precision_real": round(report["подлинный"]["precision"], 4),
            "recall_real": round(report["подлинный"]["recall"], 4),
            "f1_real": round(report["подлинный"]["f1-score"], 4),
            "precision_bot": round(report["бот"]["precision"], 4),
            "recall_bot": round(report["бот"]["recall"], 4),
            "f1_bot": round(report["бот"]["f1-score"], 4),
        },
        "confusion_matrix": {
            "TN": int(cm[0][0]), "FP": int(cm[0][1]),
            "FN": int(cm[1][0]), "TP": int(cm[1][1]),
        },
        "cross_validation": {
            "scoring": "f1_macro",
            "scores": [round(s, 4) for s in cv_scores.tolist()],
            "mean": round(cv_scores.mean(), 4),
            "std": round(cv_scores.std(), 4),
        },
        "top_features": [
            {"feature": feature_names[i], "importance": round(float(importances[i]), 4)}
            for i in top_idx
        ],
    }
    with open(RESULTS_PATH, "w", encoding="utf-8") as f:
        json.dump(results, f, ensure_ascii=False, indent=2)

    print(f"\n✓ Модель сохранена: {MODEL_PATH}")
    print(f"✓ Результаты сохранены: {RESULTS_PATH}")


if __name__ == "__main__":
    main()
