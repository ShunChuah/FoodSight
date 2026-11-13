-- Area: osm_id, the OpenStreetMap relation of each section (SS 2, PJU 6, ...).
--
-- A section's name lists the named places inside it, for example
-- "PJU 6 (Bandar Utama, Damansara Residensi)", so the name changes whenever
-- OpenStreetMap adds, renames or removes a named place there. The loader found
-- a section by its name, so a renamed section would have been added as a
-- second row. With the OSM ID the loader can rename the existing row instead:
-- its restaurants keep pointing to it, and its graph node keeps its key.
--
-- Every section is an OSM relation (the admin_level=10 members of the Petaling
-- Jaya relation, see SECTIONS_QUERY in extract_osm.py), and OpenStreetMap never
-- gives two relations the same ID, so osm_id alone is unique.
--
-- The 65 sections already in the table get their IDs below, matched by name to
-- the data loaded on 4 November 2026 (data/6_clustered/pj_clustered.json). If
-- any section is left without one, the migration stops and changes nothing.
--
-- Run from the repo root (it asks for the postgres password):
--   psql -h localhost -U postgres -d food_sight_db -v ON_ERROR_STOP=1 -f db/migrations/021_area_osm_id.sql
-- Then regenerate the table reference:
--   python db/dump_schema.py
BEGIN;

ALTER TABLE public.area ADD COLUMN osm_id bigint;

