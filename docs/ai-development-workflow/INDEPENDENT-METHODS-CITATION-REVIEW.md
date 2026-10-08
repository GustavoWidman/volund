# Independent methods and citation review

Reviewed 2026-10-01 UTC. Scope: the staged, results-pending manuscript and supplement, their bibliography and source ledger, frozen protocol, public task/seed, relevant implementation and pinned primary references. This review did not inspect campaign messages or outcomes, generated held-out fixture files, or final assessment results. It did not execute tests, native workloads, model sessions, Typst compilation, or rendering. Manuscript and frozen sources were not edited.

## Decision

The principal methods and inference claims are consistent with the implementation inspected. Correct one reference byline and make final Memcheck coverage explicit before integrating results. Two smaller precision edits are recommended below. No causal-component, first-of-kind, all-input-correctness, or proof-of-autonomy claim was found. The sole preliminary-exposure disclosure is appropriate; no earlier cohort counts or outcomes appear in the staged paper. No unrelated prior project material appears.

## Corrections to apply

### 1. PIE author list: prefer the paper byline and document the conflicting landing page

`refs.bib:17` includes Yiming Yang. The ICLR publisher landing page includes that name, but its linked publisher PDF, page 1, and the current author-submitted arXiv version 5 both list ten authors without it. The paper byline and current author record agree. Use those ten authors and amend the PIE entry in `SOURCE-LEDGER.md` to explain the publisher metadata discrepancy, rather than calling all primary author records concordant.

Exact replacement entry, retaining the established key and conference citation:

```bibtex
@inproceedings{shypula2024pie,
  author = {Shypula, Alexander and Madaan, Aman and Zeng, Yimeng and Alon, Uri and Gardner, Jacob and Hashemi, Milad and Neubig, Graham and Ranganathan, Parthasarathy and Bastani, Osbert and Yazdanbakhsh, Amir},
  title = {Learning Performance-Improving Code Edits},
  booktitle = {The Twelfth International Conference on Learning Representations},
  year = {2024},
  url = {https://proceedings.iclr.cc/paper_files/paper/2024/hash/ce65173b994cf7c925c71b482ee14a8d-Abstract-Conference.html}
}
```

Primary evidence:

