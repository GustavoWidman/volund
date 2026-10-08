# Revision build verification 2026-10-08

The revised main article is seven pages and the supplement is ten. Both compiled without warnings or errors using Typst 0.15.1, `charged-ieee:0.1.4`, and bundled fonts. Exact source, PDF, figure, and render hashes are in `FINAL-BUILD-VERIFICATION.json`. Prior build records remain under `revision-history/2026-10-02` and describe the earlier PDFs only.

The manuscript worker rendered and visually inspected all seventeen pages at 120 dpi for the main article and 110 dpi for the supplement. An initial fixed-height bibliography overflow was removed before final rendering; the references now flow in the article columns. The final PDFs show no clipped or overlapping text, broken tables, missing glyphs, or unreadable charts. A text-coordinate check also found zero spans outside either PDF's pages. The parent independently inspected all seventeen final page renders and found them clean.

Main-article Tables I and II are compact single-column tables. The three existing 3.3-inch vector figures and their underlying data are unchanged. The new tables were checked programmatically against the retained portfolio CSV and campaign-process audit. The C3 first development checkpoint is reported as 1.277 in prose, rounding the unchanged underlying 1.27747402217971 value.

All nineteen bibliography entries are cited. The four new primary-source references and one metadata correction are documented in `REVISION-NOTES-2026-10-08.md`. Rendered text contains no duplicated figure prefix or unresolved citation. The C1 shifted sparse regression and all original study-design, finite-test, compaction, and resource-accounting qualifications remain.

A byte-for-byte comparison checked all 263 tracked files in the recovered `experiments/unattended-optimization-v3` tree and found no changes. No new optimization, measurement, model call, candidate selection, or modification of frozen evidence was performed for this revision. Public evidence release, named-author approval, and submission remain separate decisions.

An independent reviewer checked the contribution and related-work claims against the new primary sources and verified Table I directly against the canonical final report in the preserved lean evidence archive. Table II matched the campaign process audit. No further correction was requested.

## Final Volund publication-facing pass

After the author selected `Volund` for the publication and lowercase `volund` for the repository path, both PDFs were rebuilt with the new title, future-public availability statements and verified repository link, no author-review footer labels, and no audience-facing pending-approval checklist. AI-use disclosure remains. The worker inspected all seventeen final rendered pages; the parent independently inspected all four changed-content pages and had already inspected the earlier complete pass. No layout issue was found. Main and supplement remain seven and ten pages. The URL is embedded as a clickable link; the wording promises public access upon publication and does not claim current public access.
