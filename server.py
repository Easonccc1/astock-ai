# -*- coding: utf-8 -*-
"""
A股新手课堂 - 本地服务（零依赖，仅用 Python 标准库）
功能：
  1) 托管当前目录下的静态网页
  2) 代理真实行情，绕开浏览器跨域(Referer/CORS)限制
     - 主数据源：新浪财经 hq.sinajs.cn
     - 备用数据源：东方财富 push2.eastmoney.com
运行：
  python server.py
然后浏览器打开：
  http://localhost:8000/
"""
import json
import math
import os
import re
import statistics
import sys
import time
import urllib.parse
import urllib.request
from concurrent.futures import ThreadPoolExecutor
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from datetime import datetime

# 站点根目录（始终以脚本所在目录为准，避免工作目录不同导致找不到网页）
BASE_DIR = os.path.dirname(os.path.abspath(__file__))

# 本地默认 8000；部署到 Render/Railway 等平台时自动读取其注入的 PORT
PORT = int(os.environ.get("PORT", "8000"))
# 平台部署需监听 0.0.0.0；本地默认只监听 127.0.0.1 更安全
HOST = os.environ.get("HOST", "0.0.0.0" if os.environ.get("PORT") else "127.0.0.1")

UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/120 Safari/537.36")

# 默认监控指数（新浪代码）
DEFAULT_INDICES = ["sh000001", "sz399001", "sz399006", "sh000300"]


def http_get(url, referer, decode="utf-8"):
    req = urllib.request.Request(url, headers={
        "User-Agent": UA,
        "Referer": referer,
        "Accept": "*/*",
    })
    with urllib.request.urlopen(req, timeout=8) as resp:
        return resp.read().decode(decode, errors="ignore")


def num(v):
    try:
        return float(v)
    except (TypeError, ValueError):
        return None


# ---------------- 代码转换 ----------------
def to_sina_code(code):
    code = re.sub(r"\D", "", code)
    if code.startswith(("6", "5", "9")):
        return "sh" + code
    if code.startswith(("0", "3", "2")):
        return "sz" + code
    if code.startswith(("4", "8")):
        return "bj" + code
    return "sh" + code


def to_eastmoney_secid(code):
    code = re.sub(r"\D", "", code)
    if code.startswith(("6", "5", "9")):
        return "1." + code
    return "0." + code


# ---------------- 新浪解析 ----------------
def parse_sina(text):
    """解析形如 var hq_str_sh600519=\"名称,今开,昨收,...\"; 的返回。"""
    result = {}
    for m in re.finditer(r'hq_str_(\w{2})(\d{6})="([^"]*)"', text):
        prefix, code, payload = m.group(1), m.group(2), m.group(3)
        f = payload.split(",")
        if len(f) < 10 or not f[0]:
            continue
        price = num(f[3])
        pre = num(f[2])
        change = None
        percent = None
        if price is not None and pre not in (None, 0):
            change = round(price - pre, 3)
            percent = round(change / pre * 100, 2)
        result[prefix + code] = {
            "code": code,
            "name": f[0],
            "price": price,
            "open": num(f[1]),
            "preClose": pre,
            "high": num(f[4]),
            "low": num(f[5]),
            "change": change,
            "percent": percent,
            "volume": num(f[8]),
            "amount": num(f[9]),
        }
    return result


def sina_fetch(codes):
    url = "https://hq.sinajs.cn/list=" + ",".join(codes)
    text = http_get(url, "https://finance.sina.com.cn/", decode="gbk")
    return parse_sina(text)


# ---------------- 东方财富备用源 ----------------
def eastmoney_quotes():
    secids = ",".join(to_eastmoney_secid(re.sub(r"\D", "", c)) for c in DEFAULT_INDICES)
    url = ("https://push2.eastmoney.com/api/qt/ulist.np/get"
           "?fltt=2&invt=2&fields=f2,f3,f4,f12,f14&secids=" + secids)
    data = json.loads(http_get(url, "https://quote.eastmoney.com/"))
    items = []
    for d in (data.get("data") or {}).get("diff") or []:
        items.append({
            "code": d.get("f12"), "name": d.get("f14"),
            "price": num(d.get("f2")), "change": num(d.get("f4")),
            "percent": num(d.get("f3")),
        })
    return items


