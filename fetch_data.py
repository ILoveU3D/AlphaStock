# -*- coding: utf-8 -*-
"""
港美股消费板块数据拉取脚本 (v3)
================================

数据源（全部为权威公开接口，无需 API Key）：
  1. 东方财富行情接口 push2/push2his
     - ulist.np/get 批量行情（股池快照，单次请求数十只，规避单票限流）
     - clist/get 全市场行情分页（港股主板 + 美股NASDAQ/NYSE/AMEX）
     - stock/kline 日 K 线（近 300 个交易日，前复权）
  2. 腾讯行情（备用源，东财接口被限流时自动切换）
     - qt.gtimg.cn 美股OTC单票行情
     - web.ifzq.gtimg.cn 前复权日 K 线（港股/美股）
  3. 东方财富数据中心 datacenter（港股 F10 财务主要指标）
  4. 美国证监会 SEC 官方 EDGAR companyfacts（美股财务，自动选择最新概念）

v3 改进（相对 v2）：
  - 行情改为 ulist 批量接口（v2 的 stock/get 逐票拉取已被东财断连限流）
  - K线缺失时自动切换腾讯 ifzq 备用源
  - 修正股池代码: 奈雪的茶 02150(原02145)、绿茶集团 06831(原01961)、
    卫龙美味 09985(原02397) —— 原代码实为上美股份/多牛科技
  - 港股F10/美股SEC财务增量化：已有代码复用，仅补缺失部分
  - 快照 52 周高低由前复权日K计算（与行情软件不复权数值略有差异）

用法：
  python fetch_data.py              # 增量模式（推荐）
  python fetch_data.py --refresh    # 全量刷新（忽略已有数据）
  python fetch_data.py --skip-market  # 跳过全市场行情
  python fetch_data.py --fast       # 跳过全市场行情（同 --skip-market）

输出（data 目录）：
  hk_全市场行情_YYYYMMDD.csv / us_全市场行情_YYYYMMDD.csv
  消费股池快照.csv、kline/*.csv、港股财务指标.csv、美股财务指标.csv
  fetch_manifest.json

依赖：pandas、numpy、requests
"""

import argparse
import json
import sys
import time
from datetime import datetime, date, timedelta
from pathlib import Path

import numpy as np
import pandas as pd
import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

sys.stdout.reconfigure(encoding="utf-8")

BASE_DIR = Path(__file__).resolve().parent
DATA_DIR = BASE_DIR / "data"

EM_UT_LIST = "bd1d9ddb04089700cf9c27f6f7426281"
EM_UT_QUOTE = "fa5fd1943c7b386f172d6893dbfba10b"
EM_UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
         "(KHTML, like Gecko) Chrome/124.0 Safari/537.36")
SEC_HEADERS = {
    "User-Agent": "ConsumerStockResearch research.script@example.com",
    "Accept-Encoding": "gzip, deflate",
}

HK_EM_MARKET = "116"
US_EM_MARKETS = ("105", "106", "107", "138")

QUOTE_FIELDS = ("f43,f44,f45,f46,f47,f48,f57,f58,f60,f84,f85,f92,f116,f117,"
                f"f162,f163,f164,f167,f168,f169,f170,f171,f174,f175,f183,f184")

# ----------------------------------------------------------------------------
# 消费股池
# ----------------------------------------------------------------------------
HK_UNIVERSE = [
    ("02555", "茶百道", "现制茶饮"), ("02097", "蜜雪集团", "现制茶饮"),
    ("01364", "古茗", "现制茶饮"), ("02150", "奈雪的茶", "现制茶饮"),
    ("02589", "沪上阿姨", "现制茶饮"), ("01405", "达势股份", "咖啡及西式快餐"),
    ("06862", "海底捞", "火锅餐饮"), ("09658", "特海国际", "火锅餐饮"),
    ("09922", "九毛九", "中式餐饮"), ("00520", "呷哺呷哺", "火锅餐饮"),
    ("00999", "小菜园", "中式餐饮"), ("06831", "绿茶集团", "中式餐饮"),
    ("09869", "海伦司", "连锁酒馆"), ("01179", "华住集团-S", "酒店住宿"),
    ("09633", "农夫山泉", "软饮料"), ("02319", "蒙牛乳业", "乳制品"),
    ("06186", "中国飞鹤", "乳制品"), ("01717", "澳优", "乳制品"),
    ("01112", "H&H国际控股", "保健食品"), ("02460", "华润饮料", "软饮料"),
    ("00151", "中国旺旺", "休闲食品"), ("00322", "康师傅", "方便食品"),
    ("00220", "统一企业中国", "方便食品"), ("00345", "维他奶国际", "软饮料"),
    ("01876", "百威亚太", "啤酒"), ("00291", "华润啤酒", "啤酒"),
    ("00168", "青岛啤酒股份", "啤酒"), ("00506", "中国食品", "软饮料"),
    ("01458", "周黑鸭", "卤味及辣味零食"), ("09985", "卫龙美味", "卤味及辣味零食"),
    ("01929", "周大福", "黄金珠宝"), ("00116", "周生生", "黄金珠宝"),
    ("00590", "六福集团", "黄金珠宝"), ("06181", "老铺黄金", "黄金珠宝"),
    ("09992", "泡泡玛特", "潮流玩具"), ("09896", "名创优品", "潮流零售"),
    ("00178", "莎莎国际", "美妆零售"), ("02020", "安踏体育", "运动服饰"),
    ("02331", "李宁", "运动服饰"), ("01368", "特步国际", "运动服饰"),
    ("01361", "361度", "运动服饰"), ("03998", "波司登", "服装"),
    ("01044", "恒安国际", "个人护理及家居"),
]

