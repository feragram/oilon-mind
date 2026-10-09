"""Ойлон — AI layer. Two narrow jobs only:
1) extract(): read a messy offer (SMS, ad, contract photo) -> structured LoanTerms JSON
2) explain(): turn computed numbers into a plain-language lesson in RU or KG

Providers (first key found wins): GEMINI_API_KEY, ANTHROPIC_API_KEY, OPENAI_API_KEY.
With no key the app still works: regex extraction + template explanation (demo never dies).
"""
from __future__ import annotations
import base64, json, os, re
import requests

TIMEOUT = 45


def _secret(name: str) -> str | None:
    v = os.environ.get(name)
    if v:
        return v
    try:
        import streamlit as st
        return st.secrets.get(name)  # type: ignore[attr-defined]
    except Exception:
        return None


def provider() -> str:
    for p, k in (("gemini", "GEMINI_API_KEY"), ("anthropic", "ANTHROPIC_API_KEY"), ("openai", "OPENAI_API_KEY")):
        if _secret(k):
            return p
    return "offline"


def _call(prompt: str, image: bytes | None = None, mime: str = "image/jpeg", json_mode: bool = False) -> str:
    p = provider()
    if p == "gemini":
        model = _secret("GEMINI_MODEL") or "gemini-2.5-flash"
        parts = [{"text": prompt}]
        if image:
            parts.append({"inline_data": {"mime_type": mime, "data": base64.b64encode(image).decode()}})
        body = {"contents": [{"parts": parts}], "generationConfig": {"temperature": 0.1}}
        if json_mode:
            body["generationConfig"]["responseMimeType"] = "application/json"
        r = requests.post(f"https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent",
                          params={"key": _secret("GEMINI_API_KEY")}, json=body, timeout=TIMEOUT)
        r.raise_for_status()
        return r.json()["candidates"][0]["content"]["parts"][0]["text"]
    if p == "anthropic":
        model = _secret("ANTHROPIC_MODEL") or "claude-haiku-5-5"
        content = []
        if image:
            content.append({"type": "image", "source": {"type": "base64", "media_type": mime,
                                                         "data": base64.b64encode(image).decode()}})
        content.append({"type": "text", "text": prompt})
        r = requests.post("https://api.anthropic.com/v1/messages", timeout=TIMEOUT,
                          headers={"x-api-key": _secret("ANTHROPIC_API_KEY"), "anthropic-version": "2023-06-01",
                                   "content-type": "application/json"},
                          json={"model": model, "max_tokens": 1500, "temperature": 0.1,
                                "messages": [{"role": "user", "content": content}]})
        r.raise_for_status()
        return "".join(b.get("text", "") for b in r.json()["content"])
    if p == "openai":
        model = _secret("OPENAI_MODEL") or "gpt-4o-mini"
        content = [{"type": "text", "text": prompt}]
        if image:
            content.append({"type": "image_url", "image_url": {
                "url": f"data:{mime};base64,{base64.b64encode(image).decode()}"}})
        body = {"model": model, "temperature": 0.1, "messages": [{"role": "user", "content": content}]}
        if json_mode:
            body["response_format"] = {"type": "json_object"}
        r = requests.post("https://api.openai.com/v1/chat/completions", timeout=TIMEOUT,
                          headers={"Authorization": f"Bearer {_secret('OPENAI_API_KEY')}"}, json=body)
        r.raise_for_status()
        return r.json()["choices"][0]["message"]["content"]
    raise RuntimeError("offline")


