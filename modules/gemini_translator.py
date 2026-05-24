"""
gemini_translator.py — Gemini 2.0 Flash for MedPay column generation
Generates specific, high-quality medical descriptions and requirements.
"""
import json, re, time

GEMINI_MODEL = "gemini-2.0-flash"
BATCH_SIZE   = 5

SYSTEM_PROMPT = """You are writing short medical service descriptions for a healthcare marketplace in Uzbekistan.

OUTPUT FORMAT: Return ONLY a JSON array. No markdown. No explanation.

For each service generate:
- name_uz: Short Uzbek Latin translation of the service name (NOT transliteration, proper translation)
- desc_ru: ONE sentence in Russian. State what this test/procedure reveals or measures. Be specific.
- desc_uz: Uzbek Latin translation of desc_ru
- req_ru: Requirements in Russian. Start with "Материал: [тип]." Then 1-2 specific preparation steps.
- req_uz: Uzbek Latin translation of req_ru. Start with "Material: [turi]."

STRICT RULES:
1. desc_ru must NEVER contain: "помогает оценить соответствующий показатель", "лабораторное исследование, которое"
2. desc_ru must say WHAT the test measures and WHY it is done
3. req_ru must specify the CORRECT material type: венозная кровь / моча / кал / мазок / эякулят / слюна
4. Keep all text SHORT and PRACTICAL

EXAMPLES OF GOOD OUTPUT:
- ОАК → desc_ru: "Определяет количество эритроцитов, лейкоцитов, тромбоцитов и уровень гемоглобина для оценки общего состояния крови."
- ТТГ → desc_ru: "Измеряет уровень тиреотропного гормона для диагностики заболеваний щитовидной железы."
- УЗИ брюшной полости → desc_ru: "Визуализирует печень, желчный пузырь, поджелудочную железу и почки для выявления структурных изменений."
- Аллерген арахис IgE → desc_ru: "Определяет уровень специфических IgE-антител к арахису для диагностики пищевой аллергии."
- ОАМ → req_ru: "Материал: моча. Собрать утреннюю среднюю порцию в стерильный контейнер после гигиены."
- ТТГ → req_ru: "Материал: венозная кровь. Натощак 8-12 часов, утром до приёма гормональных препаратов."
- Спермограмма → req_ru: "Материал: эякулят. Воздержание 3-5 дней, сбор в стерильный контейнер."

Return array of exactly N objects."""


def _call_gemini_batch(services: list, api_key: str, retries: int = 3) -> list:
    services_text = "\n".join([
        f"{i+1}. [{s['type']}] {s['name_ru']}"
        for i, s in enumerate(services)
    ])

    prompt = (
        f"Generate medical content for these {len(services)} services.\n"
        f"Return JSON array with exactly {len(services)} objects.\n"
        f'Each: {{"name_uz":"...","desc_ru":"...","desc_uz":"...","req_ru":"...","req_uz":"..."}}\n\n'
        f"Services:\n{services_text}"
    )

    for attempt in range(retries):
        try:
            import google.generativeai as genai
            genai.configure(api_key=api_key)
            model = genai.GenerativeModel(
                model_name=GEMINI_MODEL,
                system_instruction=SYSTEM_PROMPT,
                generation_config=genai.GenerationConfig(
                    temperature=0.1,
                    response_mime_type="application/json",
                )
            )
            response = model.generate_content(prompt)
            text = response.text
            text = re.sub(r"```json\s*|\s*```", "", text).strip()
            result = json.loads(text)
            if isinstance(result, list):
                while len(result) < len(services):
                    result.append({})
                return result[:len(services)]
        except Exception as e:
            err_str = str(e)
            if "429" in err_str or "quota" in err_str.lower():
                wait = 30 * (attempt + 1)
                print(f"[gemini] Rate limit, waiting {wait}s...")
                time.sleep(wait)
            else:
                print(f"[gemini] Error (attempt {attempt+1}): {err_str[:200]}")
                if attempt < retries - 1:
                    time.sleep(5)
    return []


def translate_services_batch(services: list, api_key: str, progress_callback=None) -> dict:
    """
    Translate services in batches of 5 using Gemini 2.0 Flash.
    Returns dict: name_ru -> {name_uz, desc_ru, desc_uz, req_ru, req_uz} or None on failure.
    """
    results = {}
    total   = len(services)

    for i in range(0, total, BATCH_SIZE):
        batch        = services[i:i + BATCH_SIZE]
        translations = _call_gemini_batch(batch, api_key)

        if translations:
            for svc, trans in zip(batch, translations):
                results[svc["name_ru"]] = {
                    "name_uz": trans.get("name_uz", ""),
                    "desc_ru": trans.get("desc_ru", ""),
                    "desc_uz": trans.get("desc_uz", ""),
                    "req_ru":  trans.get("req_ru",  ""),
                    "req_uz":  trans.get("req_uz",  ""),
                }
        else:
            for svc in batch:
                results[svc["name_ru"]] = None

        if progress_callback:
            progress_callback(min(i + BATCH_SIZE, total), total)

        if i + BATCH_SIZE < total:
            time.sleep(1.0)

    return results
