-- Speicherpunkt: einmal im Supabase SQL Editor ausführen.
-- Eine Zeile pro Person. Jede Person sieht und ändert nur ihre eigene Zeile.

create table if not exists public.sp_state (
  user_id    uuid primary key default auth.uid() references auth.users (id) on delete cascade,
  data       jsonb  not null,
  updated_at bigint not null default 0
);

alter table public.sp_state enable row level security;

drop policy if exists "sp_state lesen"   on public.sp_state;
drop policy if exists "sp_state anlegen" on public.sp_state;
drop policy if exists "sp_state ändern"  on public.sp_state;
drop policy if exists "sp_state löschen" on public.sp_state;

create policy "sp_state lesen"   on public.sp_state for select to authenticated using (auth.uid() = user_id);
create policy "sp_state anlegen" on public.sp_state for insert to authenticated with check (auth.uid() = user_id);
create policy "sp_state ändern"  on public.sp_state for update to authenticated using (auth.uid() = user_id) with check (auth.uid() = user_id);
create policy "sp_state löschen" on public.sp_state for delete to authenticated using (auth.uid() = user_id);

grant select, insert, update, delete on public.sp_state to authenticated;
revoke all on public.sp_state from anon;

-- Vorschläge für Mini-Schritte: Tageskontingent pro Person (schützt vor Kosten durch Missbrauch).
create table if not exists public.sp_usage (
  user_id uuid not null references auth.users (id) on delete cascade,
  day     date not null,
  n       int  not null default 0,
  primary key (user_id, day)
);
alter table public.sp_usage enable row level security;   -- keine Policies: nur die Funktion unten schreibt hier

create or replace function public.sp_take_quota()
returns boolean
language plpgsql
security definer
set search_path = public
as $$
declare c int;
begin
  if auth.uid() is null then return false; end if;
  insert into public.sp_usage (user_id, day, n) values (auth.uid(), current_date, 1)
  on conflict (user_id, day) do update set n = public.sp_usage.n + 1
  returning n into c;
  return c <= 40;   -- höchstens 40 Vorschläge pro Person und Tag
end $$;

revoke all on function public.sp_take_quota() from public, anon;
grant execute on function public.sp_take_quota() to authenticated;

-- Konto löschen: Jede Person kann ihr eigenes Konto löschen. Projekte (sp_state) und Kontingent (sp_usage)
-- werden dabei automatisch mitgelöscht (on delete cascade).
create or replace function public.sp_delete_account()
returns void
language plpgsql
security definer
set search_path = public
as $$
begin
  if auth.uid() is null then raise exception 'nicht angemeldet'; end if;
  delete from auth.users where id = auth.uid();
end $$;

revoke all on function public.sp_delete_account() from public, anon;
grant execute on function public.sp_delete_account() to authenticated;

-- Warteliste der Landingpage. Jeder darf sich eintragen, aber niemand kann die Liste über die App lesen.
-- Anschauen: im Supabase Table Editor (Tabelle sp_waitlist).
create table if not exists public.sp_waitlist (
  id         uuid primary key default gen_random_uuid(),
  email      text not null check (char_length(email) between 6 and 254 and email ~* '^[^@\s]+@[^@\s]+\.[^@\s]+$'),
  note       text check (note is null or char_length(note) <= 1000),
  source     text check (source is null or char_length(source) <= 50),
  created_at timestamptz not null default now()
);
create unique index if not exists sp_waitlist_email_idx on public.sp_waitlist (lower(email));
alter table public.sp_waitlist enable row level security;

drop policy if exists "sp_waitlist eintragen" on public.sp_waitlist;
create policy "sp_waitlist eintragen" on public.sp_waitlist for insert to anon, authenticated with check (true);

revoke all on public.sp_waitlist from anon, authenticated;
grant insert on public.sp_waitlist to anon, authenticated;

-- ---------------------------------------------------------------------------------------------
-- Schutz vor gleichzeitigem Schreiben (ab Version 8)
-- ---------------------------------------------------------------------------------------------
-- Revisionszähler: Jede Änderung an sp_state erhöht rev um 1. Die App schreibt nur, wenn rev seit dem
-- Lesen gleich geblieben ist. So überschreibt ein Gerät nie die Änderung eines anderen.
alter table public.sp_state add column if not exists rev bigint not null default 0;