EXTRACT_PROMPT = """Ты — аналитик кредитных договоров в Кыргызстане. Извлеки условия кредита/займа/рассрочки
из текста или изображения ниже. Валюта — сом (KGS), если не указано иное. НЕ считай ничего сам, только извлекай.
Если поля нет — null. Не выдумывай.

Верни ТОЛЬКО JSON:
{"principal": число|null, "term_months": целое|null, "nominal_rate_annual": число (% годовых)|null,
 "daily_rate": число (% в день)|null, "monthly_payment": число|null, "upfront_fee": число (сом)|0,
 "upfront_fee_pct": число (%)|0, "monthly_fee": число (сом)|0, "insurance_total": число (сом)|0,
 "penalty_daily_pct": число|null, "lender": строка|null,
 "product": "микрокредит"|"рассрочка"|"потребкредит"|"другое"|null,
 "notes": [до 4 коротких предупреждений на русском о скрытых условиях: обязательная страховка,
           запрет досрочного погашения, плавающая ставка, валютный кредит, залог, поручитель и т.п.]}
Срок в неделях/днях переведи в месяцы (округли вверх). "0% рассрочка" с наценкой к цене — укажи наценку в upfront_fee
как отрицательную разницу нельзя; вместо этого добавь в notes.

ТЕКСТ:
"""


def _num(s: str) -> float:
    return float(s.replace(" ", "").replace("\u00a0", "").replace(",", "."))