# ---------------- 对外组装 ----------------
def fetch_quotes(codes=None):
    """codes 为原始 6 位代码列表；为空则返回默认指数。"""
    if codes:
        sina_codes = [to_sina_code(c) for c in codes]
    else:
        sina_codes = DEFAULT_INDICES
    try:
        data = sina_fetch(sina_codes)
        items = [data[c] for c in sina_codes if c in data]
        if items:
            return {"source": "sina", "updated": now(), "items": items}
    except Exception:
        pass
    # 备用
    try:
        items = eastmoney_quotes()
        if items:
            return {"source": "eastmoney", "updated": now(), "items": items}
    except Exception:
        pass
    return {"source": "none", "updated": now(), "items": []}


def fetch_stock(code):
    code = re.sub(r"\D", "", code)
    if len(code) != 6:
        return {"error": "请输入 6 位股票代码"}
    try:
        data = sina_fetch([to_sina_code(code)])
        if data:
            item = list(data.values())[0]
            item["updated"] = now()
            return item
    except Exception as e:
        return {"error": "行情获取失败：" + str(e)}
    return {"error": "未找到该股票，请检查代码"}


def now():
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")


# ---------------- 历史K线 ----------------
def fetch_kline(code, days=60):
    """返回按时间升序的 [{day,open,high,low,close,volume}, ...]。"""
    code = re.sub(r"\D", "", code)
    sina_code = to_sina_code(code)
    # 主源：新浪
    try:
        url = ("https://money.finance.sina.com.cn/quotes_service/api/json_v2.php/"
               "CN_MarketData.getKLineData?symbol=%s&scale=240&ma=no&datalen=%d"
               % (sina_code, days))
        text = http_get(url, "https://finance.sina.com.cn/")
        rows = json.loads(text)
        out = []
        for r in rows:
            out.append({
                "day": r.get("day"),
                "open": num(r.get("open")),
                "high": num(r.get("high")),
                "low": num(r.get("low")),
                "close": num(r.get("close")),
                "volume": num(r.get("volume")),
            })
        if out:
            return out
    except Exception:
        pass
    # 备用：东方财富
    try:
        secid = to_eastmoney_secid(code)
        url = ("https://push2his.eastmoney.com/api/qt/stock/kline/get"
               "?secid=%s&fields1=f1,f2,f3&fields2=f51,f52,f53,f54,f55,f56,f57"
               "&klt=101&fqt=1&end=20500101&lmt=%d" % (secid, days))
        data = json.loads(http_get(url, "https://quote.eastmoney.com/"))
        out = []
        for line in (data.get("data") or {}).get("klines") or []:
            p = line.split(",")
            out.append({
                "day": p[0], "open": num(p[1]), "close": num(p[2]),
                "high": num(p[3]), "low": num(p[4]), "volume": num(p[5]),
            })
        return out
    except Exception:
        return []


def sma(values, n):
    if len(values) < n or n <= 0:
        return None
    return round(sum(values[-n:]) / n, 3)


def rsi(closes, n=14):
    if len(closes) < n + 1:
        return None
    gains = losses = 0.0
    for i in range(len(closes) - n, len(closes)):
        diff = closes[i] - closes[i - 1]
        if diff >= 0:
            gains += diff
        else:
            losses -= diff
    avg_gain, avg_loss = gains / n, losses / n
    if avg_loss == 0:
        return 100.0
    rs = avg_gain / avg_loss
    return round(100 - 100 / (1 + rs), 1)


def clamp(v, lo, hi):
    return max(lo, min(hi, v))


