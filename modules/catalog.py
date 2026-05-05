import pandas as pd
from modules.utils import clean_cell, safe_str

REQUIRED_COLUMNS = {"ID number", "Name RU", "Name UZ", "type", "Name KR"}


def load_catalog(file) -> tuple[pd.DataFrame, str]:
    """
    Load MedPay catalog from uploaded file.
    Returns (df, error_message). If error_message is non-empty, loading failed.
    """
    try:
        df = pd.read_excel(file, dtype=str)
    except Exception as e:
        return pd.DataFrame(), f"Ошибка чтения файла каталога: {e}"

    missing = REQUIRED_COLUMNS - set(df.columns)
    if missing:
        return pd.DataFrame(), f"Отсутствуют обязательные колонки: {', '.join(sorted(missing))}"

    # Clean all cells
    for col in df.columns:
        df[col] = df[col].apply(clean_cell)

    # Drop rows where ID is empty
    df = df[df["ID number"].str.strip() != ""].copy()
    df["ID number"] = df["ID number"].apply(safe_str)

    # Normalize type: 'Анализ' → 'Анализы', keep 'Диагностика'
    df["type"] = df["type"].apply(_normalize_type)

    df = df.reset_index(drop=True)
    return df, ""


def _normalize_type(t: str) -> str:
    t = t.strip()
    if t in ("Анализ", "Анализы", "анализ", "анализы"):
        return "Анализы"
    if t in ("Диагностика", "диагностика"):
        return "Диагностика"
    return t


def get_catalog_summary(df: pd.DataFrame) -> str:
    total      = len(df)
    unique_ids = df["ID number"].nunique()
    cols       = ", ".join(df.columns.tolist())
    return (
        f"Каталог MedPay загружен. Всего услуг: {total}. "
        f"Уникальных ID: {unique_ids}. "
        f"Колонки: {cols}. Готов к матчингу."
    )


def validate_id_exists(catalog_df: pd.DataFrame, service_id: str) -> bool:
    """Check if an ID exists in the catalog."""
    if service_id == "-" or service_id == "":
        return True
    return service_id in catalog_df["ID number"].values


def get_service_by_id(catalog_df: pd.DataFrame, service_id: str) -> dict:
    """Get catalog row by ID."""
    row = catalog_df[catalog_df["ID number"] == service_id]
    if row.empty:
        return {}
    r = row.iloc[0]
    return {
        "Name RU": r.get("Name RU", ""),
        "Name UZ": r.get("Name UZ", ""),
        "Name KR": r.get("Name KR", ""),
        "type": r.get("type", ""),
    }
