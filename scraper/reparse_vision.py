"""Чистый репарс института через vision (Sonnet) с валидацией кодов групп.

Качает актуальные файлы со страницы расписания (прямые .pdf и nextcloud-шары
oc.mpgu.su, в т.ч. ZIP), распознаёт через ClaudeClient, оставляет ТОЛЬКО группы
с валидным кодом (или 3-значным номером при --allow-numeric), нормализует
гомоглифы, склеивает дубли, санитизирует.

Usage: python -m scraper.reparse_vision <institute_id> <page_url>
         [--out FILE] [--exclude SUBSTR ...] [--allow-numeric]
"""
import sys, re, json, ssl, argparse, urllib.request, urllib.parse, tempfile, os, io, zipfile, subprocess

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from scraper.utils.claude_client import ClaudeClient
from scraper.normalizer.schedule_normalizer import sanitize_groups, fix_homoglyphs

_CTX = ssl.create_default_context(); _CTX.check_hostname = False; _CTX.verify_mode = ssl.CERT_NONE
FULL_CODE_RE = re.compile(r'[А-Я]{2,3}\d{2}-[А-Я]{2,4}\d{4}')
NUMERIC_RE = re.compile(r'^(?:группа\s*)?(\d{3})(?:\s*группа)?$', re.I)
OLD_YEAR_RE = re.compile(r'/20(1\d|2[0-4])/')  # 2010-2024 в пути аплоада


def _get(url):
    req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
    return urllib.request.urlopen(req, timeout=90, context=_CTX).read()


def _enc(url):
    p = urllib.parse.urlsplit(url)
    return urllib.parse.urlunsplit((p.scheme, p.netloc, urllib.parse.quote(p.path), p.query, p.fragment))


def list_sources(page_url, excludes):
    """Прямые .pdf + nextcloud-шары oc.mpgu.su."""
    html = _get(_enc(page_url)).decode("utf-8", "replace")
    out, seen = [], set()
    for h in re.findall(r'href="([^"]+)"', html, re.I):
        au = urllib.parse.urljoin(page_url, h.strip())
        low = urllib.parse.unquote(au).lower()
        is_pdf = low.split("?")[0].endswith(".pdf")
        is_nc = "oc.mpgu.su" in low and "/s/" in low
        if not (is_pdf or is_nc) or au in seen:
            continue
        seen.add(au)
        if is_pdf and OLD_YEAR_RE.search(au):
            continue
        if any(x in low for x in excludes):
            continue
        out.append(au)
    return out


def fetch_pdfs(url):
    """Скачивает источник, возвращает пути к PDF (раскрывая nextcloud/ZIP)."""
    dl = url
    if "oc.mpgu.su" in url and "/download" not in url:
        dl = url.rstrip("/") + "/download"
    data = _get(_enc(dl))
    paths = []
    if data[:2] == b"PK":
        zf = zipfile.ZipFile(io.BytesIO(data))
        for nm in zf.namelist():
            if nm.lower().endswith(".pdf"):
                p = tempfile.NamedTemporaryFile(suffix=".pdf", delete=False)
                p.write(zf.read(nm)); p.close(); paths.append(p.name)
    elif data[:4] == b"%PDF":
        p = tempfile.NamedTemporaryFile(suffix=".pdf", delete=False)
        p.write(data); p.close(); paths.append(p.name)
    return paths


def infer_form_degree(fname):
    f = fname.lower()
    degree = "master" if ("mag" in f or "магистр" in f or "-маг" in f) else (
        "specialist" if "spvo" in f or "спво" in f else "bachelor")
    if "ochno-zaochnoe" in f or "ozfo" in f or "очно-заочн" in f:
        form = "part_time"
    elif re.search(r'(^|[-_])zfo|зфо|[-_]z[-_.]|курс-z', f):
        form = "correspondence"
    else:
        form = "full_time"
    return form, degree


CORE_RE = re.compile(r'[А-Я]{2,4}\d{4}')