def analyze(code):
    """基于公开行情的辅助分析（规则模型，非投资建议）。"""
    quote = fetch_stock(code)
    if quote.get("error"):
        return quote
    k = fetch_kline(code, 60)
    closes = [x["close"] for x in k if x["close"] is not None]
    vols = [x["volume"] for x in k if x["volume"] is not None]
    price = quote.get("price")
    pre = quote.get("preClose")
    pct = quote.get("percent") or 0.0

    ma5, ma10, ma20 = sma(closes, 5), sma(closes, 10), sma(closes, 20)
    r = rsi(closes, 14)
    high60 = max(closes) if closes else None
    low60 = min(closes) if closes else None
    pos = None
    if high60 is not None and high60 != low60 and price is not None:
        pos = round((price - low60) / (high60 - low60) * 100, 1)

    avg_vol5 = sma(vols, 5) if vols else None
    today_vol = quote.get("volume")
    vol_ratio = round(today_vol / avg_vol5, 2) if (today_vol and avg_vol5) else None

    # ---- 评分模型 ----
    score = 50
    signals = []

    if ma5 is not None:
        if price >= ma5:
            score += 8; signals.append(("bull", "股价站上 5 日均线，短期偏强"))
        else:
            score -= 8; signals.append(("bear", "股价跌破 5 日均线，短期偏弱"))
    if ma20 is not None:
        if price >= ma20:
            score += 10; signals.append(("bull", "股价位于 20 日均线上方，中期趋势健康"))
        else:
            score -= 10; signals.append(("bear", "股价位于 20 日均线下方，中期趋势承压"))
    if ma5 is not None and ma20 is not None:
        if ma5 >= ma20:
            score += 7; signals.append(("bull", "MA5 上穿 MA20 呈多头排列"))
        else:
            score -= 7; signals.append(("bear", "MA5 位于 MA20 下方，均线空头排列"))

    score += clamp(pct * 2, -8, 8)

    if r is not None:
        if r >= 70:
            score -= 10; signals.append(("bear", "RSI=%.1f 进入超买区，谨防回调" % r))
        elif r <= 30:
            score += 8; signals.append(("bull", "RSI=%.1f 进入超卖区，或有反弹" % r))
        else:
            signals.append(("neutral", "RSI=%.1f 处于中性区间" % r))

    if pos is not None:
        if pos >= 90:
            score -= 8; signals.append(("bear", "股价接近 60 日高位（%.0f%%），追高风险大" % pos))
        elif pos <= 15:
            score += 5; signals.append(("bull", "股价接近 60 日低位（%.0f%%），安全边际较高" % pos))
        else:
            signals.append(("neutral", "股价处于 60 日区间 %.0f%% 位置" % pos))

    if vol_ratio is not None:
        if vol_ratio >= 1.5 and pct > 0:
            score += 5; signals.append(("bull", "放量上涨，量价配合良好（量比 %.2f）" % vol_ratio))
        elif vol_ratio >= 1.5 and pct < 0:
            score -= 6; signals.append(("bear", "放量下跌，抛压较重（量比 %.2f）" % vol_ratio))
        else:
            signals.append(("neutral", "成交量为 5 日均量的 %.2f 倍" % vol_ratio))

    score = int(clamp(round(score), 0, 100))
    if score >= 65:
        rating, risk = "偏多", "中"
    elif score >= 45:
        rating, risk = "中性", "中"
    else:
        rating, risk = "偏空", "较高" if pct < 0 else "中"

    # 日内振幅
    amp = None
    if quote.get("high") and quote.get("low") and pre:
        amp = round((quote["high"] - quote["low"]) / pre * 100, 2)
        if amp >= 7:
            risk = "高"

    # 近 20 日支撑 / 压力
    recent = k[-20:] if len(k) >= 20 else k
    highs = [x["high"] for x in recent if x.get("high") is not None]
    lows = [x["low"] for x in recent if x.get("low") is not None]
    resistance = round(max(highs), 2) if highs else None
    support = round(min(lows), 2) if lows else None

    def _n(x, d=2):
        return "--" if x is None else ("%." + str(d) + "f") % x

    # 每项数据的白话解读
    notes = {}
    notes["price"] = {
        "note": "较昨收 %s%.2f%%" % ("+" if pct >= 0 else "", pct),
        "tone": "bull" if pct > 0 else ("bear" if pct < 0 else "neutral"),
    }
    if ma5 is not None and price is not None:
        notes["ma5"] = {"note": "现价%s5日均线" % ("高于" if price >= ma5 else "低于"),
                        "tone": "bull" if price >= ma5 else "bear"}
    if ma20 is not None and price is not None:
        notes["ma20"] = {"note": "现价%s20日均线，%s" % (
            "高于" if price >= ma20 else "低于",
            "中期趋势健康" if price >= ma20 else "中期趋势承压"),
            "tone": "bull" if price >= ma20 else "bear"}
    if r is not None:
        if r >= 70: rn, rt = "超买，回调风险大", "bear"
        elif r >= 55: rn, rt = "偏强但未过热", "bull"
        elif r >= 45: rn, rt = "多空均衡", "neutral"
        elif r >= 30: rn, rt = "偏弱", "bear"
        else: rn, rt = "超卖，或有反弹", "bull"
        notes["rsi14"] = {"note": rn, "tone": rt}
    if pos is not None:
        if pos >= 85: pn, pt = "接近区间高点，追高风险大", "bear"
        elif pos >= 60: pn, pt = "位于区间中高位", "neutral"
        elif pos >= 40: pn, pt = "位于区间中部", "neutral"
        elif pos >= 20: pn, pt = "位于区间中低位", "neutral"
        else: pn, pt = "接近区间低点，安全边际较高", "bull"
        notes["pos"] = {"note": pn, "tone": pt}
    if vol_ratio is not None:
        if vol_ratio >= 1.5 and pct > 0: vn, vt = "放量上涨，资金积极", "bull"
        elif vol_ratio >= 1.5 and pct < 0: vn, vt = "放量下跌，抛压明显", "bear"
        elif vol_ratio >= 0.8: vn, vt = "量能与近期持平", "neutral"
        else: vn, vt = "缩量，观望情绪浓", "neutral"
        notes["volRatio"] = {"note": vn, "tone": vt}
    if quote.get("amount"):
        yi = quote["amount"] / 1e8
        if yi >= 20: an, at = "成交活跃，流动性好", "neutral"
        elif yi >= 5: an, at = "流动性较好", "neutral"
        elif yi >= 1: an, at = "流动性一般", "neutral"
        else: an, at = "成交清淡，注意流动性", "bear"
        notes["amount"] = {"note": an, "tone": at}
    if amp is not None:
        if amp >= 7: gn, gt = "振幅较大，波动风险高", "bear"
        elif amp >= 3: gn, gt = "波动中等", "neutral"
        else: gn, gt = "波动较小", "neutral"
        notes["range"] = {"note": gn, "tone": gt}

    # 综合解读
    if ma5 is not None and ma20 is not None and price is not None:
        if price >= ma5 and price < ma20:
            trend_desc = "短强中弱"
        elif price < ma5 and price >= ma20:
            trend_desc = "短弱中强"
        elif price >= ma5:
            trend_desc = "整体偏强"
        else:
            trend_desc = "整体偏弱"
    else:
        trend_desc = "数据不足"
    rsi_desc = ("，RSI %s 处于%s" % (_n(r, 1), notes.get("rsi14", {}).get("note", "中性"))) if r is not None else ""
    summary = ("%s 当前价 %s 元，日内%s%.2f%%，成交额 %s 亿元。技术面股价%s%s。"
               "股价处于 60 日区间 %s%% 位置，近 20 日支撑约 %s 元、压力约 %s 元。"
               "综合评分 %d 分，评级「%s」，风险等级「%s」。") % (
        quote.get("name") or code, _n(price), "+" if pct >= 0 else "", pct,
        _n((quote.get("amount") or 0) / 1e8), trend_desc, rsi_desc,
        _n(pos, 1), _n(support), _n(resistance), score, rating, risk)

    # 分周期操作参考
    advice = {}
    if r is not None and r >= 70:
        advice["short"] = "短线超买，谨防冲高回落，宜逢高减仓、不宜追涨。"
    elif ma5 is not None and price is not None and price >= ma5 and pct > 0:
        advice["short"] = "短线趋势向上，可持有；跌破 5 日均线（%s）则短线转弱。" % _n(ma5)
    else:
        advice["short"] = "短线走弱，谨慎参与，等放量站回 5 日均线再考虑。"
    if score >= 65:
        advice["mid"] = "中线偏多，可逢回调分批关注，跌破 20 日均线（%s）作为止损参考。" % _n(ma20)
    elif score >= 45:
        advice["mid"] = "中线中性，建议观望或轻仓，待趋势明朗再加大仓位。"
    else:
        advice["mid"] = "中线偏空，暂不建议重仓，以控制风险为主。"
    if pos is not None and pos <= 30:
        advice["long"] = "处于相对低位，长线可分批布局，但须先确认基本面（财报、估值、行业）。"
    elif pos is not None and pos >= 70:
        advice["long"] = "处于相对高位，长线不宜追高，等待回调后分批介入更稳妥。"
    else:
        advice["long"] = "位置中性，长线需结合公司基本面与估值水平判断，不宜仅凭技术面。"

    return {
        "code": quote.get("code"),
        "name": quote.get("name"),
        "price": price, "percent": pct, "change": quote.get("change"),
        "open": quote.get("open"), "high": quote.get("high"),
        "low": quote.get("low"), "preClose": pre,
        "amount": quote.get("amount"), "volume": today_vol,
        "ma5": ma5, "ma10": ma10, "ma20": ma20, "rsi14": r,
        "high60": high60, "low60": low60, "pos": pos, "volRatio": vol_ratio,
        "amp": amp, "support": support, "resistance": resistance,
        "score": score, "rating": rating, "risk": risk,
        "signals": [{"type": t, "text": s} for t, s in signals],
        "notes": notes, "summary": summary, "advice": advice,
        "spark": closes[-30:],
        "updated": now(),
    }


