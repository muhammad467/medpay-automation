import re
import pandas as pd

ALLOWED_TYPES = {"Диагностика", "Анализы"}
REQUIRED_COLUMNS = [
    "Услуга ID", "Клиника", "Филиал", "Имя RU", "Имя UZ", "Имя KR",
    "Описание UZ", "Требования UZ", "Требования RU", "Требования KR",
    "Тип услуг", "Цена", "Описание RU", "Описание KR",
    "Продолжительность (минут)", "Активен", "Категория RU", "Категория UZ",
    "Категория KR", "Код уз", "Код ру", "Код лаборатория",
]
FORBIDDEN_VALUES = {
    "Услуги врачей",
    "Лечебные процедуры",
    "Лабораторная диагностика",   # old wrong category
    "Laborator diagnostika",       # old wrong UZ category for Анализы
    "Лаборатор диагностика",       # old wrong KR category
    "Инструментальная диагностика",
}

# Allowed category values per type
VALID_CATEGORIES = {
    "Анализы": {
        "Категория RU": "Анализы",
        "Категория UZ": "Tahlillar",
        "Категория KR": "Таҳлиллар",
    },
    "Диагностика": {
        "Категория RU": "Диагностика",
        "Категория UZ": "Diagnostika",
        "Категория KR": "Диагностика",
    },
}


def validate_matching_row(row: dict, catalog_df: pd.DataFrame) -> list[str]:
    """Validate a single matching row. Returns list of error strings."""
    errors = []

    service_id = str(row.get("ID", "")).strip()
    if service_id not in ("-", "") and service_id not in catalog_df["ID number"].values:
        errors.append(f"ID '{service_id}' не существует в каталоге MedPay.")

    price = str(row.get("Цена", "")).strip()
    if price != "По запросу":
        if not re.fullmatch(r"\d+", price):
            errors.append(f"Цена '{price}' должна содержать только цифры или быть 'По запросу'.")

    service_type = str(row.get("Тип услуг", "")).strip()
    if service_type not in ALLOWED_TYPES:
        errors.append(f"Тип услуг '{service_type}' недопустим. Только: {', '.join(ALLOWED_TYPES)}.")

    return errors


def validate_final_df(df: pd.DataFrame, catalog_df: pd.DataFrame) -> list[str]:
    """Validate the final ready dataframe before export. Returns list of errors."""
    errors = []

    # Column count and order
    if list(df.columns) != REQUIRED_COLUMNS:
        errors.append(
            f"Неверный порядок или количество колонок. "
            f"Ожидается {len(REQUIRED_COLUMNS)}, получено {len(df.columns)}."
        )

    for _, row in df.iterrows():
        # Тип услуг
        stype = str(row.get("Тип услуг", "")).strip()
        if stype not in ALLOWED_TYPES:
            errors.append(f"Недопустимый тип услуг: '{stype}'")

        # Forbidden values
        for col in df.columns:
            val = str(row.get(col, "")).strip()
            for forbidden in FORBIDDEN_VALUES:
                if forbidden in val:
                    errors.append(f"Обнаружено запрещённое значение '{forbidden}' в колонке '{col}'")

        # Price
        price = str(row.get("Цена", "")).strip()
        if price not in ("По запросу", "") and not re.fullmatch(r"\d+", price):
            errors.append(f"Недопустимая цена: '{price}'")

        # ID check
        sid = str(row.get("Услуга ID", "")).strip()
        if sid not in ("-", "") and sid not in catalog_df["ID number"].values:
            errors.append(f"ID '{sid}' не существует в каталоге.")

        # Категория must match Тип услуг
        if stype in VALID_CATEGORIES:
            expected_cats = VALID_CATEGORIES[stype]
            for cat_col, expected_val in expected_cats.items():
                actual = str(row.get(cat_col, "")).strip()
                if actual and actual != expected_val:
                    errors.append(
                        f"Неверная {cat_col}: '{actual}', ожидается '{expected_val}'"
                    )

        # Активен
        active = str(row.get("Активен", "")).strip().upper()
        if active not in ("TRUE", ""):
            errors.append(f"Активен должен быть TRUE, получено: '{active}'")

        # Empty code columns
        for code_col in ("Код уз", "Код ру", "Код лаборатория"):
            val = str(row.get(code_col, "")).strip()
            if val not in ("", "nan", "None"):
                errors.append(f"Колонка '{code_col}' должна быть пустой, получено: '{val}'")

    return list(set(errors))  # deduplicate
