-- Cluster: drop area_id. A food cluster can spread over two or more
-- sections (in the first trial, 9 of 40 did), so one area per cluster would
-- be wrong for some clusters and was never filled. A cluster's sections are
-- found through its restaurants:
--   (Cluster)<-[:IN_CLUSTER]-(Restaurant)-[:LOCATED_IN]->(Location)-[:IN_AREA]->(Area)
-- The table is empty, so no data is lost. Dropping the column also drops its
-- foreign key to area.
BEGIN;

ALTER TABLE public.cluster DROP COLUMN area_id;

COMMIT;
