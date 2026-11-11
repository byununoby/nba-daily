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


def fetch_news(limit=8):
    d = get(f"{BASE}/news", {"limit": limit})
    out = []
    for a in (d or {}).get("articles", [])[:limit]:
        out.append({"headline": a.get("headline", ""), "desc": a.get("description", ""),
                    "url": ((a.get("links") or {}).get("web") or {}).get("href", "")})
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

    # 4) 야후 판타지 (9카테고리 z-score)
    fantasy = fantasy_picks(by_player, target, cur_inj)

    # 5) 경기별 이슈
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
    news = fetch_news()
    ai_summary = claude_summary(tdate, issues, returns, new_inj, standouts, flops)

    return {"date": tdate, "games": today["games"], "issues": issues, "news": news,
            "ai": ai_summary, "returns": returns, "new_inj": new_inj,
            "standouts": standouts, "flops": flops, "fantasy": fantasy}


def fantasy_picks(by_player, target, cur_inj):
    tdate = target.isoformat()
    l7_start = (target - dt.timedelta(days=6)).isoformat()
    season = {}
    for pid, ls in by_player.items():
        ls = [l for l in ls if l["date"] <= tdate]
        if len(ls) >= 3:
            season[pid] = (avg(ls), [l for l in ls if l["date"] >= l7_start], ls[-1])
    if not season:
        return {"add": [], "drop": []}
    pool = [s[0] for s in season.values() if s[0]["min"] >= 18] or [s[0] for s in season.values()]
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

    rows = []
    for pid, (sa, l7, last) in season.items():
        rows.append({"id": pid, "name": last["name"], "team": last["team"], "season": sa,
                     "sval": value(sa), "l7": avg(l7) if len(l7) >= 2 else None})
    rows.sort(key=lambda r: -r["sval"])
    for i, r in enumerate(rows, 1):
        r["rank"] = i
        r["l7val"] = value(r["l7"]) if r["l7"] else None
        r["trend"] = (r["l7val"] - r["sval"]) if r["l7"] else None
        inj = cur_inj.get(r["name"])
        r["inj"] = f"{inj['status']} ({inj['type'] or inj['comment'][:40]})" if inj else ""

    cut = min(100, int(len(rows) * 0.3))
    add = [r for r in rows if r["rank"] > cut and r["l7"] and r["trend"] > 0
           and not (cur_inj.get(r["name"], {}).get("status") == "Out")]
    add.sort(key=lambda r: -(r["l7val"] + 0.5 * r["trend"]))
    drop = [r for r in rows if 50 < r["rank"] <= 150 and r["l7"]]
    drop.sort(key=lambda r: r["trend"])
    return {"add": add[:5], "drop": drop[:5]}


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
    f = (lambda v: f"{v:.1f}") if is_avg else (lambda v: f"{int(v)}")
    if is_avg:
        fg, tp, ft = pct(s["fgm"], s["fga"]), f"{s['tpm']:.1f}", pct(s["ftm"], s["fta"])
    else:
        fg = f"{int(s['fgm'])}-{int(s['fga'])}"
        tp = f"{int(s['tpm'])}-{int(s['tpa'])}"
        ft = f"{int(s['ftm'])}-{int(s['fta'])}"
    pm = s["pm"]
    vals = [f"{s['min']:.0f}", f(s["pts"]), f(s["reb"]), f(s["ast"]), f(s["stl"]),
            f(s["blk"]), tp, fg, ft, f(s["to"]), (f"{pm:+.1f}" if is_avg else f"{int(pm):+d}")]
    return "".join(f"<td>{esc(v)}</td>" for v in vals)


HEAD = "<th>MIN</th><th>PTS</th><th>REB</th><th>AST</th><th>STL</th><th>BLK</th><th>3P</th><th>FG</th><th>FT</th><th>TO</th><th>+/-</th>"


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
            out.append(stat_cells(s, is_avg) if s else "<td colspan='11' class='l'>-</td>")
            if i == 0:
                out.append(f"<td class='l note' rowspan='{len(rows)}'>{esc(it['note'])}</td>")
            out.append("</tr>")
    out.append("</tbody></table></div>")
    return "".join(out)