US_UNIVERSE = [
    ("KO", "可口可乐", "饮料", "106"), ("PEP", "百事", "饮料", "105"),
    ("MNST", "怪物饮料", "饮料", "105"), ("KDP", "胡椒博士", "饮料", "105"),
    ("HSY", "好时", "零食", "106"), ("STZ", "星座品牌", "酒类", "106"),
    ("TAP", "摩森康胜", "酒类", "106"), ("BUD", "百威英博", "酒类", "106"),
    ("DEO", "帝亚吉欧", "酒类", "106"), ("GIS", "通用磨坊", "食品", "106"),
    ("MDLZ", "亿滋国际", "零食", "105"), ("LW", "蓝威斯顿", "食品", "106"),
    ("CAG", "康尼格拉", "食品", "106"), ("CPB", "金宝汤", "食品", "106"),
    ("SJM", "盛美家", "食品", "106"), ("KHC", "卡夫亨氏", "食品", "105"),
    ("HRL", "荷美尔", "食品", "106"), ("MKC", "味好美", "食品", "106"),
    ("PG", "宝洁", "个人护理及家居", "106"), ("CL", "高露洁", "个人护理及家居", "106"),
    ("KMB", "金佰利", "个人护理及家居", "106"), ("CHD", "切迟杜威", "个人护理及家居", "106"),
    ("CLX", "高乐氏", "个人护理及家居", "106"), ("UL", "联合利华", "个人护理及家居", "106"),
    ("EL", "雅诗兰黛", "美妆", "106"), ("MCD", "麦当劳", "快餐", "106"),
    ("SBUX", "星巴克", "咖啡餐饮", "105"), ("YUM", "百胜餐饮", "快餐", "106"),
    ("CMG", "奇波雷", "快餐", "106"), ("DRI", "达登餐饮", "休闲餐饮", "106"),
    ("QSR", "餐饮品牌国际", "快餐", "106"), ("WEN", "温迪", "快餐", "105"),
    ("PZZA", "棒约翰", "披萨", "105"), ("DPZ", "达美乐披萨", "披萨", "106"),
    ("EAT", "布林克餐饮", "休闲餐饮", "106"), ("YUMC", "百胜中国", "快餐", "106"),
    ("LKNCY", "瑞幸咖啡", "咖啡餐饮", "138"), ("CAVA", "CAVA", "快餐", "106"),
    ("WING", "Wingstop", "快餐", "105"), ("SHAK", "Shake Shack", "快餐", "106"),
    ("BROS", "荷兰兄弟", "咖啡餐饮", "106"), ("WMT", "沃尔玛", "商超零售", "106"),
    ("COST", "开市客", "商超零售", "105"), ("TGT", "塔吉特", "商超零售", "106"),
    ("DG", "达乐", "折扣零售", "106"), ("DLTR", "美元树", "折扣零售", "105"),
    ("ROST", "罗斯百货", "服装零售", "105"), ("TJX", "TJX", "服装零售", "106"),
    ("BURL", "伯灵顿", "服装零售", "106"), ("ULTA", "Ulta美妆", "美妆零售", "105"),
    ("FIVE", "Five Below", "杂货零售", "106"), ("HD", "家得宝", "家居零售", "106"),
    ("LOW", "劳氏", "家居零售", "106"), ("NKE", "耐克", "运动服饰", "106"),
    ("LULU", "露露乐蒙", "运动服饰", "105"), ("DECK", "德克斯户外", "运动服饰", "106"),
    ("ONON", "昂跑", "运动服饰", "106"), ("CROX", "卡骆驰", "服装鞋帽", "105"),
    ("AMZN", "亚马逊", "电商零售", "105"), ("BABA", "阿里巴巴", "电商零售", "106"),
    ("JD", "京东", "电商零售", "105"), ("PDD", "拼多多", "电商零售", "105"),
]


def hk_board(industry: str) -> str:
    staples = {"软饮料", "乳制品", "保健食品", "休闲食品", "方便食品", "啤酒",
               "卤味及辣味零食", "个人护理及家居", "食品"}
    return "必选消费" if industry in staples else "可选消费"


def us_board(name_cn: str) -> str:
    if any(k in name_cn for k in ("阿里", "京东", "拼多")):
        return "中概消费"
    return "可选消费"


# ----------------------------------------------------------------------------
# HTTP 层：Retry 适配器 + 连续失败冷却
# ----------------------------------------------------------------------------
class Fetcher:
    """带自动重试与限流冷却的 HTTP 客户端"""

    def __init__(self, headers, name="http"):
        self.name = name
        self.consecutive_fail = 0
        self.session = requests.Session()
        self.session.headers.update(headers)
        retry = Retry(total=4, connect=4, read=4, backoff_factor=1.2,
                      status_forcelist=[429, 500, 502, 503, 504],
                      allowed_methods=frozenset(["GET", "HEAD"]))
        adapter = HTTPAdapter(max_retries=retry, pool_connections=8,
                               pool_maxsize=8)
        self.session.mount("https://", adapter)
        self.session.mount("http://", adapter)

    def get_json(self, url, params=None, timeout=20, retries=2,
                 cooldown_after=5, cooldown_sec=75):
        """GET -> JSON。连续失败达到阈值后自动冷却等待。"""
        last_err = None
        attempt = 0
        total_attempts = retries + 1
        while attempt < total_attempts:
            attempt += 1
            try:
                r = self.session.get(url, params=params, timeout=timeout)
                if r.status_code == 200:
                    self.consecutive_fail = 0
                    return r.json()
                if r.status_code == 404:
                    self.consecutive_fail = 0
                    return None
                last_err = f"HTTP {r.status_code}"
            except Exception as e:  # noqa: BLE001
                last_err = f"{type(e).__name__}: {str(e)[:120]}"
            self.consecutive_fail += 1
            if self.consecutive_fail >= cooldown_after and attempt < total_attempts:
                print(f"    [冷却] {self.name} 连续{self.consecutive_fail}次失败"
                      f"({last_err}), 等待{cooldown_sec}s...")
                time.sleep(cooldown_sec)
            else:
                time.sleep(2.0 * attempt)
        print(f"    [警告] {self.name} 请求失败: {url[:70]} -> {last_err}")
        return None


