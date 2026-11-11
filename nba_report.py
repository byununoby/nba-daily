#!/usr/bin/env python3
"""
NBA 일일 리포트 생성기
- 데이터: ESPN 공개 API (키 불필요)
- 결과물: docs/index.html (GitHub Pages로 공개), docs/archive/날짜.html
- 선택: ANTHROPIC_API_KEY 가 있으면 Claude가 한국어 이슈 요약 작성
"""
import os, json, time, html, statistics, datetime as dt
from pathlib import Path
from zoneinfo import ZoneInfo
import requests

BASE = "https://site.api.espn.com/apis/site/v2/sports/basketball/nba"
ROOT = Path(__file__).resolve().parent
DATA = ROOT / "data"
DAYS = DATA / "days"
INJ = DATA / "injuries"
DOCS = ROOT / "docs"
ARCH = DOCS / "archive"
ET = ZoneInfo("America/New_York")
KST = ZoneInfo("Asia/Seoul")
SEASON_START = dt.date.fromisoformat(os.getenv("SEASON_START") or "2026-10-01")
CLAUDE_MODEL = os.getenv("CLAUDE_MODEL") or "claude-sonnet-5-5"

SESSION = requests.Session()
SESSION.headers.update({"User-Agent": "Mozilla/5.0 (nba-daily-report)"})


# ---------------------------------------------------------------- 공통 유틸
def get(url, params=None):
    for i in range(3):
        try:
            r = SESSION.get(url, params=params, timeout=25)
            if r.status_code == 200:
                return r.json()
            print(f"[warn] HTTP {r.status_code} {url} {params}")
        except Exception as e:
            print(f"[warn] {e}")
        time.sleep(2 * (i + 1))
    return None


def num(x):
    try:
        return float(str(x).replace("+", ""))
    except Exception:
        return 0.0


def made_att(x):
    try:
        a, b = str(x).split("-")
        return float(a), float(b)
    except Exception:
        return 0.0, 0.0


def minutes(x):
    s = str(x or "")
    if ":" in s:
        m, sec = s.split(":")
        return num(m) + num(sec) / 60
    return num(s)


def esc(s):
    return html.escape(str(s if s is not None else ""))


KEYMAP = {
    "MIN": "min", "minutes": "min",
    "FG": "fg", "fieldGoalsMade-fieldGoalsAttempted": "fg",
    "3PT": "tp", "threePointFieldGoalsMade-threePointFieldGoalsAttempted": "tp",
    "FT": "ft", "freeThrowsMade-freeThrowsAttempted": "ft",
    "OREB": "oreb", "offensiveRebounds": "oreb",
    "DREB": "dreb", "defensiveRebounds": "dreb",
    "REB": "reb", "rebounds": "reb",
    "AST": "ast", "assists": "ast",
    "STL": "stl", "steals": "stl",
    "BLK": "blk", "blocks": "blk",
    "TO": "to", "turnovers": "to",
    "PF": "pf", "fouls": "pf",
    "+/-": "pm", "plusMinus": "pm",
    "PTS": "pts", "points": "pts",
}


# ---------------------------------------------------------------- 수집
def parse_box(summary, gid, date, teams):
    out = []
    opp = {}
    if len(teams) == 2:
        opp = {teams[0]["abbr"]: teams[1]["abbr"], teams[1]["abbr"]: teams[0]["abbr"]}
    for team in (summary.get("boxscore") or {}).get("players", []):
        abbr = (team.get("team") or {}).get("abbreviation", "")
        for grp in team.get("statistics", []):
            cols = grp.get("keys") or grp.get("labels") or grp.get("names") or []
            cols = [KEYMAP.get(c, KEYMAP.get(str(c).upper(), c)) for c in cols]
            for a in grp.get("athletes", []):
                if a.get("didNotPlay") or not a.get("stats"):
                    continue
                raw = dict(zip(cols, a["stats"]))
                m = minutes(raw.get("min"))
                if m <= 0:
                    continue
                fgm, fga = made_att(raw.get("fg"))
                tpm, tpa = made_att(raw.get("tp"))
                ftm, fta = made_att(raw.get("ft"))
                ath = a.get("athlete") or {}
                out.append({
                    "id": str(ath.get("id", "")), "name": ath.get("displayName", "?"),
                    "team": abbr, "opp": opp.get(abbr, ""), "date": date, "gid": gid,
                    "pos": (ath.get("position") or {}).get("abbreviation", ""),
                    "starter": bool(a.get("starter")), "min": round(m, 1),
                    "pts": num(raw.get("pts")), "reb": num(raw.get("reb")),
                    "oreb": num(raw.get("oreb")), "dreb": num(raw.get("dreb")),
                    "ast": num(raw.get("ast")), "stl": num(raw.get("stl")),
                    "blk": num(raw.get("blk")), "to": num(raw.get("to")),
                    "pf": num(raw.get("pf")), "pm": num(raw.get("pm")),
                    "fgm": fgm, "fga": fga, "tpm": tpm, "tpa": tpa, "ftm": ftm, "fta": fta,
                })
    return out


