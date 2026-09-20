-- Bronze copy of the landed dft_2017 files: every column a string under its normalised name plus
-- the landing metadata. No filtering, no typing; the source contract decided which files were
-- landed here (quarantined batches live under _quarantined/ and are not read).
{{ config(materialized='table') }}

{{ bronze_select('landed', 'dft_2017') }}
