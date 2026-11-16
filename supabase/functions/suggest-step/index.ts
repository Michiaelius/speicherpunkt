// Speicherpunkt: schlägt drei nächste Mini-Schritte vor (Supabase Edge Function).
// Braucht das Secret ANTHROPIC_API_KEY. Prüft die Anmeldung und das Tageskontingent über sp_take_quota().

const CORS = {
  "Access-Control-Allow-Origin": "*",
  "Access-Control-Allow-Headers": "authorization, apikey, content-type, x-client-info",
  "Access-Control-Allow-Methods": "POST, OPTIONS",
};
const MODEL = "claude-haiku-5-5";

function reply(status, obj) {
  return new Response(JSON.stringify(obj), { status, headers: { ...CORS, "Content-Type": "application/json" } });
}
function clip(v, n) { return String(v == null ? "" : v).replace(/\s+/g, " ").trim().slice(0, n); }

const SYSTEM = `Du hilfst Menschen mit ADHS, an einem eigenen Projekt dranzubleiben oder nach einer Pause wieder einzusteigen.
Du schlägst genau drei nächste Mini-Schritte vor.

Regeln für jeden Schritt:
- Höchstens 10 Wörter, Deutsch, Schweizer Rechtschreibung (ss statt ß).
- Form wie eine Notiz: Objekt zuerst, Verb am Schluss. Beispiele: "Klebeband um den Türrahmen kleben", "Lohnausweis 2025 in der Mappe suchen", "Ersten Satz der Einleitung schreiben".
- Sofort machbar, konkret und körperlich vorstellbar. Keine vagen Wörter wie "planen", "organisieren", "recherchieren" ohne klares Objekt.
- Baut auf dem auf, was über den Stand bekannt ist. Erledigte Schritte nie wiederholen.
- Erfinde keine Fakten. Wenn unklar ist, wie es weitergeht, schlage einen Schritt vor, der Klarheit schafft (z. B. "Drei Stichworte notieren, was noch fehlt").

Die drei Vorschläge unterscheiden sich:
1. Winzig: in 2 Minuten erledigt, fast lächerlich klein. Er senkt nur die Hürde zum Anfangen.
2. Der naheliegende nächste Schritt: 5 bis 15 Minuten.
3. Ein anderer Weg dorthin, zum Beispiel mit Hilfe einer Person, eines Timers oder einer anderen Reihenfolge.

Antworte nur mit JSON in genau dieser Form, ohne weiteren Text:
{"vorschlaege":[{"schritt":"...","minuten":2},{"schritt":"...","minuten":10},{"schritt":"...","minuten":5}]}`;

const MODES = {
  new: "Das Projekt ist neu. Schlage erste Schritte vor.",
  next: "Die Person setzt einen Speicherpunkt und überlegt, wie es weitergeht.",
  done: "Die Person hat den letzten Schritt gerade erledigt und sucht den nächsten.",
  reopen: "Das Projekt war abgeschlossen und wird wieder geöffnet.",
  smaller: "Der geplante Schritt fühlt sich zu gross an. Schlage drei kleinere Teile davon vor, mit denen man anfangen kann.",
};

function buildPrompt(input) {
  const lines = [];
  lines.push("Situation: " + (MODES[input.mode] || MODES.next));
  lines.push("Projekt: " + (clip(input.project, 80) || "(ohne Namen)"));
  const hist = Array.isArray(input.history) ? input.history.slice(-6) : [];
  if (hist.length) {
    lines.push("Bisherige Speicherpunkte, älteste zuerst:");
    for (const h of hist) {
      const where = clip(h && h.where, 300), next = clip(h && h.next, 160);
      lines.push("- " + (where ? "Stand: " + where + " | " : "") + "Schritt: " + next + (h && h.done ? " (erledigt)" : ""));
    }
  }
  const now = clip(input.where, 600);
  if (now) lines.push("Aktueller Stand laut Person: " + now);
  const step = clip(input.step, 200);
  if (step) lines.push((input.mode === "smaller" ? "Zu grosser Schritt: " : "Aktuell geplanter Schritt: ") + step);
  return lines.join("\n");
}

function parseSuggestions(text) {
  const m = String(text || "").match(/\{[\s\S]*\}/);
  if (!m) return [];
  let obj; try { obj = JSON.parse(m[0]); } catch { return []; }
  const arr = Array.isArray(obj.vorschlaege) ? obj.vorschlaege : Array.isArray(obj.suggestions) ? obj.suggestions : [];
  return arr.map(x => ({ step: clip(x && (x.schritt || x.step), 120), minutes: Math.max(1, Math.min(60, Number(x && (x.minuten || x.minutes)) || 0)) || null }))
    .filter(x => x.step).slice(0, 3);
}

async function handle(req) {
  if (req.method === "OPTIONS") return new Response("ok", { headers: CORS });
  if (req.method !== "POST") return reply(405, { error: "method" });

  const auth = req.headers.get("authorization") || "";
  const apikey = req.headers.get("apikey") || "";
  if (!auth.startsWith("Bearer ") || !apikey) return reply(401, { error: "signed_out" });

  const base = (Deno.env.get("SUPABASE_URL") || "").replace(/\/+$/, "");
  const q = await fetch(base + "/rest/v1/rpc/sp_take_quota", {
    method: "POST", headers: { apikey, Authorization: auth, "Content-Type": "application/json" }, body: "{}",
  });
  if (q.status === 401 || q.status === 403) return reply(401, { error: "signed_out" });
  if (!q.ok) return reply(500, { error: "quota_check", status: q.status });
  if ((await q.json()) !== true) return reply(429, { error: "limit" });

  let input;
  try { input = await req.json(); } catch { return reply(400, { error: "bad_json" }); }

  const key = Deno.env.get("ANTHROPIC_API_KEY");
  if (!key) return reply(500, { error: "no_ai_key" });

  const request = JSON.stringify({
    model: MODEL,
    max_tokens: 600,
    thinking: { type: "disabled" },
    output_config: { effort: "low" },
    system: SYSTEM,
    messages: [{ role: "user", content: buildPrompt(input || {}) }],
  });
  // Höchstens zwei Versuche mit je 20 Sekunden Zeit; ein zweiter nur bei Überlastung oder Serverfehler.
  let r = null;
  for (let attempt = 0; attempt < 2; attempt++) {
    try {
      r = await fetch("https://api.anthropic.com/v1/messages", {
        method: "POST",
        headers: { "x-api-key": key, "anthropic-version": "2023-06-01", "content-type": "application/json" },
        body: request,
        signal: AbortSignal.timeout(20000),
      });
    } catch { r = null; }
    if (r && (r.ok || ![429, 500, 502, 503, 529].includes(r.status))) break;
    if (attempt === 0) await new Promise(res => setTimeout(res, 800));
  }
  if (!r) return reply(504, { error: "ai_timeout" });
  if (!r.ok) return reply(502, { error: "ai", status: r.status });
  const d = await r.json();
  const text = (d.content || []).filter(b => b.type === "text").map(b => b.text).join("");
  const suggestions = parseSuggestions(text);
  if (!suggestions.length) return reply(502, { error: "ai_format" });
  return reply(200, { suggestions });
}

Deno.serve(handle);