def fetch_day(date):
    sb = get(f"{BASE}/scoreboard", {"dates": date.strftime("%Y%m%d"), "limit": 50})
    if sb is None:
        return None
    games, players, all_done = [], [], True
    for ev in sb.get("events", []):
        stype = (ev.get("season") or {}).get("type", 2)
        if stype not in (2, 3):  # 프리시즌 제외
            continue
        comp = (ev.get("competitions") or [{}])[0]
        st = comp.get("status") or ev.get("status") or {}
        done = bool((st.get("type") or {}).get("completed"))
        teams = []
        for c in comp.get("competitors", []):
            t = c.get("team") or {}
            teams.append({"abbr": t.get("abbreviation", ""), "name": t.get("displayName", ""),
                          "score": int(num(c.get("score"))), "home": c.get("homeAway") == "home"})
        g = {"id": ev.get("id"), "done": done, "period": int(num(st.get("period", 4))),
             "teams": teams, "headline": "", "desc": ""}
        if done:
            sm = get(f"{BASE}/summary", {"event": ev.get("id")})
            time.sleep(0.3)
            if sm:
                art = sm.get("article") or {}
                g["headline"] = art.get("headline") or ""
                g["desc"] = art.get("description") or ""
                players += parse_box(sm, g["id"], date.isoformat(), teams)
        else:
            all_done = False
        games.append(g)
    return {"date": date.isoformat(), "games": games, "players": players, "complete": all_done}


def ensure_day(date, force=False):
    DAYS.mkdir(parents=True, exist_ok=True)
    p = DAYS / f"{date.isoformat()}.json"
    if p.exists() and not force:
        d = json.loads(p.read_text())
        if d.get("complete"):
            return d
    print(f"[fetch] {date}")
    d = fetch_day(date)
    if d is None:
        if p.exists():
            return json.loads(p.read_text())
        return {"date": date.isoformat(), "games": [], "players": [], "complete": False}
    p.write_text(json.dumps(d, ensure_ascii=False))
    return d


def fetch_injuries():
    d = get(f"{BASE}/injuries")
    res = {}
    if not d:
        return res
    for t in d.get("injuries", []):
        team_name = t.get("displayName", "")
        for inj in t.get("injuries", []):
            a = inj.get("athlete") or {}
            name = a.get("displayName")
            if not name:
                continue
            det = inj.get("details") or {}
            res[name] = {
                "name": name,
                "team": (a.get("team") or {}).get("abbreviation") or team_name,
                "status": inj.get("status", ""),
                "comment": inj.get("shortComment") or inj.get("longComment") or "",
                "date": str(inj.get("date", ""))[:10],
                "type": det.get("type", ""),
                "return": str(det.get("returnDate", ""))[:10],
            }
    return res


def fetch_schedule(start, end):
    """start~end(포함) 날짜별 경기 팀 목록. 판타지 주간(월~일) 잔여 경기 계산용"""
    out = {}
    d = start
    while d <= end:
        sb = get(f"{BASE}/scoreboard", {"dates": d.strftime("%Y%m%d"), "limit": 50}) or {}
        teams = []
        for ev in sb.get("events", []):
            if (ev.get("season") or {}).get("type", 2) not in (2, 3):
                continue
            comp = (ev.get("competitions") or [{}])[0]
            teams += [(c.get("team") or {}).get("abbreviation", "") for c in comp.get("competitors", [])]
        out[d.isoformat()] = teams
        d += dt.timedelta(days=1)
    return out


# ---------------------------------------------------------------- 계산
STATS = ["min", "pts", "reb", "oreb", "dreb", "ast", "stl", "blk", "to", "pf", "pm",
         "fgm", "fga", "tpm", "tpa", "ftm", "fta"]


def gscore(l):  # Hollinger Game Score
    return (l["pts"] + 0.4 * l["fgm"] - 0.7 * l["fga"] - 0.4 * (l["fta"] - l["ftm"])
            + 0.7 * l["oreb"] + 0.3 * l["dreb"] + l["stl"] + 0.7 * l["ast"]
            + 0.7 * l["blk"] - 0.4 * l["pf"] - l["to"])


def avg(lines):
    n = len(lines)
    a = {k: sum(l[k] for l in lines) / n for k in STATS}
    a["gp"] = n
    a["gs"] = sum(gscore(l) for l in lines) / n
    return a


def tags(l):
    t = []
    if sum(1 for k in ("pts", "reb", "ast", "stl", "blk") if l[k] >= 10) >= 3:
        t.append("트리플더블")
    if l["pts"] >= 40:
        t.append(f"{int(l['pts'])}점")
    if l["reb"] >= 20:
        t.append(f"{int(l['reb'])}리바운드")
    if l["ast"] >= 15:
        t.append(f"{int(l['ast'])}어시스트")
    if l["tpm"] >= 8:
        t.append(f"3점 {int(l['tpm'])}개")
    if l["blk"] >= 6:
        t.append(f"{int(l['blk'])}블록")
    if l["stl"] >= 6:
        t.append(f"{int(l['stl'])}스틸")
    return t


