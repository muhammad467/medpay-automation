"""
MedPay Automation v3.1
─────────────────────
One clinic at a time — clean, reliable, no pressure.

Catalog : loaded once, stays loaded for the whole session.

Mode    : Manual  — step-by-step, user reviews and clicks Next at each stage.
          Auto    — one click processes everything to the final file.

Entry   : A  HTML file        →  extract  →  (review)  →  match  →  (review)  →  ready
          B  price_list.xlsx  →            →  (review)  →  match  →  (review)  →  ready
          C  matching.xlsx    →                          →          →  (review)  →  ready
          D  HTML file        →  one-click Auto  →  ready

Pages   : catalog  →  setup  →  work  →  (done)
          At any point the user can start a new clinic or swap the catalog.
"""
import io
import os
import re
from pathlib import Path
import pandas as pd
import streamlit as st
from rapidfuzz import process as rfp, fuzz as rff

from modules.catalog import load_catalog, get_catalog_summary, get_service_by_id
from modules.extractor import extract_services_from_html
from modules.matcher import build_search_corpus, match_service, ALLOWED_CATALOG_TYPES, model_status, confidence_label, _get_embedding_matcher
from modules.exporter import (
    build_ready_df, export_price_list_excel,
    export_matching_excel, export_ready_excel,
)
from modules.validation import (
    validate_matching_row, validate_final_df,
    REQUIRED_COLUMNS, ALLOWED_TYPES,
)
from modules.utils import clean_cell, clean_price

# ── Constants ─────────────────────────────────────────────────────────────────
EXCEL_MIME = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
if "OPENROUTER_API_KEY" in st.secrets:
    os.environ["OPENROUTER_API_KEY"] = st.secrets["OPENROUTER_API_KEY"]

ENTRY_INFO = {
    "A": ("A — HTML  →  Прайс  →  Матчинг  →  Ready",
          "HTML-файл со страницы клиники. Программа извлечёт услуги, "
          "проведёт матчинг и сгенерирует итоговый файл."),
    "B": ("B — Готовый прайс-лист  →  Матчинг  →  Ready",
          "Уже извлечённый прайс-лист в формате .xlsx. "
          "Программа проведёт матчинг и сгенерирует итоговый файл."),
    "C": ("C — Готовый матчинг  →  Ready",
          "Уже проверенный файл матчинга в формате .xlsx. "
          "Программа сразу сгенерирует итоговый файл."),
    "D": ("D — HTML  →  Авто (один клик)",
          "HTML-файл клиники. Программа выполнит все шаги автоматически "
          "без остановок на проверку."),
}

# ── Page config ───────────────────────────────────────────────────────────────
st.set_page_config(
    page_title="MedPay Automation",
    page_icon="🏥",
    layout="wide",
    initial_sidebar_state="expanded",
)

# ── Session state defaults ────────────────────────────────────────────────────
_DEFAULTS = {
    "page":         "catalog",
    "catalog_df":   None,
    "mode":         "manual",
    "entry":        "A",
    "clinic_name":  "",
    "district":     "",
    "services":     [],
    "matched":      [],
    "match_summary": (0, 0, 0),
    "ready_df":     None,
    "work_step":    "",
    "work_error":   "",
}
for _k, _v in _DEFAULTS.items():
    if _k not in st.session_state:
        st.session_state[_k] = _v


# ═══════════════════════════════════════════════════════════════════════════════
# PURE-PYTHON HELPERS  (no st.* calls)
# ═══════════════════════════════════════════════════════════════════════════════
def _go(page: str):
    st.session_state["page"] = page
    st.rerun()


def _safe(text: str) -> str:
    return re.sub(r"[^\w\-]", "_", clean_cell(text)) or "clinic"


def _fname() -> str:
    cn = _safe(st.session_state.get("clinic_name", "clinic"))
    di = _safe(st.session_state.get("district", ""))
    return f"{cn}_{di}" if di else cn


def normalize_service_type(raw: str) -> str:
    """
    Convert any variant of service type to standard Russian values.
    Returns: "Анализы", "Диагностика", or "Лечебная процедура"
    """
    if not raw:
        return "Диагностика"
    t = raw.lower().strip()

    # Allergen codes pattern: (F25), (e1), (g4) etc → always Анализы
    if re.match(r'^\(\*?[a-zA-Z\d]', t):
        return "Анализы"

    # Strip leading numbers/dots
    t = re.sub(r'^[\d\s\.\)\-]+', '', t).strip()

    ANALYSIS_VARIANTS = {
        "анализы", "анализ", "analysis", "analyses", "analyze",
        "analyzes", "tahlil", "tahlillar", "таҳлил", "таҳлиллар",
        "лаборатор", "lab", "лаб", "analiz", "anali", "tekshir",
    }
    DIAGNOSTICS_VARIANTS = {
        "диагностика", "диагностик", "diagnostics", "diagnostic",
        "diagnostika", "diagnoz", "diagnosis", "диагноз",
        "imaging", "визуализация", "инструментальн",
    }
    LECHEBNIYE_VARIANTS = {
        "лечебная", "лечебн", "врачебн", "консультац", "процедур",
        "услуги врача", "lechebniy", "врач", "прием врача",
        "приём врача", "консультация", "лечение","лечебная процедура",
    }
    for v in ANALYSIS_VARIANTS:
        if v in t:
            return "Анализы"
    for v in DIAGNOSTICS_VARIANTS:
        if v in t:
            return "Диагностика"
    for v in LECHEBNIYE_VARIANTS:
        if v in t:
            return "Лечебная процедура"
    return "Диагностика"


