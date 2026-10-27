-- Миграция 0.8: правило может показывать текст своего варианта (поглощённого факта) вместо общего.
alter table rule add column if not exists presents text;
