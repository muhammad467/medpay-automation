import re


def _detect_material(name_ru: str) -> str:
    """Detect bio material type from Russian service name."""
    name_lower = name_ru.lower()
    if any(k in name_lower for k in ["кровь", "кровн", "сыворотк", "плазм", "гематолог",
                                      "биохимия", "гормон", "антитела", "антитело",
                                      "серолог", "иммуноглоб", "иммунофер", "пцр крови",
                                      "вич", "гепатит", "сифилис", "герпес", "цитомегало",
                                      "токсоплазм", "хламидии", "микоплазм", "уреаплазм",
                                      "холестерин", "глюкоз", "инсулин", "ферритин",
                                      "тиреотроп", "пролактин", "кортизол", "тестостерон",
                                      "эстрадиол", "прогестерон", "билирубин", "лейкоцит",
                                      "эритроцит", "тромбоцит", "гемоглобин"]):
        return "blood"
    if any(k in name_lower for k in ["моча", "мочи", "мочу", "мочой", "мочевин", "мочевой", "урин",
                                      "анализ мочи", "исследование мочи", "проба мочи",
                                      "цитология мочи", "посев мочи"]):
        return "urine"
    if any(k in name_lower for k in ["кал", "кале", "кала", "калу", "копрограмм",
                                      "исследование кала", "яйца глист", "простейши",
                                      "гельминт", "дисбакт", "дисбиоз кишечника"]):
        return "stool"
    if any(k in name_lower for k in ["мазок", "соскоб", "выделения", "секрет"]):
        return "smear"
    # Detect by common test keywords that are usually blood-based
    if any(k in name_lower for k in ["igg", "igm", "ige", "iga", "анализ крови",
                                      "определение", "уровень", "концентрация",
                                      "активность", "исследование сыворотки"]):
        return "blood"
    return "blood"  # default for lab tests


def _detect_diag_category(name_ru: str) -> str:
    """Detect diagnostics subtype."""
    name_lower = name_ru.lower()
    if any(k in name_lower for k in ["мрт", "магнитно-резон", "магнитно резон",
                                      "ядерно-магнит"]):
        return "mri"
    if any(k in name_lower for k in ["кт ", "компьютерная томография", "ктг",
                                      "томограф"]):
        return "ct"
    if any(k in name_lower for k in ["рентген", "флюорограф", "маммограф",
                                      "денситометр"]):
        return "xray"
    if any(k in name_lower for k in ["узи", "ультразвук", "допплер", "эхо",
                                      "эхокардио", "эхографи"]):
        return "ultrasound"
    return "default"


def get_duration(service_type: str, name_ru: str) -> int:
    """Return duration in minutes based on type and name."""
    if service_type == "Анализы":
        return 10
    name_lower = name_ru.lower()
    # Complex MRI/CT with contrast
    if any(k in name_lower for k in ["контраст", "ангиограф", "трактограф",
                                      "перфузи", "с введением"]):
        return 45
    if any(k in name_lower for k in ["мрт", "кт ", "томограф"]):
        return 30
    if any(k in name_lower for k in ["узи", "ультразвук", "допплер", "экг",
                                      "электрокардио", "эхо"]):
        return 20
    return 30  # default diagnostics


def get_descriptions(service_type: str, name_ru: str, name_uz: str, name_kr: str) -> dict:
    """Generate all descriptions and requirements based on templates."""
    if service_type == "Анализы":
        return _analysis_templates(name_ru, name_uz, name_kr)
    else:
        return _diagnostics_templates(name_ru, name_uz, name_kr)


