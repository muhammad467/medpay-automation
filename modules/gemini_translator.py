"""
gemini_translator.py — Gemini 2.0 Flash for MedPay column generation
Generates specific, high-quality medical descriptions and requirements,
plus Uzbek Latin translations. Falls back gracefully if API unavailable.

Columns generated:
  Описание RU   — specific Russian description (2 sentences max)
  Описание UZ   — Uzbek Latin translation of Описание RU
  Требования RU — specific Russian requirements (specimen + preparation)
  Требования UZ — Uzbek Latin translation of Требования RU
  Имя UZ        — Uzbek Latin translation of clinic service name
"""
import os
import json
import re
import time

GEMINI_MODEL = "gemini-2.0-flash"
BATCH_SIZE   = 10  # services per API call

SYSTEM_PROMPT = """You are a medical content writer for MedPay, a healthcare platform in Uzbekistan.
For each medical service, generate precise, specific content — NOT generic templates.

Rules:
1. Описание RU: 1-2 sentences in Russian. Must be SPECIFIC to this exact test/procedure.
   - What does it measure/show? What clinical purpose does it serve?
   - NEVER start with the service name followed by a dash
   - NEVER use: "помогает оценить соответствующий показатель организма"
   - BAD: "Общий анализ крови — лабораторное исследование, которое помогает оценить соответствующий показатель..."
   - GOOD for ОАК: "Исследование позволяет оценить клеточный состав крови — количество эритроцитов, лейкоцитов и тромбоцитов, уровень гемоглобина и лейкоцитарную формулу."
   - GOOD for ТТГ: "Определяет уровень тиреотропного гормона гипофиза, регулирующего функцию щитовидной железы; используется для диагностики гипо- и гипертиреоза."
   - GOOD for УЗИ брюшной: "Ультразвуковое исследование позволяет визуализировать органы брюшной полости — печень, желчный пузырь, поджелудочную железу, селезёнку и почки — для выявления структурных изменений."

2. Описание UZ: Uzbek Latin translation of Описание RU. Natural medical Uzbek, not literal.

3. Требования RU: Specific preparation in Russian.
   - Always start with "Материал: [тип]."
   - Correct specimens: венозная кровь / капиллярная кровь / моча / кал / мазок / слюна / мокрота / эякулят
   - Include specific steps for THIS test
   - GOOD ТТГ: "Материал: венозная кровь. Натощак 8-12 часов. Утром до приёма гормонов щитовидной железы."
   - GOOD HbA1c: "Материал: венозная кровь. Специальной подготовки не требуется, можно сдавать в любое время."
   - GOOD ОАМ: "Материал: моча. Утренняя средняя порция в стерильный контейнер после гигиены."
   - GOOD УЗИ брюшной: "Натощак 4-6 часов. За 2-3 дня исключить газообразующие продукты."

4. Требования UZ: Uzbek Latin translation of Требования RU. Start with "Material: [turi]."

5. Имя UZ: Short natural Uzbek Latin name. Translate the clinic name properly.
   - Keep abbreviations: MRT, UZI, EKG, KT
   - GOOD: "Tireotrop gormon (TTG)", "Bosh miya MRT", "Umumiy qon tahlili"

Return ONLY a valid JSON array. No markdown. No explanation."""


def _call_gemini_batch(services: list, api_key: str) -> list:
    import urllib.request, urllib.error

    services_text = "\n".join([
        f"{i+1}. [{s['type']}] {s['name_ru']}"
        for i, s in enumerate(services)
    ])

    prompt = (f"Generate medical content for these {len(services)} services.\n"
              f"Return a JSON array with exactly {len(services)} objects.\n"
              f'Each object: {{"name_uz":"...","desc_ru":"...","desc_uz":"...","req_ru":"...","req_uz":"..."}}\n\n'
              f"Services:\n{services_text}")

    url = (f"https://generativelanguage.googleapis.com/v1beta/models/"
           f"{GEMINI_MODEL}:generateContent?key={api_key}")

    body = json.dumps({
        "system_instruction": {"parts": [{"text": SYSTEM_PROMPT}]},
        "contents": [{"parts": [{"text": prompt}]}],
        "generationConfig": {"temperature": 0.15, "responseMimeType": "application/json"},
    }, ensure_ascii=False).encode("utf-8")

    req = urllib.request.Request(
        url, data=body,
        headers={"Content-Type": "application/json"},
        method="POST"
    )

    try:
        with urllib.request.urlopen(req, timeout=45) as resp:
            data   = json.loads(resp.read())
            text   = data["candidates"][0]["content"]["parts"][0]["text"]
            text   = re.sub(r"```json\s*|\s*```", "", text).strip()
            result = json.loads(text)
            if isinstance(result, list):
                while len(result) < len(services):
                    result.append({})
                return result[:len(services)]
    except urllib.error.HTTPError as e:
        print(f"[gemini] HTTP {e.code}: {e.read().decode('utf-8','ignore')[:200]}")
    except Exception as e:
        print(f"[gemini] Error: {e}")
    return []


def translate_services_batch(services: list, api_key: str, progress_callback=None) -> dict:
    """
    Translate services in batches of 10 using Gemini 2.0 Flash.
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
            time.sleep(0.15)

    return results