EM = Fetcher({"User-Agent": EM_UA}, "EM")
DC = Fetcher({"User-Agent": EM_UA}, "DC")
SEC = Fetcher(SEC_HEADERS, "SEC")
TX = Fetcher({"User-Agent": EM_UA}, "TX")   # 腾讯行情(备用源)

# push2 镜像主机轮换(行情类接口, http协议; https 会被断连)
EM_PUSH2_HOSTS = ["push2.eastmoney.com", "33.push2.eastmoney.com",
                  "17.push2.eastmoney.com", "88.push2.eastmoney.com"]
_em_host_i = 0


def em_push2_url(path: str) -> str:
    global _em_host_i
    _em_host_i = (_em_host_i + 1) % len(EM_PUSH2_HOSTS)
    return f"http://{EM_PUSH2_HOSTS[_em_host_i]}{path}"


def num(v):
    if v is None or v == "-" or v == "":
        return None
    try:
        f = float(v)
        return f if f == f else None
    except (TypeError, ValueError):
        return None


# ----------------------------------------------------------------------------
# 行情/K线
# ----------------------------------------------------------------------------
def fetch_quote(secid: str) -> dict | None:
    # 注: push2 的 stock/get 走 https 会被断连, 必须用 http
    d = EM.get_json("http://push2.eastmoney.com/api/qt/stock/get", params={
        "secid": secid, "fields": QUOTE_FIELDS,
        "ut": EM_UT_QUOTE, "invt": 2, "fltt": 2,
    })
    data = (d or {}).get("data")
    if not data or data.get("f43") in (None, "-"):
        return None
    return {
        "最新价": num(data.get("f43")),
        "今日最高": num(data.get("f44")),
        "今日最低": num(data.get("f45")),
        "今开": num(data.get("f46")),
        "成交量": num(data.get("f47")),
        "成交额": num(data.get("f48")),
        "昨收": num(data.get("f60")),
        "总股本": num(data.get("f84")),
        "市盈率(动)": num(data.get("f162")),
        "市盈率(静)": num(data.get("f163")),
        "市盈率TTM": num(data.get("f164")),
        "市净率": num(data.get("f167")),
        "换手率%": num(data.get("f168")),
        "涨跌幅%": num(data.get("f170")),
        "涨跌额": num(data.get("f171")),
        "52周最高(不复权)": num(data.get("f174")),
        "52周最低(不复权)": num(data.get("f175")),
        "总市值": num(data.get("f116")),
        "流通市值": num(data.get("f117")),
    }


def fetch_kline(secid: str, lmt: int = 300) -> pd.DataFrame | None:
    # 注: push2his 走 https 会被断连, 必须用 http
    d = EM.get_json("http://push2his.eastmoney.com/api/qt/stock/kline/get",
                    params={
                        "secid": secid, "fields1": "f1,f2,f3,f4,f5,f6",
                        "fields2": "f51,f52,f53,f54,f55,f56,f57,f58",
                        "klt": "101", "fqt": "1", "end": "20500101",
                        "lmt": lmt, "ut": EM_UT_LIST,
                    })
    klines = ((d or {}).get("data") or {}).get("klines") or []
    if not klines:
        return None
    rows = []
    for line in klines:
        p = line.split(",")
        if len(p) < 8:
            continue
        rows.append({"日期": p[0], "开盘": float(p[1]), "收盘": float(p[2]),
                     "最高": float(p[3]), "最低": float(p[4]),
                     "成交量": float(p[5]), "成交额": float(p[6]),
                     "振幅%": float(p[7])})
    return pd.DataFrame(rows)


# ----------------------------------------------------------------------------
# v3: 批量行情 (ulist.np/get, 单次可请求数十只, 绕过 stock/get 限流)
# ----------------------------------------------------------------------------
ULIST_FIELDS = ("f2,f3,f4,f5,f6,f8,f9,f12,f13,f14,f15,f16,f17,f18,"
                "f20,f21,f23,f114,f115")


def fetch_quotes_ulist(secids: list) -> dict:
    """批量行情: {代码: 行情dict}。代码取返回值 f12。"""
    out = {}
    for i in range(0, len(secids), 40):
        chunk = secids[i:i + 40]
        d = EM.get_json("http://push2.eastmoney.com/api/qt/ulist.np/get",
                        params={"secids": ",".join(chunk), "fields": ULIST_FIELDS,
                                "ut": EM_UT_LIST, "fltt": 2, "invt": 2,
                                "pn": 1, "np": 1, "po": 0, "fid": "f12"},
                        retries=3)
        diff = ((d or {}).get("data") or {}).get("diff") or []
        for r in diff:
            code = str(r.get("f12", ""))
            price = num(r.get("f2"))
            if not code or price is None:
                continue
            mcap, flt = num(r.get("f20")), num(r.get("f21"))
            out[code] = {
                "名称(源)": str(r.get("f14", "")),
                "最新价": price,
                "今日最高": num(r.get("f15")),
                "今日最低": num(r.get("f16")),
                "今开": num(r.get("f17")),
                "成交量": num(r.get("f5")),
                "成交额": num(r.get("f6")),
                "昨收": num(r.get("f18")),
                "总股本": round(mcap / price) if (mcap and price) else None,
                "市盈率(动)": num(r.get("f9")),
                "市盈率(静)": num(r.get("f114")),
                "市盈率TTM": num(r.get("f115")),
                "市净率": num(r.get("f23")),
                "换手率%": num(r.get("f8")),
                "涨跌幅%": num(r.get("f3")),
                "涨跌额": num(r.get("f4")),
                "总市值": mcap,
                "流通市值": flt,
            }
        time.sleep(1.0)
    return out


