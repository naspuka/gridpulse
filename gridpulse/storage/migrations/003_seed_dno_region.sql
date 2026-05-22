-- 003 — Seed the 14 UK DNO regions plus the NATIONAL sentinel.
--
-- region_id assignments match the Carbon Intensity API's regionid (1..14).
-- octopus_code is the well-known UK DNO letter code embedded in Agile tariff
-- product names (e.g. E-1R-AGILE-FLEX-22-11-25-C → London).
--
-- INSERT ... ON CONFLICT lets the migration re-run safely if we ever amend
-- the data and re-apply.

INSERT INTO ref.dno_region
    (region_id, canonical_code,           slug,                       name,                         carbon_intensity_id, octopus_code)
VALUES
    (0,        'NATIONAL',                'national',                 'National (UK rollup)',       NULL,                NULL),
    (1,        'NORTH_SCOTLAND',          'north-scotland',           'North Scotland',             1,                   'P'),
    (2,        'SOUTH_SCOTLAND',          'south-scotland',           'South Scotland',             2,                   'N'),
    (3,        'NORTH_WEST_ENGLAND',      'north-west-england',       'North West England',         3,                   'G'),
    (4,        'NORTH_EAST_ENGLAND',      'north-east-england',       'North East England',         4,                   'F'),
    (5,        'YORKSHIRE',               'yorkshire',                'Yorkshire',                  5,                   'M'),
    (6,        'NORTH_WALES_MERSEYSIDE',  'north-wales-merseyside',   'North Wales & Merseyside',   6,                   'D'),
    (7,        'SOUTH_WALES',             'south-wales',              'South Wales',                7,                   'K'),
    (8,        'WEST_MIDLANDS',           'west-midlands',            'West Midlands',              8,                   'E'),
    (9,        'EAST_MIDLANDS',           'east-midlands',            'East Midlands',              9,                   'B'),
    (10,       'EAST_ENGLAND',            'east-england',             'East England',               10,                  'A'),
    (11,       'SOUTH_WEST_ENGLAND',      'south-west-england',       'South West England',         11,                  'L'),
    (12,       'SOUTH_ENGLAND',           'south-england',            'South England',              12,                  'H'),
    (13,       'LONDON',                  'london',                   'London',                     13,                  'C'),
    (14,       'SOUTH_EAST_ENGLAND',      'south-east-england',       'South East England',         14,                  'J')
ON CONFLICT (region_id) DO UPDATE SET
    canonical_code      = EXCLUDED.canonical_code,
    slug                = EXCLUDED.slug,
    name                = EXCLUDED.name,
    carbon_intensity_id = EXCLUDED.carbon_intensity_id,
    octopus_code        = EXCLUDED.octopus_code;