def regex_extract(text: str) -> dict:
    """Offline fallback. Good enough for typical SMS/ad wording; AI handles the rest."""
    t = text.lower().replace("\u00a0", " ")
    d: dict = {"upfront_fee": 0, "upfront_fee_pct": 0, "monthly_fee": 0, "insurance_total": 0, "notes": []}
    N = r"(\d[\d \.,]*\d|\d)"
    if m := re.search(N + r"\s*(?:сом|с\b|kgs)", t):
        d["principal"] = _num(m.group(1))
    if m := re.search(N + r"\s*(?:мес|месяц)", t):
        d["term_months"] = int(_num(m.group(1)))
    elif m := re.search(N + r"\s*(?:недел)", t):
        d["term_months"] = max(1, -(-int(_num(m.group(1))) // 4))
    elif m := re.search(N + r"\s*(?:дн|день|дней)", t):
        d["term_months"] = max(1, -(-int(_num(m.group(1))) // 30))
    if m := re.search(N + r"\s*%\s*(?:в день|в сутки|/день)", t):
        d["daily_rate"] = _num(m.group(1))
    elif m := re.search(N + r"\s*%\s*(?:годовых|в год|годовые)", t):
        d["nominal_rate_annual"] = _num(m.group(1))
    elif m := re.search(N + r"\s*%\s*в месяц", t):
        d["nominal_rate_annual"] = _num(m.group(1)) * 12
    if m := re.search(r"(?:платеж|платёж)[^\d]{0,25}" + N, t):
        d["monthly_payment"] = _num(m.group(1))
    if m := re.search(r"комисси[яи][^\d%]{0,30}" + N + r"\s*%", t):
        d["upfront_fee_pct"] = _num(m.group(1))
    elif m := re.search(r"комисси[яи][^\d]{0,30}" + N + r"\s*(?:сом|с\b)", t):
        d["upfront_fee"] = _num(m.group(1))
    if m := re.search(r"страхов\w*[^\d]{0,30}" + N + r"\s*(?:сом|с\b)", t):
        d["insurance_total"] = _num(m.group(1))
    if m := re.search(r"(?:пеня|неустойк\w*|штраф)[^\d]{0,30}" + N + r"\s*%", t):
        d["penalty_daily_pct"] = _num(m.group(1))
    if "досрочн" in t and ("запрещ" in t or "штраф" in t or "комисс" in t):
        d["notes"].append("Есть ограничения или плата за досрочное погашение.")
    if "доллар" in t or "usd" in t or "$" in t:
        d["notes"].append("Кредит может быть в валюте — риск роста платежа при падении сома.")
    return d


def _parse_json(s: str) -> dict:
    s = re.sub(r"```(?:json)?|```", "", s).strip()
    m = re.search(r"\{.*\}", s, re.S)
    return json.loads(m.group(0) if m else s)


def extract(text: str = "", image: bytes | None = None, mime: str = "image/jpeg") -> tuple[dict, str]:
    """Returns (fields, source) where source is the provider name or 'offline'."""
    if provider() != "offline":
        try:
            return _parse_json(_call(EXTRACT_PROMPT + (text or "(см. изображение)"), image, mime, json_mode=True)), provider()
        except Exception as e:  # network/quota: degrade gracefully
            fields = regex_extract(text) if text else {}
            fields.setdefault("notes", []).append(f"AI недоступен ({type(e).__name__}), использован резервный разбор.")
            return fields, "offline"
    return (regex_extract(text) if text else {}), "offline"


EXPLAIN_PROMPT = """Ты — «Ойлон», честный финансовый наставник для молодёжи Кыргызстана. Не продаёшь, не советуешь
конкретные банки, не даёшь юридических гарантий. Объясни результат проверки кредита человеку 18–30 лет без
финансового образования. Язык ответа: {lang}. Пиши тепло и прямо, коротко, без жаргона.

ЦИФРЫ (уже посчитаны, НЕ пересчитывай и не меняй их):
{facts}

Формат (Markdown, всего до 170 слов):
**Коротко:** 1–2 предложения — что это за деньги на самом деле.
**Почему так:** 2–3 пункта, только из цифр выше.
**Что можно сделать:** 3 конкретных шага (спросить у кредитора X, сравнить с Y, подождать/накопить Z месяцев).
**Урок дня:** одно понятие (например, «эффективная ставка» или «долговая нагрузка») — 2 предложения.
**Вопрос себе:** один вопрос для самопроверки.
"""


def facts_text(t: dict, a: dict) -> str:
    lines = [
        f"Продукт: {t.get('product') or '—'}; кредитор: {t.get('lender') or '—'}",
        f"Сумма по договору: {t.get('principal')} сом; на руки: {a['received']} сом; срок: {t.get('term_months')} мес.",
        f"Ежемесячный платёж: {a['monthly_payment']} сом; всего выплатить: {a['total_paid']} сом",
        f"Переплата: {a['overpayment']} сом ({a['overpayment_pct']}% от полученного)",
        f"Заявленная ставка: {a['stated_rate']}% годовых; реальная эффективная: {a['effective_annual_rate']}% годовых",
    ]
    if a.get("dti_after") is not None:
        lines.append(f"Доля дохода на платежи: было {a['dti_before']}%, станет {a['dti_after']}%")
    if a.get("savings_months"):
        lines.append(f"Если откладывать сумму платежа, нужную сумму можно накопить за ~{a['savings_months']} мес.")
    lines.append("Предупреждения: " + "; ".join(x[1] for x in a["flags"]) if a["flags"] else "Предупреждений нет.")
    return "\n".join(lines)


def explain(t: dict, a: dict, lang: str = "русский") -> tuple[str, str]:
    facts = facts_text(t, a)
    if provider() != "offline":
        try:
            return _call(EXPLAIN_PROMPT.format(lang=lang, facts=facts)), provider()
        except Exception:
            pass
    # Template fallback (RU only)
    sev = {"red": "дорогие и рискованные деньги", "yellow": "деньги дороже, чем кажется",
           "green": "условия выглядят прозрачно"}[a["verdict"]]
    steps = ["Попросите у кредитора график платежей и эффективную ставку письменно.",
             "Сравните с предложением банка или рассрочкой без наценки — на ту же сумму и срок."]
    if a.get("savings_months"):
        steps.append(f"Проверьте вариант накопить: ~{a['savings_months']} мес. откладывания суммы платежа.")
    sp = lambda x: f"{x:,.0f}".replace(",", " ")
    return (f"**Коротко:** {sev}. Вы получите {sp(a['received'])} сом, а вернёте {sp(a['total_paid'])} сом.\n\n"
            f"**Почему так:** реальная ставка {a['effective_annual_rate']}% годовых"
            + (f" при заявленных {a['stated_rate']}%" if a['stated_rate'] is not None else "") + ".\n\n"
            "**Что можно сделать:**\n" + "\n".join(f"- {s}" for s in steps) +
            "\n\n**Урок дня:** эффективная ставка учитывает все комиссии и страховку — это настоящая цена денег. "
            "Сравнивайте кредиты только по ней.\n\n**Вопрос себе:** если доход упадёт на месяц, чем я заплачу?"
            ), "offline"