# ----------------------------------------------------------------------------
# v3: 腾讯行情/K线 (东财 stock/get 与 kline/get 被断连时的备用源)
# ----------------------------------------------------------------------------
TX_UA = {"User-Agent": "Mozilla/5.0"}
TX_KLINE_URL = "https://web.ifzq.gtimg.cn/appstock/app/fqkline/get"
# 东财市场代码 -> 腾讯美股后缀
US_TX_SUFFIX = {"105": "OQ", "106": "N", "107": "A", "138": "PS"}


def _tx_get(url, params, timeout=15):
    try:
        r = TX.session.get(url, params=params, timeout=timeout)
        if r.status_code == 200:
            return r.json()
    except Exception:  # noqa: BLE001
        pass
    return None


def _tx_text(url, timeout=10):
    try:
        r = TX.session.get(url, timeout=timeout)
        if r.status_code == 200:
            r.encoding = "gbk"
            return r.text
    except Exception:  # noqa: BLE001
        pass
    return None


def tx_kline_symbol(mkt: str, code: str, em_mkt: str) -> list:
    """腾讯K线代码候选列表(按可能性排序)"""
    if mkt == "港股":
        return [f"hk{code}"]
    suf = US_TX_SUFFIX.get(em_mkt, "N")
    cands = [f"us{code}.{suf}"]
    for s in ("N", "OQ", "A", "PS"):
        if f".{s}" not in cands[0]:
            cands.append(f"us{code}.{s}")
    cands.append(f"us{code}")
    return cands


def fetch_kline_tx(symbol: str, lmt: int = 320) -> pd.DataFrame | None:
    """腾讯前复权日K -> 与东财K线同构的 DataFrame"""
    d = _tx_get(TX_KLINE_URL, {"param": f"{symbol},day,,,{lmt},qfq"})
    data = ((d or {}).get("data") or {}).get(symbol) or {}
    klines = data.get("qfqday") or data.get("day") or []
    if not klines:
        return None
    rows, prev = [], None
    for k in klines:
        try:
            p = [str(x) for x in k]
            if len(p) < 6:
                continue
            o, c = float(p[1]), float(p[2])
            hi, lo = float(p[3]), float(p[4])
            vol = float(p[5])
            amt = float(p[6]) if len(p) > 6 and _num_ok(p[6]) else None
            amp = round((hi - lo) / prev * 100, 2) if prev else None
            rows.append({"日期": p[0], "开盘": o, "收盘": c, "最高": hi,
                         "最低": lo, "成交量": vol, "成交额": amt, "振幅%": amp})
            prev = c if c else prev
        except (ValueError, TypeError):
            continue
    return pd.DataFrame(rows) if rows else None


def _num_ok(s) -> bool:
    try:
        float(s)
        return True
    except (TypeError, ValueError):
        return False


def fetch_quote_tx_us(ticker: str) -> dict | None:
    """腾讯美股单票行情(东财未覆盖的OTC等)"""
    for code in (f"us{ticker}", f"us{ticker}.PS"):
        txt = _tx_text("https://qt.gtimg.cn/q=" + code)
        if not txt or "none_match" in txt:
            continue
        body = txt.split('"')
        if len(body) < 2:
            continue
        f = body[1].split("~")
        if len(f) < 63:
            continue
        price = num(f[3])
        if price is None:
            continue
        mcap = num(f[44])
        flt = num(f[45])
        return {
            "名称(源)": f[1], "最新价": price, "昨收": num(f[4]),
            "今开": num(f[5]), "成交量": num(f[6]),
            "今日最高": num(f[33]), "今日最低": num(f[34]),
            "总市值": (mcap * 1e8) if mcap else None,
            "总股本": num(f[62]), "市盈率TTM": num(f[39]),
            "市盈率(动)": num(f[39]), "市盈率(静)": num(f[41]),
            "市净率": num(f[43]), "涨跌幅%": num(f[32]),
            "涨跌额": num(f[31]), "换手率%": num(f[8]),
            "成交额": num(f[37]),
            "流通市值": (flt * 1e8) if flt else None,
        }
    return None


def fetch_fx_hkdcny() -> float:
    """港元兑人民币: 先东财ulist, 再近似值"""
    d = EM.get_json("http://push2.eastmoney.com/api/qt/ulist.np/get",
                    params={"secids": "133.HKDCNH,133.HKDCNY",
                            "fields": "f2,f12,f13", "ut": EM_UT_QUOTE,
                            "fltt": 2, "invt": 2, "pn": 1, "np": 1},
                    retries=2)
    diff = ((d or {}).get("data") or {}).get("diff") or []
    for r in diff:
        p = num(r.get("f2"))
        if p and 0.5 < p < 2.0:
            print(f"    港元兑人民币汇率: {r.get('f12')} = {p}")
            return p
    print("    [提示] 未取到港元汇率, 使用近似值 0.92")
    return 0.92


def fetch_full_market(fs: str, out_csv: Path, label: str) -> pd.DataFrame | None:
    fields = ("f2,f3,f4,f5,f6,f8,f9,f12,f13,f14,f15,f16,f17,f18,"
              "f20,f21,f23,f114,f115")
    all_rows, pn = [], 1
    while True:
        d = EM.get_json(em_push2_url("/api/qt/clist/get"),
                        params={
                            "pn": pn, "pz": 100, "po": 0, "np": 1, "fltt": 2,
                            "invt": 2, "fid": "f12", "fs": fs,
                            "fields": fields, "ut": EM_UT_LIST,
                        }, retries=3)
        data = (d or {}).get("data") or {}
        rows = data.get("diff") or []
        if not rows:
            break
        all_rows.extend(rows)
        total = data.get("total", 0)
        if pn % 10 == 0 or len(all_rows) >= total:
            print(f"    {label} 已获取 {len(all_rows)}/{total}")
        if len(all_rows) >= total:
            break
        pn += 1
        time.sleep(0.6)
    if not all_rows:
        return None
    df = pd.DataFrame(all_rows).rename(columns={
        "f12": "代码", "f14": "名称", "f13": "市场代码",
        "f2": "最新价", "f3": "涨跌幅%", "f4": "涨跌额",
        "f5": "成交量", "f6": "成交额", "f8": "换手率%",
        "f9": "市盈率(动)", "f15": "最高", "f16": "最低", "f17": "今开",
        "f18": "昨收", "f20": "总市值", "f21": "流通市值", "f23": "市净率",
        "f114": "市盈率(静)", "f115": "市盈率TTM",
    })
    df = df[["市场代码", "代码", "名称", "最新价", "涨跌幅%", "涨跌额", "今开",
             "最高", "最低", "昨收", "成交量", "成交额", "换手率%",
             "市盈率(动)", "市盈率TTM", "市盈率(静)", "市净率", "总市值",
             "流通市值"]]
    for c in df.columns:
        if c not in ("市场代码", "代码", "名称"):
            df[c] = df[c].map(num)
    df.to_csv(out_csv, index=False, encoding="utf-8-sig")
    print(f"    已保存 {out_csv.name}: {len(df)} 行")
    return df