def _run_matching(services: list, catalog_df, include_lech: bool = False) -> list:
    """Pure Python fuzzy match — zero st.* calls."""
    from rapidfuzz import fuzz as _fuzz
    from modules.exporter import _normalize_price
    corpus  = build_search_corpus(catalog_df)
    results = []
    for svc in services:
        nm       = clean_cell(svc.get("service_name", ""))
        price    = _normalize_price(svc.get("price", "По запросу"))
        svc_type = svc.get("type", "Диагностика")

        # Skip Лечебная процедура if not selected
        if svc_type == "Лечебная процедура" and not include_lech:
            continue
        hit = match_service(nm, corpus, catalog_df)
        if hit["matched_id"] != "-":
            cat_r = catalog_df[catalog_df["ID number"] == hit["matched_id"]]
            if not cat_r.empty:
                ctype = cat_r.iloc[0].get("type", "")
                if ctype in ALLOWED_CATALOG_TYPES:
                    svc_type = ctype
                else:
                    hit.update({"matched_id": "-", "matched_name": "-",
                                "comment": "Тип не допустим", "confidence": 0})

        comment = hit["comment"]
        top3    = hit.get("top3_candidates", [])
        if hit["matched_id"] == "-" and top3:
            alts = "; ".join(
                f'{c["service_id"]} {c["name"][:25]} ({c["score"]}%)'
                for c in top3[:2] if c["score"] >= 55
            )
            if alts:
                comment = f'Не найдено | Варианты: {alts}'
        elif hit["confidence"] < 75 and len(top3) > 1:
            alts = "; ".join(
                f'{c["service_id"]} ({c["score"]}%)'
                for c in top3[1:3] if c["score"] >= 60
            )
            if alts:
                comment = f'{hit["comment"]} | Альт: {alts}'

        results.append({
            "Название в MedPay":  hit["matched_name"],
            "Название в клинике": nm,
            "ID":                 hit["matched_id"],
            "Уверенность":        hit["confidence"],
            "Комментарий":        comment,
            "Цена":               price,
            "Тип услуг":          svc_type,
            "top3":               top3,
            "method":             hit.get("method", ""),
        })
    return results


def _make_ready(matched_rows: list, catalog_df) -> pd.DataFrame:
    from modules.exporter import _normalize_price
    rows = []
    for r in matched_rows:
        r = dict(r)
        r["Цена"] = _normalize_price(str(r.get("Цена", "")))
        sid = str(r.get("ID", "")).strip()
        if sid not in ("-", "") and r.get("Название в MedPay") in ("-", ""):
            info = get_service_by_id(catalog_df, sid)
            if info:
                r["Название в MedPay"] = info["Name RU"]
        rows.append(r)
    return build_ready_df(
        rows,
        st.session_state["clinic_name"],
        st.session_state["district"],
        catalog_df,
    )


def _reset_clinic():
    """Clear all per-clinic state, keep catalog."""
    for k in ("clinic_name", "district", "services", "matched",
              "match_summary", "ready_df", "work_step", "work_error"):
        st.session_state[k] = _DEFAULTS[k]


def _save_correction(clinic_name: str, service_name: str,
                     old_id: str, new_id: str, confidence: float):
    """Save a user correction to corrections.csv for future retraining."""
    import csv
    from datetime import datetime
    corrections_file = Path(__file__).parent / "corrections.csv"
    file_exists = corrections_file.exists()
    with open(corrections_file, "a", newline="", encoding="utf-8") as f:
        writer = csv.writer(f)
        if not file_exists:
            writer.writerow(["timestamp", "clinic", "service_name",
                             "old_id", "new_id", "old_confidence"])
        writer.writerow([
            datetime.now().strftime("%Y-%m-%d %H:%M"),
            clinic_name, service_name, old_id, new_id, confidence
        ])


def _transliterate_latin_to_russian(text: str) -> str:
    """
    Detect if service name is in Latin script and transliterate to Cyrillic.
    Only applied when text is predominantly Latin.
    """
    if not text:
        return text
    latin_chars    = sum(1 for c in text if c.isascii() and c.isalpha())
    cyrillic_chars = sum(1 for c in text if '\u0400' <= c <= '\u04FF')
    if latin_chars == 0 or cyrillic_chars > latin_chars:
        return text
    from modules.utils import uz_latin_to_cyrillic
    return uz_latin_to_cyrillic(text)


def _parse_pricelist_xlsx(file_bytes: bytes) -> list:
    """Parse an uploaded price_list.xlsx into services list."""
    df   = pd.read_excel(io.BytesIO(file_bytes), dtype=str)
    cols = df.columns.tolist()
    name_col  = next((c for c in cols if any(
        kw in c.lower() for kw in ("назван", "услуг", "name", "service", "xizmat", "nomi")
    )), cols[1] if len(cols) > 1 else cols[0])
    price_col = next((c for c in cols if any(
        kw in c.lower() for kw in ("цена", "price", "стоим", "narx", "нарх")
    )), None)
    type_col  = next((c for c in cols if any(
        kw in c.lower() for kw in ("тип", "type", "tur")
    )), None)
    svcs = []
    for _, row in df.iterrows():
        nm = clean_cell(str(row.get(name_col, "")))
        if not nm:
            continue
        nm_for_matching = _transliterate_latin_to_russian(nm)
        from modules.exporter import _normalize_price
        price = (_normalize_price(clean_price(str(row.get(price_col, ""))))
                 if price_col else "9999999")
        # Normalize type — handles Analysis, Diagnostics, 1.Analysis, tahlil etc.
        stype = normalize_service_type(
            clean_cell(str(row.get(type_col, ""))) if type_col else ""
        )
        svcs.append({
            "service_name":          nm_for_matching,
            "service_name_original": nm,
            "type":                  stype,
            "price":                 price,
        })
    return svcs


