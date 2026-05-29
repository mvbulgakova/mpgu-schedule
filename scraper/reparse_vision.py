"""Чистый репарс института через vision (Sonnet) с валидацией кодов групп.

Качает актуальные файлы со страницы расписания, распознаёт через ClaudeClient,
оставляет ТОЛЬКО группы с валидным кириллическим кодом (фильтр «только чистое»),
нормализует гомоглифы, склеивает дубли, санитизирует.

Usage: python -m scraper.reparse_vision <institute_id> <page_url> [--out FILE] [--exclude SUBSTR ...]
"""
import sys, re, json, ssl, argparse, urllib.request, urllib.parse, tempfile, os

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from scraper.utils.claude_client import ClaudeClient
from scraper.normalizer.schedule_normalizer import sanitize_groups, fix_homoglyphs

_CTX = ssl.create_default_context(); _CTX.check_hostname = False; _CTX.verify_mode = ssl.CERT_NONE
CODE_RE = re.compile(r'^[А-Я]{1,3}\d{2}-?[А-Я]{0,4}\d{0,4}$')
FULL_CODE_RE = re.compile(r'[А-Я]{2,3}\d{2}-[А-Я]{2,4}\d{4}')
OLD_YEAR_RE = re.compile(r'/20(1\d|2[0-4])/')  # 2010-2024 в пути аплоада


def _get(url):
    req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
    return urllib.request.urlopen(req, timeout=60, context=_CTX).read()


def _enc(url):
    p = urllib.parse.urlsplit(url)
    return urllib.parse.urlunsplit((p.scheme, p.netloc, urllib.parse.quote(p.path), p.query, p.fragment))


def list_pdfs(page_url, excludes):
    html = _get(_enc(page_url)).decode("utf-8", "replace")
    out, seen = [], set()
    for h in re.findall(r'href="([^"]+\.pdf)"', html, re.I):
        au = urllib.parse.urljoin(page_url, h)
        if au in seen:
            continue
        seen.add(au)
        low = urllib.parse.unquote(au).lower()
        if OLD_YEAR_RE.search(au):
            continue
        if any(x in low for x in excludes):
            continue
        out.append(au)
    return out


def infer_form_degree(fname):
    f = fname.lower()
    degree = "master" if ("mag" in f or "магистр" in f or "-маг" in f) else (
        "specialist" if "spvo" in f or "спво" in f else "bachelor")
    if "ochno-zaochnoe" in f or "ozfo" in f or "очно-заочн" in f:
        form = "part_time"
    elif re.search(r'(^|[-_])z(fo|-|\.)|зфо|[-_]z[-_.]|курс-z', f) or "-зфо" in f:
        form = "correspondence"
    else:
        form = "full_time"
    return form, degree


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("institute_id")
    ap.add_argument("page_url")
    ap.add_argument("--out", default=None)
    ap.add_argument("--exclude", nargs="*", default=["задолжен", "zadolzh", "ликвидац", "адаптацион"])
    args = ap.parse_args()

    client = ClaudeClient()
    pdfs = list_pdfs(args.page_url, args.exclude)
    print(f"актуальных PDF: {len(pdfs)}", file=sys.stderr)

    merged, order = {}, []
    for url in pdfs:
        fname = urllib.parse.unquote(url.rsplit("/", 1)[-1])
        form, degree = infer_form_degree(fname)
        try:
            data = _get(_enc(url))
            with tempfile.NamedTemporaryFile(suffix=".pdf", delete=False) as tf:
                tf.write(data); path = tf.name
            res = client.parse_pdf_pages(path, batch_size=1)
            os.unlink(path)
        except Exception as e:
            print(f"  ERR {fname}: {e}", file=sys.stderr); continue
        kept = 0
        for g in res.get("groups", []):
            name = fix_homoglyphs((g.get("name") or "").strip())
            if not FULL_CODE_RE.search(name):
                continue  # «только чистое»: нужен валидный код группы
            name = FULL_CODE_RE.search(name).group(0)
            g["name"] = name; g["form"] = form; g["degree"] = degree
            if name in merged:
                for wk in ("odd_week", "even_week"):
                    a = merged[name].setdefault("schedule", {}).setdefault(wk, {})
                    for d, ls in (g.get("schedule", {}).get(wk, {}) or {}).items():
                        a.setdefault(d, []).extend(ls or [])
            else:
                merged[name] = g; order.append(name)
            kept += 1
        print(f"  {fname[:55]:55} form={form} kept={kept}", file=sys.stderr)

    groups = [merged[n] for n in order]
    sanitize_groups(groups)
    groups = [g for g in groups if sum(len(v) for wk in g.get("schedule", {}).values()
                                        for v in (wk or {}).values()) > 0]
    out = args.out or f"/tmp/{args.institute_id}_result.json"
    json.dump({"groups": groups}, open(out, "w"), ensure_ascii=False, indent=2)
    print(f"\nTOTAL clean groups: {len(groups)} -> {out}")
    print("names:", sorted(g["name"] for g in groups))


if __name__ == "__main__":
    main()
