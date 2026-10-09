"""Ойлон — deterministic loan math. No AI here: every number shown to the user comes from this file.

Why separate: the LLM only *reads* the offer (extraction) and *explains* the result.
It never calculates. This keeps numbers auditable and testable (see eval.py).
"""
from __future__ import annotations
from dataclasses import dataclass, field, asdict


@dataclass
class LoanTerms:
    principal: float | None = None          # сумма кредита по договору, сом
    term_months: int | None = None          # срок, мес
    nominal_rate_annual: float | None = None  # заявленная ставка, % годовых
    daily_rate: float | None = None         # если ставка указана "% в день"
    monthly_payment: float | None = None    # ежемесячный платёж, если указан
    upfront_fee: float = 0.0                # комиссия за выдачу (удерживается), сом
    upfront_fee_pct: float = 0.0            # комиссия за выдачу, % от суммы
    monthly_fee: float = 0.0                # ежемесячная комиссия/обслуживание, сом
    insurance_total: float = 0.0            # страховка (единовременно), сом
    penalty_daily_pct: float | None = None  # пеня за просрочку, % в день
    lender: str | None = None
    product: str | None = None              # микрокредит / рассрочка / потребкредит
    notes: list[str] = field(default_factory=list)  # оговорки, найденные AI


def annuity_payment(principal: float, annual_rate_pct: float, n: int) -> float:
    r = annual_rate_pct / 100 / 12
    if r == 0:
        return principal / n
    return principal * r / (1 - (1 + r) ** -n)


def _npv(rate: float, received: float, payments: list[float]) -> float:
    return received - sum(p / (1 + rate) ** (i + 1) for i, p in enumerate(payments))


def monthly_irr(received: float, payments: list[float]) -> float | None:
    """Monthly rate that equates money actually received with all payments (bisection)."""
    if received <= 0 or not payments or sum(payments) <= received:
        return 0.0 if payments and abs(sum(payments) - received) < 1e-6 else None
    lo, hi = 0.0, 5.0  # up to 500%/month — covers payday-style loans
    for _ in range(200):
        mid = (lo + hi) / 2
        if _npv(mid, received, payments) > 0:
            hi = mid
        else:
            lo = mid
    return (lo + hi) / 2


@dataclass
class Analysis:
    ok: bool
    missing: list[str]
    monthly_payment: float = 0.0
    received: float = 0.0
    total_paid: float = 0.0
    overpayment: float = 0.0
    overpayment_pct: float = 0.0
    effective_annual_rate: float = 0.0     # ЭЭС, % годовых (сложный процент)
    stated_rate: float | None = None
    rate_gap_pp: float | None = None       # насколько реальная ставка выше заявленной
    dti_before: float | None = None
    dti_after: float | None = None
    savings_months: float | None = None    # за сколько месяцев накопить ту же сумму
    flags: list[tuple[str, str]] = field(default_factory=list)  # (level, text)
    verdict: str = ""                      # green / yellow / red

    def to_dict(self):
        return asdict(self)