- [ICLR publisher PDF, first-page byline](https://proceedings.iclr.cc/paper_files/paper/2024/file/ce65173b994cf7c925c71b482ee14a8d-Paper-Conference.pdf)
- [Author-submitted arXiv v5, 26 April 2024](https://arxiv.org/abs/2302.07867v5)
- [Conflicting ICLR landing-page metadata](https://proceedings.iclr.cc/paper_files/paper/2024/hash/ce65173b994cf7c925c71b482ee14a8d-Abstract-Conference.html)

The scientific PIE claims remain supported. Section 2 distinguishes test conformance from performance, and discusses commodity-hardware variability and deterministic simulation. No change to its related-work characterization is needed.

### 2. Final assessment: distinguish both-stratum correctness/resource checks from shared public Memcheck

`main.typ:113` says that the evaluator checks correctness and resources across both final strata. This is defensible for the oracle's process/resource checks, but it can also be read as claiming held-out-stratum Memcheck coverage. `extended-methods.typ:69` repeats the general wording without identifying the final Memcheck inputs. The coverage qualification at `extended-methods.typ:51` is useful but does not explicitly connect the final run to the shared public suite.

Suggested replacement for the last sentence of the first final-assessment paragraph:

> Before timing, the evaluator checks correctness and resource compliance in both final strata and reruns Memcheck on the shared six-family public diagnostic suite. Every required check must pass; a failed endpoint is not replaced with earlier code.

Suggested supplement addition:

> Final Memcheck uses the shared public profile-suite fixtures, not the transfer or shifted performance inputs. Its completion does not establish instrumented-memory coverage at final workload sizes or on unexercised branches.

Implementation evidence: `evaluation/run.py:227–254` invokes one Memcheck operation for the seed and each endpoint, and separate `test` operations for both strata. `development/native_backend.py:378–400` selects `profile_suite` fixtures for Memcheck, regardless of `correctness_suite` or `benchmark_suite`; the diagnostic command uses definite-leak handling plus error exit code 99. `NativeBackend.test`, around lines 297–352, validates suite-specific oracle results and per-case RSS. The final preparation source preserves the public profile suite. This recommendation describes the frozen implementation; it does not request a new test suite or evaluation change.

### 3. State explicitly that structured writes also use the execution lane

This is a precision improvement, not a contradiction in the current prose. `main.typ:95–97` and `extended-methods.typ:59–61` clearly place arbitrary shell work in the shared lane and exempt bounded read/list/search. They explain structured-write path restrictions but omit its scheduling behavior. Add “Structured writes also acquire the execution lane” to the supplement or relevant sentence.

Evidence: `runtime/workspace.py:304–312` wraps `_write` in `coordinator.async_lease('workspace_write', ...)`; read/list/search use the other branch at lines 313–314. Do not describe structured writes as shell commands or as unleased read operations.

### 4. Use “last verified incumbent” for stopped endpoints

At `main.typ:113` and `extended-methods.typ:69`, replace the broad “last verifiable source” with “last verified incumbent,” adding that an endpoint can be unavailable if no incumbent is verifiable. This prevents a reader from interpreting the stopped endpoint as an unpromoted exploratory source.

Evidence: `owner/service.py:559–564` seals `state['incumbent']` or an empty source record on stop. `evaluation/run.py:56–57` requires the endpoint to equal that retained incumbent; lines 76–77 allow no source only for incomplete campaigns, and lines 237–240 emit unavailable rows. An incomplete campaign with a verified incumbent remains assessable after all three truthful seals; completion is not silently required.

## Methods checks requiring no correction

- **Replication and design:** three serial, separately initialized campaigns of one synthetic task; campaign is the replication unit. Shared task, seed, host, model service, and design decisions preclude an unqualified independence claim. No randomized alternative arm or component attribution is claimed.
- **Task and seed:** the fixed ABI, bounds, invalid-input behavior, exact aggregates, input immutability, reentrancy, invocation lifecycle, persistent-cache prohibition, untuned indexed seed, and canonical compiler flags agree with the public contract, header, seed, and native backend.
- **Roles:** `runtime/contracts.py:59–65` specifies Sol/high lead and reviewer and Luna/xhigh measurement, implementation, and investigation roles. `start_thread_params` disables provider fallback. Prescribed roles remain separate from the still-pending evidence of actual routing and conduct.
- **Empirical review:** prompts and owner checks require executed source-bound reviewer work and evidence inspection. Nomination review requires fresh build/test/profile/full configured Memcheck/benchmark evidence. Negative claims require appropriate direct checks. A source inspection receipt is not proof of comprehension; the manuscript does not claim it is.
- **Selection:** `development/core.py:415–482` selects the first passing complete official comparison in append order across the immutable plan, not the latest or best. It preserves exact-source semantic/memory disqualification and selected-build evidence. Later reviewer execution is an additional requirement, not permission to replace the gate sample.
- **Estimator:** `native_backend.py:179–196, 422–485` and `owner/service.py:38–58, 477–482` implement median paired log ratios, equal-family geometric aggregation, 10,000 joint complete-block draws, and interpolated lower percentile. The reciprocal `1/1.10` floor correctly means at most 10% estimated latency increase. The bound is nominal one-sided 90%, not a symmetric interval, family interval, or campaign-wide efficacy test.
- **Recovery:** `owner/measurement.py`, `owner/overlap.py`, and `development/core.py:252–303` support FIFO after coordinator admission, cleanup/quarantine, exactly two attested recovery categories, whole-comparison retries, and first-valid score-independent termination. Candidate/semantic/resource failures cannot be hidden by overlap. The retained zero generic-retry setting does not cap eligible timing attempts.
- **Stopping and embargo:** closure requires reviewed disposition of the concrete queue; final text alone cannot close a campaign. No fixed research quota is specified. `evaluation/run.py` requires the exact three canonical, terminal measured identities and sealed unchanged sources before assessment. Final changed endpoints use 30 blocks per stratum and no promotion threshold; identical seed endpoints are algebraic identity. Transfer and shift remain separate portfolios.
- **Resources:** public thread endpoint reconciliation, subset accounting for cached input/reasoning, zero-default cache-write uncertainty, compaction/context distinction, observed-token-only scenarios, and missing whole-run cost are appropriately qualified. `runtime/telemetry.py`, `runtime/ACCOUNTING.md`, the reanalysis source, and pinned OpenAI source agree. The final results must still reconcile actual coverage rather than infer it from intended instrumentation.

## Primary-reference audit

All references were reopened at primary publisher, author-repository, official documentation, or official tagged-source URLs. Full paper methods or directly relevant primary text was consulted for the claims below, not metadata alone. The ICLR byline discrepancy above is the only bibliographic correction found.

| Reference | Verified identity and support |
| --- | --- |
| PIE | ICLR 2024; title and paper byline as corrected above. Publisher PDF §2 supports C++ edits, test checks, and measurement-variability claims |
| [AlphaEvolve](https://arxiv.org/html/2506.13131v1) | 18 listed authors agree; arXiv 2506.13131, v1 16 June 2025, DOI 10.48550/arXiv.2506.13131; white-paper status. §2 supports evolutionary program edits and evaluator feedback |
| [POLO](https://www.ijcai.org/proceedings/2025/0814.pdf) | Six authors agree; IJCAI 2025, pp. 7319–7328, DOI 10.24963/ijcai.2025/814. §§3.1–3.3 support bottleneck profiling and collaborating Generator/Decision agents in iterative rewriting |
| [PerfAgent](https://arxiv.org/html/2607.19653v1) | Seven authors agree; arXiv 2607.19653, v1 22 July 2026, DOI 10.48550/arXiv.2607.19653; preprint. §III supports repeated profiler, rebuild, verification, and refinement feedback; no peer-reviewed status asserted |
| [SWE-Perf record](https://proceedings.mlr.press/v306/he26y.html), [v2 methods](https://arxiv.org/html/2507.12415v2) | Nine authors agree; ICML 2026/PMLR 306, pp. 41651–41666; arXiv 2507.12415v2 is dated 1 July 2026. §3 supports real-repository optimization. Publisher PDF retrieval failed; author full text supplied claim verification |
| [GSO](https://papers.nips.cc/paper_files/paper/2025/file/ddd98389004161943e646322a16348c3-Paper-Datasets_and_Benchmarks_Track.pdf) | Six authors agree; NeurIPS 2025, volume 38, Datasets and Benchmarks track, DOI 10.52202/085713-5054. §2 and Appendix B support real-codebase scope |
| [Compiler feedback](https://arxiv.org/html/2403.14714v1) | Four authors agree; arXiv 2403.14714, v1 18 March 2024, DOI 10.48550/arXiv.2403.14714. §4 explicitly compares iterative feedback with sampling. The manuscript's cautious, nonuniversal inference is supported |
| [Kalibera and Jones](https://kar.kent.ac.uk/id/document/3127886) | Two authors, title, ISMM 2013, pp. 63–74, DOI 10.1145/2464157.2464160 agree. Introductory methods discussion supports repetition where uncertainty arises; it does not validate this manuscript's particular bootstrap. The primary repository's indexed record explicitly says its version corrects the ISMM version; direct record fetch timed out, PDF retrieved |
| [Mytkowicz et al.](https://sape.inf.usi.ch/publications/asplos09.html) | Four authors, ASPLOS 2009, pp. 265–276, DOI 10.1145/1508244.1508275 agree. Primary author-group abstract supports sensitivity to incidental setup. ACM PDF retrieval failed; claims are confined to the primary record's described findings |
| [Cawley and Talbot](https://www.jmlr.org/papers/volume11/cawley10a/cawley10a.pdf) | Two authors, JMLR 11(70), pp. 2079–2107, 2010 agree. Introduction and selection-bias discussion support separation of selection and evaluation. Application to program timings remains explicitly an inference |
| [Callgrind manual](https://valgrind.org/docs/manual/cl-manual.html) | Official manual chapter 6 title agrees. §6.1 describes instruction/call accounting and optional cache/branch simulation. It does not establish installed version or native elapsed performance |
| [Pinned response parser](https://github.com/openai/codex/blob/rust-v0.159.3/codex-rs/codex-api/src/sse/responses.rs#L121) | Official tag rust-v0.159.3; lines 121–143 establish optional input details and zero-default cache-write parsing. Descriptive software-entry title is appropriate |
| [Pinned remote compaction](https://github.com/openai/codex/blob/rust-v0.159.3/codex-rs/core/src/compact_remote_v2.rs#L223) | Official same tag; separate usage handling, compaction marker/history replacement, and context recomputation verified. Companion session/state/public-notification sources confirm distinct usage paths; this supports a possible public-counter gap, not proof of a measured campaign's missing amount |
| [API pricing](https://developers.openai.com/api/docs/pricing) | Official dated Standard short/long Sol and Luna rate structure agrees with the source. Model-specific prices are hypothetical comparison scenarios, not the campaign's bill |
| [Prompt caching](https://developers.openai.com/api/docs/guides/prompt-caching) | Official replacement-charge treatment agrees with `(I-R-C)pI + RpR + CpC + OpO`; cache-write charges are not additive ordinary-input charges |

## Reviewed source identities and remaining gate

SHA-256 of staged inputs at review:

- `main.typ`: `056df8bd153d4f558000fef8008ca87fb056359402bc8a24e991b912c7af29cb`
- `extended-methods.typ`: `3dfdebd3fb627d177baca2c706655d1563f0f051fcaed1068f65825b3f909cbb`
- `refs.bib`: `4707e4b08463fc1c2141b38fea394d61dfe21d1174d910f06fd7c781c8a1622a`
- `SOURCE-LEDGER.md`: `466e4ce9355a06c915c1dcc2b923544a0565af2516d87f8444ce943db0aa906c`

This is source-level review of a pending-results draft. Actual adherence, interventions, endpoint eligibility, final correctness/performance, usage reconciliation, and all visual/layout claims remain unreviewed until the complete evidence and analysis lane are released. Preserve the existing final integration checklist. Refresh `SOURCE-CHECK.json` after accepted source edits; this review is not a rendering pass or approval to publish.
