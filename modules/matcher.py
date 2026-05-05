"""
matcher.py — Cascade matching engine v2.1

Priority:
  1. Fine-tuned sentence-transformers model + FAISS  (primary)
  2. RapidFuzz fuzzy matching                        (fallback if model not loaded)

Confidence labels:
  ≥ 90%  → "Высокая уверенность"       — safe to use, still verify name
  75–89% → "Хорошее совпадение"         — spot-check recommended
  70–74% → "Проверить вручную"          — show to human, likely correct
  < 70%  → no ID assigned               — human must search manually

Key rule: ID is assigned ONLY if confidence >= 70%.
          Below 70% → no ID, no name assigned, human must search manually.

Model: intfloat/multilingual-e5-base (fine-tuned)
       Requires "query: " prefix for queries, "passage: " prefix for catalog.

top3_candidates: always returned so human can pick an alternative.

Model files expected at:  medpay_model/model/
FAISS index expected at:  medpay_model/catalog.faiss
Catalog meta expected at: medpay_model/catalog_meta.json
"""
import re
import os
import json
import numpy as np
import pandas as pd
from pathlib import Path
from rapidfuzz import fuzz, process
from modules.utils import clean_cell, safe_str

# ── Paths ─────────────────────────────────────────────────────────────────────
_MODEL_DIR = Path(__file__).parent.parent / "medpay_model"

# ── Constants ─────────────────────────────────────────────────────────────────
ALLOWED_CATALOG_TYPES = {"Анализы", "Анализ", "Диагностика"}

# Minimum confidence to assign an ID
MIN_CONFIDENCE = 70  # below this → _no_match()

# Confidence label thresholds
LABEL_HIGH  = 90   # "Высокая уверенность"
LABEL_GOOD  = 75   # "Хорошее совпадение"
LABEL_CHECK = 70   # "Проверить вручную"

