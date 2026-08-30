"""Долгоживущий тикер: раз в N минут поднимает сегментированный обход.

Зачем именно так. Нужны две вещи сразу, и ни одна не даётся поодиночке:

1. НАДЁЖНЫЙ РИТМ. Расписание GitHub Actions — «по возможности»: 2026-08-05
   при cron */10 у сегментированного обхода фактически случился один запуск
   за 2,3 часа. Зато одна задача живёт часами стабильно — на этом держится
   бот. Значит ритм должен задавать долгий прогон, а не крон.

2. МНОГО АДРЕСОВ. epk25 ограничивает число запросов с одного адреса, и обойти
   этот лимит паузами нельзя: 2026-08-07 обход всех 667 списков одним раннером
   пачками занял 2 часа 17 минут на проход (данные встали на 10 часов ночью),
   тогда как те же 667 страниц с другого адреса снимаются за 109 секунд с
   нулём ошибок. Лечится только числом адресов — по раннеру на долю списков.

Поэтому долгий прогон сам никуда не ходит, а раз в цикл дёргает
fetch-lists-sharded через workflow_dispatch: ритм от долгой задачи, скорость
от десяти раннеров.

Так можно: события от GITHUB_TOKEN намеренно не порождают новых прогонов,
чтобы не было рекурсии, — и workflow_dispatch одно из двух исключений из
этого правила. Задаче нужно permissions: actions: write.

Запуск: python -m scraper.dispatch_loop --workflow fetch-lists-sharded.yml
"""
import argparse
import json
import os
import urllib.error
import urllib.request

API = "https://api.github.com"


def dispatch(workflow: str, ref: str, repo: str, token: str) -> None:
    """Поднять прогон workflow на ветке ref. Бросает исключение при отказе."""
    req = urllib.request.Request(
        f"{API}/repos/{repo}/actions/workflows/{workflow}/dispatches",
        data=json.dumps({"ref": ref}).encode("utf-8"),
        headers={"Authorization": f"Bearer {token}",
                 "Accept": "application/vnd.github+json",
                 "X-GitHub-Api-Version": "2022-11-28",
                 "User-Agent": "MPGU-Abitur-Bot",
                 "Content-Type": "application/json"},
        method="POST")
    with urllib.request.urlopen(req, timeout=30) as r:
        if r.status not in (201, 204):
            raise RuntimeError(f"workflow_dispatch вернул {r.status}")


def main(argv=None) -> int:
    p = argparse.ArgumentParser()
    p.add_argument("--workflow",
                   default=os.environ.get("TARGET_WORKFLOW",
                                          "fetch-lists-sharded.yml"))
    p.add_argument("--ref", default=os.environ.get("TARGET_REF", ""),
                   help="ветка с файлом workflow (по умолчанию — текущая)")
    p.add_argument("--repo", default=os.environ.get("GITHUB_REPOSITORY", ""))
    p.add_argument("--seconds", type=int,
                   default=int(os.environ.get("RUN_SECONDS", "19800")))
    p.add_argument("--interval", type=int,
                   default=int(os.environ.get("CYCLE_SECONDS", "900")))
    args = p.parse_args(argv)

    token = os.environ.get("GITHUB_TOKEN", "")
    ref = args.ref or os.environ.get("GITHUB_REF_NAME", "")
    if not (token and args.repo and ref):
        # Без этого тикер молча крутился бы вхолостую весь прогон, а данные
        # стояли бы — то есть выглядел бы работающим, ничего не делая.
        print(f"Не хватает настроек: repo={args.repo!r} ref={ref!r} "
              f"token={'есть' if token else 'НЕТ'}", flush=True)
        return 1

    print(f"Тикер: {args.workflow} на ветке {ref}, репозиторий {args.repo}",
          flush=True)
    fails = [0]

    def step():
        try:
            dispatch(args.workflow, ref, args.repo, token)
        except urllib.error.HTTPError as e:
            fails[0] += 1
            body = e.read().decode("utf-8", "replace")[:200]
            print(f"Запуск обхода отклонён (HTTP {e.code}, подряд "
                  f"{fails[0]}): {body}", flush=True)
            raise
        fails[0] = 0
        print("Сегментированный обход запущен", flush=True)

    from scraper.crawl_loop import run_loop
    return run_loop(step, args.seconds, args.interval)


if __name__ == "__main__":
    raise SystemExit(main())