def build(target):
    # 1) 시즌 전체 데이터 확보 (처음 실행 시 자동 백필, 이후 캐시)
    days = []
    d = SEASON_START
    while d <= target:
        days.append(ensure_day(d, force=(d == target)))
        d += dt.timedelta(days=1)
    today = days[-1]
    all_lines = [l for day in days for l in day["players"]]
    by_player = {}
    for l in all_lines:
        by_player.setdefault(l["id"], []).append(l)
    for v in by_player.values():
        v.sort(key=lambda x: x["date"])
    name_to_id = {}
    for pid, ls in by_player.items():
        name_to_id[ls[-1]["name"]] = pid
    team_dates = {}
    for l in all_lines:
        team_dates.setdefault(l["team"], set()).add(l["date"])

    tdate = target.isoformat()
    today_lines = today["players"]

    def prior(pid):
        return [l for l in by_player.get(pid, []) if l["date"] < tdate]

    def season_avg(pid, upto_today=False):
        ls = [l for l in by_player.get(pid, []) if (l["date"] <= tdate if upto_today else l["date"] < tdate)]
        return avg(ls) if ls else None

    # 2) 부상 정보 (날짜별 스냅샷 저장 후 직전 스냅샷과 비교)
    INJ.mkdir(parents=True, exist_ok=True)
    cur_inj = fetch_injuries()
    (INJ / f"{tdate}.json").write_text(json.dumps(cur_inj, ensure_ascii=False))
    prev_files = sorted(p for p in INJ.glob("*.json") if p.stem < tdate)
    prev_inj = json.loads(prev_files[-1].read_text()) if prev_files else None

    played_today = {l["name"]: l for l in today_lines}

    # 복귀: (a) 팀이 3경기 이상 치르는 동안 결장했다가 오늘 출전  (b) 직전 부상자 명단에 있었는데 오늘 출전/명단 제외
    returns = {}
    for l in today_lines:
        pr = prior(l["id"])
        if not pr:
            continue
        last = pr[-1]["date"]
        missed = sum(1 for x in team_dates.get(l["team"], ()) if last < x < tdate)
        if missed >= 3:
            returns[l["name"]] = {"name": l["name"], "team": l["team"], "line": l,
                                  "note": f"{missed}경기 결장 후 복귀", "avg": season_avg(l["id"])}
    if prev_inj:
        for name, info in prev_inj.items():
            if name in returns:
                continue
            if name in played_today:
                l = played_today[name]
                returns[name] = {"name": name, "team": l["team"], "line": l,
                                 "note": f"부상자 명단({info['status']})에서 출전", "avg": season_avg(l["id"])}
            elif name not in cur_inj:
                pid = name_to_id.get(name)
                returns[name] = {"name": name, "team": info["team"], "line": None,
                                 "note": "부상자 명단에서 제외 (다음 경기 출전 예상)",
                                 "avg": season_avg(pid) if pid else None}
    returns = sorted(returns.values(), key=lambda r: -(r["avg"]["gs"] if r["avg"] else 0))

    # 신규 부상
    new_inj = []
    for name, info in cur_inj.items():
        if prev_inj is not None:
            old = prev_inj.get(name)
            is_new = old is None or (old["status"] != "Out" and info["status"] == "Out")
        else:
            is_new = info["date"] >= (target - dt.timedelta(days=1)).isoformat()
        if is_new:
            pid = name_to_id.get(name)
            new_inj.append({**info, "avg": season_avg(pid, True) if pid else None})
    new_inj.sort(key=lambda r: -(r["avg"]["gs"] if r["avg"] else 0))
    new_inj = new_inj[:25]

    # 3) 잘한 선수 / 못한 선수
    rows = []
    for l in today_lines:
        pr = prior(l["id"])
        a = avg(pr) if len(pr) >= 3 else None
        g = gscore(l)
        rows.append({"line": l, "avg": a, "gs": g, "diff": g - (a["gs"] if a else g)})
    standouts = sorted([r for r in rows if r["line"]["min"] >= 20 and r["gs"] >= 12],
                       key=lambda r: -(r["gs"] * 0.5 + r["diff"]))[:5]
    flops = sorted([r for r in rows if r["avg"] and r["avg"]["gp"] >= 5 and r["avg"]["gs"] >= 13
                    and r["line"]["min"] >= 15], key=lambda r: r["diff"])[:5]

    # 4) 일정 (야후 판타지 주간: 월~일)
    today_et = target + dt.timedelta(days=1)
    sunday = today_et + dt.timedelta(days=6 - today_et.weekday())
    next_sun = sunday + dt.timedelta(days=7)
    sch = fetch_schedule(today_et, next_sun)
    sched = {"this": {}, "next": {}, "this_range": (today_et, sunday),
             "next_range": (sunday + dt.timedelta(days=1), next_sun)}
    for d, teams in sch.items():
        key = "this" if d <= sunday.isoformat() else "next"
        for t in teams:
            sched[key][t] = sched[key].get(t, 0) + 1

    # 5) 야후 판타지 (9카테고리 + 부상/출전시간/역할 변화/일정 종합)
    fantasy = fantasy_picks(by_player, team_dates, target, cur_inj, sched)

    # 6) 경기별 이슈
    issues = []
    for g in today["games"]:
        if len(g["teams"]) != 2 or not g["done"]:
            continue
        a, b = g["teams"]
        margin = abs(a["score"] - b["score"])
        flags = []
        if g["period"] > 4:
            flags.append("연장" if g["period"] == 5 else f"{g['period'] - 4}차 연장")
        if margin <= 3:
            flags.append(f"{margin}점차 접전")
        if margin >= 30:
            flags.append(f"{margin}점차 대승")
        big = []
        for l in today_lines:
            if l["gid"] == g["id"]:
                t = tags(l)
                if t:
                    big.append(f"{l['name']}({l['team']}) {', '.join(t)}")
        issues.append({"game": g, "flags": flags, "big": big})
    ai_summary = claude_summary(tdate, issues, returns, new_inj, standouts, flops)

    return {"date": tdate, "games": today["games"], "issues": issues, "sched": sched,
            "ai": ai_summary, "returns": returns, "new_inj": new_inj,
            "standouts": standouts, "flops": flops, "fantasy": fantasy}


def mean(xs):
    xs = list(xs)
    return sum(xs) / len(xs) if xs else 0.0


def md(datestr):
    try:
        d = dt.date.fromisoformat(datestr)
        return f"{d.month}월 {d.day}일"
    except Exception:
        return ""


PROTECT_TOP = 50  # 시즌 판타지 순위 50위 이내는 방출 후보에서 제외


