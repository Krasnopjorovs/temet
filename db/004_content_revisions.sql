-- Миграция 0.16: правка одобренного текста хранится рядом с ним (draft_payload) и не скрывает его со страницы,
-- пока правку не одобрят; одобрение переносит правку в payload.
alter table content add column if not exists draft_payload jsonb;