create or replace function public.sp_state_bump()
returns trigger
language plpgsql
set search_path = public
as $$
begin
  new.rev := old.rev + 1;
  return new;
end $$;

drop trigger if exists sp_state_bump on public.sp_state;
create trigger sp_state_bump before update on public.sp_state
  for each row execute function public.sp_state_bump();

-- Die Schnittstelle für andere Programme aus Version 8 gibt es nicht mehr. Ihre Teile werden hier entfernt
-- (nichts passiert, wenn sie nie angelegt wurden). Projekte bleiben unberührt.
drop function if exists public.sp_api_open(text, boolean);
drop function if exists public.sp_api_write(text, bigint, jsonb);
drop function if exists public.sp_api_token_new();
drop function if exists public.sp_api_token_info();
drop function if exists public.sp_api_token_revoke();
drop table if exists public.sp_api_tokens;

-- ---------------------------------------------------------------------------------------------
-- Erinnerungen per Mitteilung (Push), ab Version 10
-- ---------------------------------------------------------------------------------------------
-- Ablauf: Alle 5 Minuten ruft die Datenbank die Edge Function «push» auf und gibt ihr einen Einmal-Code mit.
-- Nur mit diesem Code bekommt die Funktion die fälligen Erinnerungen. Es braucht keine Secrets.

-- Geräte, die Mitteilungen bekommen sollen. Zugriff nur über die Funktionen unten.
create table if not exists public.sp_push_subs (
  id         uuid primary key default gen_random_uuid(),
  user_id    uuid not null references auth.users (id) on delete cascade,
  endpoint   text not null unique check (endpoint ~ '^https://' and char_length(endpoint) <= 1000),
  p256dh     text not null check (char_length(p256dh) between 80 and 100),
  auth       text not null check (char_length(auth) between 16 and 40),
  created_at timestamptz not null default now()
);
create index if not exists sp_push_subs_user_idx on public.sp_push_subs (user_id);
alter table public.sp_push_subs add column if not exists test_at timestamptz;   -- gesetzt, wenn eine Probe-Mitteilung gewünscht ist
-- Was schon verschickt wurde, damit jede Erinnerung pro Gerät nur einmal kommt.
create table if not exists public.sp_push_sent (
  sub_id     uuid not null references public.sp_push_subs (id) on delete cascade,
  project_id text not null,
  remind_at  bigint not null,
  sent_at    timestamptz not null default now(),
  primary key (sub_id, project_id, remind_at)
);
-- Schlüsselpaar, mit dem sich die App bei den Mitteilungsdiensten ausweist (wird beim ersten Lauf erzeugt).
create table if not exists public.sp_push_keys (
  id   boolean primary key default true check (id),
  pub  text not null,
  priv text not null
);
create table if not exists public.sp_push_nonce (
  nonce      uuid primary key default gen_random_uuid(),
  created_at timestamptz not null default now()
);
alter table public.sp_push_subs  enable row level security;
alter table public.sp_push_sent  enable row level security;
alter table public.sp_push_keys  enable row level security;
alter table public.sp_push_nonce enable row level security;
revoke all on public.sp_push_subs, public.sp_push_sent, public.sp_push_keys, public.sp_push_nonce from anon, authenticated;

-- App: öffentlichen Schlüssel holen (null, solange der Zeitplan noch nie gelaufen ist).
create or replace function public.sp_push_public_key()
returns text language sql security definer set search_path = public stable
as $$ select pub from public.sp_push_keys limit 1 $$;

