# Synthetic MCA staging validation — October 21, 2026

The TA accepted the historical-period validation and equal-third policy, with limitations documented in Chapter 4. No further historical return-data search is required. This staging check fulfills the additional requested functional test; it is not empirical business evidence.

Eight explicitly synthetic SKUs have equal Sales Velocity and Forecasted Demand, 100 eligible ordered units each, and counted recorded refund quantities of 5, 10, 15, 20, 25, 30, 35 and 40. No original business files or operational databases are modified.

Expected refund rates are 5–40%. The cost-normalized contribution is `(40 - rate) / 35`, descending from 1 to 0. Both constant volume criteria normalize to 0.5. With equal thirds, the expected score is `(0.5 + 0.5 + normalized_return_rate) / 3`, decreasing from 2/3 to 1/3. The penalty is a lower contribution; normalized values are not negative numbers.

All eight SKUs passed independent formula checks through the connected prescriptive pipeline, SQLite persisted outputs, eight review audit events, repeated stock refresh, the production Product Prioritization page under Streamlit AppTest, and the actual CSV download payload. No fabricated refund observations enter the historical assessment.

Reproduce: `python qa/synthetic_mca_staging.py`. Automated regression: `tests/test_synthetic_mca_staging.py`. Evidence: `validation_outputs/synthetic_mca/summary.json` and `synthetic_rankings.csv`.

This is local component integration with controlled inputs, not a load benchmark or acceptance of Member 3's merged frontend. Follow `member3_acceptance_checklist.md` on the intended demo machine.

## Manuscript wording

Historical assessments at the December 2025, January 2026 and February 2026 endpoints showed non-negligible forecast variation. Pearson correlations between Sales Velocity and Forecasted Demand were 0.8707, 0.7660 and 0.7058; Spearman correlations were 0.4573, 0.8473 and 0.7940. Respectively, 11, 6 and 6 product ranks differed from Sales Velocity-only ordering. These differences demonstrate calculation behavior, not improved business outcomes.

March's maximum forecast criterion was approximately 1.26 × 10^-25 units and therefore practically near zero, despite mathematically computable correlation. Recorded return/refund rates remained zero among eligible products across all four assessments. These source coverage and product-matching constraints limit empirical evaluation of three varying criteria. Equal-third weights were retained following TA approval.

A separate synthetic staging test confirmed that increasing recorded refund rates lowers the cost-normalized contribution and MCA score when the other criteria are equal. These synthetic findings validate software behavior and are not presented as observed shop performance.