def _parse_matching_xlsx(file_bytes: bytes) -> list:
    """Parse an uploaded matching.xlsx into matched rows list."""
    from modules.exporter import _normalize_price
    df  = pd.read_excel(io.BytesIO(file_bytes), dtype=str)
    req = {"ID", "Цена", "Тип услуг"}
    missing = req - set(df.columns)
    if missing:
        raise ValueError(f"Отсутствуют колонки: {', '.join(missing)}")
    rows = df.to_dict("records")
    for r in rows:
        r["Цена"] = _normalize_price(str(r.get("Цена", "")))
        if "Название в MedPay"  not in r: r["Название в MedPay"]  = "-"
        if "Название в клинике" not in r: r["Название в клинике"] = ""
        if "Уверенность"        not in r: r["Уверенность"]        = 0
        if "Комментарий"        not in r: r["Комментарий"]        = ""
    return rows


# ═══════════════════════════════════════════════════════════════════════════════
# SIDEBAR
# ═══════════════════════════════════════════════════════════════════════════════
with st.sidebar:
    st.title("🏥 MedPay")
    st.caption("v3.1")

    cat_df = st.session_state["catalog_df"]
    if cat_df is not None:
        st.success(f"✅ Каталог: **{len(cat_df):,}** услуг")
        if st.button("🔄 Сменить каталог", key="sb_swap_cat"):
            st.session_state.update({"catalog_df": None, "page": "catalog"})
            _reset_clinic()
            st.rerun()

        # Model status
        ms = model_status()
        if ms["loaded"]:
            st.success("🤖 Модель: Fine-tuned")
        else:
            st.warning("🔤 Модель: Fuzzy (без AI)")
            if ms["error"]:
                with st.expander("Подробнее"):
                    st.caption(ms["error"])
                    st.caption(f"Ожидается: {ms['model_dir']}/model/")

        st.divider()

        page_now = st.session_state["page"]
        if page_now != "setup":
            if st.button("＋ Новая клиника", key="sb_new_clinic"):
                _reset_clinic()
                _go("setup")
        if page_now == "work":
            ws = st.session_state.get("work_step", "")
            st.caption(f"Шаг: **{ws}**")

        # Session timeout warning
        if st.session_state.get("work_step") in ("review_match", "review_price", "match"):
            st.warning(
                "⚠️ **Важно:** Streamlit сбрасывает сессию при длительном бездействии. "
                "Скачайте промежуточный файл матчинга (кнопка ⬇️ Скачать матчинг) "
                "чтобы не потерять работу."
            )

        st.divider()

        # Corrections history
        corrections_file = Path(__file__).parent / "corrections.csv"
        if corrections_file.exists():
            try:
                corr_df = pd.read_csv(corrections_file)
                st.markdown(f"**📝 Исправлений:** {len(corr_df)}")
                with st.expander("История"):
                    st.dataframe(
                        corr_df[["timestamp","service_name","old_id","new_id"]].tail(10),
                        use_container_width=True, hide_index=True
                    )
            except Exception:
                pass

        st.divider()

        st.markdown("**Поиск по ID:**")
        lid = st.text_input("ID", placeholder="700009", key="sb_id",
                            label_visibility="collapsed")
        if lid.strip():
            r = get_service_by_id(cat_df, lid.strip())
            if r:
                st.success("✅ Найдено")
                st.write(f"**RU:** {r['Name RU']}")
                if r["Name UZ"]:
                    st.write(f"**UZ:** {r['Name UZ']}")
                st.write(f"**Тип:** {r['type']}")
            else:
                st.error("ID не найден")

        st.divider()

        st.markdown("**Поиск кандидатов:**")
        sq = st.text_input("Название", placeholder="МРТ головного мозга",
                           key="sb_sq", label_visibility="collapsed")
        if sq.strip() and len(sq.strip()) >= 2:
            em = _get_embedding_matcher()
            rows_s = []
            if em.loaded:
                candidates = em.search(sq.strip(), k=9823)
                seen_s: set = set()
                for c in candidates:
                    if c["score"] < 50:
                        break
                    sid = c["service_id"]
                    if sid in seen_s:
                        continue
                    seen_s.add(sid)
                    cr = cat_df[cat_df["ID number"] == sid]
                    ct = cr.iloc[0]["type"] if not cr.empty else "?"
                    name = c["name_ru"] or c["name_uz"]
                    rows_s.append({
                        "ID": sid,
                        "Название": name[:60],
                        "Тип": ct,
                        "%": c["score"],
                    })
            else:
                corp_s = build_search_corpus(cat_df)
                hits   = rfp.extract(sq.lower(), [c[0] for c in corp_s],
                                     scorer=rff.token_sort_ratio, limit=9823, score_cutoff=40)
                seen_s: set = set()
                for _, sc, ix in hits:
                    _, orig, sid = corp_s[ix]
                    if sid in seen_s:
                        continue
                    seen_s.add(sid)
                    cr = cat_df[cat_df["ID number"] == sid]
                    ct = cr.iloc[0]["type"] if not cr.empty else "?"
                    rows_s.append({"ID": sid, "Название": orig[:60], "Тип": ct, "%": sc})
            if rows_s:
                st.dataframe(pd.DataFrame(rows_s), use_container_width=True, hide_index=True)
            else:
                st.info("Не найдено")
    else:
        st.info("Загрузите каталог MedPay")