def fantasy_picks(by_player, team_dates, target, cur_inj, sched):
    tdate = target.isoformat()
    l7_start = (target - dt.timedelta(days=6)).isoformat()
    recent_start = (target - dt.timedelta(days=9)).isoformat()

    # ---- 선수별 기본 정보
    P = {}
    for pid, ls in by_player.items():
        ls = [l for l in ls if l["date"] <= tdate]
        if len(ls) < 3:
            continue
        team = ls[-1]["team"]
        tl = [l for l in ls if l["team"] == team]
        tdates = sorted(x for x in team_dates.get(team, ()) if tl[0]["date"] <= x <= tdate)
        played = {l["date"] for l in tl}
        l7 = [l for l in ls if l["date"] >= l7_start]
        P[pid] = {
            "id": pid, "name": ls[-1]["name"], "team": team, "lines": ls, "tl": tl,
            "pos": next((l.get("pos") for l in reversed(ls) if l.get("pos")), ""),
            "season": avg(ls), "l7": avg(l7) if len(l7) >= 2 else None,
            "l5min": mean(l["min"] for l in ls[-5:]),
            "start_rate": mean(1 if l["starter"] else 0 for l in ls),
            "start_l3": sum(1 for l in ls[-3:] if l["starter"]),
            "tgames": len(tdates), "missed": sum(1 for x in tdates if x not in played),
        }
    if not P:
        return {"add": [], "drop": [], "soon": []}
    by_name = {p["name"]: p for p in P.values()}

    # ---- 9카테고리 가치(z-score 합)
    pool = [p["season"] for p in P.values() if p["season"]["min"] >= 18] or [p["season"] for p in P.values()]
    lg_fg = sum(a["fgm"] for a in pool) / max(1, sum(a["fga"] for a in pool))
    lg_ft = sum(a["ftm"] for a in pool) / max(1, sum(a["fta"] for a in pool))

    def feats(a):
        fgp = a["fgm"] / a["fga"] if a["fga"] else lg_fg
        ftp = a["ftm"] / a["fta"] if a["fta"] else lg_ft
        return {"pts": a["pts"], "reb": a["reb"], "ast": a["ast"], "stl": a["stl"],
                "blk": a["blk"], "tpm": a["tpm"], "to": -a["to"],
                "fg": a["fga"] * (fgp - lg_fg), "ft": a["fta"] * (ftp - lg_ft)}

    F = [feats(a) for a in pool]
    mu = {k: statistics.mean(f[k] for f in F) for k in F[0]}
    sd = {k: (statistics.pstdev([f[k] for f in F]) or 1) for k in F[0]}

    def value(a):
        f = feats(a)
        return sum((f[k] - mu[k]) / sd[k] for k in mu)

    rows = sorted(P.values(), key=lambda p: -value(p["season"]))
    for i, p in enumerate(rows, 1):
        p["rank"] = i
        p["sval"] = value(p["season"])
        p["l7val"] = value(p["l7"]) if p["l7"] else None
        p["trend"] = (p["l7val"] - p["sval"]) if p["l7"] else 0.0
        p["games_this"] = sched["this"].get(p["team"], 0)
        p["games_next"] = sched["next"].get(p["team"], 0)

    # ---- 부상 정보 정리
    def inj_info(name):
        inj = cur_inj.get(name)
        if not inj:
            return None
        days = None
        if inj.get("return"):
            try:
                days = (dt.date.fromisoformat(inj["return"]) - target).days
            except Exception:
                pass
        txt = (inj.get("comment") or "").lower()
        long_term = (days is not None and days >= 14) or any(
            k in txt for k in ("season", "surgery", "indefinitely", "several weeks", "months"))
        return {**inj, "days": days, "long": long_term, "is_out": inj.get("status") == "Out"}

    def ret_txt(ii):
        if ii and ii.get("return"):
            return f"{md(ii['return'])}까지 결장 예상"
        return "복귀 시점 미정"

    # ---- (A) 주축 부상 → 같은 팀 수혜자
    opp = {}
    for name, inj in cur_inj.items():
        k = by_name.get(name)
        ii = inj_info(name)
        if not k or not ii or not ii["is_out"] or k["season"]["min"] < 24:
            continue
        team = k["team"]
        klast = k["tl"][-1]["date"] if k["tl"] else ""
        without = {x for x in team_dates.get(team, ()) if klast < x <= tdate}
        with_d = {l["date"] for l in k["tl"]}
        mates = [p for p in P.values() if p["team"] == team and p["id"] != k["id"]
                 and not (inj_info(p["name"]) or {}).get("is_out")]
        base = {"k": k, "ii": ii}
        if without:
            for p in mates:
                wl = [l for l in p["tl"] if l["date"] in with_d]
                wo = [l for l in p["tl"] if l["date"] in without]
                if wl and wo:
                    b, a = mean(l["min"] for l in wl), mean(l["min"] for l in wo)
                    if a - b >= 4:
                        opp.setdefault(p["id"], []).append({**base, "before": b, "after": a,
                                                             "n": len(wo), "est": False})
        else:
            kpos = (k["pos"] or "?")[:1]
            cands = [p for p in mates if p["start_rate"] < 0.5 and p["season"]["min"] >= 12
                     and (not p["pos"] or kpos == "?" or p["pos"][:1] == kpos)]
            for p in sorted(cands, key=lambda p: -p["season"]["min"])[:2]:
                opp.setdefault(p["id"], []).append({**base, "before": p["season"]["min"],
                                                     "after": None, "n": 0, "est": True})

    # ---- (B) 장기 결장 주전 복귀 → 같은 팀 출전시간 감소자
    role_loss = {}
    for r in P.values():
        if r["season"]["min"] < 24 or len(r["tl"]) < 2:
            continue
        tds = sorted(team_dates.get(r["team"], ()))
        rd = [l["date"] for l in r["tl"]]
        for prev_d, ret_d in zip(rd, rd[1:]):
            gap = [x for x in tds if prev_d < x < ret_d]
            if len(gap) >= 3 and ret_d >= recent_start:
                gap_s, since_s = set(gap), {x for x in tds if x >= ret_d}
                for p in P.values():
                    if p["team"] != r["team"] or p["id"] == r["id"]:
                        continue
                    du = [l["min"] for l in p["tl"] if l["date"] in gap_s]
                    si = [l["min"] for l in p["tl"] if l["date"] in since_s]
                    if du and si and mean(du) - mean(si) >= 4:
                        role_loss.setdefault(p["id"], []).append(
                            {"r": r, "ret": ret_d, "during": mean(du), "since": mean(si), "n": len(si)})

    def fmt_games(p):
        return f"이번 주 잔여 {p['games_this']}경기 / 다음 주 {p['games_next']}경기"

    # ---- 영입 추천
    cut = min(100, int(len(rows) * 0.3))
    adds = []
    for p in rows:
        ii = inj_info(p["name"])
        if p["rank"] <= cut or (ii and ii["is_out"]):
            continue
        reasons, signal = [], False
        score = p["l7val"] if p["l7val"] is not None else p["sval"]
        for o in sorted(opp.get(p["id"], []), key=lambda o: -((o["after"] or 0) - o["before"]))[:1]:
            k, oi = o["k"], o["ii"]
            if o["est"]:
                bonus = 1.0
                reasons.append(f"{k['name']}(평균 {k['season']['min']:.0f}분) {ret_txt(oi)}. "
                               f"같은 포지션 백업으로 출전시간 증가 예상 (아직 결장 경기 표본 없음)")
            else:
                bonus = 1.5 + min(1.5, (o["after"] - o["before"]) / 6)
                reasons.append(f"{k['name']}(평균 {k['season']['min']:.0f}분) {ret_txt(oi)}. "
                               f"결장 {o['n']}경기 동안 출전시간 {o['before']:.0f}분 → {o['after']:.0f}분")
            if oi["days"] is not None:
                bonus += min(1.0, max(0, oi["days"]) / 14)
                if oi["days"] <= 3:
                    bonus *= 0.3
                    reasons.append("주의: 주전 복귀가 임박해 단기 활용만 권장")
            elif oi["long"]:
                bonus += 1.0
            score += bonus
            signal = True
        dmin = p["l5min"] - p["season"]["min"]
        if dmin >= 4:
            score += dmin / 4
            signal = True
            reasons.append(f"최근 5경기 평균 {p['l5min']:.0f}분 (시즌 {p['season']['min']:.0f}분)")
        if p["start_l3"] >= 2 and p["start_rate"] < 0.5:
            score += 1.0
            signal = True
            reasons.append(f"최근 3경기 중 {p['start_l3']}경기 선발 (시즌 선발 비율 {p['start_rate'] * 100:.0f}%)")
        if p["l7val"] is not None and p["trend"] >= 1.0:
            signal = True
            reasons.append(f"최근 7일 판타지 가치 {p['l7val']:+.1f} (시즌 {p['sval']:+.1f})")
        for rl in role_loss.get(p["id"], [])[:1]:
            score -= 1.5
            reasons.append(f"주의: {rl['r']['name']} 복귀({md(rl['ret'])}) 후 출전시간 "
                           f"{rl['during']:.0f}분 → {rl['since']:.0f}분")
        if ii:
            score -= 0.5
            reasons.append(f"주의: 현재 {ii['status']}")
        score += 0.3 * (p["games_this"] - 3)
        reasons.append(fmt_games(p))
        if signal:
            adds.append({**p, "score": score, "reasons": reasons})
    adds.sort(key=lambda x: -x["score"])

    # ---- 방출 고려 (시즌 상위 PROTECT_TOP 위 제외)
    drops = []
    for p in rows:
        if p["rank"] <= PROTECT_TOP or p["rank"] > 180:
            continue
        ii = inj_info(p["name"])
        score, reasons = 0.0, []
        if ii and ii["is_out"]:
            if ii["long"]:
                score += 3.0
                reasons.append(f"{ii['status']} ({ii.get('type') or '부상'}), {ret_txt(ii)}. "
                               f"IL 슬롯이 없으면 방출 우선 대상")
            elif ii["days"] is not None and ii["days"] >= 7:
                score += 1.5
                reasons.append(f"{ii['status']} ({ii.get('type') or '부상'}), {ret_txt(ii)}. IL 슬롯 활용 권장")
        for rl in role_loss.get(p["id"], [])[:1]:
            score += 2.5
            reasons.append(f"{rl['r']['name']} 복귀({md(rl['ret'])}) 후 출전시간 "
                           f"{rl['during']:.0f}분 → {rl['since']:.0f}분 (벤치 역할 축소)")
        if p["start_rate"] >= 0.6 and p["start_l3"] == 0:
            score += 1.0
            reasons.append("주전에서 벤치로 이동 (최근 3경기 선발 0회)")
        dmin = p["season"]["min"] - p["l5min"]
        if dmin >= 4:
            score += dmin / 4
            reasons.append(f"출전시간 감소: 최근 5경기 {p['l5min']:.0f}분 (시즌 {p['season']['min']:.0f}분)")
        if p["tgames"] >= 8 and p["missed"] / p["tgames"] >= 0.3:
            score += 0.7
            reasons.append(f"잦은 결장: 팀 {p['tgames']}경기 중 {p['missed']}경기 결장"
                           + (f", 현재 {ii['status']}" if ii and not ii["is_out"] else ""))
        if p["l7val"] is not None and p["trend"] <= -1.0:
            score += -p["trend"] * 0.4
            reasons.append(f"최근 7일 판타지 가치 {p['l7val']:+.1f} (시즌 {p['sval']:+.1f})")
        if not reasons:
            continue
        if p["games_this"] <= 2:
            score += 0.5
        reasons.append(fmt_games(p))
        score -= max(0, 100 - p["rank"]) / 50  # 순위가 높을수록 방출 신중
        if score > 0:
            drops.append({**p, "score": score, "reasons": reasons})
    drops.sort(key=lambda x: -x["score"])

    # ---- 복귀 임박 (7일 이내) 주요 선수: 스태시/트레이드 타이밍 참고
    soon = []
    for name in cur_inj:
        p, ii = by_name.get(name), inj_info(name)
        if p and ii and ii["is_out"] and ii["days"] is not None and 0 <= ii["days"] <= 7 \
                and p["season"]["min"] >= 22:
            soon.append({**p, "reasons": [f"{ii.get('type') or '부상'}, {md(ii['return'])} 복귀 예상",
                                          f"시즌 판타지 순위 {p['rank']}위", fmt_games(p)]})
    soon.sort(key=lambda x: x["rank"])

    return {"add": adds[:5], "drop": drops[:5], "soon": soon[:10]}