-- App: dieses Gerät anmelden. Gehörte es vorher zu einem anderen Konto, wechselt es zum aktuellen.
create or replace function public.sp_push_subscribe(p_endpoint text, p_p256dh text, p_auth text)
returns void language plpgsql security definer set search_path = public
as $$
begin
  if auth.uid() is null then raise exception 'nicht angemeldet'; end if;
  delete from public.sp_push_subs where endpoint = p_endpoint and user_id <> auth.uid();
  insert into public.sp_push_subs (user_id, endpoint, p256dh, auth) values (auth.uid(), p_endpoint, p_p256dh, p_auth)
  on conflict (endpoint) do update set p256dh = excluded.p256dh, auth = excluded.auth;
  -- höchstens 10 Geräte pro Konto, die ältesten fallen weg
  delete from public.sp_push_subs where user_id = auth.uid() and id not in
    (select id from public.sp_push_subs where user_id = auth.uid() order by created_at desc limit 10);
end $$;

-- App: Probe-Mitteilung an dieses Gerät. Löst den Versand sofort aus (höchstens alle 30 Sekunden).
create or replace function public.sp_push_test(p_endpoint text)
returns boolean language plpgsql security definer set search_path = public
as $$
begin
  if auth.uid() is null then raise exception 'nicht angemeldet'; end if;
  update public.sp_push_subs set test_at = now()
    where endpoint = p_endpoint and user_id = auth.uid() and (test_at is null or test_at < now() - interval '30 seconds');
  if not found then return false; end if;
  begin perform public.sp_push_tick(); exception when others then null; end;   -- sonst kommt sie mit dem nächsten Lauf
  return true;
end $$;

-- App: dieses Gerät abmelden.
create or replace function public.sp_push_unsubscribe(p_endpoint text)
returns void language plpgsql security definer set search_path = public
as $$
begin
  if auth.uid() is null then raise exception 'nicht angemeldet'; end if;
  delete from public.sp_push_subs where endpoint = p_endpoint and user_id = auth.uid();
end $$;

create or replace function public.sp_push_nonce_ok(p_nonce uuid)
returns boolean language sql security definer set search_path = public stable
as $$ select exists (select 1 from public.sp_push_nonce where nonce = p_nonce and created_at > now() - interval '5 minutes') $$;

-- Edge Function: fällige Erinnerungen abholen (nur mit gültigem Einmal-Code) und als verschickt vermerken.
-- Fällig heisst: Erinnerung liegt in den letzten 24 Stunden, Projekt ruht nicht und ist nicht abgeschlossen.
create or replace function public.sp_push_claim(p_nonce uuid)
returns jsonb language plpgsql security definer set search_path = public
as $$
declare
  k public.sp_push_keys%rowtype;
  ms bigint := (extract(epoch from clock_timestamp()) * 1000)::bigint;
  res jsonb;
begin
  if not public.sp_push_nonce_ok(p_nonce) then return jsonb_build_object('status', 401); end if;
  select * into k from public.sp_push_keys limit 1;
  if not found then return jsonb_build_object('status', 200, 'keys', null, 'due', '[]'::jsonb); end if;
  with due as (
    select s.id as sub_id, s.endpoint, s.p256dh, s.auth, p ->> 'id' as pid, left(p ->> 'name', 80) as name,
           (p ->> 'remindAt')::numeric::bigint as rat, left(p -> 'saves' -> -1 ->> 'next', 200) as next
    from public.sp_push_subs s
    join public.sp_state st on st.user_id = s.user_id
    cross join lateral jsonb_array_elements(
      case when jsonb_typeof(st.data -> 'projects') = 'array' then st.data -> 'projects' else '[]'::jsonb end) p
    where jsonb_typeof(p) = 'object' and jsonb_typeof(p -> 'id') = 'string' and jsonb_typeof(p -> 'remindAt') = 'number'
      and (p ->> 'remindAt')::numeric between ms - 86400000 and ms
      and p -> 'paused' is distinct from 'true'::jsonb
      and (p -> 'finished' is null or jsonb_typeof(p -> 'finished') = 'null')
    limit 500
  ), ins as (
    insert into public.sp_push_sent (sub_id, project_id, remind_at)
    select sub_id, pid, rat from due on conflict do nothing
    returning sub_id, project_id, remind_at
  )
  select coalesce(jsonb_agg(jsonb_build_object('sub', d.sub_id, 'endpoint', d.endpoint, 'p256dh', d.p256dh, 'auth', d.auth,
           'project', d.pid, 'remind', d.rat, 'name', d.name, 'next', d.next)), '[]'::jsonb) into res
  from due d join ins i on i.sub_id = d.sub_id and i.project_id = d.pid and i.remind_at = d.rat;
  -- Probe-Mitteilungen (aus den Einstellungen der App angefordert)
  with t as (update public.sp_push_subs set test_at = null where test_at is not null returning id, endpoint, p256dh, auth)
  select res || coalesce(jsonb_agg(jsonb_build_object('sub', t.id, 'endpoint', t.endpoint, 'p256dh', t.p256dh, 'auth', t.auth,
           'project', '', 'remind', 0, 'name', 'Speicherpunkt', 'text', 'Das ist eine Probe. So meldet sich die App, wenn eine Erinnerung fällig ist.')), '[]'::jsonb) into res
  from t;
  return jsonb_build_object('status', 200, 'keys', jsonb_build_object('pub', k.pub, 'priv', k.priv), 'due', res);