def _analysis_templates(name_ru: str, name_uz: str, name_kr: str) -> dict:
    material = _detect_material(name_ru)

    desc_ru = (
        f"{name_ru} — лабораторное исследование, которое помогает оценить соответствующий "
        f"показатель организма. Результат используется врачом для диагностики, контроля "
        f"состояния пациента или оценки эффективности лечения."
    )
    # Guard against broken catalog entries where Name UZ starts with lowercase (missing first letter)
    _uz_valid = name_uz and name_uz != "-" and len(name_uz) > 0 and (name_uz[0].isupper() or name_uz[0].isdigit())
    desc_uz = (
        f"{name_uz} — organizmdagi tegishli ko'rsatkichni baholashga yordam beradigan laborator "
        f"tahlil. Natija shifokor tomonidan tashxis qo'yish, bemor holatini nazorat qilish yoki "
        f"davolash samaradorligini baholashda ishlatiladi."
    ) if _uz_valid else (
        f"Ushbu laborator tahlil organizmdagi tegishli ko'rsatkichni baholashga yordam beradi. "
        f"Natija shifokor tomonidan tashxis qo'yish va davolashda ishlatiladi."
    )
    _kr_valid = name_kr and name_kr != "-" and len(name_kr) > 0 and (name_kr[0].isupper() or name_kr[0].isdigit())
    desc_kr = (
        f"{name_kr} — организмдаги тегишли кўрсаткични баҳолашга ёрдам берадиган лаборатор "
        f"таҳлил. Натижа шифокор томонидан ташхис қўйиш, бемор ҳолатини назорат қилиш ёки "
        f"даволаш самарадорлигини баҳолашда ишлатилади."
    ) if _kr_valid else (
        f"Ушбу лаборатор таҳлил организмдаги тегишли кўрсаткични баҳолашга ёрдам беради."
    )

    if material == "blood":
        req_ru = (
            "Материал: венозная кровь. Рекомендуется сдавать анализ натощак за 8–12 часов "
            "до процедуры, если врач не назначил иначе."
        )
        req_uz = (
            "Material: venoz qon. Agar shifokor boshqacha tavsiya qilmagan bo'lsa, tahlilni "
            "8–12 soat och qoringa topshirish tavsiya etiladi."
        )
        req_kr = (
            "Материал: веноз қон. Агар шифокор бошқача тавсия қилмаган бўлса, таҳлилни "
            "8–12 соат оч қоринга топшириш тавсия этилади."
        )
    elif material == "urine":
        req_ru = (
            "Материал: моча. Перед сбором необходимо провести гигиенические процедуры; "
            "обычно собирается утренняя средняя порция мочи в стерильный контейнер."
        )
        req_uz = (
            "Material: siydik. Yig'ishdan oldin gigiyenik muolajalar bajariladi; odatda "
            "ertalabki siydikning o'rta qismi steril idishga yig'iladi."
        )
        req_kr = (
            "Материал: сийдик. Йиғишдан олдин гигиеник муолажалар бажарилади; одатда "
            "эрталабки сийдикнинг ўрта қисми стерил идишга йиғилади."
        )
    elif material == "stool":
        req_ru = (
            "Материал: кал. Образец собирается в стерильный контейнер; желательно избегать "
            "примеси мочи и воды."
        )
        req_uz = (
            "Material: najas. Namuna steril idishga yig'iladi; siydik yoki suv "
            "aralashmasligiga e'tibor berish kerak."
        )
        req_kr = (
            "Материал: нажас. Намуна стерил идишга йиғилади; сийдик ёки сув "
            "аралашмаслигига эътибор бериш керак."
        )
    else:  # smear
        req_ru = (
            "Материал: мазок. Перед процедурой следует соблюдать рекомендации врача; "
            "материал обычно берется медицинским специалистом."
        )
        req_uz = (
            "Material: surtma. Jarayon oldidan shifokor tavsiyalariga amal qilish kerak; "
            "material odatda tibbiyot xodimi tomonidan olinadi."
        )
        req_kr = (
            "Материал: суртма. Жараён олдидан шифокор тавсияларига амал қилиш керак; "
            "материал одатда тиббиёт ходими томонидан олинади."
        )

    return {
        "Описание RU": desc_ru,
        "Описание UZ": desc_uz,
        "Описание KR": desc_kr,
        "Требования RU": req_ru,
        "Требования UZ": req_uz,
        "Требования KR": req_kr,
    }