# ---------------------------------------------------------------- Claude 요약 (선택)
def claude_summary(tdate, issues, returns, new_inj, standouts, flops):
    key = os.getenv("ANTHROPIC_API_KEY")
    if not key:
        return ""
    def short(l):
        return f"{l['name']}({l['team']}) {int(l['pts'])}점 {int(l['reb'])}리 {int(l['ast'])}어"
    payload = {
        "date": tdate,
        "games": [{"score": " vs ".join(f"{t['abbr']} {t['score']}" for t in i["game"]["teams"]),
                   "flags": i["flags"], "big": i["big"], "headline": i["game"]["headline"]} for i in issues],
        "returns": [f"{r['name']}({r['team']}) {r['note']}" for r in returns[:10]],
        "new_injuries": [f"{r['name']}({r['team']}) {r['status']} {r['comment']}" for r in new_inj[:10]],
        "standouts": [short(r["line"]) for r in standouts],
        "underperformers": [short(r["line"]) for r in flops],
    }
    prompt = ("다음은 NBA 하루치 경기 데이터다. 한국어로 그날의 핵심 이슈 6~10개를 한 줄씩 써라. "
              "각 줄은 '- '로 시작하고, 사실만 쓰고 데이터에 없는 내용은 추측하지 마라. 이모티콘 금지.\n\n"
              + json.dumps(payload, ensure_ascii=False))
    try:
        r = requests.post("https://api.anthropic.com/v1/messages", timeout=90, headers={
            "x-api-key": key, "anthropic-version": "2023-06-01", "content-type": "application/json"},
            json={"model": CLAUDE_MODEL, "max_tokens": 1200,
                  "messages": [{"role": "user", "content": prompt}]})
        r.raise_for_status()
        return "".join(b.get("text", "") for b in r.json().get("content", []))
    except Exception as e:
        print(f"[warn] Claude 요약 실패: {e}")
        return ""


