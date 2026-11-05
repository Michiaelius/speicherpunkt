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
