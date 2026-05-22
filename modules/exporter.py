"""
exporter.py — Excel export with exact spec compliance.

Key rules from spec:
- Sheet name = <ClinicName_District_ready>
- No autofilter
- Vertical alignment: center
- White background on all cells
- Dynamic column widths based on content
- Arial 10, thin black borders, wrap text
- No merged cells, no colored headers

Price rule:
- If price == "Цена по запросу" (or variants) → store as "9999999" in all exports
- If any service has 9999999 price → clinic name gets * suffix (e.g. "Green Lukas*")
- * suffix means unsigned clinic with no real pricing
- Rows with ID == "-" are excluded from ready file
"""
import io
import re
import pandas as pd
import openpyxl
from openpyxl.styles import Font, Alignment, Border, Side, PatternFill
from openpyxl.utils import get_column_letter

from modules.utils import clean_cell, safe_str, uz_latin_to_cyrillic
from modules.extractor import _normalize_district
from modules.templates import get_descriptions, get_duration
from modules.validation import REQUIRED_COLUMNS

CATEGORY_MAP = {
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

# Style constants
THIN_BORDER = Border(
    left=Side(style="thin"),
    right=Side(style="thin"),
    top=Side(style="thin"),
    bottom=Side(style="thin"),
)
WHITE_FILL = PatternFill("solid", fgColor="FFFFFF")

CENTER_COLS = {
    "Услуга ID", "Цена", "Продолжительность (минут)",
    "Активен", "Тип услуг",
    "Код уз", "Код ру", "Код лаборатория",
}

COL_MIN_WIDTH = 8
COL_MAX_WIDTH = 60
WIDE_COLS = {
    "Имя RU", "Имя UZ", "Имя KR",
    "Описание RU", "Описание UZ", "Описание KR",
    "Требования RU", "Требования UZ", "Требования KR",
}
WIDE_COLS_MIN = 35
WIDE_COLS_MAX = 55

# Price sentinel
PRICE_ON_REQUEST_SENTINEL = "9999999"
PRICE_ON_REQUEST_LABELS   = {"цена по запросу", "по запросу", "price on request"}


def _normalize_price(price) -> str:
    """
    Convert "Цена по запросу" (and variants) → "9999999".
    Already "9999999" → stays "9999999".
    Everything else → as-is string.
    """
    val = str(price).strip()
    if val.lower() in PRICE_ON_REQUEST_LABELS or val == PRICE_ON_REQUEST_SENTINEL:
        return PRICE_ON_REQUEST_SENTINEL
    return val


def _has_on_request_price(rows: list[dict]) -> bool:
    """Return True if any row has a 9999999 price (after normalization)."""
    for row in rows:
        if _normalize_price(row.get("Цена", "")) == PRICE_ON_REQUEST_SENTINEL:
            return True
    return False


def _clinic_export_name(clinic_name: str, has_on_request: bool) -> str:
    """
    Build the clinic name for export.
    If has_on_request → append * with no space: "Green Lukas*"
    Strip any existing * first to avoid doubling.
    """
    name = clean_cell(clinic_name.strip().rstrip("*").strip())
    if has_on_request:
        return name + "*"
    return name


def _make_sheet_name(clinic_name: str, district: str) -> str:
    """Generate Excel sheet name from clinic + district. Max 31 chars."""
    clean_cn = clinic_name.rstrip("*").strip()
    base = f"{clean_cell(clean_cn)}_{clean_cell(district)}"
    safe = re.sub(r"[\\/*?\[\]:]", "_", base)
    return safe[:31] if safe else "Ready"


def _calc_col_width(ws, col_idx: int, col_name: str, max_rows: int = 100) -> float:
    """Calculate column width based on content in first max_rows rows."""
    max_len = len(col_name)
    for row in range(2, min(ws.max_row + 1, max_rows + 2)):
        val = ws.cell(row=row, column=col_idx).value
        if val is not None:
            text = str(val)
            effective = min(len(text), max(
                max(len(word) for word in text.split()) + 2,
                len(text) // 3
            ))
            max_len = max(max_len, effective)

    if col_name in WIDE_COLS:
        return max(WIDE_COLS_MIN, min(WIDE_COLS_MAX, max_len + 4))
    return max(COL_MIN_WIDTH, min(COL_MAX_WIDTH, max_len + 4))


def _apply_cell_style(cell, is_header: bool = False, col_name: str = ""):
    """Apply standard cell formatting."""
    cell.font = Font(name="Arial", size=10, bold=is_header)
    cell.fill = WHITE_FILL
    cell.border = THIN_BORDER

    if is_header:
        cell.alignment = Alignment(
            horizontal="center", vertical="center", wrap_text=True
        )
    else:
        h_align = "center" if col_name in CENTER_COLS else "left"
        cell.alignment = Alignment(
            horizontal=h_align, vertical="center", wrap_text=True
        )


def build_ready_df(
    matched_rows: list[dict],
    clinic_name: str,
    district: str,
    catalog_df: pd.DataFrame,
    gemini_api_key: str = "",
    progress_callback=None,
) -> pd.DataFrame:
    """Build final ready DataFrame with all 22 columns."""

    # Normalize all prices first
    for row in matched_rows:
        row["Цена"] = _normalize_price(row.get("Цена", ""))

    has_on_request = _has_on_request_price(matched_rows)
    export_name    = _clinic_export_name(clinic_name, has_on_request)
    district       = _normalize_district(district.strip())

    # ── Gemini translation (if API key provided) ──────────────────────────────
    gemini_cache = {}
    use_gemini   = bool(gemini_api_key and gemini_api_key.strip())

    if use_gemini:
        try:
            from modules.gemini_translator import translate_services_batch
            # Collect unique service names that have matched IDs
            unique_svcs = []
            seen = set()
            for row in matched_rows:
                sid  = clean_cell(str(row.get("ID", "-")))
                name = clean_cell(str(row.get("Название в клинике", "")))
                stype = clean_cell(str(row.get("Тип услуг", "Диагностика")))
                if sid not in ("-", "") and name and name not in seen:
                    unique_svcs.append({"name_ru": name, "type": stype})
                    seen.add(name)
            if unique_svcs:
                gemini_cache = translate_services_batch(
                    unique_svcs, gemini_api_key, progress_callback
                )
                print(f"[gemini] Translated {len(gemini_cache)} services")
        except Exception as e:
            print(f"[gemini] Translation failed: {e} — falling back to templates")
            gemini_cache = {}
            use_gemini   = False

    records = []

    for row in matched_rows:
        service_id   = clean_cell(str(row.get("ID", "-")))
        if service_id in ("-", ""):
            continue

        service_type = clean_cell(str(row.get("Тип услуг", "Диагностика")))
        clinic_svc   = clean_cell(str(row.get("Название в клинике", "")))
        price        = row.get("Цена", PRICE_ON_REQUEST_SENTINEL)

        if service_type not in ("Диагностика", "Анализы"):
            service_type = "Диагностика"

        name_ru, name_uz, name_kr = clinic_svc, "-", "-"

        if service_id not in ("-", ""):
            cat_row = catalog_df[catalog_df["ID number"] == service_id]
            if not cat_row.empty:
                r = cat_row.iloc[0]
                cat_uz = safe_str(r.get("Name UZ", ""))
                cat_kr = safe_str(r.get("Name KR", ""))
                if cat_uz and len(cat_uz) > 2 and (cat_uz[0].isupper() or cat_uz[0].isdigit()):
                    name_uz = cat_uz
                else:
                    name_uz = "-"
                if cat_kr and len(cat_kr) > 2 and (cat_kr[0].isupper() or cat_kr[0].isdigit()):
                    name_kr = cat_kr
                else:
                    name_kr = "-"

        # Override with Gemini translation if available
        gemini_data = gemini_cache.get(clinic_svc) if use_gemini else None
        if gemini_data:
            if gemini_data.get("name_uz") and gemini_data["name_uz"] != "-":
                name_uz = gemini_data["name_uz"]

        name_ru = clean_cell(name_ru)
        name_uz = clean_cell(name_uz)

        if not name_kr or name_kr == "-":
            name_kr = uz_latin_to_cyrillic(name_uz) if name_uz and name_uz != "-" else "-"
        name_kr = clean_cell(name_kr)

        # ── Descriptions and requirements ─────────────────────────────────────
        if gemini_data:
            # Use Gemini-generated content
            desc_ru = clean_cell(gemini_data.get("desc_ru", ""))
            desc_uz = clean_cell(gemini_data.get("desc_uz", ""))
            req_ru  = clean_cell(gemini_data.get("req_ru",  ""))
            req_uz  = clean_cell(gemini_data.get("req_uz",  ""))
            # Generate KR from UZ via transliteration
            desc_kr = clean_cell(uz_latin_to_cyrillic(desc_uz)) if desc_uz else ""
            req_kr  = clean_cell(uz_latin_to_cyrillic(req_uz))  if req_uz  else ""
            texts = {
                "Описание RU":   desc_ru,
                "Описание UZ":   desc_uz,
                "Описание KR":   desc_kr,
                "Требования RU": req_ru,
                "Требования UZ": req_uz,
                "Требования KR": req_kr,
            }
        else:
            # Fallback to template-based generation
            texts = get_descriptions(service_type, name_ru, name_uz, name_kr)

        duration = get_duration(service_type, name_ru)
        cat      = CATEGORY_MAP.get(service_type, CATEGORY_MAP["Диагностика"])

        records.append({
            "Услуга ID":                  service_id,
            "Клиника":                    export_name,
            "Филиал":                     district,
            "Имя RU":                     name_ru,
            "Имя UZ":                     name_uz,
            "Имя KR":                     name_kr,
            "Описание UZ":                clean_cell(texts.get("Описание UZ", "")),
            "Требования UZ":              clean_cell(texts.get("Требования UZ", "")),
            "Требования RU":              clean_cell(texts.get("Требования RU", "")),
            "Требования KR":              clean_cell(texts.get("Требования KR", "")),
            "Тип услуг":                  service_type,
            "Цена":                       price,
            "Описание RU":                clean_cell(texts.get("Описание RU", "")),
            "Описание KR":                clean_cell(texts.get("Описание KR", "")),
            "Продолжительность (минут)":  str(duration),
            "Активен":                    "TRUE",
            "Категория RU":               cat["Категория RU"],
            "Категория UZ":               cat["Категория UZ"],
            "Категория KR":               cat["Категория KR"],
            "Код уз":                     "",
            "Код ру":                     "",
            "Код лаборатория":            "",
        })

    return pd.DataFrame(records, columns=REQUIRED_COLUMNS)


def export_price_list_excel(
    services: list[dict], clinic_name: str, district: str
) -> bytes:
    """Export extracted price list. Normalizes 'Цена по запросу' → 9999999."""
    rows = [
        {
            "#": i,
            "Название услуги": s.get("service_name", ""),
            "Тип": s.get("type", ""),
            "Цена": _normalize_price(s.get("price", "")),
        }
        for i, s in enumerate(services, 1)
    ]
    df  = pd.DataFrame(rows)
    buf = io.BytesIO()
    wb  = openpyxl.Workbook()
    ws  = wb.active
    ws.title = "Прайс-лист"

    for ci, col in enumerate(df.columns, 1):
        _apply_cell_style(ws.cell(row=1, column=ci, value=col), is_header=True)

    for ri, row in enumerate(df.itertuples(index=False), 2):
        for ci, val in enumerate(row, 1):
            cell = ws.cell(row=ri, column=ci,
                           value=None if str(val) in ("", "nan") else val)
            _apply_cell_style(cell, col_name=df.columns[ci - 1])

    for ci, col in enumerate(df.columns, 1):
        ws.column_dimensions[get_column_letter(ci)].width = _calc_col_width(ws, ci, col)

    ws.freeze_panes = "A2"
    wb.save(buf)
    return buf.getvalue()


def export_matching_excel(matched_rows: list[dict]) -> bytes:
    """Export matching results. Normalizes 'Цена по запросу' → 9999999."""
    cols = ["Название в MedPay", "Название в клинике", "ID",
            "Уверенность", "Комментарий", "Цена", "Тип услуг"]
    buf = io.BytesIO()
    wb  = openpyxl.Workbook()
    ws  = wb.active
    ws.title = "Матчинг"

    red_fill    = PatternFill("solid", fgColor="FFE0E0")
    yellow_fill = PatternFill("solid", fgColor="FFFDE0")

    for ci, col in enumerate(cols, 1):
        _apply_cell_style(ws.cell(row=1, column=ci, value=col), is_header=True)

    for ri, rec in enumerate(matched_rows, 2):
        id_val       = str(rec.get("ID", "")).strip()
        conf         = rec.get("Уверенность", 0)
        is_unmatched = id_val == "-"
        is_low_conf  = not is_unmatched and isinstance(conf, (int, float)) and conf < 90

        for ci, col in enumerate(cols, 1):
            val = rec.get(col, "")
            if col == "Цена":
                val = _normalize_price(val)
            cell = ws.cell(row=ri, column=ci,
                           value=None if str(val) in ("", "nan") else val)
            _apply_cell_style(cell, col_name=col)
            if is_unmatched:
                cell.fill = red_fill
            elif is_low_conf:
                cell.fill = yellow_fill

    for ci, col in enumerate(cols, 1):
        ws.column_dimensions[get_column_letter(ci)].width = _calc_col_width(ws, ci, col)

    ws.freeze_panes = "A2"
    wb.save(buf)
    return buf.getvalue()


def export_ready_excel(
    ready_df: pd.DataFrame,
    clinic_name: str = "",
    district: str = "",
) -> bytes:
    """Export final ready Excel."""
    buf = io.BytesIO()
    wb  = openpyxl.Workbook()
    ws  = wb.active

    # Sheet name strips * (not allowed in Excel sheet names)
    clean_cn   = clinic_name.strip().rstrip("*").strip()
    sheet_name = _make_sheet_name(clean_cn, district) + "_ready"
    ws.title   = sheet_name[:31]

    for ci, col in enumerate(REQUIRED_COLUMNS, 1):
        _apply_cell_style(ws.cell(row=1, column=ci, value=col), is_header=True, col_name=col)

    for ri in range(len(ready_df)):
        rec = ready_df.iloc[ri]
        for ci, col in enumerate(REQUIRED_COLUMNS, 1):
            raw = rec[col]

            if raw is None or str(raw).strip().lower() in ("nan", "none", ""):
                val = None
            elif col in ("Код уз", "Код ру", "Код лаборатория"):
                val = None
            elif col == "Цена":
                val = _normalize_price(str(raw))
            else:
                val = clean_cell(str(raw)) or None

            cell = ws.cell(row=ri + 2, column=ci, value=val)
            _apply_cell_style(cell, col_name=col)

    for ci, col in enumerate(REQUIRED_COLUMNS, 1):
        ws.column_dimensions[get_column_letter(ci)].width = _calc_col_width(ws, ci, col)

    ws.row_dimensions[1].height = 25
    for ri in range(2, ws.max_row + 1):
        max_chars = max(
            (len(str(ws.cell(row=ri, column=ci).value or ""))
             for ci in range(1, 23)),
            default=0,
        )
        estimated_lines = max(1, max_chars // 40)
        ws.row_dimensions[ri].height = max(20, min(120, estimated_lines * 15))

    ws.freeze_panes = "A2"
    wb.save(buf)
    return buf.getvalue()
