import re


def clean_cell(value) -> str:
    """Strip spaces, normalize internal whitespace, remove line breaks."""
    if value is None:
        return ""
    value = str(value)
    if value.strip().lower() in ("nan", "none", ""):
        return ""
    value = value.replace("\r\n", " ").replace("\n", " ").replace("\r", " ")
    value = re.sub(r"\s+", " ", value)
    return value.strip()


def clean_price(raw: str) -> str:
    """
    Extract numeric price or return 'По запросу'.
    '350 000 сум' → '350000'
    'от 150 000 сум' → '150000'
    'Цена по запросу' → 'По запросу'
    """
    if not raw:
        return "По запросу"
    raw = str(raw).strip()
    lower = raw.lower()
    if "по запросу" in lower or "цена" in lower and re.search(r"[a-zа-яё]", lower.replace("цена", "")):
        return "По запросу"
    if re.search(r"\d", raw):
        digits = re.sub(r"[^\d]", "", raw)
        if digits:
            return digits
    return "По запросу"


def safe_str(value) -> str:
    """Convert to string, return empty string for nan/None."""
    if value is None:
        return ""
    s = str(value).strip()
    if s.lower() in ("nan", "none"):
        return ""
    return s


# ── Uzbek Latin → Cyrillic transliteration ────────────────────────────────────
def uz_latin_to_cyrillic(text: str) -> str:
    """
    Convert Latin-script Uzbek (Name UZ) to Cyrillic-script Uzbek (Name KR).
    Used when catalog has empty Name KR but has Name UZ.
    """
    if not text or text.strip() in ("", "-"):
        return text
    MULTI = [
        ("o'", "ў"), ("O'", "Ў"), ("g'", "ғ"), ("G'", "Ғ"),
        ("a'", "аъ"), ("A'", "Аъ"),
        ("ch", "ч"), ("Ch", "Ч"), ("CH", "Ч"),
        ("sh", "ш"), ("Sh", "Ш"), ("SH", "Ш"),
        ("ng", "нг"),
        ("ts", "ц"), ("Ts", "Ц"), ("TS", "Ц"),
        ("yo", "ё"), ("Yo", "Ё"),
        ("yu", "ю"), ("Yu", "Ю"),
        ("ya", "я"), ("Ya", "Я"),
        ("ye", "е"), ("Ye", "Е"),
        ("gh", "ғ"), ("Gh", "Ғ"),
    ]
    SINGLE = {
        "a":"а","b":"б","d":"д","f":"ф","g":"г","h":"ҳ",
        "i":"и","j":"ж","k":"к","l":"л","m":"м","n":"н",
        "o":"о","p":"п","q":"қ","r":"р","s":"с","t":"т",
        "u":"у","v":"в","x":"х","y":"й","z":"з","e":"е",
        "A":"А","B":"Б","D":"Д","F":"Ф","G":"Г","H":"Ҳ",
        "I":"И","J":"Ж","K":"К","L":"Л","M":"М","N":"Н",
        "O":"О","P":"П","Q":"Қ","R":"Р","S":"С","T":"Т",
        "U":"У","V":"В","X":"Х","Y":"Й","Z":"З","E":"Э",
    }
    result = []
    i = 0
    prev_alpha = False
    while i < len(text):
        matched = False
        for lat, cyr in MULTI:
            if text[i:i+len(lat)] == lat:
                result.append(cyr)
                i += len(lat)
                prev_alpha = True
                matched = True
                break
        if not matched:
            ch = text[i]
            if ch in ("e", "E") and not prev_alpha:
                result.append("э" if ch == "e" else "Э")
            else:
                result.append(SINGLE.get(ch, ch))
            prev_alpha = ch.isalpha()
            i += 1
    return "".join(result)
