/**
 * Telegram-бот расписания МПГУ (Cloudflare Worker).
 *
 * Пользователь присылает код группы (или его часть) — бот ищет в
 * meta/groups.json, тянет расписание группы и отвечает парами на сегодня.
 *
 * Развёртывание:
 *   cd cloudflare-worker-bot && wrangler deploy
 *   wrangler secret put BOT_TOKEN          # токен от @BotFather
 *   wrangler secret put WEBHOOK_SECRET      # произвольная строка
 * Регистрация вебхука (один раз):
 *   curl "https://api.telegram.org/bot<BOT_TOKEN>/setWebhook?url=https://<worker>.workers.dev&secret_token=<WEBHOOK_SECRET>"
 *
 * Данные берутся через прокси-воркер (DATA_BASE), который уже кэширует data-ветку.
 */

const DATA_BASE = "https://mpgu-schedule.workers.dev"; // прокси данных; переопредели при необходимости

const DAYS = ["sunday", "monday", "tuesday", "wednesday", "thursday", "friday", "saturday"];
const DAY_RU = {
  monday: "Понедельник", tuesday: "Вторник", wednesday: "Среда",
  thursday: "Четверг", friday: "Пятница", saturday: "Суббота", sunday: "Воскресенье",
};
const TYPE_RU = { lecture: "ЛК", practice: "ПЗ", lab: "ЛР", seminar: "СЕМ", other: "" };

const HOMO = { A: "А", B: "В", C: "С", E: "Е", H: "Н", K: "К", M: "М", O: "О", P: "Р", T: "Т", X: "Х", Y: "У" };
function searchKey(s) {
  return s.trim().toUpperCase().replace(/[A-Z]/g, (c) => HOMO[c] || c).replace(/[\s\-_]/g, "");
}

export default {
  async fetch(request, env) {
    if (request.method !== "POST") return new Response("ok"); // health check
    if (env.WEBHOOK_SECRET &&
        request.headers.get("X-Telegram-Bot-Api-Secret-Token") !== env.WEBHOOK_SECRET) {
      return new Response("forbidden", { status: 403 });
    }
    let update;
    try { update = await request.json(); } catch { return new Response("ok"); }

    const msg = update.message || update.edited_message;
    const text = (msg && msg.text || "").trim();
    const chatId = msg && msg.chat && msg.chat.id;
    if (!chatId || !text) return new Response("ok");

    try {
      const reply = await handle(text);
      await send(env, chatId, reply);
    } catch (e) {
      await send(env, chatId, "Что-то пошло не так. Попробуйте позже.");
    }
    return new Response("ok");
  },
};

async function handle(text) {
  if (text.startsWith("/start") || text.startsWith("/help")) {
    return "👋 Бот расписания МПГУ.\n\nПришлите код группы — например <b>ВОП40-ПФК2501</b> " +
      "(можно часть кода) — и я покажу пары на сегодня.";
  }
  const q = searchKey(text.replace(/^\/\S+\s*/, ""));
  if (q.length < 3) return "Пришлите код группы (минимум 3 символа), например ВОП40-ПФК2501.";

  const index = await getJson(`${DATA_BASE}/meta/groups.json`);
  const all = (index.groups || []);
  const exact = all.filter((g) => g.key === q);
  const matches = exact.length ? exact : all.filter((g) => g.key.includes(q));

  if (matches.length === 0) return `Группа «${escapeHtml(text)}» не найдена. Проверьте код.`;
  if (matches.length > 1 && exact.length !== 1) {
    const list = matches.slice(0, 12).map((g) => `• <b>${escapeHtml(g.code)}</b> — ${escapeHtml(g.institute_short)}`).join("\n");
    const more = matches.length > 12 ? `\n…и ещё ${matches.length - 12}` : "";
    return `Нашёл несколько групп — уточните код:\n${list}${more}`;
  }

  const g = matches[0];
  const group = await getJson(`${DATA_BASE}/institutes/${g.institute}/groups/${encodeURIComponent(g.file)}.json`);
  return formatToday(group, g);
}

async function getJson(url) {
  const r = await fetch(url, { headers: { "User-Agent": "MPGU-Schedule-Bot" } });
  if (!r.ok) throw new Error(`HTTP ${r.status}`);
  return r.json();
}

function isEvenWeek(date) {
  // ISO-номер недели; чётная = знаменатель (even_week)
  const d = new Date(Date.UTC(date.getUTCFullYear(), date.getUTCMonth(), date.getUTCDate()));
  const dayNum = (d.getUTCDay() + 6) % 7;
  d.setUTCDate(d.getUTCDate() - dayNum + 3);
  const firstThursday = new Date(Date.UTC(d.getUTCFullYear(), 0, 4));
  const week = 1 + Math.round((d - firstThursday) / 604800000);
  return week % 2 === 0;
}

function formatToday(group, meta) {
  // Москва = UTC+3
  const now = new Date(Date.now() + 3 * 3600 * 1000);
  const day = DAYS[now.getUTCDay()];
  const wk = isEvenWeek(now) ? "even_week" : "odd_week";
  const lessons = ((group.schedule || {})[wk] || {})[day] || [];
  const header = `📅 <b>${escapeHtml(group.name || meta.code)}</b> · ${DAY_RU[day]} · ${isEvenWeek(now) ? "чётная" : "нечётная"} неделя`;
  if (!lessons.length) return `${header}\n\nЗанятий нет 🎉`;
  const body = lessons
    .sort((a, b) => (a.time_start || "").localeCompare(b.time_start || ""))
    .map((l) => {
      const t = TYPE_RU[l.type] ? ` (${TYPE_RU[l.type]})` : "";
      const time = `${l.time_start || ""}${l.time_end ? "–" + l.time_end : ""}`;
      const extra = [l.teacher, l.room].filter(Boolean).map(escapeHtml).join(", ");
      return `🕐 <b>${time}</b> ${escapeHtml(l.subject || "")}${t}${extra ? "\n   " + extra : ""}`;
    })
    .join("\n\n");
  return `${header}\n\n${body}`;
}

function escapeHtml(s) {
  return String(s == null ? "" : s).replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;");
}

async function send(env, chatId, text) {
  await fetch(`https://api.telegram.org/bot${env.BOT_TOKEN}/sendMessage`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ chat_id: chatId, text, parse_mode: "HTML", disable_web_page_preview: true }),
  });
}
