-- Миграция: переименование полей photo_id_* в media_*
-- Выполнить в схеме VSEPExchanger

-- Переименование photo_id_mbt в media_mbt
UPDATE "VSEPExchanger"."system_settings" 
SET key = 'media_mbt' 
WHERE key = 'photo_id_mbt';

-- Переименование photo_id_start в media_start
UPDATE "VSEPExchanger"."system_settings" 
SET key = 'media_start' 
WHERE key = 'photo_id_start';

-- Переименование photo_id_end в media_finish
UPDATE "VSEPExchanger"."system_settings" 
SET key = 'media_finish' 
WHERE key = 'photo_id_end';

-- Проверка результатов
SELECT key, value FROM "VSEPExchanger"."system_settings" 
WHERE key IN ('media_mbt', 'media_start', 'media_finish')
ORDER BY key; 