# ---------------------------------------------------------------- HTML
def pct(m, a):
    return f"{m / a * 100:.1f}%" if a else "-"


def stat_cells(s, is_avg):
    """야후 9카테고리 + 출전시간"""
    f = (lambda v: f"{v:.1f}") if is_avg else (lambda v: f"{int(v)}")
    if is_avg:
        fg, ft = pct(s["fgm"], s["fga"]), pct(s["ftm"], s["fta"])
    else:
        fg = f"{int(s['fgm'])}-{int(s['fga'])}"
        ft = f"{int(s['ftm'])}-{int(s['fta'])}"
    vals = [f"{s['min']:.0f}", f(s["pts"]), f(s["reb"]), f(s["ast"]), f(s["stl"]),
            f(s["blk"]), f(s["tpm"]), fg, ft, f(s["to"])]
    return "".join(f"<td>{esc(v)}</td>" for v in vals)


HEAD = "<th>MIN</th><th>PTS</th><th>REB</th><th>AST</th><th>STL</th><th>BLK</th><th>3PM</th><th>FG</th><th>FT</th><th>TO</th>"


def player_table(items, extra_label="비고"):
    """items: [{name, team, note, rows: [(라벨, stats|None, is_avg)]}]"""
    if not items:
        return "<p class='empty'>해당 선수 없음</p>"
    out = [f"<div class='scroll'><table><thead><tr><th class='l'>선수</th><th class='l'>구분</th>{HEAD}<th class='l'>{esc(extra_label)}</th></tr></thead><tbody>"]
    for it in items:
        rows = [r for r in it["rows"] if r[1]] or [("기록 없음", None, False)]
        for i, (lab, s, is_avg) in enumerate(rows):
            out.append("<tr class='first'>" if i == 0 else "<tr>")
            if i == 0:
                out.append(f"<td class='l name' rowspan='{len(rows)}'>{esc(it['name'])}<span>{esc(it['team'])}</span></td>")
            out.append(f"<td class='l lab'>{esc(lab)}</td>")
            out.append(stat_cells(s, is_avg) if s else "<td colspan='10' class='l'>-</td>")
            if i == 0:
                out.append(f"<td class='l note' rowspan='{len(rows)}'>{esc(it['note'])}</td>")
            out.append("</tr>")
    out.append("</tbody></table></div>")
    return "".join(out)