end $$;

-- Edge Function: beim allerersten Lauf das Schlüsselpaar ablegen. Gibt das gültige Paar zurück.
create or replace function public.sp_push_setkeys(p_nonce uuid, p_pub text, p_priv text)
returns jsonb language plpgsql security definer set search_path = public
as $$
declare k public.sp_push_keys%rowtype;
begin
  if not public.sp_push_nonce_ok(p_nonce) then return jsonb_build_object('status', 401); end if;
  if p_pub is null or char_length(p_pub) not between 80 and 100 or p_priv is null or char_length(p_priv) > 600 then
    return jsonb_build_object('status', 422);
  end if;
  insert into public.sp_push_keys (pub, priv) values (p_pub, p_priv) on conflict (id) do nothing;
  select * into k from public.sp_push_keys limit 1;
  return jsonb_build_object('status', 200, 'keys', jsonb_build_object('pub', k.pub, 'priv', k.priv));
end $$;

-- Edge Function: Ergebnis melden. Abgemeldete Geräte werden entfernt, Fehlgeschlagenes beim nächsten Lauf wiederholt.
create or replace function public.sp_push_report(p_nonce uuid, p_gone uuid[], p_failed jsonb)
returns jsonb language plpgsql security definer set search_path = public
as $$
begin
  if not public.sp_push_nonce_ok(p_nonce) then return jsonb_build_object('status', 401); end if;
  if p_gone is not null then delete from public.sp_push_subs where id = any (p_gone); end if;
  if jsonb_typeof(p_failed) = 'array' then
    delete from public.sp_push_sent t using jsonb_array_elements(p_failed) f
    where t.sub_id = (f ->> 'sub')::uuid and t.project_id = f ->> 'project' and t.remind_at = (f ->> 'remind')::bigint;
  end if;
  return jsonb_build_object('status', 200);
end $$;

-- Zeitplan: räumt auf, erzeugt einen Einmal-Code und ruft die Edge Function «push» auf.
create or replace function public.sp_push_tick()
returns void language plpgsql security definer set search_path = public
as $$
declare n uuid;
begin
  delete from public.sp_push_nonce where created_at < now() - interval '1 hour';
  delete from public.sp_push_sent where sent_at < now() - interval '3 days';
  if exists (select 1 from public.sp_push_keys) and not exists (select 1 from public.sp_push_subs) then return; end if;
  insert into public.sp_push_nonce default values returning nonce into n;
  perform net.http_post(
    url := 'https://satqwruqmwgcflcggbul.supabase.co/functions/v1/push',
    body := jsonb_build_object('nonce', n),
    headers := '{"Content-Type": "application/json"}'::jsonb);
end $$;

