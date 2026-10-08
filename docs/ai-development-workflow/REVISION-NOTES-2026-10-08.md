# Manuscript revision 2026-10-08

## Provenance

Revised from exact final commit `23cfd8448d819c8e9a245e9afef5869791abc484`, rather than the stale local worktree. The prior main PDF SHA-256 is `f4ead58f7f9b3446f4cc03ba1ffb8c7b1780a5cd24a2244283d83987c875cec7`; prior supplement is `54ee7a98648deddbaedf7cb5b4602031c02966e9a2c5c2fac3bf01a35a92f65d`. Both recovered PDFs match these identities. Exact prior sources and PDFs were preserved before editing.

## Changes

- The introduction now opens with the concrete campaign outcomes and contribution: source-linked empirical evidence connecting candidate sources, validation, hypotheses, reviewer decisions, and development trajectories. Design limits remain explicit.
- Added orchestration, review, and verification literature: AutoGen, MetaGPT, ChatDev, and AgentCoder. The text distinguishes executable checks from formal or exhaustive verification and does not claim a new multiagent framework.
- Added compact main-article Table I with six final portfolio estimates and nominal one-sided 90% lower bounds, retaining the higher-precision supplementary table. Moved the campaign process-count table to main-article Table II, with definitions and review-count scope.
- Corrected duplicated figure prefixes while preserving all three compact single-column vector figures.
- Added truthful private-data availability statements. No public URL, DOI, release, or access promise is invented.
- Added manuscript and supporting-work AI-use disclosures, distinct from the measured campaign models and accounting.
- Replaced the stale blanket submission-readiness paragraph with current author-review status and intended SSRN preprint context. Final author consent and submission are not asserted.
- Corrected the C3 first development checkpoint’s prose rounding from 1.278 to 1.277, consistent with the retained value 1.27747402217971. No underlying value changed.
- Corrected the PIE bibliography’s author metadata to include Yiming Yang, as listed by the official ICLR proceedings record.
- Updated reproduction instructions and retained prior build receipts as dated history.

## Evidence checks

Table I values derive from `analysis/figures/measured-data-01/heldout.csv`; Table II counts are checked against `analysis/final-audit/process-audit.json` and the original supplementary table. The development rounding correction is checked against `analysis/figures/measured-data-01/trajectories.csv`. These paths are relative to `experiments/unattended-optimization-v3`.

The C1 shifted sparse regression, finite-test limitations, shared-host and single-task scope, lack of a matched comparator, unknown compaction work, and token/cost-accounting limits remain. No new optimization campaign, performance run, or frozen-evidence modification forms part of this revision.

## New citation verification

- AutoGen: final COLM 2024 paper, Sections 2.1–2.2, tool-backed agents and conversation programming. Primary PDF: https://www.microsoft.com/en-us/research/wp-content/uploads/2023/08/LLM_agent.pdf . Uses the final plural title “Conversations” and Ahmed Awadallah author metadata.
- MetaGPT: official ICLR 2024 metadata, https://proceedings.iclr.cc/paper_files/paper/2024/hash/6507b115562bb0a305f1958ccc87355a-Abstract-Conference.html . Claims checked against Sections 3.1–3.3 of https://arxiv.org/html/2308.00352v6 . Proceedings author naming/order retained rather than mixing version-specific author blocks.
- ChatDev: ACL 2024, Section 3.1 and Figure 2 distinguish static code review and dynamic testing. https://aclanthology.org/2024.acl-long.810/ ; DOI `10.18653/v1/2024.acl-long.810`.
- AgentCoder: arXiv `2312.13010`, original 2023 metadata with May 2024 revision noted; Sections 3.2–3.3 and 4.7 support role separation, Section 4.5 documents erroneous generated test oracles. https://arxiv.org/html/2312.13010v3 . Its functional code-generation results are not treated as runtime-optimization results, and no conference venue is invented.
- PIE metadata correction: official ICLR proceedings author list at https://proceedings.iclr.cc/paper_files/paper/2024/hash/ce65173b994cf7c925c71b482ee14a8d-Abstract-Conference.html .

## Remaining decisions

Final named-author approval, any required submission declarations, the artifact license and public-release destination remain separate from editorial preparation. The current private repository is not described as a public archive. No publication or submission occurred in this revision.

## Publication-ready wording requested after delivery

The author requested future public availability wording for the publication version: the repository will be made public after validation and before publication. Audience-facing status checks and author-review footer labels have been removed in this working copy; availability states that study code, frozen protocol, paired measurements, process records, and analysis scripts will be publicly available in the accompanying repository upon publication. No URL, DOI, actual-publication claim, date, or coauthor approval has been invented. The existing AI-use disclosure remains.

Remaining release checks are retained here and in TODO.md rather than in the audience-facing supplement: validate the repository contents, agree on the project/repository name, verify the final repository URL, confirm applicable declarations and license, obtain final named-author approval, and explicitly authorize changing repository visibility. The repository remains private during validation. The selected name is lowercase `volund`. The main title is “volund: An Empirical Study of Unattended Multiagent Program Optimization”. The accompanying repository URL was verified as https://github.com/GustavoWidman/volund, private under GustavoWidman, before insertion into both availability statements. The statements describe future public availability upon publication; current access remains private.

### Final capitalization correction

The author subsequently selected `Volund` for the paper and supplement, including titles and prose. Lowercase `volund` remains only in the repository URL and any command or path names. The final main title is “Volund: An Empirical Study of Unattended Multiagent Program Optimization”. This supersedes the earlier lowercase title choice.
