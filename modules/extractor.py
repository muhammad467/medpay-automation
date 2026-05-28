"""
extractor.py — HTML extraction with Med24-aware parsing.

Med24 URL-based category filtering (confirmed from med24.uz):
  KEEP:    /diagnostika/*   → Диагностика (УЗИ, МРТ, КТ, ЭКГ, Рентген, Эндоскопия...)
  KEEP:    /uslugi/analizy  → Анализы (кровь, моча, ПЦР, биохимия...)
  EXCLUDE: /uslugi/plasticheskaya-khirurgiya  → plastic surgery
  EXCLUDE: /uslugi/travmatologiya-ortopediya  → orthopedics/trauma
  EXCLUDE: /uslugi/ginekologiya               → gynecology procedures
  EXCLUDE: /uslugi/lor-otolaringologiya       → ENT procedures
  EXCLUDE: /uslugi/urologiya                  → urology procedures
  EXCLUDE: /uslugi/nevrologiya                → neurology procedures
  EXCLUDE: /uslugi/dermatologiya              → dermatology procedures
  EXCLUDE: /uslugi/gastroenterologiya         → gastroenterology procedures
  EXCLUDE: /uslugi/obshchie-protsedury        → general procedures
  EXCLUDE: /uslugi/vaktsinatsiya              → vaccinations
  EXCLUDE: /uslugi/andrologiya                → andrology
  EXCLUDE: /uslugi/mammologiya                → mammology procedures
  EXCLUDE: /uslugi/narkologiya                → narcology
  EXCLUDE: /uslugi/proktologiya               → proctology

Med24 page structure (confirmed by HTML inspection):
  Each service is a <div> with Tailwind classes:
    flex justify-between border-b gap-[15px] cursor-pointer
    border-[#F3F3F3] mb-[12px] pb-[12px] group
  Inside:
    - <a class="sm:block hidden ..." href="/diagnostika/uzi">SERVICE NAME</a>
    - <div class="hidden sm:flex ...">
        <p class="flex-shrink-0"><span>110 000 сум</span></p>
      </div>
"""
import re
from bs4 import BeautifulSoup
from modules.utils import clean_cell, clean_price

# ── Med24 CSS fingerprint ─────────────────────────────────────────────────────
MED24_ROW_REQUIRED = {
    "flex", "justify-between", "border-b",
    "gap-[15px]", "cursor-pointer",
    "border-[#F3F3F3]", "mb-[12px]", "pb-[12px]", "group",
}

# ── Med24 URL-based category rules ────────────────────────────────────────────
# Based on med24.uz site structure:
# /diagnostika/* = instrumental diagnostics → Диагностика
# /uslugi/analizy* = laboratory tests → Анализы
# Everything else (/uslugi/ginekologiya, /uslugi/plasticheskaya-khirurgiya etc.)
# = medical procedures/surgery → EXCLUDED from MedPay
MED24_DIAGNOSTIKA_PREFIX = "med24.uz/diagnostika"
MED24_ANALIZY_PREFIX     = "med24.uz/uslugi/analizy"

def _med24_category_from_href(href: str) -> str | None:
    """
    Returns 'Диагностика', 'Анализы', or None (exclude).
    None means this service belongs to a medical procedure category
    that is not allowed in MedPay (surgery, ENT, gynecology etc.)
    """
    if not href:
        return None
    h = href.lower()
    if MED24_DIAGNOSTIKA_PREFIX in h:
        return "Диагностика"
    if MED24_ANALIZY_PREFIX in h:
        return "Анализы"
    # /uslugi/* but not /uslugi/analizy = medical procedure → Лечебная процедура
    if "med24.uz/uslugi/" in h:
      return "Лечебная процедура"
    # Unknown URL - fall back to keyword classification
    return "UNKNOWN"


# ── Keyword-based type classification (fallback for non-Med24 pages) ──────────
_ANALYSIS_KW = [
    "анализ", "кровь", "моча", "кал", "мазок", "пцр", "pcr",
    "igg", "igm", "ige", "iga", "гормон", "антитела", "антитело",
    "биохимия", "бакпосев", "серология", "иммуноглоб", "цитология",
    "гематолог", "коагулограмм", "лейкоцит", "эритроцит",
    "тромбоцит", "гемоглобин", "билирубин", "холестерин",
    "глюкоз", "инсулин", "ферритин", "фолиевая", "витамин",
    "тиреотроп", "пролактин", "кортизол", "тестостерон",
    "эстрадиол", "прогестерон", "антиген",
    "вич", "гепатит", "сифилис", "герпес", "цитомегало",
    "токсоплазм", "хламидии", "микоплазм", "уреаплазм",
    "кандида", "трихомонад", "гонококк", "helicobacter",
    "anti-", "определение антител", "определение днк",
    "определение рнк", "методом пцр", "иммуноферм",
    "биоматериал", "бак посев", "посев",
]