# ── Query expansion ───────────────────────────────────────────────────────────
_EXPAND_MAP = {
    # Lab abbreviations
    "АСТ":        "АСТ аспартатаминотрансфераза",
    "АЛТ":        "АЛТ аланинаминотрансфераза",
    "АЛАТ":       "АЛАТ аланинаминотрансфераза",
    "АСАТ":       "АСАТ аспартатаминотрансфераза",
    "ЛДГ":        "ЛДГ лактатдегидрогеназа",
    "ГГТ":        "ГГТ гамма-глутамилтранспептидаза",
    "ЩФ":         "ЩФ щелочная фосфатаза",
    "КФК":        "КФК креатинфосфокиназа",
    "КК":         "КК креатинкиназа",
    "СРБ":        "СРБ С-реактивный белок",
    "РФ":         "РФ ревматоидный фактор",
    "ПСА":        "ПСА простатический специфический антиген",
    "ТТГ":        "ТТГ тиреотропный гормон",
    "TSH":        "ТТГ тиреотропный гормон TSH",
    "Т3":         "Т3 трийодтиронин",
    "Т4":         "Т4 тироксин",
    "ЛГ":         "ЛГ лютеинизирующий гормон",
    "ФСГ":        "ФСГ фолликулостимулирующий гормон",
    "АМГ":        "АМГ антимюллеров гормон",
    "ДГЭА":       "ДГЭА дегидроэпиандростерон",
    "ДЭА":        "ДЭА дегидроэпиандростерон",
    "DHEA":       "DHEA дегидроэпиандростерон",
    "ГТТ":        "ГТТ глюкозотолерантный тест",
    "ПЦР":        "ПЦР полимеразная цепная реакция",
    "ИФА":        "ИФА иммуноферментный анализ",
    "ЛПВП":       "ЛПВП липопротеины высокой плотности",
    "ЛПНП":       "ЛПНП липопротеины низкой плотности холестерин",
    "ЛПОНП":      "ЛПОНП липопротеины очень низкой плотности",
    "ХС":         "ХС холестерин",
    "ОАК":        "ОАК общий анализ крови",
    "ОАМ":        "ОАМ общий анализ мочи",
    "СОЭ":        "СОЭ скорость оседания эритроцитов",
    "HbsAg":      "HbsAg поверхностный антиген гепатита B Hepatitis B surface antigen HBsAg",
    "HBsAg":      "HBsAg поверхностный антиген гепатита B Hepatitis B surface antigen HbsAg",
    "Covid":      "Covid SARS-CoV SARS coronavirus коронавирус COVID-19 ПЦР антитела",
    "covid":      "covid SARS-CoV SARS coronavirus коронавирус COVID-19 ПЦР антитела",
    "COVID":      "COVID SARS-CoV SARS coronavirus коронавирус COVID-19 ПЦР антитела",
    "SARS":       "SARS CoV coronavirus коронавирус COVID COVID-19",
    "HIV":        "HIV ВИЧ антитела",
    "ВИЧ":        "ВИЧ антитела иммунодефицит",
    "Вич":        "ВИЧ антитела иммунодефицит HIV",
    # Imaging abbreviations
    "МРТ":        "МРТ магнитно-резонансная томография",
    "КТ":         "КТ компьютерная томография",
    "МСКТ":       "МСКТ мультиспиральная компьютерная томография",
    "УЗИ":        "УЗИ ультразвуковое исследование",
    "ЭКГ":        "ЭКГ электрокардиограмма",
    "ЭЭГ":        "ЭЭГ электроэнцефалограмма",
    "ЭМГ":        "ЭМГ электромиограмма",
    "ЭХОКГ":      "ЭХОКГ эхокардиография ультразвуковое исследование сердца",
    "ФГС":        "ФГС фиброгастроскопия",
    "ФГДС":       "ФГДС фиброгастродуоденоскопия",
    "ЭГДС":       "ЭГДС эзофагогастродуоденоскопия",
    "КТГ":        "КТГ кардиотокография",
    # New abbreviations from Hilol Hospital analysis
    "АЦЦП":       "АЦЦП антитела к циклическому цитруллинированному пептиду ревматоидный артрит",
    "АКТГ":       "АКТГ адренокортикотропный гормон",
    "ПТИ":        "ПТИ протромбиновый индекс протромбин коагуляция",
    "ХОЛТЕР":     "ХОЛТЕР суточное мониторирование ЭКГ сердца",
    "НСГ":        "НСГ нейросонография головного мозга ультразвуковое",
    "ТКДГ":       "ТКДГ транскраниальная допплерография сосудов",
    "SCL":        "SCL склеродермия антитела аутоантитела",
    "MUSK":       "MUSK мышечно-специфическая тирозинкиназа антитела миастения",
    "Б27":        "Б27 HLA-B27 антиген лейкоцитарный генотипирование",
    "ИФР":        "ИФР инсулиноподобный фактор роста соматомедин",
    "МНО":        "МНО международное нормализованное отношение коагуляция",
    "СМАД":       "СМАД суточное мониторирование артериального давления",
    "ANA":        "ANA антинуклеарные антитела аутоиммунный",
    "Anti-dsDNA": "Anti-dsDNA антитела к двуспиральной ДНК системная красная волчанка",
    "ENA":        "ENA антитела к экстрагируемым ядерным антигенам",
    "HLAB27":     "HLAB27 HLA-B27 антиген лейкоцитарный генотипирование Бехтерев",
    "ПТГ":        "ПТГ паратиреоидный гормон паратгормон",
    "СТГ":        "СТГ соматотропный гормон гормон роста",
    "АТ-ТПО":     "АТ-ТПО антитела к тиреоидной пероксидазе",
    "АТ-ТГ":      "АТ-ТГ антитела к тиреоглобулину",
    "ХГЧ":        "ХГЧ хорионический гонадотропин беременность",
    "ХГ":         "ХГ хорионический гонадотропин беременность",
    "АФП":        "АФП альфа-фетопротеин онкомаркер",
    "РЭА":        "РЭА раково-эмбриональный антиген онкомаркер",
    "ПАП":        "ПАП цитология мазок шейка матки",
    "ОЖСС":       "ОЖСС железосвязывающая способность сыворотки железо",
    "HDV":        "HDV гепатит D дельта вирус",
    "HBV":        "HBV гепатит B вирус ДНК",
    "HCV":        "HCV гепатит C вирус антитела РНК",
    "HAV":        "HAV гепатит A вирус антитела",
}

