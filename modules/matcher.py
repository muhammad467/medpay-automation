"""
matcher.py — Cascade matching engine v2.0

Priority:
  1. Fine-tuned sentence-transformers model + FAISS  (primary)
  2. RapidFuzz fuzzy matching                        (fallback if model not loaded)

Confidence labels (always assigned, ID always returned):
  ≥ 90%  → "Высокая уверенность"       — safe to use, still verify name
  75–89% → "Хорошее совпадение"         — spot-check recommended
  60–74% → "Проверить вручную"          — show to human, likely correct
  < 60%  → "Требует проверки"           — show to human, may be wrong

Key rule: ID is ALWAYS assigned if a match is found (even at 30%).
          Human always sees the matched name and decides.
          The comment field tells them how confident to be.

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
# below 70   →     no ID assigned

# ── Query expansion — from Notebook 2 session report ─────────────────────────
# Essential for short abbreviations: АСТ, ТТГ, ОАК etc.
_EXPAND_MAP = {
    # Lab abbreviations
    "АСТ":    "АСТ аспартатаминотрансфераза",
    "АЛТ":    "АЛТ аланинаминотрансфераза",
    "АЛАТ":   "АЛАТ аланинаминотрансфераза",
    "АСАТ":   "АСАТ аспартатаминотрансфераза",
    "ЛДГ":    "ЛДГ лактатдегидрогеназа",
    "ГГТ":    "ГГТ гамма-глутамилтранспептидаза",
    "ЩФ":     "ЩФ щелочная фосфатаза",
    "КФК":    "КФК креатинфосфокиназа",
    "КК":     "КК креатинкиназа",
    "СРБ":    "СРБ С-реактивный белок",
    "РФ":     "РФ ревматоидный фактор",
    "ПСА":    "ПСА простатический специфический антиген",
    "ТТГ":    "ТТГ тиреотропный гормон",
    "TSH":    "ТТГ тиреотропный гормон TSH",
    "Т3":     "Т3 трийодтиронин",
    "Т4":     "Т4 тироксин",
    "ЛГ":     "ЛГ лютеинизирующий гормон",
    "ФСГ":    "ФСГ фолликулостимулирующий гормон",
    "АМГ":    "АМГ антимюллеров гормон",
    "ДГЭА":   "ДГЭА дегидроэпиандростерон",
    "ДЭА":    "ДЭА дегидроэпиандростерон",
    "DHEA":   "DHEA дегидроэпиандростерон",
    "ГТТ":    "ГТТ глюкозотолерантный тест",
    "ПЦР":    "ПЦР полимеразная цепная реакция",
    "ИФА":    "ИФА иммуноферментный анализ",
    "ЛПВП":   "ЛПВП липопротеины высокой плотности",
    "ЛПНП":   "ЛПНП липопротеины низкой плотности",
    "ХС":     "ХС холестерин",
    "ОАК":    "ОАК общий анализ крови",
    "ОАМ":    "ОАМ общий анализ мочи",
    "СОЭ":    "СОЭ скорость оседания эритроцитов",
    "HbsAg":  "HbsAg антиген гепатита B поверхностный",
    "HBsAg":  "HBsAg антиген гепатита B поверхностный",
    "HIV":    "HIV ВИЧ антитела",
    "ВИЧ":    "ВИЧ антитела иммунодефицит",
    # Imaging abbreviations
    "МРТ":    "МРТ магнитно-резонансная томография",
    "КТ":     "КТ компьютерная томография",
    "МСКТ":   "МСКТ мультиспиральная компьютерная томография",
    "УЗИ":    "УЗИ ультразвуковое исследование",
    "ЭКГ":    "ЭКГ электрокардиограмма",
    "ЭЭГ":    "ЭЭГ электроэнцефалограмма",
    "ЭМГ":    "ЭМГ электромиограмма",
    "ЭХОКГ":  "ЭХОКГ эхокардиография",
    "ФГС":    "ФГС фиброгастроскопия",
    "ФГДС":   "ФГДС фиброгастродуоденоскопия",
    "ЭГДС":   "ЭГДС эзофагогастродуоденоскопия",
    "КТГ":    "КТГ кардиотокография",
    # ── Abbreviations from Hilol Hospital analysis ──────────────────────────
    "АЦЦП":       "АЦЦП антитела к циклическому цитруллинированному пептиду",
    "АКТГ":       "АКТГ адренокортикотропный гормон",
    "ПТИ":        "ПТИ протромбиновый индекс протромбин",
    "ХОЛТЕР":     "ХОЛТЕР суточное мониторирование ЭКГ сердца",
    "НСГ":        "НСГ нейросонография головного мозга",
    "ТКДГ":       "ТКДГ транскраниальная допплерография",
    "ANA":        "ANA антинуклеарные антитела",
    "Anti-dsDNA": "Anti-dsDNA антитела к двуспиральной ДНК волчанка",
    "ENA":        "ENA антитела к ядерным антигенам",
    "ЛПОНП":      "ЛПОНП липопротеины очень низкой плотности",
    "Вич":        "ВИЧ антитела иммунодефицит HIV",
    "Covid":      "Covid SARS-CoV коронавирус COVID-19",
    "covid":      "covid SARS-CoV коронавирус COVID-19",
    "COVID":      "COVID SARS-CoV коронавирус COVID-19",
    "HBsAg":      "HBsAg поверхностный антиген гепатита B",
    "HbsAg":      "HbsAg поверхностный антиген гепатита B",
    "МНО":        "МНО международное нормализованное отношение коагуляция",
    "СМАД":       "СМАД суточное мониторирование артериального давления",
    "ПТГ":        "ПТГ паратиреоидный гормон паратгормон",
    "СТГ":        "СТГ соматотропный гормон гормон роста",
    "ХГЧ":        "ХГЧ хорионический гонадотропин беременность",
    "АФП":        "АФП альфа-фетопротеин онкомаркер",
    "РЭА":        "РЭА раково-эмбриональный антиген",
    "ОЖСС":       "ОЖСС железосвязывающая способность сыворотки",
    # ── Uzbek Latin medical terms → Russian equivalents ─────────────────────
    # These handle clinics that enter service names in Uzbek
    "Albumin":         "альбумин белок сыворотка",
    "Globulin":        "глобулин белок",
    "Karbamid":        "карбамид мочевина",
    "Kreatinin":       "креатинин",
    "Triglitseridlar": "триглицериды",
    "Xolesterin":      "холестерин",
    "Glyukoza":        "глюкоза сахар",
    "Bilirubin":       "билирубин",
    "Ferritin":        "ферритин",
    "Gemoglobin":      "гемоглобин",
    "Fosfor":          "фосфор",
    "Magniy":          "магний",
    "Kaliy":           "калий",
    "Natriy":          "натрий",
    "Kaltsiy":         "кальций",
    "Xlor":            "хлор хлориды",
    "Temir":           "железо сывороточное",
    "Sink":            "цинк",
    "Mis":             "медь",
    "Seruloplazmin":   "церулоплазмин",
    "Sistatin":        "цистатин",
    "Homosistein":     "гомоцистеин",
    "Xolinesteraza":   "холинэстераза",
    "Kalsitonin":      "кальцитонин",
    "Osteokalsin":     "остеокальцин",
    "Gialuron":        "гиалуроновая кислота",
    "Tsh":             "ТТГ тиреотропный гормон",
    "TSh":             "ТТГ тиреотропный гормон",
    "Tiroglobulin":    "тиреоглобулин",
    "Kortizol":        "кортизол",
    "Testosteron":     "тестостерон",
    "Estradiol":       "эстрадиол",
    "Estriol":         "эстриол",
    "Progesteron":     "прогестерон",
    "Prolaktin":       "пролактин",
    "Inhibin":         "ингибин",
    "Insulin":         "инсулин",
    "Mikroalbumin":    "микроальбумин",
    "Koprogramma":     "копрограмма",
    "Gelmint":         "гельминты яйца глистов",
    "gelmint":         "гельминты яйца глистов",
    "Najas":           "кал фекалии",
    "najas":           "кал фекалии",
    "Disbiyoz":        "дисбиоз дисбактериоз кишечника",
    "Protrombin":      "протромбин коагуляция",
    "Fibrinogen":      "фибриноген",
    "Koagulograma":    "коагулограмма",
    "Immunoglobulin":  "иммуноглобулин",
    "Antikor":         "антитела",
    "antikor":         "антитела",
    "Antikorlar":      "антитела",
    "UZD":             "УЗИ ультразвуковое исследование",
    "uzd":             "УЗИ ультразвуковое исследование",
    "Ultratovush":     "ультразвуковое исследование УЗИ",
    "ultratovush":     "ультразвуковое исследование УЗИ",
    "Doppler":         "допплерография",
    "doppler":         "допплерография",
    "Dupleks":         "дуплексное сканирование",
    "Elastografiya":   "эластография",
    "Jigar":           "печень",
    "jigar":           "печень",
    "Buyrak":          "почка почки",
    "buyrak":          "почка почки",
    "Taloq":           "селезёнка",
    "Qalqonsimon":     "щитовидная железа",
    "qalqonsimon":     "щитовидная железа",
    "Bachadon":        "матка",
    "bachadon":        "матка",
    "Prostata":        "простата предстательная железа",
    "prostata":        "простата предстательная железа",
    "Oshqozon":        "желудок",
    "Skrotum":         "мошонка",
    "Limfa":           "лимфатические узлы",
    "PCR":             "ПЦР полимеразная цепная реакция",
    "Gepatit":         "гепатит",
    "gepatit":         "гепатит",
    "Qon":             "кровь анализ крови",
    "Eritrotsit":      "эритроциты",
    "Leykosit":        "лейкоциты",
    "Trombotsit":      "тромбоциты",
    "Allergopanel":    "аллергопанель аллергены",
    "allergopanel":    "аллергопанель аллергены",
    "Neyrosonografiya": "нейросонография НСГ головной мозг",
    "Fibroskanatsiya": "фибросканирование эластометрия",
    "Siydik":          "моча мочи",
    "siydik":          "моча мочи",
    "Kalprotektin":    "кальпротектин",
    "Sil":             "туберкулёз QuantiFERON",
    "Giardia":         "лямблии гиардия",
    "giardia":         "лямблии гиардия",
    "Reberg":          "проба Реберга клиренс креатинина",
    "Qorin":           "брюшная полость живот",
    "qorin":           "брюшная полость живот",
    "Yurak":           "сердце кардио",
    "yurak":           "сердце кардио",
    "Sut":             "молочная железа грудь",
    "Simfiz":          "лонное сочленение симфиз",
    "Timus":           "тимус вилочковая железа",
    "Aorta":           "аорта",
    "aorta":           "аорта",
}

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
]
_NOISE_RE = re.compile("|".join(_NOISE_PATTERNS), re.IGNORECASE)


# ═══════════════════════════════════════════════════════════════════════════════
# MODEL ENGINE  (fine-tuned sentence-transformers + FAISS)
# ═══════════════════════════════════════════════════════════════════════════════
class EmbeddingMatcher:
    """
    Loads the fine-tuned model and FAISS index once.
    Provides fast top-k search against the catalog.
    """
    def __init__(self):
        self.model      = None
        self.index      = None
        self.meta       = None   # list of {service_id, name_ru, name_uz, type}
        self.loaded     = False
        self.load_error = ""

    def load(self, model_dir: Path) -> bool:
        """Try to load model + index. Returns True on success."""
        try:
            import faiss
            from sentence_transformers import SentenceTransformer

            model_path = model_dir / "model"
            faiss_path = model_dir / "catalog.faiss"
            meta_path  = model_dir / "catalog_meta.json"

            if not model_path.exists() or not faiss_path.exists() or not meta_path.exists():
                # Try HuggingFace Hub (for Streamlit Cloud deployment)
                return self._try_load_from_hf()

            self.model = SentenceTransformer(str(model_path))
            self.index = faiss.read_index(str(faiss_path))

            with open(meta_path, encoding="utf-8") as f:
                self.meta = json.load(f)

            self.loaded = True
            return True

        except ImportError as e:
            self.load_error = f"Missing package: {e}. Run: pip install sentence-transformers faiss-cpu"
            return False
        except Exception as e:
            self.load_error = f"Load error: {e}"
            return False

    def _try_load_from_hf(self) -> bool:
        """Try loading model from HuggingFace Hub (Streamlit Cloud fallback)."""
        try:
            import faiss, os
            from sentence_transformers import SentenceTransformer
            from huggingface_hub import snapshot_download, hf_hub_download

            HF_REPO  = "admin11011/medpay-matcher"
            hf_token = os.environ.get("HF_TOKEN")
            local_dir = "/tmp/medpay_model"
            os.makedirs(local_dir, exist_ok=True)

            print(f"[matcher] Loading from HuggingFace: {HF_REPO}")
            snapshot_download(repo_id=HF_REPO, token=hf_token,
                              ignore_patterns=["catalog.faiss", "catalog_meta.json"],
                              local_dir=local_dir)
            self.model = SentenceTransformer(local_dir)

            faiss_local = hf_hub_download(repo_id=HF_REPO, filename="catalog.faiss",
                                          token=hf_token, local_dir=local_dir)
            self.index = faiss.read_index(faiss_local)

            meta_local = hf_hub_download(repo_id=HF_REPO, filename="catalog_meta.json",
                                         token=hf_token, local_dir=local_dir)
            with open(meta_local, encoding="utf-8") as f:
                self.meta = json.load(f)

            self.loaded = True
            print("[matcher] Loaded from HuggingFace successfully")
            return True
        except Exception as e:
            self.load_error = f"HF load error: {e}"
            return False

    def search(self, query: str, k: int = 3) -> list[dict]:
        """
        Search catalog for top-k matches.
        Returns list of {service_id, name_ru, name_uz, type, score}
        score is 0-100 (cosine similarity × 100).
        """
        if not self.loaded:
            return []

        # E5 model requires "query: " prefix for search queries
        expanded = "query: " + expand_query(query)
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


# Singleton — loaded once when matcher is first used
_embedding_matcher = EmbeddingMatcher()
_model_load_attempted = False


def _get_embedding_matcher() -> EmbeddingMatcher:
    """Load model on first use, return singleton."""
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
    """
    Expand abbreviations token by token.
    'АСТ' → 'АСТ аспартатаминотрансфераза'
    'ТТГ (TSH)' → 'ТТГ тиреотропный гормон TSH ТТГ тиреотропный гормон'
    """
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
    """Normalize for fuzzy matching (lowercase + noise strip + expand)."""
    t = text.lower().strip()
    t = _NOISE_RE.sub(" ", t)
    t = re.sub(r"\s+", " ", t).strip()
    # Expand abbreviations
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
    """
    Human-readable label based on score.
    All matches get an ID — the label tells the human how carefully to check.
    """
    if score >= LABEL_HIGH:
        return "Высокая уверенность"
    if score >= LABEL_GOOD:
        return "Хорошее совпадение"
    if score >= LABEL_CHECK:
        return "Проверить вручную"
    return "Требует проверки"


def confidence_color(score: float) -> str:
    """CSS color hint for UI."""
    if score >= LABEL_HIGH:  return "green"
    if score >= LABEL_GOOD:  return "orange"
    if score >= LABEL_CHECK: return "red"
    return "darkred"


# ═══════════════════════════════════════════════════════════════════════════════
# FUZZY FALLBACK ENGINE
# ═══════════════════════════════════════════════════════════════════════════════
def build_search_corpus(catalog_df: pd.DataFrame) -> list[tuple[str, str, str]]:
    """Build (normalized_name, original_name, id) for fuzzy fallback."""
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
    """Return top-3 matches using RapidFuzz."""
    norm_q    = _normalize_fuzzy(query)
    norm_q_ns = _normalize_fuzzy(_strip_noise(query))
    corp_norms = [c[0] for c in corpus]

    best: dict[str, dict] = {}   # service_id → best result

    for q in list({norm_q, norm_q_ns}):
        for scorer in [fuzz.token_sort_ratio, fuzz.token_set_ratio, fuzz.partial_ratio]:
            hits = process.extract(q, corp_norms, scorer=scorer,
                                   limit=5, score_cutoff=0)
            for _, score, idx in hits:
                _, orig, sid = corpus[idx]
                if sid not in best or score > best[sid]["score"]:
                    # Verify ID is valid
                    if sid in catalog_df["ID number"].values:
                        cat_r  = catalog_df[catalog_df["ID number"] == sid]
                        ctype  = cat_r.iloc[0]["type"] if not cat_r.empty else ""
                        name_r = safe_str(cat_r.iloc[0].get("Name RU","")) if not cat_r.empty else ""
                        name_u = safe_str(cat_r.iloc[0].get("Name UZ","")) if not cat_r.empty else ""
                        best[sid] = {
                            "service_id": sid,
                            "name_ru":    name_r,
                            "name_uz":    name_u,
                            "type":       ctype,
                            "score":      round(score),
                        }

    # Return top-3 sorted by score
    sorted_results = sorted(best.values(), key=lambda x: x["score"], reverse=True)
    return sorted_results[:3]


# ═══════════════════════════════════════════════════════════════════════════════
# MAIN MATCH FUNCTION
# ═══════════════════════════════════════════════════════════════════════════════
def match_service(
    clinic_name: str,
    corpus: list[tuple[str, str, str]],   # fuzzy corpus (always passed for fallback)
    catalog_df: pd.DataFrame,
) -> dict:
    """
    Match a clinic service name to the catalog.

    Returns:
        matched_name:    best match catalog name (RU)
        matched_id:      catalog ID (always set if any match found)
        confidence:      0-100 score
        comment:         human-readable label
        top3_candidates: list of top-3 {service_id, name_ru, score, type}
    """
    if not clinic_name:
        return _no_match()

    matcher = _get_embedding_matcher()

    # ── Path A: Fine-tuned embedding model ────────────────────────────────────
    if matcher.loaded:
        candidates = matcher.search(clinic_name, k=3)

        # Filter to allowed types
        candidates = [
            c for c in candidates
            if c["type"] in ALLOWED_CATALOG_TYPES
        ]

        if not candidates:
            return _no_match()

        best  = candidates[0]
        score = best["score"]

        # Block low-confidence matches — no ID assigned below 70%
        if score < MIN_CONFIDENCE:
            return _no_match()

        sid = best["service_id"]

        # Always verify ID exists in catalog
        if sid not in catalog_df["ID number"].values:
            return _no_match()

        # Get full catalog row for name
        cat_r    = catalog_df[catalog_df["ID number"] == sid]
        name_ru  = safe_str(cat_r.iloc[0].get("Name RU", "")) if not cat_r.empty else best["name_ru"]
        name_uz  = safe_str(cat_r.iloc[0].get("Name UZ", "")) if not cat_r.empty else best["name_uz"]
        display  = name_ru or name_uz or best["name_ru"]

        label    = confidence_label(score)

        # Format top-3 for UI display
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

    # Block low-confidence matches — no ID assigned below 70%
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
    """
    Match a list of extracted clinic services to the catalog.
    Returns list of matching rows ready for the review table.
    """
    corpus = build_search_corpus(catalog_df)  # built once, used for fuzzy fallback
    rows   = []

    for svc in services:
        name     = clean_cell(svc.get("service_name", ""))
        price    = svc.get("price", "По запросу")
        svc_type = svc.get("type", "Диагностика")

        m = match_service(name, corpus, catalog_df)

        # Use catalog type if matched (overrides extracted type)
        if m["matched_id"] != "-":
            cat_r = catalog_df[catalog_df["ID number"] == m["matched_id"]]
            if not cat_r.empty:
                ctype = cat_r.iloc[0].get("type", "").strip()
                if ctype in ALLOWED_CATALOG_TYPES:
                    # Normalize: catalog uses "Анализ", app uses "Анализы"
                    svc_type = "Анализы" if ctype == "Анализ" else ctype

        rows.append({
            "Название в MedPay":  m["matched_name"],
            "Название в клинике": name,
            "ID":                 m["matched_id"],
            "Уверенность":        m["confidence"],
            "Комментарий":        m["comment"],
            "Цена":               price,
            "Тип услуг":          svc_type,
            "top3":               m.get("top3_candidates", []),
            "method":             m.get("method", ""),
        })

    return rows


def model_status() -> dict:
    """Return info about the loaded model for display in UI."""
    m = _get_embedding_matcher()
    return {
        "loaded":     m.loaded,
        "error":      m.load_error,
        "model_dir":  str(_MODEL_DIR),
    }