# ---------------- 低风险参考池 ----------------
# 说明：以下为跨行业的知名蓝筹/稳健标的样本池，仅用于演示"低风险特征筛选"。
# 通过历史波动率、最大回撤、流动性与趋势稳定性打分，不构成任何买入建议。
UNIVERSE = [
    ("601398", "工商银行"), ("601939", "建设银行"), ("601288", "农业银行"),
    ("601988", "中国银行"), ("600036", "招商银行"), ("601166", "兴业银行"),
    ("601318", "中国平安"), ("600900", "长江电力"), ("600028", "中国石化"),
    ("601857", "中国石油"), ("601088", "中国神华"), ("600519", "贵州茅台"),
    ("000858", "五粮液"), ("600887", "伊利股份"), ("000333", "美的集团"),
    ("000651", "格力电器"), ("600690", "海尔智家"), ("601668", "中国建筑"),
    ("601390", "中国中铁"), ("600585", "海螺水泥"), ("601006", "大秦铁路"),
    ("600104", "上汽集团"), ("601899", "紫金矿业"), ("600276", "恒瑞医药"),
    ("000001", "平安银行"),
]

_lowrisk_cache = {"time": 0, "data": None}
LOWRISK_TTL = 600  # 秒，10 分钟缓存


def _safe_metrics(code):
    try:
        k = fetch_kline(code, 60)
        closes = [x["close"] for x in k if x.get("close") is not None]
        if len(closes) < 21:
            return None
        rets = []
        for i in range(1, len(closes)):
            if closes[i - 1]:
                rets.append(closes[i] / closes[i - 1] - 1)
        vol = statistics.pstdev(rets) * math.sqrt(252) * 100 if len(rets) > 1 else 0.0
        peak, mdd = closes[0], 0.0
        for c in closes:
            peak = max(peak, c)
            if peak:
                mdd = max(mdd, (peak - c) / peak * 100)
        n60 = min(60, len(closes))
        ma60 = sum(closes[-n60:]) / n60
        ma20 = sum(closes[-20:]) / 20
        return {"vol": vol, "mdd": mdd, "ma20": ma20, "ma60": ma60}
    except Exception:
        return None