CSS = """
:root{--bg:#f6f7f9;--panel:#fff;--ink:#14213d;--sub:#5b6478;--line:#dfe3ea;--accent:#c2410c;--warn:#b91c1c;color-scheme:light}
@media (prefers-color-scheme:dark){:root{--bg:#0f1420;--panel:#171e2e;--ink:#e8ecf4;--sub:#9aa4b8;--line:#2a3347;--accent:#fb923c;--warn:#f87171;color-scheme:dark}}
*{box-sizing:border-box}
body{margin:0;background:var(--bg);color:var(--ink);font-family:"Noto Sans KR",system-ui,-apple-system,sans-serif;line-height:1.55}
main{max-width:1100px;margin:0 auto;padding:24px 16px 64px}
header h1{font-size:1.9rem;margin:0 0 4px;font-weight:800}
header p{margin:0;color:var(--sub)}
nav{margin:14px 0 4px;display:flex;flex-wrap:wrap;gap:6px}
nav a{font-size:.85rem;color:var(--ink);text-decoration:none;border:1px solid var(--line);padding:4px 10px;border-radius:999px;background:var(--panel)}
nav a:hover{border-color:var(--accent)}
section{background:var(--panel);border:1px solid var(--line);border-radius:10px;padding:18px;margin-top:18px}
h2{font-size:1.15rem;margin:0 0 4px;padding-left:10px;border-left:4px solid var(--accent)}
.desc{margin:0 0 12px;padding-left:14px;color:var(--sub);font-size:.85rem}
.scroll{overflow-x:auto}
table{border-collapse:collapse;width:100%;font-size:.86rem;font-variant-numeric:tabular-nums}
th,td{padding:6px 7px;text-align:right;white-space:nowrap;border-bottom:1px solid var(--line)}
th{color:var(--sub);font-weight:600;font-size:.78rem}
.l{text-align:left}
tr.first td{border-top:2px solid var(--line)}
td.name{font-weight:700;vertical-align:top}
td.name span{display:block;font-weight:400;color:var(--sub);font-size:.78rem}
td.lab{color:var(--sub)}
td.note{white-space:pre-line;min-width:260px;max-width:420px;vertical-align:top;color:var(--ink);font-size:.82rem}
.games{display:grid;grid-template-columns:repeat(auto-fill,minmax(250px,1fr));gap:10px}
.game{border:1px solid var(--line);border-radius:8px;padding:10px 12px}
.game .score{font-weight:700;font-size:1.02rem}
.game .win{color:var(--accent)}
.flag{display:inline-block;font-size:.75rem;border:1px solid var(--accent);color:var(--accent);border-radius:4px;padding:0 6px;margin:4px 4px 0 0}
.game ul{margin:6px 0 0;padding-left:18px;font-size:.85rem}
.ai{white-space:pre-wrap;margin:0 0 12px}
.empty{color:var(--sub)}
.sched{display:grid;grid-template-columns:auto 1fr;gap:6px 14px;font-size:.88rem}
.sched b{white-space:nowrap}
.method{font-size:.85rem;color:var(--sub)}
.method p{margin:6px 0}
.archive a{margin-right:10px;color:var(--ink)}
"""


def section(sid, title, desc, body):
    d = f"<p class='desc'>{esc(desc)}</p>" if desc else ""
    return f"<section id='{sid}'><h2>{esc(title)}</h2>{d}{body}</section>"