# ═══════════════════════════════════════════════════════════════════════════════
# MAIN AREA
# ═══════════════════════════════════════════════════════════════════════════════
st.title("🏥 MedPay Automation")
st.divider()

page = st.session_state["page"]


# ─────────────────────────────────────────────────────────────────────────────
# PAGE: CATALOG
# ─────────────────────────────────────────────────────────────────────────────
if page == "catalog":
    st.header("Шаг 1 — Загрузка каталога MedPay")
    st.caption(
        "Каталог загружается **один раз** и используется для всех клиник в сессии. "
        "Обязательные колонки: `ID number`, `Name RU`, `Name UZ`, `type`, `Name KR`."
    )

    DEFAULT_CATALOG = Path(__file__).parent / "services (3).xlsx"

    def _load_and_set(file_source):
        df_cat, err = load_catalog(file_source)
        if err:
            st.error(f"❌ {err}")
            return False
        st.session_state["catalog_df"] = df_cat
        st.success(f"✅ {get_catalog_summary(df_cat)}")
        for t, n in df_cat["type"].value_counts().items():
            st.write(f"• {t}: **{n:,}**")
        return True

    if DEFAULT_CATALOG.exists():
        st.info(f"📂 Найден файл каталога по умолчанию: `services (3).xlsx`")
        col1, col2 = st.columns(2)
        with col1:
            if st.button("✅ Использовать каталог по умолчанию",
                         type="primary", key="btn_default_cat"):
                with st.spinner("Загрузка каталога..."):
                    if _load_and_set(str(DEFAULT_CATALOG)):
                        _go("setup")
        with col2:
            st.caption("или загрузите другой файл ↓")

    cat_file = st.file_uploader(
        "Загрузить другой каталог (.xlsx)" if DEFAULT_CATALOG.exists()
        else "Excel-файл каталога (.xlsx)",
        type=["xlsx"], key="cat_up"
    )
    if cat_file:
        with st.spinner("Загрузка каталога..."):
            if _load_and_set(cat_file):
                st.button("➡️ Выбрать режим и тип входных данных",
                          type="primary", on_click=_go, args=("setup",))


