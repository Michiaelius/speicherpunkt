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