# ── Cyrillic/Latin normalization for mixed-script names ──────────────────────
# Some clinic names use Cyrillic letters inside Latin words e.g. "HСV" (Cyrillic С)
_MIXED_SCRIPT_MAP = {
    "С": "C", "с": "c",  # Cyrillic С → Latin C
    "А": "A", "а": "a",  # Cyrillic А → Latin A
    "В": "B", "в": "b",  # Cyrillic В → Latin B (context-dependent)
    "Е": "E", "е": "e",  # Cyrillic Е → Latin E
    "К": "K", "к": "k",  # Cyrillic К → Latin K
    "М": "M", "м": "m",  # Cyrillic М → Latin M
    "Н": "H", "н": "h",  # Cyrillic Н → Latin H
    "О": "O", "о": "o",  # Cyrillic О → Latin O
    "Р": "P", "р": "p",  # Cyrillic Р → Latin P
    "Т": "T", "т": "t",  # Cyrillic Т → Latin T
    "Х": "X", "х": "x",  # Cyrillic Х → Latin X
}

def _normalize_mixed_script(text: str) -> str:
    """
    Normalize mixed Cyrillic/Latin tokens.
    Detects tokens that look like Latin abbreviations but contain Cyrillic lookalikes,
    and converts them to pure Latin. E.g. 'HСV' → 'HCV'.
    """
    tokens = text.split()
    result = []
    for token in tokens:
        # Check if token has both Latin and Cyrillic characters
        has_latin   = any(c.isascii() and c.isalpha() for c in token)
        has_cyrillic = any('\u0400' <= c <= '\u04FF' for c in token)
        if has_latin and has_cyrillic:
            # Mixed token — normalize Cyrillic lookalikes to Latin
            normalized = ''.join(_MIXED_SCRIPT_MAP.get(c, c) for c in token)
            result.append(normalized)
        else:
            result.append(token)
    return ' '.join(result)


# ── Noise patterns to strip before matching ───────────────────────────────────
_NOISE_PATTERNS = [
    r"\bсвис\s+лаб\b", r"\bswiss\s+lab\b", r"\bинвитро\b", r"\bгемотест\b", r"\bкдл\b",
    r"\d+\s*параметр[оав]*",
    r"\(\s*с\s+формулой\s*\)", r"\(\s*без\s+формулы\s*\)",
    r"\(\s*\d+\s*точки?\s*[:\s].*?\)",
    r"[-–]\s*гормоны?\b",
    r"\bсахарная\s+кривая\b",
    r"\bпервичный\b", r"\bповторный\b",
    r"\(\s*хс\s*\)", r"\(\s*хороший\s+холестерин\s*\)", r"\(\s*плохой\s+холестерин\s*\)",
    r"\bгистология\s*-\s*", r"\bгистол\.\s*",
    r"[-–]\s+диагностика\s+биоценоза\s+у\s+\w+",
    r"\bандрофлор\s+скрин\b", r"\bфемофлор\s+скрин\b",
    r"\(\s*острицы\s*\)",
    r"\(?\s*сахарная\s+кривая\s*\)?",
    r"\bв\s+\d+.х\s+порциях?\b",
    r"\bпо\s+нечипоренко\b", r"\bпо\s+земницкому\b",
    r"\bClia\b", r"\bclia\b",          # lab brand name noise
    r"\bИФА\b",                         # method noise when appended to name
    r"\bэкспресс\s+тест\b",
]
_NOISE_RE = re.compile("|".join(_NOISE_PATTERNS), re.IGNORECASE)