def _liquidity_score(amount):
    if not amount:
        return 2
    yi = amount / 1e8
    if yi >= 30:
        return 15
    if yi >= 10:
        return 12
    if yi >= 3:
        return 8
    if yi >= 1:
        return 5
    return 2


def _risk_level(score):
    if score >= 75:
        return ("低", "risk-low")
    if score >= 60:
        return ("中低", "risk-midlow")
    if score >= 45:
        return ("中", "risk-mid")
    return ("中高", "risk-high")


def fetch_lowrisk(limit=8):
    if _lowrisk_cache["data"] and time.time() - _lowrisk_cache["time"] < LOWRISK_TTL:
        return _lowrisk_cache["data"]

    codes = [c for c, _ in UNIVERSE]
    name_map = dict(UNIVERSE)
    try:
        qdata = sina_fetch([to_sina_code(c) for c in codes])
    except Exception:
        qdata = {}

    with ThreadPoolExecutor(max_workers=8) as ex:
        metrics = list(ex.map(_safe_metrics, codes))

    rows = []
    for code, m in zip(codes, metrics):
        if not m:
            continue
        q = qdata.get(to_sina_code(code)) or {}
        price = q.get("price")
        pct = q.get("percent") or 0.0
        amount = q.get("amount")
        vol, mdd = m["vol"], m["mdd"]

        s_vol = clamp(40 - (vol - 10) * 1.6, 0, 40)
        s_dd = clamp(35 - mdd * 0.8, 0, 35)
        s_liq = _liquidity_score(amount)
        if price is not None and price >= m["ma20"] and m["ma20"] >= m["ma60"]:
            s_trend = 10
        elif price is not None and price >= m["ma20"]:
            s_trend = 6
        else:
            s_trend = 2
        score = int(round(s_vol + s_dd + s_liq + s_trend))
        level, level_cls = _risk_level(score)

        reasons = []
        reasons.append("年化波动率 %.1f%%" % vol)
        reasons.append("60日最大回撤 %.1f%%" % mdd)
        if amount:
            reasons.append("日成交额 %.1f 亿" % (amount / 1e8))
        if price is not None and price >= m["ma20"]:
            reasons.append("站上20日均线")

        rows.append({
            "code": code,
            "name": q.get("name") or name_map.get(code, code),
            "price": price, "percent": pct, "amount": amount,
            "vol": round(vol, 1), "mdd": round(mdd, 1),
            "score": score, "level": level, "levelCls": level_cls,
            "reasons": reasons,
        })

    rows.sort(key=lambda r: r["score"], reverse=True)
    result = {
        "updated": now(),
        "universe": len(codes),
        "items": rows[:limit],
        "note": "基于历史波动率/回撤/流动性量化筛选，仅供学习观察，不构成买入建议。",
    }
    _lowrisk_cache.update({"time": time.time(), "data": result})
    return result


