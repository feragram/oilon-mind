"""AI-eval: how well does extraction read real-world wording? Run: python eval.py
Each case = offer text + ground-truth fields. Score = share of fields extracted exactly (±1%).
Run once offline (regex baseline) and once with an API key (LLM) — show both numbers in the pitch."""
import ai
from engine import LoanTerms, analyze

CASES = [
 ("Займ 15 000 сом на 2 месяца, 0,6% в день, комиссия 3%", dict(principal=15000, term_months=2, daily_rate=0.6, upfront_fee_pct=3)),
 ("Кредит 200 000 сом, 24 мес, 28% годовых, комиссия за выдачу 2%", dict(principal=200000, term_months=24, nominal_rate_annual=28, upfront_fee_pct=2)),
 ("Рассрочка 85 000 сом на 12 месяцев, ежемесячный платёж 8 200 сом, страховка 4 500 сом", dict(principal=85000, term_months=12, monthly_payment=8200, insurance_total=4500)),
 ("Быстрые деньги: 5000 с на 30 дней под 1% в день", dict(principal=5000, term_months=1, daily_rate=1)),
 ("Микрокредит 50 000 сом сроком 6 месяцев, 3% в месяц", dict(principal=50000, term_months=6, nominal_rate_annual=36)),
 ("Автокредит 1 200 000 сом на 36 мес. под 22% годовых, комиссия 1,5%", dict(principal=1200000, term_months=36, nominal_rate_annual=22, upfront_fee_pct=1.5)),
 ("Получи 30 000 сом за 10 минут! 8 недель, 0,9% в день", dict(principal=30000, term_months=2, daily_rate=0.9)),
 ("Ипотечный займ 2 500 000 сом, 120 месяцев, 16% годовых", dict(principal=2500000, term_months=120, nominal_rate_annual=16)),
 ("Телефон в рассрочку 0%: 60 000 сом, 10 мес., платёж 6 600 сом", dict(principal=60000, term_months=10, monthly_payment=6600)),
 ("Займ 10 000 сом, 3 месяца, 4% в месяц, комиссия 500 сом, пеня 0,5%", dict(principal=10000, term_months=3, nominal_rate_annual=48, upfront_fee=500, penalty_daily_pct=0.5)),
]

def close(a, b):
    try: return abs(float(a) - float(b)) <= max(0.01 * abs(float(b)), 0.01)
    except (TypeError, ValueError): return False

hit = tot = 0
for text, truth in CASES:
    got, src = ai.extract(text=text)
    ok = [k for k in truth if close(got.get(k), truth[k])]
    hit += len(ok); tot += len(truth)
    miss = [f"{k}: {got.get(k)}≠{truth[k]}" for k in truth if k not in ok]
    print(("✓" if not miss else "✗"), text[:55], "|", "; ".join(miss))
print(f"\nProvider: {ai.provider()}  Field accuracy: {hit}/{tot} = {hit/tot:.0%}")

# Engine sanity checks (math must be exact, independent of AI)
a = analyze(LoanTerms(principal=100000, term_months=12, nominal_rate_annual=12))
assert abs(a.effective_annual_rate - 12.68) < 0.05, a.effective_annual_rate
a = analyze(LoanTerms(principal=100000, term_months=12, nominal_rate_annual=12, upfront_fee_pct=5))
assert a.effective_annual_rate > 22, a.effective_annual_rate
print("Engine checks passed.")
