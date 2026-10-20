# Final correction disposition

Product candidate: `1858656a86869ba462545a9232b89a0e1e1c319c`.

Claude Opus 5.5 completed a full replacement review at `cbb180af857f1c89956db8ac5128e4182d9b9ea8`, including the complete 63-file product diff, critical full-source contexts, regression tests and CI recipes. There were no Critical or High findings. All two Medium and six Low findings were addressed in this candidate.

| Finding | Correction | Verification |
|---|---|---|
| M1 required parser features | Configure fails without SAX1/PUSH/SCHEMAS/THREAD; warns without ICONV/ICU | Actual macOS/Linux configure; six feature-control configurations; config-mode include probe |
| M2 Windows interpreter | Shared build action selects `python` on Windows, `python3` elsewhere | Source review; Windows execution remains unverified |
| L1 streaming comment/PI retention | Disable unused default DOM-building callbacks in both SAX modes | Regression tests; native probe: 20,000 retained nodes before, zero after |
| L2 attribute lifetime/copies | Non-owning pointer view, deleted const/nonconst temporary constructors, copy assignment restored | Compile-time assertions and aliasing/copy tests |
| L3 dependency guard | Scan nested CMake and package recipes; prune generated/vendor trees; tolerate source encodings | Ten unit tests on both hosts |
| L4 large mzIdentML values | HUGE parsing with explicit amplification limit 5 | Text and attribute over 10 MB; entity-amplification rejection |
| L5 diagnostics | Filename and context-local line/column error messages | Malformed/unsupported encoding tests; no global error handler |
| L6 warning handling | Test strict SAX2 warning-only parse continues | Relative namespace warning and successful completion |

An independent Codex review verified the complete 11-file correction diff and relevant callers, then confirmed that the exact committed diff matches its reviewed SHA-256. Kimi completed a separate follow-up on the same packet with no new concrete defects and confirmed each original correction. Its residual observations concern the documented scope of the guard and unexecuted Windows/Docker CI, rather than newly demonstrated product failures. No broad warning/error downgrade or Latin-1-as-UTF-8 shortcut was introduced.

See the separate exact-candidate Claude follow-up receipt for its final result. Interrupted earlier Claude invocations are not counted as completed reviews. Private reviewer stderr/reasoning is not published.

The earlier Codex and Kimi reviews found and verified fixes for document-vs-DTD traversal, foreign-namespace record selection, imzML namespace validation, legacy namespace-disabled compatibility, CI guard diagnostics, and the legacy DOM writer's software-version fallback; their phase reports remain attached. Remaining inherited writer business logic and malformed XL-MS array bounds limitations are explicitly disclosed in the migration summary.
