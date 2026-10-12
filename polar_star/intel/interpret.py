"""Interpretation layer — user mandate 2026-09-09 (readability):

    财报一定要能看懂，公告一定要知道含义，新闻一定要有时效性，
    投研报告一定要全面，且权威有参考性；往往公告和新闻对短线
    的影响更大。

Static fact-level aids only: category keyword -> generic meaning,
master-row numbers -> plain-language digest, news timestamps -> heat
counts, rating payloads -> aggregate summary. Event-specific judgment
stays with the AI agent (model.py impact convention).
"""

from collections import Counter
from datetime import date, datetime

from .. import config


def _f(v):
    try:
        if v is None or v != v:          # None or NaN
            return None
        return float(v)
    except (TypeError, ValueError):
        return None


# ---------------------------------------------------------------------------
# 公告含义（用户要求：公告一定要知道含义）
# ---------------------------------------------------------------------------
# (keyword, 含义, 短线方向提示) — first hit wins; category is scanned
# before title. Simplified + traditional (HK mirror) variants included.
ANN_MEANINGS = [
    ("业绩预告", "业绩方向指引，读幅度而非只看预增/预减", "neutral"),
    ("业绩快报", "实际业绩快报（预告的验证版）", "neutral"),
    ("财务报告", "定期财报披露（季报/中报/年报）", "neutral"),
    ("利润分配", "分红送转方案，短期含权/除权波动", "positive"),
    ("股权激励", "绑定核心团队，费用摊销压利润", "positive"),
    ("限售", "限售股上市流通（解禁），供给冲击", "negative"),
    ("减持", "股东卖出，内部人信心信号", "negative"),
    ("減持", "股东卖出，内部人信心信号", "negative"),
    ("增持", "股东买入，内部人信心信号", "positive"),
    ("回购", "公司买入自家股票（护盘或注销）", "positive"),
    ("購回", "公司买入自家股票（护盘或注销）", "positive"),
    ("定增", "向特定对象增发，摊薄现有股权", "negative"),
    ("非公开发行", "向特定对象增发，摊薄现有股权", "negative"),
    ("配售", "股份配售，摊薄现有股权", "negative"),
    ("配股", "向全体股东强制融资，摊薄", "negative"),
    ("重大合同", "订单催化，看金额占营收比", "positive"),
    ("中标", "订单催化，看金额占营收比", "positive"),
    ("收购", "外延扩张，关注对价与商誉", "neutral"),
    ("兼并", "外延扩张，关注对价与商誉", "neutral"),
    ("对外投资", "外延扩张，关注回报周期", "neutral"),
    ("关联交易", "关联方交易，需查定价公允性", "neutral"),
    ("高管变动", "管理层不确定性", "neutral"),
    ("辞职", "高管/董事辞职，管理层不确定性", "neutral"),
    ("诉讼", "或有负债", "negative"),
    ("仲裁", "或有负债", "negative"),
    ("担保", "或有负债", "negative"),
    ("质押", "股东资金链信号，高比例质押是风险", "negative"),
    ("处罚", "监管处罚", "negative"),
    ("违规", "监管风险", "negative"),
    ("立案", "监管立案调查，重大风险", "negative"),
    ("退市", "生存风险", "negative"),
    ("停牌", "流动性中断", "neutral"),
    ("复牌", "流动性恢复，常伴随补涨/补跌", "neutral"),
    ("投资者关系", "机构关注度信号", "positive"),
    ("调研", "机构关注度信号", "positive"),
    ("募集", "融资行为", "negative"),
]


def notice_meaning(category: str, title: str = "") -> tuple[str, str]:
    """公告分类 → (含义, impact 提示)；未命中返回 ("", "neutral")。"""
    for field in (category or "", title or ""):
        for kw, meaning, hint in ANN_MEANINGS:
            if kw in field:
                return meaning, hint
    return "", "neutral"


