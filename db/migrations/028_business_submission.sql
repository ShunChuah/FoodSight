-- Business registration: a user registers a restaurant (the Register Business form), an admin
-- checks it, and an approved one is added by the next nightly pipeline run.
--
--   business_submission     one row per registration, kept after approval. Its restaurant
--                           columns are named like the columns they fill; the contact person,
--                           the email, the SSM number and the halal details stay here, admin only
--   submission_round        one row per submission and resubmission: when it was sent, which
--                           fields the user changed, who reviewed it and the decision
--   submission_field_check  the admin's mark on each form field in a round: checked, or
--                           flagged with a note telling the user what to fix
--   submission_document     the uploaded files themselves (bytea), one per kind
--
-- restaurant gets "source": extracted (OpenStreetMap and Google, the pipeline) or submitted
-- (from a business submission). A submitted restaurant has no OpenStreetMap object, so osm_id
-- and osm_type may be empty, but only together.
--
-- The value lists (restaurant.source and business_submission.status in
-- src/reference/categories.json; the round decision, field check state and document kind in
-- the backend) have no CHECK here, on purpose: a list can change without a migration. The
-- number and logic rules are here.
BEGIN;

ALTER TABLE public.restaurant
    ADD COLUMN source varchar(20) NOT NULL DEFAULT 'extracted';
ALTER TABLE public.restaurant ALTER COLUMN osm_id DROP NOT NULL;
ALTER TABLE public.restaurant ALTER COLUMN osm_type DROP NOT NULL;
ALTER TABLE public.restaurant
    ADD CONSTRAINT chk_restaurant_osm_both CHECK ((osm_id IS NULL) = (osm_type IS NULL));

CREATE TABLE public.business_submission (
    submission_id     serial           PRIMARY KEY,
    user_id           integer          NOT NULL REFERENCES auth.users(user_id) ON DELETE CASCADE,
    status            varchar(20)      NOT NULL DEFAULT 'waiting',
    round_no          smallint         NOT NULL DEFAULT 1 CHECK (round_no >= 1),
    restaurant_id     integer          UNIQUE REFERENCES public.restaurant(restaurant_id) ON DELETE SET NULL,
    -- Admin only
    manager_name      varchar(150)     NOT NULL,
    manager_phone     varchar(50)      NOT NULL,
    business_email    varchar(254)     NOT NULL,
    ssm_number        varchar(12)      NOT NULL,
    halal_status      varchar(20)      NOT NULL,
    halal_certified   boolean          NOT NULL DEFAULT false,
    halal_cert_expiry date,
    sells_pork        boolean,
    serves_alcohol    boolean,
    -- The restaurant
    name              varchar(255)     NOT NULL,
    brand             varchar(150),
    business_style    varchar(100)     NOT NULL,
    restaurant_type   varchar(100)     NOT NULL,
    business_status   varchar(50)      NOT NULL,
    phone             varchar(50)      NOT NULL,
    website           varchar(500),
    description       varchar(1000)    NOT NULL,
    address           varchar(450)     NOT NULL,
    postcode          varchar(10)      NOT NULL,
    latitude          double precision NOT NULL,
    longitude         double precision NOT NULL,
    monday            varchar(50)      NOT NULL,
    tuesday           varchar(50)      NOT NULL,
    wednesday         varchar(50)      NOT NULL,
    thursday          varchar(50)      NOT NULL,
    friday            varchar(50)      NOT NULL,
    saturday          varchar(50)      NOT NULL,
    sunday            varchar(50)      NOT NULL,
    cuisines          text             NOT NULL,
    avg_meal_price    double precision NOT NULL CHECK (avg_meal_price > 0),
    service_style     varchar(100)     NOT NULL,
    target_segment    text             NOT NULL,
    ambiance          varchar(100)     NOT NULL,
    facilities        text,
    created_at        timestamptz      NOT NULL DEFAULT now(),
    updated_at        timestamptz      NOT NULL DEFAULT now(),
    CONSTRAINT chk_submission_certified_expiry CHECK (NOT halal_certified OR halal_cert_expiry IS NOT NULL)
);
CREATE INDEX idx_business_submission_user ON public.business_submission (user_id);
CREATE INDEX idx_business_submission_status ON public.business_submission (status);
CREATE TRIGGER trg_business_submission_updated_at BEFORE UPDATE ON public.business_submission
    FOR EACH ROW EXECUTE FUNCTION update_updated_at();

CREATE TABLE public.submission_round (
    round_id          serial      PRIMARY KEY,
    submission_id     integer     NOT NULL REFERENCES public.business_submission(submission_id) ON DELETE CASCADE,
    round_no          smallint    NOT NULL CHECK (round_no >= 1),
    submitted_at      timestamptz NOT NULL DEFAULT now(),
    changed_fields    text,
    reviewer_id       integer     REFERENCES auth.users(user_id) ON DELETE SET NULL,
    review_started_at timestamptz,
    decision          varchar(20),
    decided_at        timestamptz,
    UNIQUE (submission_id, round_no),
    CONSTRAINT chk_round_decided CHECK ((decision IS NULL) = (decided_at IS NULL))
);

CREATE TABLE public.submission_field_check (
    round_id   integer      NOT NULL REFERENCES public.submission_round(round_id) ON DELETE CASCADE,
    field      varchar(50)  NOT NULL,
    state      varchar(10)  NOT NULL,
    note       varchar(500),
    checked_at timestamptz  NOT NULL DEFAULT now(),
    PRIMARY KEY (round_id, field)
);

CREATE TABLE public.submission_document (
    document_id   serial       PRIMARY KEY,
    submission_id integer      NOT NULL REFERENCES public.business_submission(submission_id) ON DELETE CASCADE,
    kind          varchar(30)  NOT NULL,
    file_name     varchar(255) NOT NULL,
    content_type  varchar(100) NOT NULL,
    size_bytes    integer      NOT NULL CHECK (size_bytes > 0),
    content       bytea        NOT NULL,
    uploaded_at   timestamptz  NOT NULL DEFAULT now(),
    UNIQUE (submission_id, kind)
);

COMMIT;