def authoritative(path):
    """Коды групп из текстового слоя PDF: (полные коды, ядра). Пусто для скана."""
    try:
        txt = subprocess.run(["pdftotext", path, "-"], capture_output=True,
                             text=True, timeout=60).stdout
    except Exception:
        return set(), set()
    txt = fix_homoglyphs(txt)
    return set(FULL_CODE_RE.findall(txt)), set(CORE_RE.findall(txt))


def clean_name(raw, allow_numeric, full_codes, cores):
    """Возвращает чистое имя группы или None.

    Если у файла есть текстовый слой (cores непусто) — код ОБЯЗАН совпасть с
    эталоном (иначе это misread vision → отбрасываем). Полный код берём из
    эталона, если он там есть."""
    name = fix_homoglyphs((raw or "").strip())
    m = FULL_CODE_RE.search(name)
    if m:
        code = m.group(0)
        core = CORE_RE.search(code).group(0)
        if cores:  # текстовый источник — валидируем по эталону
            if core not in cores:
                return None
            for fc in full_codes:  # предпочитаем полный эталонный код
                if fc.endswith(core):
                    return fc
            return code
        return code  # скан — без валидации, как прочитал vision
    if allow_numeric and not cores:
        m = NUMERIC_RE.match(name)
        if m:
            return f"{m.group(1)} группа"
    return None


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("institute_id")
    ap.add_argument("page_url")
    ap.add_argument("--out", default=None)
    ap.add_argument("--exclude", nargs="*",
                    default=["задолжен", "zadolzh", "ликвидац", "адаптацион"])
    ap.add_argument("--allow-numeric", action="store_true")
    ap.add_argument("--batch", type=int, default=12,
                    help="страниц за вызов; крупно = весь документ сразу "
                         "(сохраняет связь колонка→код через страницы-продолжения)")
    ap.add_argument("--surya", action="store_true",
                    help="для сканов: Surya разбивает на колонки-группы, "
                         "каждая читается отдельно (чистые коды без слияния)")
    args = ap.parse_args()

    client = ClaudeClient()
    surya = None
    if args.surya:
        from scraper.parsers.surya_column_parser import SuryaColumnParser
        surya = SuryaColumnParser()
    sources = list_sources(args.page_url, args.exclude)
    print(f"источников: {len(sources)}", file=sys.stderr)

    merged, order = {}, []
    for url in sources:
        fname = urllib.parse.unquote(url.rsplit("/", 1)[-1])
        form, degree = infer_form_degree(fname)
        try:
            pdfs = fetch_pdfs(url)
        except Exception as e:
            print(f"  ERR fetch {fname}: {e}", file=sys.stderr); continue
        if not pdfs:
            print(f"  -- {fname[:50]}: не PDF/ZIP (возможно требует логина)", file=sys.stderr); continue
        kept = 0
        for path in pdfs:
            full_codes, cores = authoritative(path)
            try:
                if surya is not None:
                    res = {"groups": surya.parse(path)}
                else:
                    res = client.parse_pdf_pages(path, batch_size=args.batch)
            except Exception as e:
                print(f"  ERR parse {fname}: {e}", file=sys.stderr); res = {"groups": []}
            finally:
                try: os.unlink(path)
                except OSError: pass
            for g in res.get("groups", []):
                # Surya уже отдаёт чистый валидный код; для сканов нет текстового
                # слоя, поэтому не отбрасываем по cores — доверяем мажоритарному коду.
                name = clean_name(g.get("name"), args.allow_numeric,
                                  full_codes, set() if surya is not None else cores)
                if not name:
                    continue
                g["name"] = name; g["form"] = form; g["degree"] = degree
                if name in merged:
                    for wk in ("odd_week", "even_week"):
                        a = merged[name].setdefault("schedule", {}).setdefault(wk, {})
                        for d, ls in (g.get("schedule", {}).get(wk, {}) or {}).items():
                            a.setdefault(d, []).extend(ls or [])
                else:
                    merged[name] = g; order.append(name)
                kept += 1
        print(f"  {fname[:52]:52} form={form} kept={kept}", file=sys.stderr)

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
