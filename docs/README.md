# docs

All project documentation, organized by document purpose and lifecycle. Code-local READMEs (`gui/`, `config/`, `Arduino_Sketches/`, `tests/`, etc.) stay beside the code they describe.

| Folder | Contents |
|---|---|
| [`architecture/`](architecture/README.md) | How the current system is built: GUI, firmware designs and implementation notes. |
| [`specifications/`](specifications/README.md) | Behavior contracts: main app, GUI tabs, pressure map, force calibration. |
| [`plans/`](plans/README.md) | Proposed, in-progress, or hardware-pending plans (features, refactoring, firmware, testing). |
| [`testing/`](testing/README.md) | Test and benchmark evidence: results, benchmarks, datasets (raw data, figures). |
| [`reports/`](reports/README.md) | Reviews, diagnoses, and exported formal reports (PDF, DOCX). |
| [`guides/`](guides/README.md) | User and operator guides, plus the heatmap parameter workbook. |
| [`history/`](history/README.md) | Completed work: completion reports, refactoring log, completed and superseded plans. |

## Where does a new document go?

- Describes how something is built now: `architecture/`.
- Defines required behavior: `specifications/`.
- Proposes or tracks unfinished work: `plans/`. When finished, move it to `history/completed-plans/` and add a status note at the top.
- Records measurements or test outcomes: `testing/results/` or `testing/benchmarks/`; raw CSV/JSON/figures live beside them.
- Reviews, diagnoses, or exported deliverables: `reports/`.
- Tells a user how to do something: `guides/`.

Naming: use `<SUBJECT>_<TYPE>.md`; put dates in generated artifact names (for example `TestBoard_7953_Channel11_Report_2026-10-09.pdf`).