# ----------------------------------------------------------------------------
# 港股 F10
# ----------------------------------------------------------------------------
HK_F10_KEEP = {
    "SECUCODE": "证券代码", "SECURITY_NAME_ABBR": "名称",
    "REPORT_DATE": "报告期", "REPORT_TYPE": "报告类型",
    "OPERATE_INCOME": "营业收入", "OPERATE_INCOME_YOY": "营业收入同比%",
    "HOLDER_PROFIT": "归母净利润", "HOLDER_PROFIT_YOY": "归母净利润同比%",
    "GROSS_PROFIT": "毛利", "GROSS_PROFIT_RATIO": "毛利率%",
    "NET_PROFIT_RATIO": "净利率%", "ROE_AVG": "ROE%", "ROA": "ROA%",
    "BASIC_EPS": "基本EPS", "BPS": "每股净资产",
    "DPS_HKD": "每股股息HKD", "DIVIDEND_RATE": "股息率%",
    "TOTAL_MARKET_CAP": "报告期市值", "PE_TTM": "报告期PE_TTM",
    "PB_TTM": "报告期PB", "DEBT_ASSET_RATIO": "资产负债率%",
    "NETCASH_OPERATE": "经营现金流净额", "END_CASH": "期末现金",
    "DATE_TYPE_CODE": "报告期类型",
}


def fetch_hk_f10(code5: str) -> pd.DataFrame | None:
    d = DC.get_json("https://datacenter.eastmoney.com/securities/api/data/v1/get",
                    params={
                        "reportName": "RPT_HKF10_FN_MAININDICATOR",
                        "columns": "ALL", "filter": f'(SECUCODE="{code5}.HK")',
                        "pageNumber": 1, "pageSize": 12,
                        "sortTypes": "-1", "sortColumns": "REPORT_DATE",
                        "source": "F10", "client": "PC",
                    })
    rows = ((d or {}).get("result") or {}).get("data") or []
    if not rows:
        return None
    df = pd.DataFrame(rows)
    df = df[[c for c in HK_F10_KEEP if c in df.columns]]
    df = df.rename(columns=HK_F10_KEEP)
    df["报告期"] = df["报告期"].astype(str).str.slice(0, 10)
    return df


# ----------------------------------------------------------------------------
# 美股财务：SEC EDGAR companyfacts + 概念自动选择
# ----------------------------------------------------------------------------
CURRENCIES = {"USD", "EUR", "GBP", "CHF", "CAD", "JPY", "AUD", "SEK", "NOK",
              "CNY", "MXN", "BRL", "ZAR", "SGD", "HKD", "DKK", "INR", "KRW"}

REV_NAMES = ["Revenues", "RevenueFromContractWithCustomerExcludingAssessedTax",
             "RevenueFromContractWithCustomerIncludingAssessedTax",
             "RevenueFromContractsWithCustomers", "Revenue",
             "RevenueFromContractWithCustomer", "SalesRevenueNet",
             "SalesRevenueGoodsNet"]
NI_NAMES = ["NetIncomeLoss", "ProfitLoss",
            "NetIncomeLossAvailableToCommonStockholdersBasic"]
EQ_NAMES = ["StockholdersEquity", "Equity",
            "StockholdersEquityIncludingPortionAttributableToNoncontrollingInterest"]


def _duration_days(entry) -> int:
    try:
        s = date.fromisoformat(entry["start"])
        e = date.fromisoformat(entry["end"])
        return (e - s).days
    except Exception:  # noqa: BLE001
        return 0


def _annual_entries(arr):
    return [e for e in arr
            if e.get("form") in ("10-K", "20-F") and _duration_days(e) >= 300]


def _dedup_by_end(entries):
    out = {}
    for e in entries:
        k = e["end"]
        if k not in out or e.get("filed", "") >= out[k].get("filed", ""):
            out[k] = e
    return [out[k] for k in sorted(out)]


def pick_concept(facts: dict, names: list):
    """在 companyfacts 中选择‘最新报告期最新’的概念"""
    best = None  # (latest_end, tax, name, unit, annual_entries)
    for tax in ("us-gaap", "ifrs-full"):
        taxo = (facts.get("facts") or {}).get(tax) or {}
        for name in names:
            cdef = taxo.get(name)
            if not cdef:
                continue
            for unit, arr in (cdef.get("units") or {}).items():
                if unit not in CURRENCIES:
                    continue
                ann = _dedup_by_end(_annual_entries(arr))
                if not ann:
                    continue
                latest_end = ann[-1]["end"]
                if best is None or latest_end > best[0]:
                    best = (latest_end, tax, name, unit, ann)
    return best