# ═══════════════════════════════════════════════════════════════════════════════
# MODEL ENGINE  (fine-tuned sentence-transformers + FAISS)
# ═══════════════════════════════════════════════════════════════════════════════
class EmbeddingMatcher:
    """
    Loads the fine-tuned model and FAISS index once.
    Uses intfloat/multilingual-e5-base (requires "query: " prefix).
    """
    def __init__(self):
        self.model      = None
        self.index      = None
        self.meta       = None
        self.loaded     = False
        self.load_error = ""

    def load(self, model_dir: Path) -> bool:
        try:
            import faiss
            import os
            from sentence_transformers import SentenceTransformer

            HF_REPO  = "admin11011/medpay-matcher"
            hf_token = os.environ.get("HF_TOKEN")

            # ── Try local first (works when running locally) ──────────────────
            model_path = model_dir / "model"
            faiss_path = model_dir / "catalog.faiss"
            meta_path  = model_dir / "catalog_meta.json"

            if model_path.exists() and faiss_path.exists() and meta_path.exists():
                print(f"[matcher] Loading from local: {model_dir}")
                self.model = SentenceTransformer(str(model_path))
                self.index = faiss.read_index(str(faiss_path))
                with open(meta_path, encoding="utf-8") as f:
                    self.meta = json.load(f)
                self.loaded = True
                return True

            # ── Fallback: load from HuggingFace Hub (Streamlit Cloud) ─────────
            print(f"[matcher] Local model not found, loading from HuggingFace: {HF_REPO}")
            from huggingface_hub import snapshot_download, hf_hub_download

            local_dir = "/tmp/medpay_model"
            os.makedirs(local_dir, exist_ok=True)

            # Download model weights
            snapshot_download(
                repo_id=HF_REPO,
                token=hf_token,
                ignore_patterns=["catalog.faiss", "catalog_meta.json"],
                local_dir=local_dir,
            )
            self.model = SentenceTransformer(local_dir)

            # Download FAISS index
            faiss_local = hf_hub_download(
                repo_id=HF_REPO,
                filename="catalog.faiss",
                token=hf_token,
                local_dir=local_dir,
            )
            self.index = faiss.read_index(faiss_local)

            # Download catalog meta
            meta_local = hf_hub_download(
                repo_id=HF_REPO,
                filename="catalog_meta.json",
                token=hf_token,
                local_dir=local_dir,
            )
            with open(meta_local, encoding="utf-8") as f:
                self.meta = json.load(f)

            self.loaded = True
            print(f"[matcher] Loaded from HuggingFace successfully")
            return True

        except ImportError as e:
            self.load_error = f"Missing package: {e}"
            return False
        except Exception as e:
            self.load_error = f"Load error: {e}"
            return False

    def search(self, query: str, k: int = 3) -> list[dict]:
        """Search catalog. Uses 'query: ' prefix required for E5 model."""
        if not self.loaded:
            return []

        # E5 model requires "query: " prefix
        expanded = "query: " + expand_query(_normalize_mixed_script(query))

        emb = self.model.encode(
            [expanded],
            normalize_embeddings=True,
            convert_to_numpy=True,
        )
        D, I = self.index.search(emb.astype("float32"), k)

        results = []
        for score, idx in zip(D[0], I[0]):
            if idx < 0 or idx >= len(self.meta):
                continue
            m = self.meta[idx]
            results.append({
                "service_id": m["service_id"],
                "name_ru":    m.get("name_ru", ""),
                "name_uz":    m.get("name_uz", ""),
                "type":       m.get("type", ""),
                "score":      round(float(score) * 100, 1),
            })
        return results


_embedding_matcher = EmbeddingMatcher()
_model_load_attempted = False


def _get_embedding_matcher() -> EmbeddingMatcher:
    global _model_load_attempted
    if not _model_load_attempted:
        _model_load_attempted = True
        success = _embedding_matcher.load(_MODEL_DIR)
        if success:
            print(f"[matcher] Fine-tuned model loaded from {_MODEL_DIR}")
        else:
            print(f"[matcher] Model not loaded: {_embedding_matcher.load_error}")
            print("[matcher] Falling back to fuzzy matching")
    return _embedding_matcher


# ═══════════════════════════════════════════════════════════════════════════════
# QUERY EXPANSION + NORMALIZATION
# ═══════════════════════════════════════════════════════════════════════════════
def expand_query(query: str) -> str:
    """Expand abbreviations token by token."""
    tokens   = query.split()
    expanded = []
    for token in tokens:
        clean = token.strip("().,:-–")
        if clean in _EXPAND_MAP:
            expanded.append(_EXPAND_MAP[clean])
        else:
            expanded.append(token)
    return " ".join(expanded)


def _strip_noise(text: str) -> str:
    t = _NOISE_RE.sub(" ", text)
    return re.sub(r"\s+", " ", t).strip(" -–(),.")


def _normalize_fuzzy(text: str) -> str:
    t = _normalize_mixed_script(text.lower().strip())
    t = _NOISE_RE.sub(" ", t)
    t = re.sub(r"\s+", " ", t).strip()
    tokens = t.split()
    expanded = []
    for tok in tokens:
        clean = tok.strip("().,:-–")
        upper = clean.upper()
        if upper in _EXPAND_MAP:
            expanded.append(_EXPAND_MAP[upper].lower())
        else:
            expanded.append(tok)
    return " ".join(expanded)