revoke all on function public.sp_push_public_key()                 from public, anon;
revoke all on function public.sp_push_subscribe(text, text, text)  from public, anon;
revoke all on function public.sp_push_unsubscribe(text)            from public, anon;
revoke all on function public.sp_push_test(text)                   from public, anon;
grant execute on function public.sp_push_test(text)                  to authenticated;
revoke all on function public.sp_push_nonce_ok(uuid)               from public, anon, authenticated;
revoke all on function public.sp_push_tick()                       from public, anon, authenticated;
revoke all on function public.sp_push_claim(uuid)                  from public;
revoke all on function public.sp_push_setkeys(uuid, text, text)    from public;
revoke all on function public.sp_push_report(uuid, uuid[], jsonb)  from public;
grant execute on function public.sp_push_public_key()                to authenticated;
grant execute on function public.sp_push_subscribe(text, text, text) to authenticated;
grant execute on function public.sp_push_unsubscribe(text)           to authenticated;
-- Diese drei ruft die Edge Function ohne Anmeldung auf; sie prüfen den Einmal-Code selbst.
grant execute on function public.sp_push_claim(uuid)                 to anon, authenticated;
grant execute on function public.sp_push_setkeys(uuid, text, text)   to anon, authenticated;
grant execute on function public.sp_push_report(uuid, uuid[], jsonb) to anon, authenticated;

-- ---------------------------------------------------------------------------------------------
-- Anonyme Zählung: Kommen Leute wieder? (ab Version 10)
-- ---------------------------------------------------------------------------------------------
-- Pro Gerät eine zufällige Nummer und die Tage, an denen die App geöffnet wurde. Keine Verbindung zu Konto oder E-Mail.
create table if not exists public.sp_visits (
  device uuid not null,
  day    date not null default current_date,
  primary key (device, day)
);
alter table public.sp_visits enable row level security;
revoke all on public.sp_visits from anon, authenticated;

create or replace function public.sp_seen(p_device uuid)
returns void language sql security definer set search_path = public
as $$ insert into public.sp_visits (device) values (p_device) on conflict do nothing $$;
revoke all on function public.sp_seen(uuid) from public;
grant execute on function public.sp_seen(uuid) to anon, authenticated;

-- Anschauen: Supabase → Table Editor → sp_wiederkehr. Eine Zeile pro Woche, in der Geräte zum ersten Mal kamen.
create or replace view public.sp_wiederkehr as
with f as (select device, min(day) as first from public.sp_visits group by device)
select date_trunc('week', f.first)::date as startwoche,
       count(*) as geraete,
       count(*) filter (where exists (select 1 from public.sp_visits v where v.device = f.device and v.day between f.first + 1 and f.first + 7))  as zurueck_in_woche_1,
       count(*) filter (where exists (select 1 from public.sp_visits v where v.device = f.device and v.day between f.first + 8 and f.first + 14)) as zurueck_in_woche_2,
       count(*) filter (where exists (select 1 from public.sp_visits v where v.device = f.device and v.day > f.first + 14))                        as zurueck_spaeter
from f group by 1 order by 1 desc;
revoke all on public.sp_wiederkehr from anon, authenticated;

-- ---------------------------------------------------------------------------------------------
-- Zeitplan für die Erinnerungen einschalten (ganz am Schluss, damit ein Fehler hier nichts anderes stört)
-- ---------------------------------------------------------------------------------------------
create or replace function public.sp_push_zeitplan()
returns text language plpgsql set search_path = public
as $$
begin
  begin execute 'create extension if not exists pg_net with schema extensions'; exception when others then
    begin execute 'create extension if not exists pg_net'; exception when others then
      return 'Zeitplan NICHT aktiv: pg_net fehlt (' || sqlerrm || '). Unter Database → Extensions «pg_net» einschalten und nochmals ausführen.';
    end;
  end;
  begin execute 'create extension if not exists pg_cron with schema pg_catalog'; exception when others then
    return 'Zeitplan NICHT aktiv: pg_cron fehlt (' || sqlerrm || '). Unter Database → Extensions «pg_cron» einschalten und nochmals ausführen.';
  end;
  begin execute $q$select cron.schedule('speicherpunkt-push', '*/5 * * * *', 'select public.sp_push_tick()')$q$;
  exception when others then return 'Zeitplan NICHT aktiv: ' || sqlerrm;
  end;
  return 'Zeitplan aktiv: Erinnerungen werden alle 5 Minuten geprüft.';
end $$;
revoke all on function public.sp_push_zeitplan() from public, anon, authenticated;

select public.sp_push_zeitplan() as erinnerungen;