UPDATE public.area SET osm_id = 17005186 WHERE name = 'PJS 1 (Taman Petaling Utama)';
UPDATE public.area SET osm_id = 16886642 WHERE name = 'PJS 10 (Bandar Sunway, Taman Dato'' Hormat, Taman Sri Subang, Taman Subang Indah)';
UPDATE public.area SET osm_id = 16999240 WHERE name = 'PJS 2 (Taman Dato Harun)';
UPDATE public.area SET osm_id = 16901854 WHERE name = 'PJS 3 (Taman Medan, Taman Sri Manja)';
UPDATE public.area SET osm_id = 16896981 WHERE name = 'PJS 4';
UPDATE public.area SET osm_id = 12011799 WHERE name = 'PJS 5 (Petaling Jaya Selatan, Taman Desa Ria)';
UPDATE public.area SET osm_id = 16892888 WHERE name = 'PJS 6 (Bandar Sunway, Desa Mentari, Kampung Lindungan)';
UPDATE public.area SET osm_id = 16886641 WHERE name = 'PJS 8 (Bandar Sunway, Taman Sri Subang)';
UPDATE public.area SET osm_id = 17136990 WHERE name = 'PJU 1 (Taman Bukit Mayang Mas)';
UPDATE public.area SET osm_id = 17139543 WHERE name = 'PJU 10';
UPDATE public.area SET osm_id = 17137931 WHERE name = 'PJU 1A (Ara Damansara, Ara Putra, Seri Pilmoor Selatan, Seri Pilmoor Timur, Seri Pilmoor Utara, Taman Megah Emas)';
UPDATE public.area SET osm_id = 17137932 WHERE name = 'PJU 2';
UPDATE public.area SET osm_id = 17144671 WHERE name = 'PJU 3';
UPDATE public.area SET osm_id = 17144602 WHERE name = 'PJU 4';
UPDATE public.area SET osm_id = 17139691 WHERE name = 'PJU 5 (Kota Damansara, Sierra Damansara, Taman Sains Selangor 1, Villa Damansara)';
UPDATE public.area SET osm_id = 17135864 WHERE name = 'PJU 6 (Bandar Utama, Damansara Residensi)';
UPDATE public.area SET osm_id = 17138409 WHERE name = 'PJU 7 (Mutiara Damansara)';
UPDATE public.area SET osm_id = 17139509 WHERE name = 'PJU 8';
UPDATE public.area SET osm_id = 17139508 WHERE name = 'PJU 9 (Bandar Sri Damansara)';
UPDATE public.area SET osm_id = 17051666 WHERE name = 'SS 1 (Kampung Tunku)';
UPDATE public.area SET osm_id = 16888022 WHERE name = 'SS 10 (Bandar Sunway, Sungai Way)';
UPDATE public.area SET osm_id = 17041291 WHERE name = 'SS 11';
UPDATE public.area SET osm_id = 17101075 WHERE name = 'SS 2';
UPDATE public.area SET osm_id = 17132086 WHERE name = 'SS 20 (Damansara Kim, Damansara Utama)';
UPDATE public.area SET osm_id = 17133500 WHERE name = 'SS 21 (Damansara Uptown, Damansara Utama)';
UPDATE public.area SET osm_id = 17131623 WHERE name = 'SS 22 (Damansara Jaya)';
UPDATE public.area SET osm_id = 17131624 WHERE name = 'SS 22A (Damansara Jaya)';
UPDATE public.area SET osm_id = 17129962 WHERE name = 'SS 23 (Taman SEA)';
UPDATE public.area SET osm_id = 17128675 WHERE name = 'SS 24 (Taman Megah)';
UPDATE public.area SET osm_id = 17126963 WHERE name = 'SS 25 (Taman Bukit Emas, Taman Desa Suria, Taman Mayang)';
UPDATE public.area SET osm_id = 17133800 WHERE name = 'SS 26 (Taman Mayang Jaya)';
UPDATE public.area SET osm_id = 17051416 WHERE name = 'SS 3 (Seaport, Taman Subang, Taman Universiti)';
UPDATE public.area SET osm_id = 17049280 WHERE name = 'SS 4 (Kelana Jaya)';
UPDATE public.area SET osm_id = 17049041 WHERE name = 'SS 5 (Kelana Jaya, SS 5C)';
UPDATE public.area SET osm_id = 17046669 WHERE name = 'SS 6 (Kelana Jaya)';
UPDATE public.area SET osm_id = 17041292 WHERE name = 'SS 7 (Kelana Jaya)';
UPDATE public.area SET osm_id = 17044520 WHERE name = 'SS 8 (Sungai Way)';
UPDATE public.area SET osm_id = 17065212 WHERE name = 'SS 9 (Sungai Way)';
UPDATE public.area SET osm_id = 17045721 WHERE name = 'SS 9A (Sungai Way)';
UPDATE public.area SET osm_id = 17061010 WHERE name = 'Seksyen 1 (PJ Old Town)';
UPDATE public.area SET osm_id = 17077548 WHERE name = 'Seksyen 10';
UPDATE public.area SET osm_id = 17075600 WHERE name = 'Seksyen 11';
UPDATE public.area SET osm_id = 17075384 WHERE name = 'Seksyen 12';
UPDATE public.area SET osm_id = 17052568 WHERE name = 'Seksyen 13';
UPDATE public.area SET osm_id = 17073694 WHERE name = 'Seksyen 14';
UPDATE public.area SET osm_id = 17081725 WHERE name = 'Seksyen 16 (Seksyen 16 (Petaling Jaya))';
UPDATE public.area SET osm_id = 17086552 WHERE name = 'Seksyen 17 (Happy Garden)';
UPDATE public.area SET osm_id = 17086551 WHERE name = 'Seksyen 17A (Kampung Seri Damansara)';
UPDATE public.area SET osm_id = 17040402 WHERE name = 'Seksyen 18 (Taman Kanagapuram)';
UPDATE public.area SET osm_id = 17100422 WHERE name = 'Seksyen 19';
UPDATE public.area SET osm_id = 17055673 WHERE name = 'Seksyen 1A (Kawasan Rukun Tetangga Jalan Carey)';
UPDATE public.area SET osm_id = 17061003 WHERE name = 'Seksyen 2 (PJ Old Town)';
UPDATE public.area SET osm_id = 17078184 WHERE name = 'Seksyen 20 (Taman Paramount)';
UPDATE public.area SET osm_id = 17079035 WHERE name = 'Seksyen 21 (SEA Park)';
UPDATE public.area SET osm_id = 17071581 WHERE name = 'Seksyen 22 (Taman Lean Seng)';
UPDATE public.area SET osm_id = 17060996 WHERE name = 'Seksyen 3 (PJ Old Town)';
UPDATE public.area SET osm_id = 17060987 WHERE name = 'Seksyen 4 (PJ Old Town)';
UPDATE public.area SET osm_id = 17056748 WHERE name = 'Seksyen 5 (Bukit Gasing, Taman Petaling)';
UPDATE public.area SET osm_id = 17065287 WHERE name = 'Seksyen 51 (Zon Perindustrian Seksyen 51)';
UPDATE public.area SET osm_id = 17069650 WHERE name = 'Seksyen 51A';
UPDATE public.area SET osm_id = 17072867 WHERE name = 'Seksyen 52 (PJ State)';
UPDATE public.area SET osm_id = 17065056 WHERE name = 'Seksyen 6';
UPDATE public.area SET osm_id = 17066095 WHERE name = 'Seksyen 7 (PJ State)';
UPDATE public.area SET osm_id = 17065397 WHERE name = 'Seksyen 8';
UPDATE public.area SET osm_id = 17077663 WHERE name = 'Seksyen 9';

DO $$
DECLARE
    missing text;
BEGIN
    SELECT string_agg(name, '; ') INTO missing FROM public.area WHERE osm_id IS NULL;
    IF missing IS NOT NULL THEN
        RAISE EXCEPTION 'These sections got no osm_id, nothing was changed: %', missing;
    END IF;
END $$;

ALTER TABLE public.area ALTER COLUMN osm_id SET NOT NULL;
ALTER TABLE public.area ADD CONSTRAINT uq_area_osm_id UNIQUE (osm_id);

COMMIT;
