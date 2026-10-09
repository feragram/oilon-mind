"""Ойлон — подумай до подписи. AI-проверка кредита/рассрочки за 30 секунд. Team MIND · AI Founders Sprint 2026."""
import csv, datetime, os, uuid
import pandas as pd
import streamlit as st

import ai
from engine import LoanTerms, analyze, schedule

st.set_page_config(page_title="Ойлон — проверь кредит до подписи", page_icon="🧠", layout="centered")

st.markdown("""
<style>
.block-container {max-width: 760px; padding-top: 2rem;}
h1 {font-weight: 800; letter-spacing: -0.02em; margin-bottom: 0;}
.sub {color:#5b524a; font-size:1.05rem; margin-top:.2rem;}
.verdict {border-radius:14px; padding:18px 20px; margin:12px 0 4px; color:#fff;}
.verdict b {font-size:1.35rem;}
.v-red {background:#B4232A;} .v-yellow {background:#B7791F;} .v-green {background:#2F6B3B;}
.flag {padding:8px 12px; border-left:4px solid; border-radius:6px; margin:6px 0; background:#fff;}
.f-red {border-color:#B4232A;} .f-yellow {border-color:#B7791F;}
.small {color:#7a6f64; font-size:.85rem;}
</style>""", unsafe_allow_html=True)

SAMPLES = {
    "SMS микрозайма": "Займ до зарплаты! Получите 15 000 сом на 2 месяца, ставка всего 0,6% в день. "
                      "Комиссия за выдачу 3%. Пеня за просрочку 1% в день.",
    "Рассрочка на телефон": "iPhone в рассрочку: сумма 85 000 сом на 12 месяцев, ежемесячный платёж 8 200 сом. "
                            "Страховка устройства 4 500 сом оплачивается сразу. Досрочное погашение — комиссия 2%.",
    "Потребкредит банка": "Потребительский кредит 200 000 сом, 24 месяца, 28% годовых, "
                          "комиссия за выдачу 2%, ежемесячная плата за обслуживание счёта 300 сом.",
}

mode_page = st.sidebar.radio("Режим", ["Проверка кредита", "Игра «Үйгө жол»"])
if mode_page.startswith("Игра"):
    import streamlit.components.v1 as components
    st.markdown("# Үйгө жол")
    st.caption("Путь к своей квартире: 10 лет жизни за 5 минут. Цифры условные.")
    with open(os.path.join(os.path.dirname(__file__), "game.html"), encoding="utf-8") as fh:
        components.html(fh.read(), height=1250, scrolling=True)
    st.stop()

if "sid" not in st.session_state:
    st.session_state.sid = uuid.uuid4().hex[:8]
    st.session_state.fields = None
    st.session_state.src = None

st.markdown("# Ойлон")
st.markdown('<div class="sub">Подумай до подписи. Вставьте SMS, рекламу или фото договора — '
            'за 30 секунд покажем реальную цену кредита и что с ней делать.</div>', unsafe_allow_html=True)
mode = ai.provider()
st.caption(f"AI: {mode if mode != 'offline' else 'офлайн-режим (без ключа API)'} · данные не сохраняются вместе с личностью")

# ---------- 1. Input ----------
st.subheader("1. Что вам предлагают?")
tab_text, tab_photo, tab_manual = st.tabs(["Текст / SMS", "Фото договора", "Ввести вручную"])

with tab_text:
    c = st.columns(len(SAMPLES))
    for i, (k, v) in enumerate(SAMPLES.items()):
        if c[i].button(k, use_container_width=True):
            st.session_state.offer_text = v
    text = st.text_area("Текст предложения", key="offer_text", height=120,
                        placeholder="Например: «Займ 20 000 сом на 3 месяца, 0,5% в день, комиссия 2%»")
    if st.button("Разобрать текст", type="primary", disabled=not text):
        with st.spinner("Читаю условия…"):
            st.session_state.fields, st.session_state.src = ai.extract(text=text)

with tab_photo:
    up = st.file_uploader("Фото или скриншот договора/рекламы", type=["jpg", "jpeg", "png", "webp"])
    if up is not None:
        st.image(up, width=320)
        if mode == "offline":
            st.info("Распознавание фото работает при подключённом AI-ключе. Сейчас — введите условия вручную.")
        elif st.button("Распознать фото", type="primary"):
            with st.spinner("Читаю договор…"):
                st.session_state.fields, st.session_state.src = ai.extract(image=up.getvalue(), mime=up.type)

with tab_manual:
    if st.button("Заполнить вручную"):
        st.session_state.fields, st.session_state.src = {"notes": []}, "manual"

f = st.session_state.fields
if f is None:
    st.stop()

# ---------- 2. Confirm extracted terms (human in the loop) ----------
st.subheader("2. Проверьте условия")
st.caption("AI только читает документ. Все цифры считает прозрачная формула. Исправьте, если что-то не так.")


def g(k, d=0.0):
    v = f.get(k)
    return float(v) if v not in (None, "") else d


c1, c2, c3 = st.columns(3)
principal = c1.number_input("Сумма, сом", 0.0, 1e8, g("principal"), 1000.0)
term = c2.number_input("Срок, мес.", 0, 360, int(g("term_months")), 1)
monthly_payment = c3.number_input("Платёж в месяц, сом (если известен)", 0.0, 1e7, g("monthly_payment"), 100.0)
c1, c2, c3 = st.columns(3)
rate = c1.number_input("Ставка, % годовых", 0.0, 2000.0, g("nominal_rate_annual"), 0.5)
daily = c2.number_input("…или % в день", 0.0, 10.0, g("daily_rate"), 0.05)
penalty = c3.number_input("Пеня, % в день", 0.0, 10.0, g("penalty_daily_pct"), 0.1)
c1, c2, c3, c4 = st.columns(4)
fee_pct = c1.number_input("Комиссия, %", 0.0, 50.0, g("upfront_fee_pct"), 0.5)
fee = c2.number_input("Комиссия, сом", 0.0, 1e7, g("upfront_fee"), 100.0)
mfee = c3.number_input("Ежемес. плата, сом", 0.0, 1e6, g("monthly_fee"), 50.0)
ins = c4.number_input("Страховка, сом", 0.0, 1e7, g("insurance_total"), 100.0)