# ═══════════════════════════════════════════════════════════════════════════════
# CONFIDENCE LABELING
# ═══════════════════════════════════════════════════════════════════════════════
def confidence_label(score: float) -> str:
    if score >= LABEL_HIGH:
        return "Высокая уверенность"
    if score >= LABEL_GOOD:
        return "Хорошее совпадение"
    if score >= LABEL_CHECK:
        return "Проверить вручную"
    return "Требует проверки"


def confidence_color(score: float) -> str:
    if score >= LABEL_HIGH:  return "green"
    if score >= LABEL_GOOD:  return "orange"
    if score >= LABEL_CHECK: return "red"
    return "darkred"


# ═══════════════════════════════════════════════════════════════════════════════
# FUZZY FALLBACK ENGINE
# ═══════════════════════════════════════════════════════════════════════════════
def build_search_corpus(catalog_df: pd.DataFrame) -> list[tuple[str, str, str]]:
    corpus = []
    for _, row in catalog_df.iterrows():
        rtype = safe_str(row.get("type", "")).strip()
        if rtype not in ALLOWED_CATALOG_TYPES:
            continue
        sid = safe_str(row.get("ID number", ""))
        for col in ("Name RU", "Name UZ", "Name KR"):
            name = safe_str(row.get(col, ""))
            if name:
                corpus.append((_normalize_fuzzy(name), name, sid))
    return corpus


def _fuzzy_top3(
    query: str,
    corpus: list[tuple[str, str, str]],
    catalog_df: pd.DataFrame,
) -> list[dict]:
    norm_q     = _normalize_fuzzy(query)
    norm_q_ns  = _normalize_fuzzy(_strip_noise(query))
    corp_norms = [c[0] for c in corpus]

    best: dict[str, dict] = {}

    for q in list({norm_q, norm_q_ns}):
        for scorer in [fuzz.token_sort_ratio, fuzz.token_set_ratio, fuzz.partial_ratio]:
            hits = process.extract(q, corp_norms, scorer=scorer,
                                   limit=5, score_cutoff=0)
            for _, score, idx in hits:
                _, orig, sid = corpus[idx]
                if sid not in best or score > best[sid]["score"]:
                    if sid in catalog_df["ID number"].values:
                        cat_r  = catalog_df[catalog_df["ID number"] == sid]
                        ctype  = cat_r.iloc[0]["type"] if not cat_r.empty else ""
                        name_r = safe_str(cat_r.iloc[0].get("Name RU", "")) if not cat_r.empty else ""
                        name_u = safe_str(cat_r.iloc[0].get("Name UZ", "")) if not cat_r.empty else ""
                        best[sid] = {
                            "service_id": sid,
                            "name_ru":    name_r,
                            "name_uz":    name_u,
                            "type":       ctype,
                            "score":      round(score),
                        }

    sorted_results = sorted(best.values(), key=lambda x: x["score"], reverse=True)
    return sorted_results[:3]


