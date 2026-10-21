> Current policy update (October 21): equal-third baseline weights and reporting the historical baseline with its limitations are approved. Expanded-period checks and final validation remain required. Earlier pending-weight statements below describe the previous checkpoint. This is still a backup branch, not an issued handoff.

﻿# Return/refund coverage record

Updated October 20, 2026 using the client/leader statements, supplied Export History screenshots, and the cleaned handoff archive.

| Item | Recorded value |
| --- | --- |
| Historical sales coverage | May 22, 2020–April 24, 2026 |
| Provisional MCA order-date period | May 22, 2020–April 24, 2026, inclusive |
| Selected return/request-date coverage | May 1, 2020–April 24, 2026, inclusive |
| Export requests | October 15–16, 2026; client-confirmed |
| Latest export request visible | October 16, 2026, 14:51:35, for the April 2026 report |
| Timezone | Not displayed; unspecified. Do not convert or assume a timezone |
| April report | Order.return_refund.20260401_20260424.xls; user confirms April 24 was the original data endpoint |
| Other monthly reports | Full calendar months, according to the client |
| Empty files | May 2020, September 2025, October 2025, March 2026; present, header-only |
| Date filter | Appears to be Return Creation Time/request date, supported by source-month alignment |

Exact per-file times are optional provenance, not a prerequisite for technical implementation. No new export or manual timestamp transcription is required to record this date-level scope. Request Time documents when the report was requested; it does not prove a simultaneous final-status update cutoff for every record.

## Checked evidence

The supplied ZIP contains 3,705 request/product lines and 2,839 distinct Return IDs, plus a manifest of 72 monthly workbooks. All populated lines fall in their recorded source month and match existing sales/product identities. The original monthly workbooks are not included, so their bytes and selected duplicate-download versions cannot be independently verified from this ZIP.

Export History shows repeated requests for some report months. Do not concatenate repeated downloads. The supplied cleaned dataset is the input snapshot; later replacement evidence must be matched explicitly to its source records.

Observed request dates span June 2, 2020–April 22, 2026. These observed extrema do not replace the selected filter boundaries. The earlier statement that April covered April 30 is superseded by the screenshot and user confirmation.

Archive SHA-256: c7468d9b38805981122600e94ba4e105a3c44459aa5a17306e0082a9fb0f10ff.

## Assessment interpretation

The provisional rate measures recorded refunded quantities for eligible orders placed in the order-date period, considering only requests created within the supplied request-date coverage. It is not a lifetime return rate. An April 24 order may have a later request absent from these files. Exporting in October does not add requests created after April 24.

Retain observed source statuses. Blank completion dates remain blank, including the 29 refunded requests without a completion time. Do not infer a dispute outcome from its label or invent a physical-return interpretation for Refund Only quantities.

An empty monthly request export is not a missing file. Unknown coverage is not zero. A zero rate requires confirmed selected-window coverage, a positive matched-order denominator, and no unresolved relevant evidence.

## Approval and remaining decision

TA Option 3 authorizes implementation/testing. Both weight scenarios remain provisional. See [three-criterion implementation and TA results](three_criterion_implementation_results.md) for actual eligibility, correlation, sensitivity, validation and remaining decisions. No exact export-time question remains outstanding.