def quarter_yoy_from_facts(facts: dict, best_rev):
    """用选中收入概念的全部条目计算最新季度同比"""
    if not best_rev:
        return None, None
    _end, tax, name, _unit, _ann = best_rev
    cdef = ((facts.get("facts") or {}).get(tax) or {}).get(name) or {}
    quarters = []
    for unit, arr in (cdef.get("units") or {}).items():
        if unit not in CURRENCIES:
            continue
        for e in arr:
            days = _duration_days(e)
            if 80 <= days <= 100 and e.get("form") in ("10-Q", "10-K"):
                quarters.append(e)
    if not quarters:
        return None, None
    quarters.sort(key=lambda x: x["end"])
    latest = quarters[-1]
    try:
        s = date.fromisoformat(latest["start"])
        e = date.fromisoformat(latest["end"])
        py_s = s.replace(year=s.year - 1).isoformat()
        py_e = e.replace(year=e.year - 1).isoformat()
        for cand in quarters:
            if cand["start"] == py_s and cand["end"] == py_e:
                base, cur = cand.get("val"), latest.get("val")
                if base and cur and base != 0:
                    return (cur - base) / abs(base) * 100.0, latest["end"]
    except Exception:  # noqa: BLE001
        pass
    return None, latest["end"]


def fetch_us_fundamentals_cf(ticker: str, cik: int) -> dict | None:
    d = SEC.get_json(
        f"https://data.sec.gov/api/xbrl/companyfacts/CIK{cik:010d}.json",
        timeout=90, retries=3)
    if not d or not d.get("facts"):
        return None

    best_rev = pick_concept(d, REV_NAMES)
    best_ni = pick_concept(d, NI_NAMES)
    best_eq = pick_concept(d, EQ_NAMES)
    if not best_rev and not best_ni:
        return None

    def series(best, shift=0):
        if not best or len(best[4]) <= shift:
            return None, None
        e = best[4][-(1 + shift)]
        return e.get("val"), e["end"]

    def yoy(best):
        if not best or len(best[4]) < 2:
            return None
        prev, cur = best[4][-2].get("val"), best[4][-1].get("val")
        if prev and cur and prev != 0:
            return (cur - prev) / abs(prev) * 100.0
        return None

    rev0, rev_end = series(best_rev)
    rev1, _ = series(best_rev, 1)
    ni0, _ = series(best_ni)
    ni1, _ = series(best_ni, 1)
    eq0, _ = series(best_eq)
    eq1, _ = series(best_eq, 1)
    q_yoy, q_end = quarter_yoy_from_facts(d, best_rev)

    cur = (best_rev[3] if best_rev else
           (best_ni[3] if best_ni else None))
    row = {
        "代码": ticker,
        "最新财年期末": rev_end,
        "币种": cur,
        "营业收入(最新财年)": rev0,
        "营业收入(上年)": rev1,
        "营收同比%": yoy(best_rev),
        "净利润(最新财年)": ni0,
        "净利润(上年)": ni1,
        "净利润同比%": yoy(best_ni),
        "股东权益(最新)": eq0,
        "股东权益(上年)": eq1,
        "最新季度营收同比%": q_yoy,
        "最新季度期末": q_end,
    }
    return row


def load_sec_cik_map() -> dict:
    d = SEC.get_json("https://www.sec.gov/files/company_tickers.json",
                     timeout=30)
    if not d:
        return {}
    return {v["ticker"].upper(): v["cik_str"] for v in d.values()}


# ----------------------------------------------------------------------------
# 增量逻辑
# ----------------------------------------------------------------------------
def existing_snapshot(data_dir: Path) -> pd.DataFrame | None:
    p = data_dir / "消费股池快照.csv"
    if not p.exists():
        return None
    try:
        return pd.read_csv(p, dtype={"代码": str})
    except Exception:  # noqa: BLE001
        return None


def kline_is_fresh(path: Path, market: str) -> bool:
    """K线最后一根是否足够新(美股3个自然日内, 港股当日)"""
    if not path.exists():
        return False
    try:
        kl = pd.read_csv(path)
        if kl.empty:
            return False
        last = date.fromisoformat(str(kl.iloc[-1]["日期"])[:10])
        today = date.today()
        days = (today - last).days
        return days <= (0 if market == "港股" else 3)
    except Exception:  # noqa: BLE001
        return False