# ═══════════════════════════════════════════════════════════════════════════════
# MAIN MATCH FUNCTION
# ═══════════════════════════════════════════════════════════════════════════════
def match_service(
    clinic_name: str,
    corpus: list[tuple[str, str, str]],
    catalog_df: pd.DataFrame,
) -> dict:
    if not clinic_name:
        return _no_match()

    # Normalize mixed script before matching
    clinic_name = _normalize_mixed_script(clinic_name)
    matcher = _get_embedding_matcher()

    # ── Path A: Fine-tuned embedding model ────────────────────────────────────
    if matcher.loaded:
        candidates = matcher.search(clinic_name, k=3)

        candidates = [
            c for c in candidates
            if c["type"] in ALLOWED_CATALOG_TYPES
        ]

        if not candidates:
            return _no_match()

        best  = candidates[0]
        score = best["score"]

        if score < MIN_CONFIDENCE:
            return _no_match()

        sid = best["service_id"]

        if sid not in catalog_df["ID number"].values:
            return _no_match()

        cat_r   = catalog_df[catalog_df["ID number"] == sid]
        name_ru = safe_str(cat_r.iloc[0].get("Name RU", "")) if not cat_r.empty else best["name_ru"]
        name_uz = safe_str(cat_r.iloc[0].get("Name UZ", "")) if not cat_r.empty else best["name_uz"]
        display = name_ru or name_uz or best["name_ru"]
        label   = confidence_label(score)

        top3 = [
            {
                "service_id": c["service_id"],
                "name":       c["name_ru"] or c["name_uz"],
                "score":      c["score"],
                "type":       c["type"],
            }
            for c in candidates
        ]

        return {
            "matched_name":    display,
            "matched_id":      sid,
            "confidence":      score,
            "comment":         label,
            "top3_candidates": top3,
            "method":          "embedding",
        }

    # ── Path B: Fuzzy fallback ────────────────────────────────────────────────
    if not corpus:
        return _no_match()

    fuzzy_top3 = _fuzzy_top3(clinic_name, corpus, catalog_df)

    if not fuzzy_top3:
        return _no_match()

    best  = fuzzy_top3[0]
    score = best["score"]

    if score < MIN_CONFIDENCE:
        return _no_match()

    sid   = best["service_id"]
    label = confidence_label(score)

    cat_r   = catalog_df[catalog_df["ID number"] == sid]
    name_ru = safe_str(cat_r.iloc[0].get("Name RU", "")) if not cat_r.empty else ""
    name_uz = safe_str(cat_r.iloc[0].get("Name UZ", "")) if not cat_r.empty else ""
    display = name_ru or name_uz

    top3 = [
        {
            "service_id": c["service_id"],
            "name":       c["name_ru"] or c["name_uz"],
            "score":      c["score"],
            "type":       c["type"],
        }
        for c in fuzzy_top3
    ]

    return {
        "matched_name":    display,
        "matched_id":      sid,
        "confidence":      score,
        "comment":         label,
        "top3_candidates": top3,
        "method":          "fuzzy",
    }


def _no_match() -> dict:
    return {
        "matched_name":    "-",
        "matched_id":      "-",
        "confidence":      0,
        "comment":         "Не найдено",
        "top3_candidates": [],
        "method":          "none",
    }


# ═══════════════════════════════════════════════════════════════════════════════
# BATCH MATCHING  (used by app.py)
# ═══════════════════════════════════════════════════════════════════════════════
def match_all_services(services: list[dict], catalog_df: pd.DataFrame) -> list[dict]:
    corpus = build_search_corpus(catalog_df)
    rows   = []

    for svc in services:
        name     = clean_cell(svc.get("service_name", ""))
        price    = svc.get("price", "По запросу")
        svc_type = svc.get("type", "Диагностика")

        m = match_service(name, corpus, catalog_df)

        if m["matched_id"] != "-":
            cat_r = catalog_df[catalog_df["ID number"] == m["matched_id"]]
            if not cat_r.empty:
                ctype = cat_r.iloc[0].get("type", "").strip()
                if ctype in ALLOWED_CATALOG_TYPES:
                    svc_type = "Анализы" if ctype == "Анализ" else ctype

        # Build comment with top-2 alternatives for unmatched/low confidence
        comment = m["comment"]
        top3    = m.get("top3_candidates", [])
        if m["matched_id"] == "-" and len(top3) > 0:
            alts = "; ".join(
                f'{c["service_id"]} {c["name"][:30]} ({c["score"]}%)'
                for c in top3[:2]
                if c["score"] >= 55
            )
            if alts:
                comment = f'Не найдено | Варианты: {alts}'
        elif m["confidence"] < 75 and len(top3) > 1:
            alts = "; ".join(
                f'{c["service_id"]} ({c["score"]}%)'
                for c in top3[1:3]
                if c["score"] >= 60
            )
            if alts:
                comment = f'{m["comment"]} | Альт: {alts}'

        rows.append({
            "Название в MedPay":  m["matched_name"],
            "Название в клинике": name,
            "ID":                 m["matched_id"],
            "Уверенность":        m["confidence"],
            "Комментарий":        comment,
            "Цена":               price,
            "Тип услуг":          svc_type,
            "top3":               top3,
            "method":             m.get("method", ""),
        })

    return rows


def model_status() -> dict:
    m = _get_embedding_matcher()
    return {
        "loaded":     m.loaded,
        "error":      m.load_error,
        "model_dir":  str(_MODEL_DIR),
    }