def _diagnostics_templates(name_ru: str, name_uz: str, name_kr: str) -> dict:
    subtype = _detect_diag_category(name_ru)

    desc_ru = (
        f"{name_ru} — диагностическое исследование, которое помогает врачу оценить состояние "
        f"органов, тканей или систем организма. Процедура применяется для уточнения диагноза, "
        f"контроля заболевания или выбора дальнейшей тактики лечения."
    )
    desc_uz = (
        f"{name_uz} — shifokorga a'zolar, to'qimalar yoki organizm tizimlari holatini "
        f"baholashga yordam beradigan diagnostik tekshiruv. Jarayon tashxisni aniqlashtirish, "
        f"kasallikni nazorat qilish yoki keyingi davolash taktikasini tanlash uchun qo'llaniladi."
    ) if name_uz and name_uz != "-" else (
        f"Ushbu diagnostik tekshiruv shifokorga a'zolar va tizimlar holatini baholashga yordam "
        f"beradi. Tashxisni aniqlashtirish va davolash taktikasini tanlash uchun qo'llaniladi."
    )
    desc_kr = (
        f"{name_kr} — шифокорга аъзолар, тўқималар ёки организм тизимлари ҳолатини баҳолашга "
        f"ёрдам берадиган диагностик текширув. Жараён ташхисни аниқлаштириш, касалликни "
        f"назорат қилиш ёки кейинги даволаш тактикасини танлаш учун қўлланилади."
    ) if name_kr and name_kr != "-" else (
        f"Ушбу диагностик текширув шифокорга аъзолар ва тизимлар ҳолатини баҳолашга ёрдам "
        f"беради."
    )

    if subtype in ("mri", "ct", "xray"):
        req_ru = (
            "Специальная подготовка зависит от зоны исследования и необходимости контраста. "
            "Перед процедурой сообщите врачу о беременности, аллергиях, имплантах или "
            "хронических заболеваниях."
        )
        req_uz = (
            "Maxsus tayyorgarlik tekshiruv sohasi va kontrast modda qo'llanishiga bog'liq. "
            "Jarayon oldidan homiladorlik, allergiya, implantlar yoki surunkali kasalliklar "
            "haqida shifokorga xabar bering."
        )
        req_kr = (
            "Махсус тайёргарлик текширув соҳаси ва контраст модда қўлланишига боғлиқ. "
            "Жараён олдидан ҳомиладорлик, аллергия, имплантлар ёки сурункали касалликлар "
            "ҳақида шифокорга хабар беринг."
        )
    elif subtype == "ultrasound":
        req_ru = (
            "Специальной подготовки может не требоваться, однако для некоторых видов УЗИ может "
            "понадобиться голодание или наполненный мочевой пузырь. Следуйте назначению врача."
        )
        req_uz = (
            "Maxsus tayyorgarlik talab qilinmasligi mumkin, ammo ayrim ultratovush tekshiruvlari "
            "uchun och qorin yoki siydik pufagining to'liq bo'lishi kerak bo'lishi mumkin. "
            "Shifokor ko'rsatmasiga amal qiling."
        )
        req_kr = (
            "Махсус тайёргарлик талаб қилинмаслиги мумкин, аммо айрим ультратовуш "
            "текширувлари учун оч қорин ёки сийдик пуфагининг тўлиқ бўлиши керак бўлиши "
            "мумкин. Шифокор кўрсатмасига амал қилинг."
        )
    else:
        req_ru = (
            "Специальная подготовка зависит от вида исследования. Следуйте назначению врача "
            "и возьмите с собой предыдущие результаты обследований, если они есть."
        )
        req_uz = (
            "Maxsus tayyorgarlik tekshiruv turiga bog'liq. Shifokor ko'rsatmasiga amal qiling "
            "va mavjud bo'lsa, oldingi tekshiruv natijalarini olib keling."
        )
        req_kr = (
            "Махсус тайёргарлик текширув турига боғлиқ. Шифокор кўрсатмасига амал қилинг "
            "ва мавжуд бўлса, олдинги текширув натижаларини олиб келинг."
        )

    return {
        "Описание RU": desc_ru,
        "Описание UZ": desc_uz,
        "Описание KR": desc_kr,
        "Требования RU": req_ru,
        "Требования UZ": req_uz,
        "Требования KR": req_kr,
    }
