# Combined-build acceptance checklist

**Future checks, not completed by preparing this package.** Member 3 runs these after merging; the team/owner provides final human acceptance. The assistant can help run/debug checks once the combined source and environment are available.

Record: merged commit, Python/dependencies, machine/RAM, data hashes, stock source, assessment dates, as-of date, test date and tester. Preserve logs/screenshots without publishing private records.

- [ ] Verify archive hashes and corrected CSV/database inputs against `MANIFEST.json` before launching. Confirm prepared/fact rows are 226,203; do not compare the old incremental fixture with the full dataset.
- [ ] Run `.\.venv\Scripts\python.exe -m pytest tests -q` on the merged version. The frozen checkpoint's saved result is 432 passed with one existing warning; investigate changes/failures rather than assuming the same count proves equivalence.
- [ ] Start the actual merged app, verify login/logout and all connected pages. Check desktop and intended demo viewport.
- [ ] On isolated copies, test valid sales upload, repeated upload and invalid upload. Repeats must not double-count; invalid uploads must not replace valid state. Record timings separately for upload processing and visible forecast completion.
- [ ] Connect the documented raw stock workbook. Confirm ambiguous/reused identifiers remain excluded and stale/future stock warnings behave correctly. Record dates so clock-dependent guards are understood.
- [ ] Activate the three-criterion workflow with the private backend CSV and explicit coverage. Inspect readiness reasons, approved equal-third labels, ranking and sensitivity downloads.
- [ ] Compare frontend tables and downloaded CSVs to backend results for the same inputs, at full precision. Check small values, N/A and undefined R². Do not infer equality from rounded screenshots.
- [ ] Independently hand-check sample forecast validation pairs and MAE/RMSE/MAPE/R² where defined; check refund numerator/denominator, normalized criteria and final MCA score. Use real eligible records; label synthetic edge-case fixtures separately.
- [ ] With the same corrected historical configuration, investigate any difference from prior 62 forecast SKUs/61 ranked SKUs. Do not enforce those counts when source mappings or dates differ legitimately.
- [ ] Test accepted repeat return/sales refreshes and connected stock refresh: audit events must show unresolved disputes were re-evaluated. Missing records from a partial upload must not erase earlier evidence. Use synthetic controlled cases for outcome transitions when actual records do not provide them.
- [ ] Test missing coverage and unresolved relevant evidence: affected rates/ranks remain unavailable, never default zero. Check refresh failure leaves no falsely valid MCA results.
- [ ] Restart/reload and change datasets; ensure persisted review history remains available and old derived outputs are invalidated correctly.
- [ ] Measure actual performance on the demo machine using isolated data, recording workload and elapsed time. Earlier benchmark figures do not certify a different combined build or device. Re-run benchmark scripts only after their documented private prerequisites are available.
- [ ] Record the received final TA approval of historical-period validation. Reflect accepted limitations in Chapter 4; do not claim varying refund sensitivity or business improvement from these tests alone.
- [ ] Team/owner accepts intended workflow and presentation after seeing the exact integrated version. Record unresolved limitations and final screenshots.

Until these checks are recorded, label the package an integration candidate, not a fully validated final system.
