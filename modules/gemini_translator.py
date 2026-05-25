"""
gemini_translator.py — Gemini 2.0 Flash for MedPay column generation
Generates patient-friendly descriptions and proper requirements.
"""
import json, re, time

GEMINI_MODEL = "gemini-2.0-flash"
BATCH_SIZE   = 5

SYSTEM_PROMPT = """You are a Senior Medical Data Entry and Localization Specialist for MedPay, a healthcare marketplace in Uzbekistan.

Your task: For each medical service, generate multilingual content for a patient-facing database.

LANGUAGES: Russian (RU), Uzbek Latin (UZ), Uzbek Cyrillic (KR)

OUTPUT RULES:

1. name_uz: Short, natural Uzbek Latin translation of the service name.
   - Translate properly, do NOT transliterate
   - Keep abbreviations: MRT, UZI, EKG, KT
   - Example: "Общий анализ крови" → "Umumiy qon tahlili"

2. desc_ru: 2-3 patient-friendly sentences in Russian.
   - Sentence 1: What is this test/procedure?
   - Sentence 2: What does it reveal or measure?
   - Sentence 3: Why is it needed / when is it prescribed?
   - NEVER use: "помогает оценить соответствующий показатель организма"
   - GOOD: "Общий анализ крови — это базовое лабораторное исследование, которое определяет количество и качество клеток крови. Он показывает уровень гемоглобина, лейкоцитов, тромбоцитов и эритроцитов. Назначается для диагностики анемии, воспалительных процессов и общей оценки состояния здоровья."
   - GOOD: "ТТГ (тиреотропный гормон) — анализ крови, который оценивает работу щитовидной железы. Повышенный или пониженный уровень ТТГ указывает на гипотиреоз или гипертиреоз. Назначается при симптомах усталости, набора веса, выпадения волос или нарушениях менструального цикла."

3. desc_uz: Uzbek Latin translation of desc_ru. Natural, patient-friendly.

4. req_ru: Specific preparation instructions in Russian.
   - MUST start with: "Материал: [тип материала]."
   - Material types: венозная кровь / капиллярная кровь / моча / кал / мазок / эякулят / слюна / мокрота
   - Include preparation steps specific to THIS test
   - If no prep needed: "Материал: [тип]. Специальной подготовки не требуется."
   - GOOD ТТГ: "Материал: венозная кровь. Сдавать натощак (8–12 часов голодания). Утром до приёма гормональных препаратов и йодсодержащих средств."
   - GOOD ОАМ: "Материал: моча. Собрать среднюю порцию утренней мочи в стерильный контейнер. Предварительно провести гигиену наружных половых органов."
   - GOOD УЗИ брюшной: "Специальной подготовки не требуется. За 3–4 часа до исследования не есть и не пить. Исключить газообразующие продукты за 1–2 дня."
   - GOOD Спермограмма: "Материал: эякулят. Воздержание от половой жизни 3–5 дней. Сбор производится путём мастурбации в стерильный контейнер в специальной комнате клиники."
   - GOOD Аллерген IgE: "Материал: венозная кровь. Специальной подготовки не требуется. Рекомендуется не принимать антигистаминные препараты за 3–5 дней до анализа."

5. req_uz: Uzbek Latin translation of req_ru.
   - MUST start with: "Material: [material turi]."
   - Material: venoz qon / kapillyar qon / siydik / najas / surtma / ejakulyat / so'lak / balghm

6. req_kr: Uzbek Cyrillic translation of req_uz (transliterate req_uz to Cyrillic).

Return ONLY a valid JSON array. No markdown. No explanation. Exactly N objects."""


def _call_gemini_batch(services: list, api_key: str, retries: int = 3) -> list:
    services_text = "\n".join([
        f"{i+1}. [{s['type']}] {s['name_ru']}"
        for i, s in enumerate(services)
    ])

    prompt = (
        f"Generate medical content for these {len(services)} medical services.\n"
        f"Return a JSON array with exactly {len(services)} objects.\n"
        f'Each object must have: {{"name_uz":"...","desc_ru":"...","desc_uz":"...","req_ru":"...","req_uz":"...","req_kr":"..."}}\n\n'
        f"Services:\n{services_text}"
    )

    for attempt in range(retries):
        try:
            from google import genai
            from google.genai import types
            client = genai.Client(api_key=api_key)
            response = client.models.generate_content(
                model=GEMINI_MODEL,
                contents=prompt,
                config=types.GenerateContentConfig(
                    system_instruction=SYSTEM_PROMPT,
                    temperature=0.1,
                    response_mime_type="application/json",
                )
            )
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
    Returns dict: name_ru -> {name_uz, desc_ru, desc_uz, req_ru, req_uz, req_kr} or None on failure.
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
                    "req_kr":  trans.get("req_kr",  ""),
                }
        else:
            for svc in batch:
                results[svc["name_ru"]] = None

        if progress_callback:
            progress_callback(min(i + BATCH_SIZE, total), total)

        if i + BATCH_SIZE < total:
            time.sleep(1.0)

    return results