def render(r):
    now = dt.datetime.now(KST).strftime("%Y-%m-%d %H:%M")
    fz = r["fantasy"]
    sc = r["sched"]
    P = []

    # ---- 판타지 (구단주 관점에서 가장 먼저 볼 내용)
    def fan_items(lst):
        return [{"name": x["name"], "team": f"{x['team']} {x['pos']} / 판타지 {x['rank']}위",
                 "note": "\n".join(f"- {t}" for t in x["reasons"]),
                 "rows": [("최근 7일", x["l7"], True), ("시즌 평균", x["season"], True)]} for x in lst]

    P.append(section("add", "영입 추천 5",
                     "주축 부상에 따른 출전시간 증가, 선발 승격, 최근 생산력, 이번 주 경기 수를 종합. 시즌 순위 상위권(로스터 보유 가능성 높은 선수)은 제외.",
                     player_table(fan_items(fz["add"]), "추천 근거")))
    P.append(section("drop", "방출 고려 5",
                     f"시즌 판타지 순위 {PROTECT_TOP}위 이내 핵심 선수는 제외. 장기 부상, 주전 복귀로 인한 역할 축소, 벤치 강등, 출전시간 감소, 잦은 결장을 종합.",
                     player_table(fan_items(fz["drop"]), "방출 근거")))
    P.append(section("soon", "복귀 임박 주요 선수 (7일 이내)",
                     "웨이버에 있으면 미리 잡아두기, 내 선수면 IL 해제 준비. 같은 팀 대체 자원은 출전시간이 줄어들 수 있음.",
                     player_table([{"name": x["name"], "team": f"{x['team']} {x['pos']}",
                                    "note": "\n".join(f"- {t}" for t in x["reasons"]),
                                    "rows": [("시즌 평균", x["season"], True)]} for x in fz["soon"]], "상태")))

    # 일정
    def sched_block(cnt):
        groups = {}
        for t, n in cnt.items():
            groups.setdefault(n, []).append(t)
        if not groups:
            return "<p class='empty'>일정 정보 없음</p>"
        return "<div class='sched'>" + "".join(
            f"<b>{n}경기</b><span>{esc(', '.join(sorted(groups[n])))}</span>" for n in sorted(groups, reverse=True)) + "</div>"
    a, b = sc["this_range"]
    c, d = sc["next_range"]
    P.append(section("sched", "팀별 경기 수",
                     "경기 수가 많은 팀 선수가 주간 누적 기록에 유리. 스트리밍(단기 영입) 판단용.",
                     f"<h3>이번 주 잔여 ({md(a.isoformat())}~{md(b.isoformat())})</h3>{sched_block(sc['this'])}"
                     f"<h3>다음 주 ({md(c.isoformat())}~{md(d.isoformat())})</h3>{sched_block(sc['next'])}"))

    # ---- 부상
    items = [{"name": x["name"], "team": x["team"], "note": f"- {x['note']}",
              "rows": [("오늘", x["line"], False), ("시즌 평균", x["avg"], True)]} for x in r["returns"]]
    P.append(section("returns", f"부상 복귀 ({len(items)}명)", "같은 팀 대체 선수의 출전시간 감소 여부 확인 필요.", player_table(items)))
    items = [{"name": x["name"], "team": x["team"],
              "note": "\n".join(t for t in [f"- {x['status']} / {x['type'] or '부위 미상'}",
                                            f"- {md(x['return'])} 복귀 예상" if x["return"] else "- 복귀 시점 미정",
                                            f"- {x['comment']}" if x["comment"] else ""] if t),
              "rows": [("시즌 평균", x["avg"], True)]} for x in r["new_inj"]]
    P.append(section("injuries", f"신규 부상 ({len(items)}명)", "주축이면 같은 팀 백업이 영입 후보가 됨.", player_table(items, "상태")))

    # ---- 경기 리뷰
    def perf_items(lst):
        return [{"name": x["line"]["name"], "team": f"{x['line']['team']} vs {x['line']['opp']}",
                 "note": f"- 게임스코어 {x['gs']:.1f} (평소 대비 {x['diff']:+.1f})"
                         + ("\n- " + ", ".join(tags(x["line"])) if tags(x["line"]) else ""),
                 "rows": [("오늘", x["line"], False), ("시즌 평균", x["avg"], True)]} for x in lst]
    P.append(section("best", "눈에 띄게 잘한 선수 5", "", player_table(perf_items(r["standouts"]))))
    P.append(section("worst", "기대보다 못한 선수 5", "시즌 평균 대비 하락폭 기준. 한 경기 부진은 방출 사유가 아님.", player_table(perf_items(r["flops"]))))

    body = []
    if r["ai"]:
        body.append(f"<p class='ai'>{esc(r['ai'])}</p>")
    if not r["issues"]:
        body.append("<p class='empty'>이 날짜에 종료된 경기가 없습니다.</p>")
    body.append("<div class='games'>")
    for i in r["issues"]:
        ta, tb = i["game"]["teams"]
        w = ta if ta["score"] > tb["score"] else tb
        def t(x):
            cls = " class='win'" if x is w else ""
            return f"<span{cls}>{esc(x['abbr'])} {x['score']}</span>"
        body.append(f"<div class='game'><div class='score'>{t(ta)} : {t(tb)}</div>")
        body.append("".join(f"<span class='flag'>{esc(f)}</span>" for f in i["flags"]))
        if i["big"]:
            body.append("<ul>" + "".join(f"<li>{esc(x)}</li>" for x in i["big"]) + "</ul>")
        body.append("</div>")
    body.append("</div>")
    P.append(section("issues", "경기 결과와 이슈", "", "".join(body)))

    P.append(f"""<section class='method'><h2>판단 기준</h2>
<p>판타지 가치: 야후 기본 9카테고리(FG%, FT%, 3PM, PTS, REB, AST, STL, BLK, TO) z-score 합. 포인트 리그는 결과가 다를 수 있음.</p>
<p>영입 추천: 최근 7일 가치에 가산점. 주축(평균 24분 이상) 결장 시 그 기간 출전시간이 4분 이상 늘어난 같은 팀 선수, 결장 기간이 길수록 가산. 주전 복귀가 3일 이내면 감점. 출전시간 증가, 선발 승격, 이번 주 경기 수 반영.</p>
<p>방출 고려: 시즌 {PROTECT_TOP}위 이내 제외. 장기 부상(복귀 14일 이상 또는 시즌아웃/수술), 장기 결장 주전 복귀 후 출전시간 4분 이상 감소, 선발에서 벤치 이동, 결장 비율 30% 이상, 최근 가치 하락. 순위가 높을수록 감점.</p>
<p>야후 보유율은 로그인 없이 가져올 수 없어 반영하지 않음. 리그 웨이버에 실제로 있는지 확인 필요. 데이터 출처: ESPN.</p></section>""")

    files = sorted(ARCH.glob("*.html"), reverse=True)[:30]
    if files:
        P.append("<section class='archive'><h2>지난 리포트</h2>" +
                 "".join(f"<a href='archive/{f.name}'>{f.stem}</a>" for f in files) + "</section>")

    nav = "".join(f"<a href='#{a}'>{b}</a>" for a, b in [
        ("add", "영입 추천"), ("drop", "방출 고려"), ("soon", "복귀 임박"), ("sched", "경기 수"),
        ("returns", "부상 복귀"), ("injuries", "신규 부상"), ("best", "잘한 선수"),
        ("worst", "못한 선수"), ("issues", "경기 결과")])
    return f"""<!doctype html><html lang="ko"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>NBA 판타지 리포트 {r['date']}</title>
<link rel="preconnect" href="https://fonts.googleapis.com"><link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>
<link href="https://fonts.googleapis.com/css2?family=Noto+Sans+KR:wght@400;600;800&display=swap" rel="stylesheet">
<style>{CSS}</style></head><body><main>
<header><h1>NBA 판타지 리포트 {r['date']}</h1><p>미국 동부시간 기준 경기일 / 업데이트 {now} (KST)</p><nav>{nav}</nav></header>
{''.join(P)}
</main></body></html>"""


# ---------------------------------------------------------------- main
def main():
    td = (os.getenv("TARGET_DATE") or "").strip()
    target = dt.date.fromisoformat(td) if td else (dt.datetime.now(ET) - dt.timedelta(days=1)).date()
    print(f"[run] target={target}")
    r = build(target)
    ARCH.mkdir(parents=True, exist_ok=True)
    page = render(r)
    (ARCH / f"{r['date']}.html").write_text(page.replace("href='archive/", "href='"), encoding="utf-8")
    (DOCS / "index.html").write_text(render(r), encoding="utf-8")
    print("[done] docs/index.html")


if __name__ == "__main__":
    main()