# ----------------------------------------------------------------------------
# 主流程
# ----------------------------------------------------------------------------
def main():
    ap = argparse.ArgumentParser(description="港美股消费板块数据拉取 v2")
    ap.add_argument("--refresh", action="store_true", help="忽略已有数据, 全量刷新")
    ap.add_argument("--skip-market", action="store_true", help="跳过全市场行情")
    ap.add_argument("--fast", action="store_true",
                    help="同 --skip-market(兼容v1参数)")
    ap.add_argument("--data-dir", default=str(DATA_DIR))
    args = ap.parse_args()
    skip_market = args.skip_market or args.fast

    data_dir = Path(args.data_dir)
    kline_dir = data_dir / "kline"
    kline_dir.mkdir(parents=True, exist_ok=True)

    t0 = time.time()
    print("=" * 72)
    print("港美股消费板块数据拉取脚本 v3 (批量行情+腾讯备用源+增量)")
    print(f"模式: {'全量刷新' if args.refresh else '增量'}"
          f"{', 跳过全市场' if skip_market else ', 含全市场行情'}")
    print(f"输出目录: {data_dir}")
    print("=" * 72)

    manifest = {"start_time": datetime.now().isoformat(timespec="seconds"),
                "mode": "refresh" if args.refresh else "incremental",
                "failures": [], "reused": [],
                "sources": ["东方财富 push2 ulist 批量行情",
                            "东方财富 push2his 日K",
                            "腾讯行情/ifzq 日K (备用源)",
                            "东方财富 datacenter 港股F10",
                            "SEC EDGAR companyfacts"]}

    # ---- 0. 汇率 ----
    print("\n[0/6] 探测港元兑人民币汇率...")
    fx = fetch_fx_hkdcny()
    manifest["fx_hkdcny"] = fx

    # ---- 1. 消费股池行情 (批量) + 日K (增量, 腾讯补缺) ----
    print(f"\n[1/6] 消费股池行情 (港股{len(HK_UNIVERSE)}+美股{len(US_UNIVERSE)}只, "
          f"ulist批量+腾讯备用)...")
    hk_secids = [f"{HK_EM_MARKET}.{c}" for c, _, _ in HK_UNIVERSE]
    us_secids = [f"{m}.{t}" for t, _, _, m in US_UNIVERSE]
    quotes = fetch_quotes_ulist(hk_secids)
    quotes.update(fetch_quotes_ulist(us_secids))

    # 缺失行情重试一轮(限流可能是瞬时的)
    missing_us = [t for t, _, _, _ in US_UNIVERSE if t not in quotes]
    missing_hk = [c for c, _, _ in HK_UNIVERSE if c not in quotes]
    if missing_us or missing_hk:
        retry_ids = ([f"{m}.{t}" for t, _, _, m in US_UNIVERSE if t in missing_us]
                     + [f"{HK_EM_MARKET}.{c}" for c in missing_hk])
        print(f"    重试缺失行情 {len(retry_ids)} 只...")
        time.sleep(5)
        quotes.update(fetch_quotes_ulist(retry_ids))
    print(f"    ulist批量行情: 港股 {sum(1 for c,_,_ in HK_UNIVERSE if c in quotes)}"
          f"/{len(HK_UNIVERSE)}, 美股 {sum(1 for t,_,_,_ in US_UNIVERSE if t in quotes)}"
          f"/{len(US_UNIVERSE)}")

    tasks = ([("港股", c, n, i, f"{HK_EM_MARKET}.{c}")
              for c, n, i in HK_UNIVERSE]
             + [("美股", t, n, i, f"{m}.{t}")
                for t, n, i, m in US_UNIVERSE])
    snap_rows = []
    for mkt, code, name, industry, secid in tasks:
        em_mkt = secid.split(".")[0]
        q = quotes.get(code)
        if q is None and mkt == "美股":
            q = fetch_quote_tx_us(code)
            if q:
                manifest["reused"].append(f"US {code} {name}: 腾讯备用源行情")
        if q is None:
            manifest["failures"].append(f"{mkt} {code} {name}: 行情获取失败")
            continue
        src_name = q.pop("名称(源)", "")
        if src_name and src_name != name:
            print(f"    [注意] {code} 股池名称[{name}] 与源名称[{src_name}] 不一致")
        row = {"市场": mkt, "代码": code, "名称": name,
               "板块": hk_board(industry) if mkt == "港股" else us_board(name),
               "细分行业": industry,
               "货币": "HKD" if mkt == "港股" else "USD", **q}
        snap_rows.append(row)

    # ---- 1b. 日K: 复用新鲜文件, 缺失/过期 -> 东财 -> 腾讯 ----
    print(f"\n[1b/6] 日K线补齐 (增量)...")
    em_kline_dead = False   # EM K线连续失败探测(被限流时自动放弃, 直接走腾讯)
    em_kline_fails = 0
    for mkt, code, name, industry, secid in tasks:
        kfile = kline_dir / f"{mkt}_{code}.csv"
        em_mkt = secid.split(".")[0]
        if kline_is_fresh(kfile, mkt):
            continue
        kl = None
        src = ""
        if not em_kline_dead:
            if mkt == "港股":
                kl = fetch_kline(secid)
                src = "东财"
            else:
                for m in (em_mkt,) + tuple(x for x in US_EM_MARKETS if x != em_mkt):
                    kl = fetch_kline(f"{m}.{code}")
                    if kl is not None:
                        src = "东财"
                        break
                    kl = None
        if kl is None:
            em_kline_fails += 1
            if em_kline_fails >= 3 and not em_kline_dead:
                em_kline_dead = True
                print("    [提示] EM日K连续失败(限流), 后续直接使用腾讯备用源")
            for sym in tx_kline_symbol(mkt, code, em_mkt):
                kl = fetch_kline_tx(sym)
                if kl is not None:
                    src = f"腾讯({sym})"
                    break
        else:
            em_kline_fails = 0
        if kl is not None and len(kl) >= 100:
            kl.to_csv(kfile, index=False, encoding="utf-8-sig")
            print(f"    {code} {name}: K线 {len(kl)}根 [{src}] 末{kl.iloc[-1]['日期']}")
        else:
            manifest["failures"].append(f"{mkt} {code} {name}: K线获取失败")

    # ---- 1c. 快照补52周高低(前复权, 由K线计算) ----
    for row in snap_rows:
        kfile = kline_dir / f"{row['市场']}_{row['代码']}.csv"
        hi = lo = None
        if kfile.exists():
            try:
                kl = pd.read_csv(kfile)
                if not kl.empty and "收盘" in kl.columns:
                    close = kl["收盘"].astype(float).to_numpy()
                    w52 = close[-252:] if len(close) >= 252 else close
                    hi, lo = float(np.max(w52)), float(np.min(w52))
            except Exception:  # noqa: BLE001
                pass
        row["52周最高(前复权)"] = round(hi, 4) if hi else None
        row["52周最低(前复权)"] = round(lo, 4) if lo else None

    if snap_rows:
        pd.DataFrame(snap_rows).to_csv(data_dir / "消费股池快照.csv",
                                       index=False, encoding="utf-8-sig")
    manifest["universe_rows"] = len(snap_rows)
    n_kline = sum(1 for mkt, code, *_ in tasks
                  if (kline_dir / f"{mkt}_{code}.csv").exists())
    print(f"    快照完成: {len(snap_rows)} 只, K线文件 {n_kline}/{len(tasks)}")

    # ---- 2. 港股 F10 (增量: 已有代码复用, 仅补缺) ----
    fin_path = data_dir / "港股财务指标.csv"
    old_fin = None
    if fin_path.exists() and not args.refresh:
        try:
            old_fin = pd.read_csv(fin_path, dtype={"证券代码": str})
        except Exception:  # noqa: BLE001
            old_fin = None
    have = set()
    if old_fin is not None:
        have = {str(c).split(".")[0].zfill(5) for c in old_fin["证券代码"]}
    todo_fin = [(c, n) for c, n, _ in HK_UNIVERSE if c not in have]
    if old_fin is not None and not todo_fin:
        manifest["reused"].append(f"港股财务指标.csv ({len(old_fin)}行)")
        print(f"\n[2/6] 港股F10财务: 复用已有 {len(old_fin)} 行")
    elif todo_fin:
        print(f"\n[2/6] 港股F10财务 (补缺 {len(todo_fin)} 只: "
              f"{', '.join(c for c, _ in todo_fin)})...")
        frames = ([old_fin] if old_fin is not None else [])
        for code, name in todo_fin:
            try:
                df = fetch_hk_f10(code)
                if df is None or df.empty:
                    manifest["failures"].append(f"HK {code} {name}: F10无数据")
                    continue
                frames.append(df)
                latest = df.iloc[0]
                print(f"    {code} {name}: {latest.get('报告类型')} "
                      f"营收同比{latest.get('营业收入同比%')} ROE{latest.get('ROE%')}")
            except Exception as e:  # noqa: BLE001
                manifest["failures"].append(f"HK {code} {name}: F10异常 {e}")
            time.sleep(0.5)
        if len(frames) > (1 if old_fin is not None else 0):
            fin = pd.concat(frames, ignore_index=True)
            fin.to_csv(fin_path, index=False, encoding="utf-8-sig")
            manifest["hk_financial_rows"] = len(fin)
            print(f"    港股财务指标: 共 {len(fin)} 个报告期")

    # ---- 3. 美股财务 SEC companyfacts (已有则复用) ----
    us_fin_path = data_dir / "美股财务指标.csv"
    reuse_us = False
    if us_fin_path.exists() and not args.refresh:
        try:
            old_us = pd.read_csv(us_fin_path, dtype={"代码": str})
            covered = {str(t).upper() for t in old_us["代码"]}
            miss_us = [t for t, _, _, _ in US_UNIVERSE
                       if t.upper() not in covered]
            if len(miss_us) <= 2:
                manifest["reused"].append(f"美股财务指标.csv ({len(old_us)}行)")
                print(f"\n[3/6] 美股财务: 复用已有 {len(old_us)} 行 (缺 {miss_us})")
                manifest["us_financial_rows"] = len(old_us)
                reuse_us = True
        except Exception:  # noqa: BLE001
            reuse_us = False
    us_rows = []
    if not reuse_us:
        print(f"\n[3/6] 美股财务 (SEC EDGAR companyfacts, {len(US_UNIVERSE)}只)...")
        print("    下载 SEC 代码映射...")
        cik_map = load_sec_cik_map()
        if not cik_map:
            print("    [警告] SEC映射获取失败")
        for ticker, name, _ind, _m in US_UNIVERSE:
            cik = cik_map.get(ticker)
            if not cik:
                manifest["failures"].append(f"US {ticker} {name}: SEC无CIK映射")
                continue
            try:
                row = fetch_us_fundamentals_cf(ticker, cik)
                if row is None:
                    manifest["failures"].append(f"US {ticker} {name}: companyfacts无财务")
                    continue
                row["名称"] = name
                us_rows.append(row)
                print(f"    {ticker} {name}: FY末 {row['最新财年期末']} "
                      f"币种{row['币种']} 营收同比 "
                      f"{round(row['营收同比%'], 1) if row['营收同比%'] is not None else '-'}%")
            except Exception as e:  # noqa: BLE001
                manifest["failures"].append(f"US {ticker} {name}: SEC异常 {e}")
            time.sleep(0.25)
        if us_rows:
            us_fin = pd.DataFrame(us_rows)
            us_fin.to_csv(us_fin_path, index=False, encoding="utf-8-sig")
            manifest["us_financial_rows"] = len(us_fin)
            print(f"    美股财务指标: {len(us_fin)} 只")

    # ---- 4/5. 全市场行情 (最后, 非阻塞) ----
    if not skip_market:
        print("\n[4/6] 港股全市场行情 (东财, 分页约180页)...")
        hk_all = fetch_full_market("m:128",
                                   data_dir / f"hk_全市场行情_{date.today():%Y%m%d}.csv",
                                   "港股")
        manifest["hk_market_rows"] = len(hk_all) if hk_all is not None else 0
        print("\n[5/6] 美股全市场行情 (东财, 分页约138页)...")
        us_all = fetch_full_market("m:105,m:106,m:107,m:138",
                                   data_dir / f"us_全市场行情_{date.today():%Y%m%d}.csv",
                                   "美股")
        manifest["us_market_rows"] = len(us_all) if us_all is not None else 0
    else:
        print("\n[4/6][5/6] 跳过全市场行情")

    # ---- 6. 清单 ----
    manifest["end_time"] = datetime.now().isoformat(timespec="seconds")
    manifest["elapsed_sec"] = round(time.time() - t0, 1)
    with open(data_dir / "fetch_manifest.json", "w", encoding="utf-8") as f:
        json.dump(manifest, f, ensure_ascii=False, indent=2)

    print("\n" + "=" * 72)
    print("拉取完成!")
    print(f"  用时 {manifest['elapsed_sec']}s | 快照 {manifest.get('universe_rows', 0)} 只"
          f" (复用 {manifest.get('universe_reused', 0)})")
    print(f"  美股财务 {manifest.get('us_financial_rows', 0)} 只 | "
          f"失败 {len(manifest['failures'])} 条")
    print(f"  全市场: 港股 {manifest.get('hk_market_rows', '-')} 行, "
          f"美股 {manifest.get('us_market_rows', '-')} 行")
    print("=" * 72)


if __name__ == "__main__":
    main()