CSS = """
:root{--bg:#f6f7f9;--panel:#fff;--ink:#14213d;--sub:#5b6478;--line:#dfe3ea;--accent:#c2410c;--good:#15803d;--bad:#b91c1c;color-scheme:light}
@media (prefers-color-scheme:dark){:root{--bg:#0f1420;--panel:#171e2e;--ink:#e8ecf4;--sub:#9aa4b8;--line:#2a3347;--accent:#fb923c;--good:#4ade80;--bad:#f87171;color-scheme:dark}}
*{box-sizing:border-box}
body{margin:0;background:var(--bg);color:var(--ink);font-family:"Noto Sans KR",system-ui,-apple-system,sans-serif;line-height:1.55}
main{max-width:1100px;margin:0 auto;padding:24px 16px 64px}
header h1{font-size:1.9rem;margin:0 0 4px;font-weight:800}
header p{margin:0;color:var(--sub)}
nav{margin:14px 0 4px;display:flex;flex-wrap:wrap;gap:6px}
nav a{font-size:.85rem;color:var(--ink);text-decoration:none;border:1px solid var(--line);padding:4px 10px;border-radius:999px;background:var(--panel)}
nav a:hover{border-color:var(--accent)}
section{background:var(--panel);border:1px solid var(--line);border-radius:10px;padding:18px;margin-top:18px}
h2{font-size:1.15rem;margin:0 0 12px;padding-left:10px;border-left:4px solid var(--accent)}
.scroll{overflow-x:auto}
table{border-collapse:collapse;width:100%;font-size:.86rem;font-variant-numeric:tabular-nums}
th,td{padding:6px 7px;text-align:right;white-space:nowrap;border-bottom:1px solid var(--line)}
th{color:var(--sub);font-weight:600;font-size:.78rem}
.l{text-align:left}
tr.first td{border-top:2px solid var(--line)}
td.name{font-weight:700;vertical-align:top}
td.name span{display:block;font-weight:400;color:var(--sub);font-size:.78rem}
td.lab{color:var(--sub)}
td.note{white-space:normal;min-width:180px;vertical-align:top;color:var(--sub)}
.games{display:grid;grid-template-columns:repeat(auto-fill,minmax(250px,1fr));gap:10px}
.game{border:1px solid var(--line);border-radius:8px;padding:10px 12px}
.game .score{font-weight:700;font-size:1.02rem}
.game .win{color:var(--accent)}
.flag{display:inline-block;font-size:.75rem;border:1px solid var(--accent);color:var(--accent);border-radius:4px;padding:0 6px;margin:4px 4px 0 0}
.game ul{margin:6px 0 0;padding-left:18px;font-size:.85rem}
.game .hl{font-size:.82rem;color:var(--sub);margin-top:6px}
.ai{white-space:pre-wrap;margin:0 0 12px}
.news a{color:var(--ink)}
.empty{color:var(--sub)}
.up{color:var(--good)}.down{color:var(--bad)}
.method{font-size:.85rem;color:var(--sub)}
.archive a{margin-right:10px;color:var(--ink)}
"""


