-- Allow longer area names: a section's name lists the familiar places inside it,
-- such as PJU 6 (Bandar Utama, Damansara Residensi).
BEGIN;

ALTER TABLE public.area ALTER COLUMN name TYPE varchar(250);

COMMIT;