# EDGAR 披露文件类型 → 含义（US 公告，用户要求：公告一定要知道含义）
EDGAR_FORM_MEANINGS = {
    "8-K": "重大事项临时披露（并购/业绩快报/管理层变更等，看 items 字段）",
    "10-K": "年报：全年经营数据 + 审计意见",
    "10-Q": "季报",
    "20-F": "外国发行人年报（ADR 中概的'10-K'）",
    "6-K": "外国发行人临时披露（ADR 中概的'8-K'：业绩/回购/重大事项）",
    "3": "内部人持股初次声明",
    "4": "内部人交易（S=卖出 A=授予 P=买入 F=税扣，看方向与频率）",
    "4/A": "内部人交易修正",
    "25": "退市/摘牌通知",
    "25-NSE": "交易所退市通知",
    "S-1": "IPO 注册",
    "S-3": "上架注册（未来增发的弹药库）",
    "S-4": "并购换股注册",
    "S-8": "员工股权激励注册",
    "SC 13G": "被动举牌（机构持股 5%+）",
    "SC 13D": "主动举牌（进攻信号）",
    "DEF 14A": "股东大会委托书（薪酬/治理）",
    "DEFA14A": "股东大会补充委托材料",
    "424B": "招募说明书（增发摊薄）",
    "FWP": "债券发行说明书",
    "PX14A6G": "股东投票征集",
}


def form_meaning(form: str) -> str:
    """EDGAR form → 含义；精确匹配优先，其次前缀匹配（4/A 等）。"""
    f = (form or "").strip()
    if not f:
        return ""
    if f in EDGAR_FORM_MEANINGS:
        return EDGAR_FORM_MEANINGS[f]
    for k, v in EDGAR_FORM_MEANINGS.items():
        if f.startswith(k):
            return v
    return ""


# ---------------------------------------------------------------------------
# 财报速读（用户要求：财报一定要能看懂）
# ---------------------------------------------------------------------------
_PERIOD = {3: "一季报", 6: "中报", 9: "三季报", 12: "年报"}


def earnings_digest(row: dict, extras: dict | None = None) -> dict | None:
    """master/watchlist 财务列 → 白话财报速读。

    row: rev_yoy / profit_yoy / roe / gross_margin / net_margin /
    cash_conversion / report_date。extras（A 股由 a_financials +
    a_cashflow 补充）: revenue / profit（元）、deduct_eps / basic_eps、
    ocf（元）。row 缺 report_date 或增长数据 → None（caller 报缺失）。
    """
    if not row:
        return None
    rd = str(row.get("report_date") or "")[:10]
    if len(rd) < 7:
        return None
    extras = extras or {}
    try:
        month = int(rd[5:7])
    except ValueError:
        month = 0
    out = {"report_date": rd,
           "period": f"{rd[:4]}{_PERIOD.get(month, '报告期')}"}

    rev = _f(row.get("rev_yoy"))
    prof = _f(row.get("profit_yoy"))
    if rev is None and prof is None:
        return None
    out["rev_yoy"], out["profit_yoy"] = rev, prof
    g = " / ".join(x for x in (
        None if rev is None else f"营收同比 {rev:+.1f}%",
        None if prof is None else f"归母净利同比 {prof:+.1f}%") if x)
    if rev is not None and prof is not None:
        if rev > 0 and prof > 0:
            tag = "双增"
        elif rev > 0 and prof <= 0:
            tag = "增收不增利"
        elif rev <= 0 < prof:
            tag = "利润修复但收入承压"
        else:
            tag = "双降"
        g += f"（{tag}）"
    out["growth"] = g

    p = []
    for key, label in (("roe", "ROE"), ("gross_margin", "毛利率"),
                       ("net_margin", "净利率")):
        v = _f(row.get(key))
        if v is not None:
            p.append(f"{label} {v:.1f}%")
    out["profitability"] = " · ".join(p)

    q = []
    levels = []
    revenue = _f(extras.get("revenue"))
    profit = _f(extras.get("profit"))
    if revenue is not None:
        levels.append(f"营收 {revenue / 1e8:.1f} 亿")
    if profit is not None:
        levels.append(f"归母净利 {profit / 1e8:.1f} 亿")
    deduct = _f(extras.get("deduct_eps"))
    basic = _f(extras.get("basic_eps"))
    if deduct is not None and basic is not None and basic != 0:
        if basic > 0:
            ratio = deduct / basic
            q.append(f"扣非/基本EPS {deduct:.2f}/{basic:.2f}"
                     f"（扣非占{ratio:.0%}）")
            if ratio < 0.6:
                q.append("非经常性损益贡献偏高")
        else:
            q.append(f"扣非/基本EPS {deduct:.2f}/{basic:.2f}"
                      "（当期亏损，占比不适用）")
    ocf = _f(extras.get("ocf"))
    if ocf is not None and profit is not None and profit > 0:
        cash_ratio = ocf / profit
        q.append(f"OCF/净利 {cash_ratio:.2f}")
        if 0 <= cash_ratio < config.EQ_OCF_RATIO_MIN:
            q.append("利润现金含量低")
    elif ocf is not None:
        q.append(f"经营现金流 {ocf / 1e8:.1f} 亿（当期亏损或利润缺，"
                 "OCF/净利不适用）")
    else:
        cc = _f(row.get("cash_conversion"))
        if cc is not None:
            q.append(f"OCF/净利 {cc / 100:.2f}")
    out["quality"] = q
    out["levels"] = levels

    read = [out["period"] + "：" + out["growth"]]
    if out["profitability"]:
        read.append(out["profitability"])
    if q:
        read.append("；".join(q))
    if levels:
        read.append("，".join(levels))
    out["read"] = "；".join(read)
    return out