# ─────────────────────────────────────────────────────────────────────────────
# PAGE: SETUP
# ─────────────────────────────────────────────────────────────────────────────
elif page == "setup":
    if st.session_state["catalog_df"] is None:
        st.warning("Сначала загрузите каталог.")
        st.button("⬅️ К каталогу", on_click=_go, args=("catalog",))

    else:
        st.header("Шаг 2 — Настройка")

        st.markdown("### 1 · Режим")
        m_col, m_info = st.columns([1, 2])
        with m_col:
            mode = st.radio(
                "Режим", options=["manual", "auto"],
                format_func=lambda x: (
                    "🖐  Ручной" if x == "manual" else "⚡  Авто"
                ),
                key="setup_mode", label_visibility="collapsed",
            )
        with m_info:
            if mode == "manual":
                st.info(
                    "**Ручной режим:** вы видите данные на каждом шаге, "
                    "можете редактировать и нажать «Далее» когда готовы."
                )
            else:
                st.info(
                    "**Авто режим:** одно нажатие — программа выполняет "
                    "все шаги автоматически и показывает готовый файл."
                )

        st.divider()

        st.markdown("### 2 · Типы услуг")
        t_col1, t_col2, t_info = st.columns([1, 1, 2])
        with t_col1:
            include_main = st.checkbox(
                "🔬 Анализы + Диагностика",
                value=True, key="include_main_types"
            )
        with t_col2:
            include_lech = st.checkbox(
                "👨‍⚕️ Врачебные услуги",
                value=False, key="include_lech_types"
            )
        if not include_main and not include_lech:
            st.warning("⚠️ Выберите хотя бы один тип услуг.")
        with t_info:
            selected = []
            if include_main: selected.append("Анализы, Диагностика")
            if include_lech: selected.append("Врачебные услуги")
            if selected:
                st.info(f"Будут обработаны: **{' + '.join(selected)}**")

        st.divider()

        st.markdown("### 3 · Входные данные")
        entry_opts = ["A", "B", "C"] if mode == "manual" else ["A", "B", "C", "D"]
        e_col, e_info = st.columns([1, 2])
        with e_col:
            entry = st.radio(
                "Точка входа", options=entry_opts,
                format_func=lambda x: ENTRY_INFO[x][0],
                key="setup_entry", label_visibility="collapsed",
            )
        with e_info:
            st.info(ENTRY_INFO[entry][1])

        st.divider()

        st.markdown("### 4 · Файл клиники")
        if entry in ("A", "D"):
            ft, fl = ["html", "htm"], "HTML-страница прайс-листа (.html)"
        elif entry == "B":
            ft, fl = ["xlsx"], "Готовый прайс-лист (.xlsx)"
        else:
            ft, fl = ["xlsx"], "Файл матчинга (.xlsx)"

        uploaded = st.file_uploader(fl, type=ft, key="clinic_file")

        if uploaded:
            ov_c1, ov_c2 = st.columns(2)
            cn_ov = ov_c1.text_input(
                "Название клиники (если нужно уточнить)",
                placeholder="МедЦентр", key="cn_ov",
            )
            di_ov = ov_c2.text_input(
                "Филиал / Район (если нужно уточнить)",
                placeholder="Yashnobod", key="di_ov",
            )

        st.divider()

        if uploaded and st.button("🚀 Начать обработку", type="primary", key="btn_start"):
            fbytes = uploaded.read()
            cat_df = st.session_state["catalog_df"]
            cn_ov  = st.session_state.get("cn_ov", "").strip()
            di_ov  = st.session_state.get("di_ov", "").strip()

            _reset_clinic()
            st.session_state["mode"]  = mode
            st.session_state["entry"] = entry

            if entry in ("A", "D"):
                try:
                    with st.spinner("Извлечение услуг из HTML..."):
                        c_auto, d_auto, svcs = extract_services_from_html(
                            fbytes, uploaded.name
                        )
                    st.session_state["clinic_name"] = cn_ov or c_auto
                    st.session_state["district"]    = di_ov or d_auto
                    st.session_state["services"]    = svcs
                    if not svcs:
                        st.session_state["work_step"]  = "error"
                        st.session_state["work_error"] = (
                            "Услуги не найдены в HTML файле. "
                            "Проверьте, что страница содержит прайс-лист."
                        )
                    elif mode == "auto" or entry == "D":
                        with st.spinner(f"Матчинг {len(svcs)} услуг (~30–60 с)..."):
                            matched = _run_matching(svcs, cat_df, include_lech=st.session_state.get("include_lech_types", False))
                        n_ok  = sum(1 for r in matched if r["ID"] != "-")
                        n_no  = len(matched) - n_ok
                        n_low = sum(1 for r in matched
                                    if r["ID"] != "-"
                                    and int(float(r.get("Уверенность", 0) or 0) if str(r.get("Уверенность", 0)).replace(".", "").replace("-", "").isdigit() or str(r.get("Уверенность", 0)) == "0" else 0) < 90)
                        st.session_state["matched"]       = matched
                        st.session_state["match_summary"] = (n_ok, n_no, n_low)
                        st.session_state["ready_df"]      = _make_ready(matched, cat_df)
                        st.session_state["work_step"]     = "done"
                    else:
                        st.session_state["work_step"] = "review_price"
                except Exception as ex:
                    st.session_state["work_step"]  = "error"
                    st.session_state["work_error"] = f"Ошибка парсинга HTML: {ex}"

            elif entry == "B":
                try:
                    svcs = _parse_pricelist_xlsx(fbytes)
                    st.session_state["clinic_name"] = (
                        cn_ov or uploaded.name.replace(".xlsx", "").split("_")[0]
                    )
                    st.session_state["district"]  = di_ov or ""
                    st.session_state["services"]  = svcs
                    if not svcs:
                        st.session_state["work_step"]  = "error"
                        st.session_state["work_error"] = "Услуги не найдены в прайс-листе."
                    elif mode == "auto":
                        with st.spinner(f"Матчинг {len(svcs)} услуг (~30–60 с)..."):
                            matched = _run_matching(svcs, cat_df, include_lech=st.session_state.get("include_lech_types", False))
                        n_ok  = sum(1 for r in matched if r["ID"] != "-")
                        n_no  = len(matched) - n_ok
                        n_low = sum(1 for r in matched
                                    if r["ID"] != "-"
                                    and int(float(r.get("Уверенность", 0) or 0) if str(r.get("Уверенность", 0)).replace(".", "").replace("-", "").isdigit() or str(r.get("Уверенность", 0)) == "0" else 0) < 90)
                        st.session_state["matched"]       = matched
                        st.session_state["match_summary"] = (n_ok, n_no, n_low)
                        st.session_state["ready_df"]      = _make_ready(matched, cat_df)
                        st.session_state["work_step"]     = "done"
                    else:
                        st.session_state["work_step"] = "review_price"
                except Exception as ex:
                    st.session_state["work_step"]  = "error"
                    st.session_state["work_error"] = f"Ошибка чтения прайс-листа: {ex}"

            elif entry == "C":
                try:
                    matched = _parse_matching_xlsx(fbytes)
                    st.session_state["clinic_name"] = (
                        cn_ov or uploaded.name.split("_")[0]
                    )
                    st.session_state["district"] = di_ov or ""
                    st.session_state["matched"]  = matched
                    if mode == "auto":
                        st.session_state["ready_df"]  = _make_ready(matched, cat_df)
                        st.session_state["work_step"] = "done"
                    else:
                        st.session_state["work_step"] = "review_match"
                except Exception as ex:
                    st.session_state["work_step"]  = "error"
                    st.session_state["work_error"] = f"Ошибка чтения матчинга: {ex}"

            _go("work")