_DIAGNOSTICS_KW = [
    "мрт", "кт ", "ктг", "узи", "рентген", "экг", "эхо",
    "эндоскопия", "гастроскопия", "колоноскопия", "допплер",
    "томография", "флюорограф", "маммограф", "денситометр",
    "сцинтиграф", "ангиограф", "артроскоп",
    "бронхоскоп", "цистоскоп", "кольпоскоп",
    "спирометр", "спирограф", "аудиометр",
    "офтальмоскоп", "электроэнцефалог", "ээг",
    "холтер", "велоэргометр", "стресс-тест",
    "импеданс", "тимпанометр", "нейросоногр",
    "эластограф", "допплерограф", "дуплексн",
]


# ── Keywords for services to EXCLUDE entirely (not Анализы or Диагностика) ────
# These are doctor visits, procedures, surgeries — not allowed in MedPay matching
_EXCLUDE_KW = [
    "консультация", "консультацию", "консультации",
    "приём", "прием", "прием врача",
    "осмотр", "осмотра",
    "врач", "врача",
    "хирург", "терапевт", "педиатр", "гинеколог", "уролог",
    "невролог", "кардиолог", "офтальмолог", "окулист",
    "лор", "отоларинголог", "дерматолог", "эндокринолог",
    "ортопед", "травматолог", "психиатр", "психолог",
    "нарколог", "онколог", "гематолог", "ревматолог",
    "вакцинация", "вакцинацию", "прививка", "прививку", "иммунизация",
    "капельница", "инъекция", "укол", "инфузия",
    "массаж", "физиотерапия", "физиолечение",
    "перевязка", "перевязку",
    "операция", "операции",
    "удаление", "иссечение", "резекция",
    "вскрытие", "дренирование",
    "лечение зубов", "пломбирование", "протезирование",
    "чистка зубов", "отбеливание",
]


def _is_excluded_service(name: str) -> bool:
    """
    Return True if this service should be excluded entirely —
    it is a врачебный приём, procedure, vaccination, etc.
    These are NOT Анализы or Диагностика.
    For Med24 pages this is handled by URL filtering.
    This function handles non-Med24 sources (table/generic parsers).
    """
    n = name.lower().strip()
    # Short names that are exactly a role (e.g. "Хирург", "Терапевт")
    for kw in _EXCLUDE_KW:
        # Word boundary check: "консультация" matches but "консультативный" does not
        if re.search(r'\b' + re.escape(kw) + r'\b', n):
            return True
    return False


def classify_type(name: str) -> str:
    """Classify service as Анализы or Диагностика based on keywords."""
    n = name.lower()
    for kw in _ANALYSIS_KW:
        if kw in n:
            return "Анализы"
    for kw in _DIAGNOSTICS_KW:
        if kw in n:
            return "Диагностика"
    return "Диагностика"


# ── Junk filters (for generic fallback parser) ────────────────────────────────
_JUNK_LOWER = [
    "официальный канал", "med24", "medion clinic",
    "г. ташкент", "узбекистан,", "100005,",
    "приём подтверждён", "одна из лучших",
    "лет стажа", "врач высшей категории",
]
_JUNK_MONTH_RE = re.compile(
    r"\b(января|февраля|марта|апреля|мая|июня|июля|августа"
    r"|сентября|октября|ноября|декабря)\s+202\d",
    re.IGNORECASE,
)


def _is_junk(name: str) -> bool:
    s = name.strip()
    if len(s) < 3:
        return True
    if s.lower() == "позвонить":
        return True
    if re.search(r"\+?998\s*\(?\d", s):
        return True
    if "ул." in s or "пер." in s:
        return True
    if re.search(r"дата:\s*\d{4}", s, re.IGNORECASE):
        return True
    if _JUNK_MONTH_RE.search(s):
        return True
    sl = s.lower()
    for j in _JUNK_LOWER:
        if j in sl:
            return True
    return False


# ── Price parsing ─────────────────────────────────────────────────────────────
def _parse_price(raw: str) -> str:
    t = raw.strip()
    if not t:
        return "По запросу"
    if "по запросу" in t.lower() or t in ("-", ""):
        return "По запросу"
    digits = re.sub(r"[^\d]", "", t)
    return digits if digits else "По запросу"