# ---------------- 持仓卖出计划 ----------------
def _f(v, default=0.0):
    try:
        return float(v)
    except (TypeError, ValueError):
        return default


def sell_plan(code, cost, qty):
    """根据买入成本与实时技术面，给出止盈/止损参考（非投资建议）。"""
    a = analyze(code)
    if a.get("error"):
        return a

    cost = _f(cost)
    qty = _f(qty)
    price = a.get("price") or 0.0
    ma20 = a.get("ma20")
    rsi = a.get("rsi14")
    score = a.get("score", 50)
    pct = a.get("percent") or 0.0

    cost_value = cost * qty if cost and qty else None
    market_value = price * qty if price and qty else None
    profit = (price - cost) * qty if (cost and qty) else None
    profit_pct = ((price - cost) / cost * 100) if cost else None

    stop_loss = round(cost * 0.92, 2) if cost else None
    target1 = round(cost * 1.10, 2) if cost else None
    target2 = round(cost * 1.20, 2) if cost else None
    trailing = round(price * 0.95, 2) if (profit_pct is not None and profit_pct > 10 and price) else None

    reasons = []
    action, action_cls = "继续持有", "ok"

    if profit_pct is not None and stop_loss and price and price <= stop_loss:
        action, action_cls = "建议止损", "danger"
        reasons.append("现价 %.2f 已跌破参考止损位 %.2f" % (price, stop_loss))
    elif ma20 is not None and price and price < ma20:
        action, action_cls = "趋势转弱，减仓观察", "warn"
        reasons.append("现价低于 20 日均线 %.2f，中期趋势走弱" % ma20)
    elif rsi is not None and rsi >= 70:
        action, action_cls = "接近超买，分批止盈", "warn"
        reasons.append("RSI=%.1f 进入超买区，短期有回调压力" % rsi)
    elif profit_pct is not None and profit_pct >= 20:
        action, action_cls = "达到目标，分批止盈", "warn"
        reasons.append("浮盈 %.1f%%，已达到第二目标附近" % profit_pct)
    elif score < 40:
        action, action_cls = "技术面偏弱，减仓观察", "warn"
        reasons.append("综合评分 %d 偏低" % score)
    else:
        reasons.append("技术面尚未出现明显卖点，可继续持有并跟踪")

    if profit_pct is not None:
        reasons.append("当前浮动盈亏 %+.2f%%" % profit_pct)
    if trailing and profit_pct is not None and profit_pct > 10:
        reasons.append("已有浮盈，可用 %.2f 作为移动止盈线保护利润" % trailing)
    if a.get("pos") is not None:
        reasons.append("股价处于 60 日区间 %.0f%% 位置" % a["pos"])

    return {
        "code": a.get("code"), "name": a.get("name"),
        "price": price, "percent": pct, "cost": cost, "qty": qty,
        "costValue": cost_value, "marketValue": market_value,
        "profit": profit, "profitPct": profit_pct,
        "ma20": ma20, "rsi14": rsi, "score": score, "pos": a.get("pos"),
        "stopLoss": stop_loss, "target1": target1, "target2": target2,
        "trailing": trailing,
        "action": action, "actionCls": action_cls,
        "reasons": reasons, "updated": a.get("updated") or now(),
    }


