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
-- Schnittstelle (API) für andere Programme, zum Beispiel ZbiWeb. Ab Version 8.
-- ---------------------------------------------------------------------------------------------

-- Revisionszähler: Jede Änderung an sp_state erhöht rev um 1. App und Schnittstelle schreiben nur,
-- wenn rev seit dem Lesen gleich geblieben ist. So überschreibt niemand die Änderung eines anderen.
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

-- Ein API-Token pro Person. Gespeichert wird nur eine Prüfsumme (SHA-256), nie der Token selbst.
create table if not exists public.sp_api_tokens (
  user_id      uuid primary key references auth.users (id) on delete cascade,
  token_hash   text not null unique,
  created_at   timestamptz not null default now(),
  last_used_at timestamptz,
  window_start timestamptz not null default now(),   -- Beginn der laufenden Minute (Ratenbegrenzung)
  window_hits  int not null default 0
);
alter table public.sp_api_tokens enable row level security;   -- keine Policies: nur die Funktionen unten
revoke all on public.sp_api_tokens from anon, authenticated;

-- In der App: neuen Token erzeugen. Ein bestehender Token wird dabei ungültig.
create or replace function public.sp_api_token_new()
returns text
language plpgsql
security definer
set search_path = public
as $$
declare t text;
begin
  if auth.uid() is null then raise exception 'nicht angemeldet'; end if;
  t := 'sp_' || replace(gen_random_uuid()::text, '-', '') || replace(gen_random_uuid()::text, '-', '');
  insert into public.sp_api_tokens (user_id, token_hash, created_at, last_used_at, window_start, window_hits)
  values (auth.uid(), encode(sha256(convert_to(t, 'UTF8')), 'hex'), now(), null, now(), 0)
  on conflict (user_id) do update
    set token_hash = excluded.token_hash, created_at = excluded.created_at,
        last_used_at = null, window_start = excluded.window_start, window_hits = 0;
  return t;
end $$;

-- In der App: Ist ein Token aktiv, seit wann, wann zuletzt benutzt?
create or replace function public.sp_api_token_info()
returns json
language plpgsql
security definer
set search_path = public
as $$
declare r json;
begin
  if auth.uid() is null then raise exception 'nicht angemeldet'; end if;
  -- Zeitpunkte als Millisekunden seit 1970, so liest jeder Browser sie gleich.
  select json_build_object('aktiv', true, 'erstellt', (extract(epoch from created_at) * 1000)::bigint,
                           'zuletzt', (extract(epoch from last_used_at) * 1000)::bigint) into r
    from public.sp_api_tokens where user_id = auth.uid();
  return coalesce(r, json_build_object('aktiv', false));
end $$;

-- In der App: Token löschen. Danach antwortet die Schnittstelle mit 401.
create or replace function public.sp_api_token_revoke()
returns void
language plpgsql
security definer
set search_path = public
as $$
begin
  if auth.uid() is null then raise exception 'nicht angemeldet'; end if;
  delete from public.sp_api_tokens where user_id = auth.uid();
end $$;

-- Für die Edge Function «api»: Token prüfen, Aufruf zählen (höchstens 60 pro Minute), Daten liefern.
create or replace function public.sp_api_open(p_token text, p_count boolean default true)
returns jsonb
language plpgsql
security definer
set search_path = public
as $$
declare
  tk public.sp_api_tokens%rowtype;
  st public.sp_state%rowtype;
begin
  if p_token is null or p_token !~ '^sp_[0-9a-f]{64}$' then return jsonb_build_object('status', 401); end if;
  select * into tk from public.sp_api_tokens
    where token_hash = encode(sha256(convert_to(p_token, 'UTF8')), 'hex') for update;
  if not found then return jsonb_build_object('status', 401); end if;
  if p_count then
    if tk.window_start <= now() - interval '1 minute' then
      update public.sp_api_tokens set window_start = now(), window_hits = 1, last_used_at = now() where user_id = tk.user_id;
    elsif tk.window_hits >= 60 then
      return jsonb_build_object('status', 429,
        'retry', greatest(1, ceil(extract(epoch from (tk.window_start + interval '1 minute' - now()))))::int);
    else
      update public.sp_api_tokens set window_hits = window_hits + 1, last_used_at = now() where user_id = tk.user_id;
    end if;
  end if;
  select * into st from public.sp_state where user_id = tk.user_id;
  if not found then return jsonb_build_object('status', 200, 'data', null, 'rev', null); end if;
  return jsonb_build_object('status', 200, 'data', st.data, 'rev', st.rev);
end $$;

-- Für die Edge Function «api»: Daten schreiben, aber nur wenn rev noch stimmt (sonst 409, die Funktion liest neu).
create or replace function public.sp_api_write(p_token text, p_rev bigint, p_data jsonb)
returns jsonb
language plpgsql
security definer
set search_path = public
as $$
declare
  u uuid;
  r bigint;
  ms bigint := (extract(epoch from clock_timestamp()) * 1000)::bigint;
begin
  if p_token is null or p_token !~ '^sp_[0-9a-f]{64}$' then return jsonb_build_object('status', 401); end if;
  select user_id into u from public.sp_api_tokens where token_hash = encode(sha256(convert_to(p_token, 'UTF8')), 'hex');
  if not found then return jsonb_build_object('status', 401); end if;
  if p_data is null or jsonb_typeof(p_data) <> 'object' or jsonb_typeof(p_data -> 'projects') is distinct from 'array'
     or octet_length(p_data::text) > 5000000 then
    return jsonb_build_object('status', 422);
  end if;
  if p_rev is null then
    insert into public.sp_state (user_id, data, updated_at) values (u, p_data, ms)
      on conflict (user_id) do nothing
      returning rev into r;
  else
    update public.sp_state set data = p_data, updated_at = ms
      where user_id = u and rev = p_rev
      returning rev into r;
  end if;
  if r is null then return jsonb_build_object('status', 409); end if;
  return jsonb_build_object('status', 200, 'rev', r);
end $$;

revoke all on function public.sp_api_token_new()    from public, anon;
revoke all on function public.sp_api_token_info()   from public, anon;
revoke all on function public.sp_api_token_revoke() from public, anon;
grant execute on function public.sp_api_token_new()    to authenticated;
grant execute on function public.sp_api_token_info()   to authenticated;
grant execute on function public.sp_api_token_revoke() to authenticated;
-- Die beiden folgenden ruft die Edge Function ohne Anmeldung auf; sie prüfen den Token selbst.
revoke all on function public.sp_api_open(text, boolean)       from public;
revoke all on function public.sp_api_write(text, bigint, jsonb) from public;
grant execute on function public.sp_api_open(text, boolean)       to anon, authenticated;
grant execute on function public.sp_api_write(text, bigint, jsonb) to anon, authenticated;