# ---------------------------------------------------------------------------
# 新闻热度（用户要求：新闻一定要有时效性）
# ---------------------------------------------------------------------------
def news_heat(items: list, asof: date | None = None) -> dict | None:
    """新闻时间线 → 热度计数（日粒度）+ 最新一条时效。

    today/3天/7天 vs 前7天 → 升温/降温/持平（短线关注边际变化，
    升温=注意力聚集，骤升往往是高潮预警）。items 新→旧由 API 保证。
    """
    if not items:
        return None
    asof = asof or date.today()
    days = [max(0, (asof - i.event_date).days) for i in items]
    today = sum(1 for d in days if d == 0)
    n3 = sum(1 for d in days if d <= 2)
    n7 = sum(1 for d in days if d <= 6)
    prior7 = sum(1 for d in days if 7 <= d <= 13)
    if n7 >= 3 and n7 >= 2 * prior7:
        verdict = "升温"
    elif prior7 >= 3 and n7 * 3 <= prior7:
        verdict = "降温"
    else:
        verdict = "持平"
    out = {"today": today, "d3": n3, "d7": n7, "prior7": prior7,
           "verdict": verdict, "latest_hours": None}
    st = str(items[0].payload.get("show_time") or "")
    try:
        t = datetime.strptime(st[:19], "%Y-%m-%d %H:%M:%S")
        out["latest_hours"] = round(
            (datetime.now() - t).total_seconds() / 3600.0, 1)
    except ValueError:
        pass
    return out


# ---------------------------------------------------------------------------
# 研报汇总（用户要求：投研报告一定要全面，且权威有参考性）
# ---------------------------------------------------------------------------
def ratings_summary(items: list) -> dict | None:
    """A 股评级列表（新→旧）→ 汇总：分布/上调下调/一致 EPS/目标价。

    每家机构只取最新一份评级（旧评级只计入上/下调计数），覆盖机构
    数量与主力机构名供 AI 判断权威性与覆盖密度。
    """
    if not items:
        return None
    by_org: dict[str, list] = {}
    for i in items:
        by_org.setdefault(i.payload.get("org") or "", []).append(i)
    dist: Counter = Counter()
    ups = downs = inits = 0
    eps_now, eps_next, tps = [], [], []
    for lst in by_org.values():
        latest = lst[0]
        r = latest.payload.get("rating") or ""
        if r:
            dist[r] += 1
        for it in lst:
            ch = str(it.payload.get("rating_change") or "")
            if ch == "2":
                ups += 1
            elif ch == "1":
                downs += 1
            elif ch == "4":
                inits += 1
        e1 = _f(latest.payload.get("eps_this_year"))
        e2 = _f(latest.payload.get("eps_next_year"))
        if e1:
            eps_now.append(e1)
        if e2:
            eps_next.append(e2)
        tp = _f(latest.payload.get("target_price"))
        if tp:
            tps.append(tp)

    def _avg(xs):
        return round(sum(xs) / len(xs), 3) if xs else None

    top = [o for o, _ in sorted(
        Counter(i.payload.get("org") or "" for i in items).items(),
        key=lambda kv: -kv[1]) if o][:3]
    return {"total": len(items), "orgs": len(by_org), "top_orgs": top,
            "distribution": dict(dist), "upgrades": ups,
            "downgrades": downs, "initiations": inits,
            "eps_this_year_avg": _avg(eps_now),
            "eps_next_year_avg": _avg(eps_next),
            "target_price_high": max(tps) if tps else None,
            "target_price_low": min(tps) if tps else None}