# ── Clinic info ───────────────────────────────────────────────────────────────
# District Russian → Latin mapping per spec
DISTRICT_MAP = {
    "яшнабадский":      "Yashnobod",
    "чиланзарский":     "Chilonzor",
    "юнусабадский":     "Yunusobod",
    "учтепинский":      "Uchtepa",
    "мирабадский":      "Mirobod",
    "яккасарайский":    "Yakkasaroy",
    "шайхантахурский":  "Shayxontohur",
    "олмазорский":      "Olmazor",
    "сергелийский":     "Sergeli",
    "янгихаётский":     "Yangihayot",
    "бектемирский":     "Bektemir",
    "мирзо-улугбекский":"Mirzo-Ulugbek",
    "мирзоулугбекский": "Mirzo-Ulugbek",
}


def _normalize_district(raw: str) -> str:
    """Map Russian district name to Latin. Returns original if not found."""
    if not raw:
        return raw
    lower = raw.lower().strip()
    for ru, lat in DISTRICT_MAP.items():
        if ru in lower:
            return lat
    return clean_cell(raw)


def extract_clinic_info(soup: BeautifulSoup, filename: str) -> tuple[str, str]:
    clinic_name = ""
    district = ""

    title = soup.find("title")
    if title:
        t = clean_cell(title.get_text())
        t = re.sub(r"\s*-\s*(цены|отзывы|запись).*$", "", t, flags=re.IGNORECASE).strip()
        parts = [p.strip() for p in t.split(",")]
        clinic_name = parts[0] if parts else t
        for p in parts[1:]:
            if any(kw in p.lower() for kw in ["район", "district", "тумани"]):
                district = _normalize_district(p.strip())
                break
        if not district and len(parts) > 1:
            district = _normalize_district(parts[1].strip())

    if not clinic_name:
        h1 = soup.find("h1")
        if h1:
            clinic_name = clean_cell(h1.get_text())

    og = soup.find("meta", property="og:site_name")
    if og and not clinic_name:
        clinic_name = clean_cell(og.get("content", ""))

    if not clinic_name:
        base = re.sub(r"\.(html?|htm)$", "", filename, flags=re.IGNORECASE)
        parts = base.split("_")
        clinic_name = clean_cell(parts[0]) if parts else base
        if len(parts) > 1:
            district = clean_cell(parts[1])

    # Strip * from clinic name
    clinic_name = clean_cell(clinic_name.strip().strip("*").strip())
    return clinic_name or "Клиника", district or "Основной"


# ── Strategy 1: Med24 structured parser ──────────────────────────────────────
def _extract_med24_structured(soup: BeautifulSoup) -> list[dict]:
    """
    Parse Med24 HTML using CSS fingerprint + URL-based category filtering.
    Only keeps services from /diagnostika/* and /uslugi/analizy.
    Excludes surgeries, ENT, gynecology, orthopedics and other procedures.
    """
    services = []
    seen: set[str] = set()
    excluded_count = 0

    for div in soup.find_all("div"):
        cls = set(div.get("class", []))
        if not MED24_ROW_REQUIRED.issubset(cls):
            continue

        # Get the anchor tag — it has the category URL
        name_a = div.find("a", class_=lambda c: c and "sm:block" in c)
        if not name_a:
            continue

        name = clean_cell(name_a.get_text(strip=True))
        if not name or len(name) < 2:
            continue

        # ── URL-based category filter ─────────────────────────────────────────
        href = name_a.get("href", "")
        category = _med24_category_from_href(href)

        if category is None:
          excluded_count += 1
          continue
# Лечебная процедура services are kept but will be filtered
# later in _run_matching if include_lech=False

        if category == "UNKNOWN":
            # Unknown URL format — use keyword fallback
            category = classify_type(name)

        # Deduplicate
        key = name.lower()
        if key in seen:
            continue
        seen.add(key)

        # Price
        price = "По запросу"
        price_container = div.find(
            "div", class_=lambda c: c and "sm:flex" in c and "hidden" in c
        )
        if price_container:
            price_p = price_container.find(
                "p", class_=lambda c: c and "flex-shrink-0" in c
            )
            if price_p:
                price = _parse_price(price_p.get_text(strip=True))

        services.append({
            "service_name": name,
            "type":  category,
            "price": price,
        })

    if services:
        print(f"[Med24 parser] Extracted: {len(services)} | Excluded (procedures): {excluded_count}")

    return services