# ─────────────────────────────────────────────────────────────────────────────
# PAGE: WORK
# ─────────────────────────────────────────────────────────────────────────────
elif page == "work":
    cat_df     = st.session_state["catalog_df"]
    work_step  = st.session_state["work_step"]
    mode       = st.session_state["mode"]
    clinic_nm  = st.session_state["clinic_name"]
    district   = st.session_state["district"]

    entry = st.session_state["entry"]
    STEPS_FOR_ENTRY = {
        "A": ["review_price", "match", "review_match", "done"],
        "B": ["review_price", "match", "review_match", "done"],
        "C": ["review_match", "done"],
        "D": ["done"],
    }
    steps_list = STEPS_FOR_ENTRY.get(entry, ["done"])
    if mode == "auto" and entry not in ("C",):
        steps_list = ["done"]

    if work_step not in ("error",):
        labels = {
            "review_price": "📋 Прайс",
            "match":        "🔍 Матчинг",
            "review_match": "✏️ Проверка",
            "done":         "✅ Готово",
        }
        prog_cols = st.columns(len(steps_list))
        for ci, s in enumerate(steps_list):
            lbl = labels.get(s, s)
            if s == work_step:
                prog_cols[ci].markdown(f"**▶ {lbl}**")
            elif steps_list.index(s) < steps_list.index(work_step) if work_step in steps_list else False:
                prog_cols[ci].markdown(f"~~{lbl}~~ ✓")
            else:
                prog_cols[ci].markdown(f"{lbl}")
        st.divider()

    # ── Sub-step: error ───────────────────────────────────────────────────────
    if work_step == "error":
        st.error(f"❌ {st.session_state['work_error']}")
        c1, c2 = st.columns(2)
        c1.button("⬅️ Назад к настройкам", on_click=_go, args=("setup",))
        if c2.button("🔄 Новая клиника"):
            _reset_clinic()
            _go("setup")

    # ── Sub-step: review_price ────────────────────────────────────────────────
    elif work_step == "review_price":
        svcs = st.session_state["services"]
        n_ana   = sum(1 for s in svcs if s["type"] == "Анализы")
        n_dia   = sum(1 for s in svcs if s["type"] == "Диагностика")
        n_lech  = sum(1 for s in svcs if s["type"] == "Лечебная процедура")
        n_other = len(svcs) - n_ana - n_dia - n_lech

        st.markdown(f"### 📋 Прайс-лист · {clinic_nm} / {district}")
        st.caption(
            f"**{len(svcs)}** услуг (Анализы: {n_ana}, Диагностика: {n_dia}"
            + (f", Врачебные: {n_lech}" if n_lech > 0 else "")
            + "). Проверьте, отредактируйте при необходимости, затем нажмите «Далее»."
        )

        other_svcs = [s for s in svcs if s["type"] not in ("Анализы", "Диагностика", "Лечебная процедура")]
        if other_svcs:
            with st.expander(
                f"⚠️ Найдено {len(other_svcs)} услуг с нестандартным типом — нажмите чтобы посмотреть",
                expanded=True
            ):
                st.warning(
                    "Следующие услуги имеют нераспознанный тип. "
                    "Они **не будут включены** в итоговый файл. "
                    "Вы можете изменить тип вручную в таблице ниже."
                )
                other_df = pd.DataFrame([
                    {"#": i+1, "Название услуги": s["service_name"],
                     "Тип (определён как)": s["type"], "Цена": s["price"]}
                    for i, s in enumerate(other_svcs)
                ])
                st.dataframe(other_df, use_container_width=True, hide_index=True)

        price_df = pd.DataFrame([
            {"#": i+1, "Название услуги": s["service_name"],
             "Тип": s["type"], "Цена": s["price"]}
            for i, s in enumerate(svcs)
        ])
        edited_p = st.data_editor(
            price_df, use_container_width=True, num_rows="dynamic",
            column_config={
                "#":               st.column_config.NumberColumn(disabled=True, width=55),
                "Название услуги": st.column_config.TextColumn(width="large"),
                "Тип":             st.column_config.SelectboxColumn(
                                       options=sorted(ALLOWED_TYPES), width=160),
                "Цена":            st.column_config.TextColumn(width=120),
            },
            key="price_editor",
        )

        ba, bb, bc = st.columns([1, 1, 1])
        with ba:
            st.button("⬅️ Назад", on_click=_go, args=("setup",))
        with bb:
            pl_svcs = [
                {"service_name": clean_cell(str(r["Название услуги"])),
                 "type": clean_cell(str(r["Тип"])),
                 "price": clean_price(str(r["Цена"]))}
                for _, r in edited_p.iterrows()
                if clean_cell(str(r.get("Название услуги", "")))
            ]
            st.download_button(
                "⬇️ Скачать прайс-лист",
                data=export_price_list_excel(pl_svcs, clinic_nm, district),
                file_name=f"{_fname()}_price_list.xlsx",
                mime=EXCEL_MIME,
                key="dl_pl",
            )
        with bc:
            if st.button("➡️ К матчингу", type="primary", key="btn_to_match"):
                st.session_state["services"] = [
                    {"service_name": clean_cell(str(r.get("Название услуги", ""))),
                     "type":  normalize_service_type(clean_cell(str(r.get("Тип", "")))),
                     "price": clean_price(str(r.get("Цена", "")))}
                    for _, r in edited_p.iterrows()
                    if clean_cell(str(r.get("Название услуги", "")))
                ]
                st.session_state["work_step"] = "match"
                st.rerun()

    # ── Sub-step: match ───────────────────────────────────────────────────────
    elif work_step == "match":
        svcs = st.session_state["services"]
        st.markdown(f"### 🔍 Матчинг · {clinic_nm} / {district}")
        st.write(
            f"Услуг: **{len(svcs)}** · Порог уверенности: **85%** — "
            "ниже этого ID не назначается (требует ручной проверки)."
        )

        c1, c2 = st.columns([1, 2])
        with c1:
            run_btn = st.button("🔍 Запустить матчинг",
                                type="primary", key="btn_run_match")
        with c2:
            st.button("⬅️ Назад к прайс-листу",
                      on_click=lambda: st.session_state.update(
                          {"work_step": "review_price"}
                      ) or st.rerun(),
                      key="btn_back_price")

        if run_btn:
            with st.spinner(f"Матчинг {len(svcs)} услуг (~30–60 с)..."):
                matched = _run_matching(svcs, cat_df, include_lech=st.session_state.get("include_lech_types", False))
            n_ok  = sum(1 for r in matched if r["ID"] != "-")
            n_no  = len(matched) - n_ok
            n_low = sum(1 for r in matched
                        if r["ID"] != "-"
                        and int(float(r.get("Уверенность", 0) or 0) if str(r.get("Уверенность", 0)).replace(".", "").replace("-", "").isdigit() or str(r.get("Уверенность", 0)) == "0" else 0) < 90)
            st.session_state["matched"]       = matched
            st.session_state["match_summary"] = (n_ok, n_no, n_low)
            st.session_state["work_step"]     = "review_match"
            st.rerun()

    # ── Sub-step: review_match ────────────────────────────────────────────────
    elif work_step == "review_match":
        matched = st.session_state["matched"]
        n_ok, n_no, n_low = st.session_state["match_summary"]

        st.markdown(f"### ✏️ Проверка матчинга · {clinic_nm} / {district}")

        def _conf(r):
            try:
                return int(float(r.get("Уверенность", 0) or 0))
            except (ValueError, TypeError):
                return 0

        mc1, mc2, mc3, mc4, mc5 = st.columns(5)
        mc1.metric("Всего",               len(matched))
        mc2.metric("✅ Высокая (≥90%)",   sum(1 for r in matched if _conf(r) >= 90))
        mc3.metric("🟡 Хорошая (75-89%)", sum(1 for r in matched if 75 <= _conf(r) < 90))
        mc4.metric("🔴 Проверить (<75%)", sum(1 for r in matched if 0 < _conf(r) < 75))
        mc5.metric("⬜ Не найдено",        sum(1 for r in matched if str(r.get("ID","-")) == "-"))

        needs_review = [r for r in matched if _conf(r) < 75
                        and str(r.get("ID", "-")) != "-"]
        not_found    = [r for r in matched if str(r.get("ID", "-")) == "-"]

        if needs_review or not_found:
            st.warning(
                f"⚠️ **{len(needs_review)} строк требуют проверки** (уверенность <75%)  |  "
                f"**{len(not_found)} не найдено**.  "
                "Проверьте их ниже перед генерацией."
            )

        rows_to_review = not_found + needs_review
        if rows_to_review:
            with st.expander(
                f"🔍 Проверить кандидатов ({len(rows_to_review)} строк)",
                expanded=True
            ):
                st.caption(
                    "Для каждой строки показаны топ-3 кандидата из каталога. "
                    "Нажмите **Выбрать** чтобы применить кандидата, "
                    "или отредактируйте ID вручную в таблице ниже."
                )
                for ridx, row in enumerate(rows_to_review):
                    score = _conf(row)
                    sid   = str(row.get("ID", "-"))
                    label = row.get("Комментарий", "")
                    top3  = row.get("top3", [])

                    color = "#ffe0e0" if sid == "-" else "#fffde0"
                    st.markdown(
                        f'<div style="background:{color};padding:8px;border-radius:6px;margin-bottom:8px">'
                        f'<b>#{ridx+1}</b> &nbsp; {row.get("Название в клинике","")[:70]}'
                        f'&nbsp;&nbsp; <code>{label}</code> ({score}%)'
                        f'</div>',
                        unsafe_allow_html=True,
                    )

                    if top3:
                        cand_cols = st.columns(len(top3))
                        for ci, cand in enumerate(top3):
                            with cand_cols[ci]:
                                cname  = cand.get("name", "")[:50]
                                cscore = cand.get("score", 0)
                                csid   = cand.get("service_id", "")
                                ctype  = cand.get("type", "")
                                st.caption(f"**{cscore:.0f}%** · `{csid}` · {ctype}")
                                st.caption(cname)
                                if st.button("Применить", key=f"pick_{ridx}_{ci}"):
                                    clinic_nm_svc = row.get("Название в клинике","")
                                    old_id = str(row.get("ID", "-"))
                                    old_conf = float(row.get("Уверенность", 0) or 0)
                                    for mr in matched:
                                        if mr.get("Название в клинике","") == clinic_nm_svc:
                                            mr["Название в MedPay"] = cname
                                            mr["ID"]               = csid
                                            mr["Уверенность"]      = int(cscore)
                                            mr["Комментарий"]      = f"Выбрано вручную ({cscore:.0f}%)"
                                            break
                                    # Save correction for retraining
                                    if old_id != csid:
                                        _save_correction(
                                            st.session_state.get("clinic_name", ""),
                                            clinic_nm_svc, old_id, csid, old_conf
                                        )
                                    st.session_state["matched"] = matched
                                    st.rerun()
                    else:
                        st.caption("Кандидаты не найдены — введите ID вручную")
                    st.divider()

        mdf = pd.DataFrame([
            {k: v for k, v in r.items() if k != "top3" and k != "method"}
            for r in matched
        ])

        st.markdown("##### ✏️ Редактор строк")
        st.caption(
            "🟢 ≥90% · 🟡 75-89% · 🔴 <75% · ⬜ не найдено. "
            "Все строки имеют ID — проверьте названия перед генерацией."
        )
        edited_m = st.data_editor(
            mdf, use_container_width=True, num_rows="dynamic",
            column_config={
                "Название в MedPay":  st.column_config.TextColumn(width="large"),
                "Название в клинике": st.column_config.TextColumn(width="large"),
                "ID":                 st.column_config.TextColumn(width=115),
                "Уверенность":        st.column_config.NumberColumn(
                                          min_value=0, max_value=100,
                                          width=115, disabled=True),
                "Комментарий":        st.column_config.TextColumn(width="medium"),
                "Цена":               st.column_config.TextColumn(width=115),
                "Тип услуг":          st.column_config.SelectboxColumn(
                                          options=sorted(ALLOWED_TYPES), width=160),
            },
            key="match_editor",
        )

        val_errs = []
        for idx, row in edited_m.iterrows():
            rd = row.to_dict()
            rd["Цена"] = clean_price(str(rd.get("Цена", "")))
            for e in validate_matching_row(rd, cat_df):
                val_errs.append(f"Строка {idx+1}: {e}")

        ab1, ab2, ab3 = st.columns([2, 1, 1])
        with ab1:
            if val_errs:
                st.error(f"⚠️ Ошибок валидации: {len(val_errs)}")
                for e in val_errs[:3]:
                    st.error(e)
            else:
                st.success("✅ Все строки прошли валидацию.")
        with ab2:
            mb = export_matching_excel(edited_m.to_dict("records"))
            st.download_button(
                "⬇️ Скачать матчинг",
                data=mb,
                file_name=f"{_fname()}_matching.xlsx",
                mime=EXCEL_MIME,
                key="dl_matching",
            )
        with ab3:
            if st.button("➡️ Сгенерировать файл", type="primary",
                         key="btn_gen", disabled=bool(val_errs)):
                try:
                    rdf = _make_ready(edited_m.to_dict("records"), cat_df)
                    st.session_state["matched"]   = edited_m.to_dict("records")
                    st.session_state["ready_df"]  = rdf
                    st.session_state["work_step"] = "done"
                    st.rerun()
                except Exception as ex:
                    st.session_state["work_step"]  = "error"
                    st.session_state["work_error"] = str(ex)
                    st.rerun()

        st.button("⬅️ Повторить матчинг",
                  on_click=lambda: st.session_state.update({"work_step": "match"}) or st.rerun(),
                  key="btn_rematch")

    # ── Sub-step: done ────────────────────────────────────────────────────────
    elif work_step == "done":
        rdf = st.session_state["ready_df"]
        st.markdown(f"### ✅ Готово · {clinic_nm} / {district}")

        fin_errs = validate_final_df(rdf, cat_df)
        if fin_errs:
            st.error(f"❌ Ошибок финальной валидации: {len(fin_errs)}")
            for e in fin_errs[:8]:
                st.error(e)
        else:
            st.success(
                f"Валидация пройдена — **{len(rdf)}** строк · "
                f"22 колонки · "
                f"Типы: {', '.join(sorted(rdf['Тип услуг'].unique()))}"
            )

        m1, m2, m3, m4, m5, m6 = st.columns(6)
        m1.metric("Строк",              len(rdf))
        m2.metric("Диагностика",        int((rdf["Тип услуг"] == "Диагностика").sum()))
        m3.metric("Анализы",            int((rdf["Тип услуг"] == "Анализы").sum()))
        m4.metric("Лечебная процедура", int((rdf["Тип услуг"] == "Лечебная процедура").sum()))
        m5.metric("С ID",               int((rdf["Услуга ID"] != "-").sum()))
        m6.metric("По запросу",         int((rdf["Цена"] == "По запросу").sum()))
        st.markdown("##### ✏️ Финальное редактирование (необязательно)")
        edited_r = st.data_editor(
            rdf, use_container_width=True, num_rows="dynamic",
            column_config={
                "Услуга ID":    st.column_config.TextColumn(width=115),
                "Клиника":      st.column_config.TextColumn(width=160),
                "Филиал":       st.column_config.TextColumn(width=160),
                "Имя RU":       st.column_config.TextColumn(width="large"),
                "Имя UZ":       st.column_config.TextColumn(width="large"),
                "Имя KR":       st.column_config.TextColumn(width="large"),
                "Тип услуг":    st.column_config.SelectboxColumn(
                                    options=sorted(ALLOWED_TYPES)),
                "Цена":         st.column_config.TextColumn(width=115),
                "Активен":      st.column_config.TextColumn(width=80,  disabled=True),
                "Категория RU": st.column_config.TextColumn(width=200, disabled=True),
                "Категория UZ": st.column_config.TextColumn(width=200, disabled=True),
                "Категория KR": st.column_config.TextColumn(width=200, disabled=True),
            },
            key="ready_editor",
        )

        re_errs = validate_final_df(edited_r, cat_df)
        if re_errs:
            st.error(f"⚠️ Ошибок после редактирования: {len(re_errs)}")
            for e in re_errs[:5]:
                st.error(e)

        xl_fname   = f"{_fname()}_ready.xlsx"
        sheet_name = f"{_fname()}_ready"[:31]
        if not re_errs:
            st.download_button(
                f"⬇️ Скачать  {xl_fname}",
                data=export_ready_excel(
                    edited_r,
                    clinic_name=clinic_nm,
                    district=district,
                ),
                file_name=xl_fname,
                mime=EXCEL_MIME,
                type="primary",
                use_container_width=True,
                key="dl_ready",
            )
            st.success(
                f"**Файл:** `{xl_fname}` · "
                f"{len(edited_r)} строк · 22 колонки · "
                f"Лист: `{sheet_name}`"
            )
        else:
            st.button("⬇️ Скачать (исправьте ошибки)",
                      disabled=True, use_container_width=True)

        st.divider()
        nc1, nc2 = st.columns(2)
        nc1.button("➕ Новая клиника",
                   type="primary",
                   on_click=lambda: (_reset_clinic(), _go("setup")),
                   key="btn_new")
        nc2.button("🔄 Новый сеанс (сменить каталог)",
                   on_click=lambda: (
                       st.session_state.update(
                           {"catalog_df": None, "page": "catalog"}
                       ),
                       _reset_clinic(),
                       st.rerun()
                   ),
                   key="btn_reset")

# ── Footer ────────────────────────────────────────────────────────────────────
st.divider()
ws_label  = st.session_state.get("work_step", "")
mode_lbl  = "⚡ Авто" if st.session_state.get("mode") == "auto" else "🖐 Ручной"
entry_lbl = st.session_state.get("entry", "")
st.caption(
    f"MedPay Automation v3.1 · {mode_lbl}"
    + (f" · Вход {entry_lbl}" if entry_lbl else "")
    + (f" · Шаг: {ws_label}" if ws_label else "")
)
