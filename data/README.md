# Curated reproduction data

`raw-arithmetic/` contains original byte-identical pair, result and bootstrap
records for all 52 retained comparisons (156 files, about 424 KB). Its manifest
pins each file to the separately retained immutable evidence archive. It supports
arithmetic reproduction only, not source/build/attempt/command provenance validation.

`plot-data.json` retains every row consumed by the existing plotter, source hashes,
completion flags and limitations from an authenticated offline extraction. Its
curation metadata states which unused tables/fields were omitted. Re-rendering
produced all 17 figures with PNG bytes identical to the full extraction.

The existing 11 measured-data CSV tables are byte-identical to fresh extraction.
No inference, native timing, endpoint reselection or experimental rerun was used.
Full scientific evidence verification still requires the separate archive.