def build_sellplans(holdings):
    valid = [h for h in holdings if re.sub(r"\D", "", str(h.get("code", "")))]
    if not valid:
        return {"updated": now(), "items": []}
    with ThreadPoolExecutor(max_workers=6) as ex:
        items = list(ex.map(lambda h: sell_plan(h.get("code"), h.get("cost"), h.get("qty")), valid))
    return {"updated": now(), "items": items}


# ---------------- HTTP 服务 ----------------
class Handler(SimpleHTTPRequestHandler):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, directory=BASE_DIR, **kwargs)

    def _send_json(self, obj, status=200):
        body = json.dumps(obj, ensure_ascii=False).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Cache-Control", "no-store")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self):
        parsed = urllib.parse.urlparse(self.path)
        path, qs = parsed.path, urllib.parse.parse_qs(parsed.query)

        if path == "/healthz":
            self._send_json({"ok": True, "time": now()})
            return
        if path == "/api/quotes":
            raw = (qs.get("codes") or [""])[0]
            codes = [c for c in re.split(r"[,\s]+", raw) if c] if raw else None
            self._send_json(fetch_quotes(codes))
            return
        if path == "/api/stock":
            code = (qs.get("code") or [""])[0]
            if not code:
                self._send_json({"error": "缺少 code 参数"}, 400)
                return
            self._send_json(fetch_stock(code))
            return
        if path == "/api/kline":
            code = (qs.get("code") or [""])[0]
            days = int((qs.get("days") or ["60"])[0])
            if not code:
                self._send_json({"error": "缺少 code 参数"}, 400)
                return
            self._send_json({"code": code, "items": fetch_kline(code, days)})
            return
        if path == "/api/analyze":
            code = (qs.get("code") or [""])[0]
            if not code:
                self._send_json({"error": "缺少 code 参数"}, 400)
                return
            self._send_json(analyze(code))
            return
        if path == "/api/lowrisk":
            limit = int((qs.get("limit") or ["8"])[0])
            try:
                self._send_json(fetch_lowrisk(limit))
            except Exception as e:
                self._send_json({"error": str(e), "items": []}, 502)
            return
        if path == "/api/sellplan":
            code = (qs.get("code") or [""])[0]
            if not code:
                self._send_json({"error": "缺少 code 参数"}, 400)
                return
            self._send_json(sell_plan(code, (qs.get("cost") or ["0"])[0], (qs.get("qty") or ["0"])[0]))
            return
        return SimpleHTTPRequestHandler.do_GET(self)

    def do_POST(self):
        parsed = urllib.parse.urlparse(self.path)
        if parsed.path != "/api/sellplan":
            self._send_json({"error": "not found"}, 404)
            return
        try:
            length = int(self.headers.get("Content-Length") or 0)
            payload = json.loads(self.rfile.read(length).decode("utf-8")) if length else {}
            holdings = payload.get("holdings") or []
            self._send_json(build_sellplans(holdings))
        except Exception as e:
            self._send_json({"error": str(e), "items": []}, 502)

    def log_message(self, fmt, *args):
        sys.stdout.write("[%s] %s\n" % (datetime.now().strftime("%H:%M:%S"), fmt % args))


if __name__ == "__main__":
    print("AI股票分析 服务已启动")
    print("监听地址: http://%s:%d/" % (HOST, PORT))
    if HOST == "127.0.0.1":
        print("请用浏览器打开: http://localhost:%d/" % PORT)
    print("按 Ctrl+C 停止")
    ThreadingHTTPServer((HOST, PORT), Handler).serve_forever()
