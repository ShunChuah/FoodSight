-- 022: drop the dish table.
--
-- No part of the pipeline ever filled it (no data source for menus), and it
-- was empty. The graph no longer has Dish nodes or HAS_DISH (ontology.json),
-- and the validator no longer has a "dishes" field.
--
-- Its ID counter (dish_dish_id_seq), primary key, CHECK (price > 0) and its
-- foreign keys to restaurant and cuisine go with it. Nothing else points to it.
--
-- Stops without changing anything if the table has any rows.

BEGIN;

DO $$
BEGIN
    IF EXISTS (SELECT 1 FROM public.dish) THEN
        RAISE EXCEPTION 'public.dish has rows: not dropped';
    END IF;
END $$;

DROP TABLE public.dish;

COMMIT;