def render(r):
    now = dt.datetime.now(KST).strftime("%Y-%m-%d %H:%M")
    P = []
    # 경기 & 이슈
    P.append("<section id='issues'><h2>경기 결과와 이슈</h2>")
    if r["ai"]:
        P.append(f"<p class='ai'>{esc(r['ai'])}</p>")
    if not r["issues"]:
        P.append("<p class='empty'>이 날짜에 종료된 경기가 없습니다.</p>")
    P.append("<div class='games'>")
    for i in r["issues"]:
        a, b = i["game"]["teams"]
        w = a if a["score"] > b["score"] else b
        def t(x):
            cls = " class='win'" if x is w else ""
            return f"<span{cls}>{esc(x['abbr'])} {x['score']}</span>"
        P.append(f"<div class='game'><div class='score'>{t(a)} : {t(b)}</div>")
        P.append("".join(f"<span class='flag'>{esc(f)}</span>" for f in i["flags"]))
        if i["big"]:
            P.append("<ul>" + "".join(f"<li>{esc(x)}</li>" for x in i["big"]) + "</ul>")
        if i["game"]["headline"]:
            P.append(f"<div class='hl'>{esc(i['game']['headline'])}</div>")
        P.append("</div>")
    P.append("</div>")
    if r["news"]:
        P.append("<h3>ESPN 주요 뉴스</h3><ul class='news'>")
        for n in r["news"]:
            P.append(f"<li><a href='{esc(n['url'])}' target='_blank' rel='noopener'>{esc(n['headline'])}</a></li>")
        P.append("</ul>")
    P.append("</section>")

    # 복귀
    items = [{"name": x["name"], "team": x["team"], "note": x["note"],
              "rows": [("오늘", x["line"], False), ("시즌 평균", x["avg"], True)]} for x in r["returns"]]
    P.append(f"<section id='returns'><h2>부상 복귀 ({len(items)}명)</h2>{player_table(items)}</section>")

    # 신규 부상
    items = [{"name": x["name"], "team": x["team"],
              "note": f"{x['status']} / {x['type']} {('/ 복귀예상 ' + x['return']) if x['return'] else ''} / {x['comment']}",
              "rows": [("시즌 평균", x["avg"], True)]} for x in r["new_inj"]]
    P.append(f"<section id='injuries'><h2>신규 부상 ({len(items)}명)</h2>{player_table(items, '상태')}</section>")

    # 잘한 / 못한
    def perf_items(lst):
        out = []
        for x in lst:
            d = x["diff"]
            out.append({"name": x["line"]["name"], "team": f"{x['line']['team']} vs {x['line']['opp']}",
                        "note": f"게임스코어 {x['gs']:.1f} (평소 대비 {d:+.1f})" + (" / " + ", ".join(tags(x["line"])) if tags(x["line"]) else ""),
                        "rows": [("오늘", x["line"], False), ("시즌 평균", x["avg"], True)]})
        return out
    P.append(f"<section id='best'><h2>눈에 띄게 잘한 선수 5</h2>{player_table(perf_items(r['standouts']))}</section>")
    P.append(f"<section id='worst'><h2>기대보다 못한 선수 5</h2>{player_table(perf_items(r['flops']))}</section>")

    # 판타지
    def fan_items(lst, kind):
        out = []
        for x in lst:
            note = (f"시즌 가치 {x['sval']:+.1f} ({x['rank']}위) / 최근7일 {x['l7val']:+.1f} "
                    f"({'상승' if x['trend'] > 0 else '하락'} {x['trend']:+.1f})")
            if x["inj"]:
                note += f" / 부상: {x['inj']}"
            out.append({"name": x["name"], "team": x["team"], "note": note,
                        "rows": [("최근 7일", x["l7"], True), ("시즌 평균", x["season"], True)]})
        return out
    P.append(f"<section id='add'><h2>야후 판타지 영입 추천 5</h2>{player_table(fan_items(r['fantasy']['add'], 'add'), '판단 근거')}</section>")
    P.append(f"<section id='drop'><h2>야후 판타지 방출 고려 5</h2>{player_table(fan_items(r['fantasy']['drop'], 'drop'), '판단 근거')}</section>")

    P.append("""<section class='method'><h2>판단 기준</h2>
<p>잘한/못한 선수: Hollinger 게임스코어 기준. 잘한 선수는 오늘 게임스코어와 시즌 평균 대비 상승폭을 함께 반영(20분 이상 출전). 못한 선수는 시즌 평균 게임스코어 13 이상 주축 선수 중 평소 대비 하락폭이 큰 순(15분 이상 출전).</p>
<p>판타지: 야후 기본 9카테고리(FG%, FT%, 3PM, PTS, REB, AST, STL, BLK, TO) z-score 합산. 영입 추천은 시즌 가치 100위 밖이면서 최근 7일 가치가 오른 선수. 방출 고려는 시즌 51~150위 중 최근 7일 가치 하락폭이 큰 선수. 야후 보유율은 로그인 없이 가져올 수 없어 반영하지 않음. 포인트 리그라면 결과가 다를 수 있음.</p>
<p>부상 복귀: 팀이 3경기 이상 치르는 동안 결장 후 출전했거나, 직전 부상자 명단에서 빠진 선수. 데이터 출처: ESPN.</p></section>""")

    files = sorted(ARCH.glob("*.html"), reverse=True)[:30]
    if files:
        P.append("<section class='archive'><h2>지난 리포트</h2>" +
                 "".join(f"<a href='archive/{f.name}'>{f.stem}</a>" for f in files) + "</section>")

    nav = "".join(f"<a href='#{a}'>{b}</a>" for a, b in [
        ("issues", "이슈"), ("returns", "복귀"), ("injuries", "부상"), ("best", "잘한 선수"),
        ("worst", "못한 선수"), ("add", "영입 추천"), ("drop", "방출 고려")])
    return f"""<!doctype html><html lang="ko"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>NBA 일일 리포트 {r['date']}</title>
<link rel="preconnect" href="https://fonts.googleapis.com"><link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>
<link href="https://fonts.googleapis.com/css2?family=Noto+Sans+KR:wght@400;600;800&display=swap" rel="stylesheet">
<style>{CSS}</style></head><body><main>
<header><h1>NBA 일일 리포트 {r['date']}</h1><p>미국 동부시간 기준 경기일 / 업데이트 {now} (KST)</p><nav>{nav}</nav></header>
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