# ── Strategy 2: Table parser ──────────────────────────────────────────────────
def _extract_from_tables(soup: BeautifulSoup) -> list[dict]:
    services = []
    seen: set[str] = set()

    for table in soup.find_all("table"):
        rows = table.find_all("tr")
        if not rows:
            continue
        headers = [clean_cell(th.get_text()) for th in rows[0].find_all(["th", "td"])]
        name_col  = _col_idx(headers, ["название", "услуга", "наименование", "name"])
        price_col = _col_idx(headers, ["цена", "стоимость", "price", "сум"])
        if name_col is None:
            continue
        for row in rows[1:]:
            cells = row.find_all(["td", "th"])
            if len(cells) <= name_col:
                continue
            name = clean_cell(cells[name_col].get_text())
            if not name or len(name) < 3 or _is_junk(name) or _is_excluded_service(name):
                continue
            name = _clean_name_fallback(name)
            if not name or _is_junk(name):
                continue
            key = name.lower()
            if key in seen:
                continue
            seen.add(key)
            price = "По запросу"
            if price_col is not None and len(cells) > price_col:
                price = _parse_price(clean_cell(cells[price_col].get_text()))
            services.append({"service_name": name, "type": classify_type(name), "price": price})

    return services


# ── Strategy 3: Generic price-text scan ──────────────────────────────────────
def _extract_generic(soup: BeautifulSoup) -> list[dict]:
    services = []
    seen: set[str] = set()
    price_re = re.compile(r"\d[\d\s]*(?:сум|руб|uzs)?", re.IGNORECASE)

    for tag in soup.find_all(["li", "div", "p", "tr", "span", "td"]):
        text = clean_cell(tag.get_text(" "))
        if len(text) < 4 or len(text) > 400:
            continue
        if not (bool(price_re.search(text)) or "по запросу" in text.lower()):
            continue
        name, price = _split_name_price(text)
        name = _clean_name_fallback(clean_cell(name))
        if not name or len(name) < 3 or _is_junk(name) or _is_excluded_service(name):
            continue
        key = name.lower()
        if key in seen:
            continue
        seen.add(key)
        services.append({"service_name": name, "type": classify_type(name), "price": price})

    return services


# ── Main entry point ──────────────────────────────────────────────────────────
def extract_services_from_html(
    content: bytes, filename: str
) -> tuple[str, str, list[dict]]:
    """
    Parse HTML and extract services.
    Returns (clinic_name, district, services).
    Each service: { service_name, type, price }
    """
    soup = BeautifulSoup(content, "lxml")
    clinic_name, district = extract_clinic_info(soup, filename)

    services = _extract_med24_structured(soup)
    if services:
        return clinic_name, district, services

    services = _extract_from_tables(soup)
    if services:
        return clinic_name, district, services

    return clinic_name, district, _extract_generic(soup)


# ── Helpers ───────────────────────────────────────────────────────────────────
def _col_idx(headers: list[str], keywords: list[str]) -> int | None:
    for i, h in enumerate(headers):
        for kw in keywords:
            if kw in h.lower():
                return i
    return None


def _clean_name_fallback(raw: str) -> str:
    """
    Clean corrupted service names from fallback parsers.
    'БеременностьБеременностьПозвонить150000' → 'Беременность'
    'Снятие гипсаСнятие гипсаПозвонить110000' → 'Снятие гипса'
    'AcAT - цена' → 'AcAT'
    """
    s = raw.strip()

    # Step 1: Find Позвонить marker and take everything before it
    for marker in ("Позвонить", "Позвон"):
        pos = s.find(marker)
        if pos > 5:
            before = s[:pos].strip()
            if len(before) >= 3:
                # Step 2: The text before marker is often duplicated: "НазваниеНазвание"
                # Find the shortest prefix that fully repeats
                before = _deduplicate_name(before)
                return before

    # Step 3: Remove trailing "- цена" or " цена"
    s = re.sub(r"\s*-\s*цена\s*$", "", s, flags=re.IGNORECASE).strip()
    s = re.sub(r"\s+цена\s*$", "", s, flags=re.IGNORECASE).strip()
    return s


def _deduplicate_name(text: str) -> str:
    """
    If text is a repeated string, return just the first half.
    'БеременностьБеременность' → 'Беременность'
    'Снятие гипсаСнятие гипса' → 'Снятие гипса'
    'Нормальное название' → 'Нормальное название' (unchanged)
    """
    n = len(text)
    if n < 6:
        return text
    # Try all split points from n//2 down to 2
    for split in range(n // 2, 1, -1):
        if text[:split] == text[split:split * 2]:
            return text[:split].strip()
    return text


def _split_name_price(text: str) -> tuple[str, str]:
    if "\t" in text:
        parts = text.split("\t")
        return clean_cell(parts[0]), _parse_price(parts[-1])
    m = re.search(r"([\d\s]{3,}(?:сум|руб|uzs)?)\s*$", text, re.IGNORECASE)
    if m:
        return clean_cell(text[: m.start()].strip(" :-–—")), _parse_price(m.group(1))
    m2 = re.search(r"(по запросу)\s*$", text, re.IGNORECASE)
    if m2:
        return clean_cell(text[: m2.start()].strip(" :-–—")), "По запросу"
    return clean_cell(text), "По запросу"