def analyze(t: LoanTerms, income: float | None = None, other_payments: float = 0.0) -> Analysis:
    missing = []
    if not t.principal:
        missing.append("сумма кредита")
    if not t.term_months:
        missing.append("срок (мес.)")
    stated = t.nominal_rate_annual
    if stated is None and t.daily_rate is not None:
        stated = t.daily_rate * 365
    if t.monthly_payment is None and stated is None:
        missing.append("ставка или ежемесячный платёж")
    if missing:
        return Analysis(ok=False, missing=missing)

    n = int(t.term_months)
    pay = t.monthly_payment if t.monthly_payment else annuity_payment(t.principal, stated, n)
    pay_total = pay + (t.monthly_fee or 0)
    fee = (t.upfront_fee or 0) + t.principal * (t.upfront_fee_pct or 0) / 100
    received = t.principal - fee - (t.insurance_total or 0)
    payments = [pay_total] * n
    total = sum(payments)
    r = monthly_irr(received, payments)
    ear = ((1 + r) ** 12 - 1) * 100 if r is not None else 0.0

    a = Analysis(ok=True, missing=[])
    a.monthly_payment = round(pay_total, 2)
    a.received = round(received, 2)
    a.total_paid = round(total, 2)
    a.overpayment = round(total - received, 2)
    a.overpayment_pct = round((total - received) / received * 100, 1) if received > 0 else 0
    a.effective_annual_rate = round(ear, 1)
    a.stated_rate = round(stated, 2) if stated is not None else None
    # Gap attributable to fees/insurance only (same schedule, no deductions)
    r0 = monthly_irr(t.principal, [pay] * n)
    ear_clean = ((1 + r0) ** 12 - 1) * 100 if r0 is not None else ear
    a.rate_gap_pp = round(ear - ear_clean, 1) if (fee or t.insurance_total or t.monthly_fee) else 0.0

    if income and income > 0:
        a.dti_before = round(other_payments / income * 100, 1)
        a.dti_after = round((other_payments + pay_total) / income * 100, 1)
        surplus = income * 0.2 if income else 0
        a.savings_months = round(received / max(pay_total, surplus), 1) if pay_total else None
    else:
        a.savings_months = round(received / pay_total, 1) if pay_total else None

    # ---- flags (rule-based, transparent) ----
    f = a.flags
    if t.daily_rate is not None:
        f.append(("red", f"Ставка указана «в день» ({t.daily_rate}%/день) — это ≈{t.daily_rate*365:.0f}% годовых без учёта сложного процента."))
    if a.rate_gap_pp is not None and a.rate_gap_pp > 5:
        f.append(("yellow", f"Комиссии и страховка добавляют к реальной ставке {a.rate_gap_pp} п.п."))
    if fee + (t.insurance_total or 0) > 0:
        sp = lambda x: f"{x:,.0f}".replace(",", " ")
        f.append(("yellow", f"На руки вы получите {sp(received)} сом, а не {sp(t.principal)}: удержания {sp(fee + (t.insurance_total or 0))} сом."))
    if ear >= 60:
        f.append(("red", f"Эффективная ставка {ear:.0f}% годовых — очень дорогие деньги."))
    elif ear >= 30:
        f.append(("yellow", f"Эффективная ставка {ear:.0f}% годовых — дорого; сравните с банком."))
    if t.penalty_daily_pct and t.penalty_daily_pct >= 0.5:
        f.append(("red", f"Пеня {t.penalty_daily_pct}% в день: месяц просрочки ≈ +{t.penalty_daily_pct*30:.0f}% к долгу."))
    if a.dti_after is not None:
        if a.dti_after > 60:
            f.append(("red", f"Платежи займут {a.dti_after}% дохода. По проекту правил НБКР при >60% кредитор обязан письменно предупредить о риске дефолта."))
        elif a.dti_after > 40:
            f.append(("yellow", f"Платежи займут {a.dti_after}% дохода — мало запаса на непредвиденное."))
    for note in t.notes:
        f.append(("yellow", note))

    reds = sum(1 for lv, _ in f if lv == "red")
    yel = sum(1 for lv, _ in f if lv == "yellow")
    a.verdict = "red" if reds else ("yellow" if yel else "green")
    return a


def schedule(t: LoanTerms, a: Analysis) -> list[dict]:
    """Approximate annuity balance schedule for the chart (interest vs principal)."""
    stated = t.nominal_rate_annual if t.nominal_rate_annual is not None else (
        t.daily_rate * 365 if t.daily_rate is not None else None)
    n = int(t.term_months)
    bal = t.principal
    base_pay = a.monthly_payment - (t.monthly_fee or 0)
    r = (stated / 100 / 12) if stated is not None else None
    if r is None:  # derive implied nominal from payment
        rr = monthly_irr(t.principal, [base_pay] * n) or 0
        r = rr
    rows = []
    for m in range(1, n + 1):
        interest = bal * r
        princ = max(base_pay - interest, 0)
        bal = max(bal - princ, 0)
        rows.append({"месяц": m, "проценты и комиссии": round(interest + (t.monthly_fee or 0), 2),
                     "основной долг": round(princ, 2)})
    return rows