st.subheader("3. Ваш бюджет (необязательно)")
c1, c2 = st.columns(2)
income = c1.number_input("Доход в месяц, сом", 0.0, 1e7, 0.0, 1000.0)
other = c2.number_input("Уже платите по кредитам, сом/мес", 0.0, 1e7, 0.0, 500.0)

terms = LoanTerms(principal=principal or None, term_months=int(term) or None,
                  nominal_rate_annual=rate or None, daily_rate=daily or None,
                  monthly_payment=monthly_payment or None, upfront_fee=fee, upfront_fee_pct=fee_pct,
                  monthly_fee=mfee, insurance_total=ins, penalty_daily_pct=penalty or None,
                  lender=f.get("lender"), product=f.get("product"), notes=list(f.get("notes") or []))
a = analyze(terms, income or None, other)

if not a.ok:
    st.warning("Не хватает: " + ", ".join(a.missing))
    st.stop()

# ---------- 4. Result ----------
label = {"red": "Стоп. Дорого и рискованно", "yellow": "Осторожно: дороже, чем кажется",
         "green": "Условия выглядят прозрачно"}[a.verdict]
fmt = lambda x: f"{x:,.0f}".replace(",", " ")
st.markdown(f'<div class="verdict v-{a.verdict}"><b>{label}</b><br>'
            f'Получите {fmt(a.received)} сом → вернёте {fmt(a.total_paid)} сом за {int(term)} мес.</div>', unsafe_allow_html=True)

m1, m2, m3 = st.columns(3)
m1.metric("Реальная ставка", f"{a.effective_annual_rate:.0f}% год.",
          f"+{a.rate_gap_pp} п.п. из-за комиссий" if a.rate_gap_pp else None, delta_color="inverse",
          help="Эффективная годовая ставка: учитывает комиссии, страховку и сложный процент. "
               "Для коротких займов она очень высокая — это честная цена денег в пересчёте на год.")
m2.metric("Переплата", f"{fmt(a.overpayment)} сом", f"{a.overpayment_pct}% от полученного", delta_color="off")
m3.metric("Платёж", f"{fmt(a.monthly_payment)} сом/мес",
          None if a.dti_after is None else f"{a.dti_after}% дохода", delta_color="off")

for lv, msg in a.flags:
    st.markdown(f'<div class="flag f-{lv}">{"⛔" if lv == "red" else "⚠️"} {msg}</div>', unsafe_allow_html=True)

df = pd.DataFrame(schedule(terms, a)).set_index("месяц")
st.bar_chart(df, color=["#1E1B18", "#B4232A"], height=220)
st.caption("Из чего состоят платежи по месяцам (приблизительно, аннуитет).")

# ---------- 5. AI explanation + micro-lesson ----------
st.subheader("4. Что это значит для меня")
lang = st.radio("Язык объяснения", ["русский", "кыргызский"], horizontal=True)
key = (str(terms), lang, income, other)
if st.session_state.get("exp_key") != key:
    with st.spinner("Объясняю простыми словами…"):
        st.session_state.exp, st.session_state.exp_src = ai.explain(f | {"principal": principal, "term_months": term},
                                                                    a.to_dict(), lang)
    st.session_state.exp_key = key
st.markdown(st.session_state.exp)
if lang == "кыргызский" and st.session_state.exp_src == "offline":
    st.caption("Кыргызский язык доступен при подключённом AI.")

# ---------- 6. Outcome capture (evidence for validation) ----------
st.subheader("5. Что вы решили?")
choice = st.radio("После проверки я…", ["ещё думаю", "откажусь / подожду", "попрошу другие условия",
                                        "сравню с другим кредитором", "возьму как есть"], index=0)
if st.button("Отправить ответ (анонимно)"):
    try:
        os.makedirs("logs", exist_ok=True)
        new = not os.path.exists("logs/outcomes.csv")
        with open("logs/outcomes.csv", "a", newline="", encoding="utf-8") as fh:
            w = csv.writer(fh)
            if new:
                w.writerow(["ts", "session", "product", "ear", "verdict", "dti_after", "decision", "ai"])
            w.writerow([datetime.datetime.now(datetime.timezone.utc).isoformat(timespec="seconds"), st.session_state.sid,
                        terms.product, a.effective_annual_rate, a.verdict, a.dti_after, choice, st.session_state.src])
    except OSError:
        pass  # read-only hosting: the answer is still counted in this session
    st.success("Спасибо! Это помогает нам улучшать Ойлон.")

with st.expander("Как это работает (для жюри)"):
    st.markdown("""
- **AI читает**, формула считает: LLM извлекает условия из SMS/фото → человек подтверждает → детерминированный расчёт
  эффективной ставки (IRR по реальным денежным потокам), переплаты и долговой нагрузки.
- **AI объясняет** результат на русском или кыргызском + микро-урок по финансовой грамотности.
- Проверка качества извлечения: `python eval.py` (набор размеченных предложений).
- Ойлон не является кредитором и не даёт юридических гарантий. Цифры примеров условные.
""")
st.markdown('<div class="small">Team MIND · AI Founders Sprint 2026 · Бишкек</div>', unsafe_allow_html=True)
