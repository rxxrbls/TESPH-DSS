# Member 1 data dictionary

This summary is based on the validated workbook
[`final_outputs/member1_data_dictionary.xlsx`](../final_outputs/member1_data_dictionary.xlsx),
which remains the authoritative, complete field-level dictionary for prepared
transactions, the fact table, and every dimension.

## Field lineage

- **Source**: a value supplied directly by a Shopee export and preserved when available.
- **Cleaned Source**: the same business value after conservative technical standardization (for example whitespace normalization or safe type conversion); it is not an invented replacement.
- **Derived**: a value calculated from source/cleaned-source fields, such as `product_key`, `year_month`, or a status flag.

The Excel dictionary uses only the explicit lineage values `Source`, `Cleaned
Source`, and `Derived`. The `Shopee_Source_Fields` sheet lists the **60 original
Shopee fields** as `Source`; the seven final-table sheets distinguish preserved
source values, conservatively standardized source values, and derived fields.

## Original Shopee export fields

All 84 raw Shopee workbooks were verified to use the same **60-field** source
schema. The table below contains those 60 fields—no ETL provenance or analytical
fields are counted as original Shopee fields.

“Required” below means required to process the approved historical transaction
pipeline, not that every cell must be populated. A present required column may
still contain missing values, which validation reports separately. All other
fields are optional for ingestion and are preserved when available.

| Field | Meaning | Type | Required/Optional | Notes |
|---|---|---|---|---|
| Order ID | Shopee order identifier | Text | Required | Repetition alone is not a duplicate; an order may have multiple lines |
| Order Status | Order lifecycle status | Text | Optional | Examples: Completed, Cancelled, Order Received |
| Hot Listing | Hot-listing indicator | Text | Optional | Y/N |
| Cancel reason | Cancellation explanation | Text | Optional | Blank for non-cancelled orders |
| Return / Refund Status | Return/refund workflow status | Text | Optional | Used with returned quantity for derived return status |
| Tracking Number* | Shipment tracking identifier | Text | Optional | Identifier, not a measure |
| Shipping Option | Shipping service | Text | Optional | |
| Shipment Method | Fulfilment handoff method | Text | Optional | Examples: Drop-off, pickup |
| Estimated Ship Out Date | Expected ship-out timestamp | Datetime | Optional | Datetime-compatible when present |
| Ship Time | Actual ship timestamp | Datetime | Optional | Datetime-compatible when present |
| Order Creation Date | Transaction creation timestamp | Datetime | Required | Drives the analytical calendar fields |
| Order Paid Time | Payment timestamp | Datetime | Optional | Datetime-compatible when present |
| Parent SKU Reference No. | Seller parent-level SKU | Text | Optional | Missing in 226,202 rows (99.9987%); preserved when available |
| Product Name | Shopee product listing name | Text | Required | Used with variation to derive the stable product key |
| SKU Reference No. | Seller variation/item SKU | Text | Optional | Missing in 225,372 rows (99.6318%); preserved when available |
| Variation Name | Product variation label | Text | Optional | Missing variation is represented in deterministic key generation |
| Original Price | Original unit/list price | Numeric | Optional | Monetary sign is preserved |
| Deal Price | Deal unit price | Numeric | Optional | Monetary sign is preserved |
| Quantity | Quantity sold on the transaction line | Integer-compatible | Required | Missing values are reported, never automatically changed to zero |
| Returned quantity | Quantity returned on the transaction line | Integer-compatible | Optional | Dictionary source spelling uses lowercase “quantity” |
| Total Buyer Payment | Total paid by buyer | Numeric | Optional | Monetary sign is preserved |
| Total Discount(PHP) | Total PHP discount | Numeric | Optional | Monetary sign is preserved |
| Price Discount(from Seller)(PHP) | Seller-funded PHP price discount | Numeric | Optional | Monetary sign is preserved |
| Shopee Rebate(PHP) | Shopee-funded PHP rebate | Numeric | Optional | Monetary sign is preserved |
| SKU Total Weight | Transaction-line SKU weight | Numeric | Optional | |
| Number of Items in Order | Total item count for order | Integer-compatible | Optional | |
| Order Total Weight | Total order weight | Numeric | Optional | |
| Seller Voucher(PHP) | Seller-funded voucher amount | Numeric | Optional | Monetary sign is preserved |
| Coin Cashback Voucher Amount Sponsored by Seller | Seller-sponsored coin cashback | Numeric | Optional | Monetary sign is preserved |
| Shopee Voucher(PHP) | Shopee-funded voucher amount | Numeric | Optional | Monetary sign is preserved |
| Bundle Deals Indicator(Y/N) | Bundle-deal indicator | Text | Optional | Y/N |
| Shopee Bundle Discount(PHP) | Shopee-funded bundle discount | Numeric | Optional | Monetary sign is preserved |
| Seller Bundle Discount(PHP) | Seller-funded bundle discount | Numeric | Optional | Monetary sign is preserved |
| Shopee Coins Offset(PHP) | Coins offset amount | Numeric | Optional | Monetary sign is preserved |
| Credit Card Discount Total(PHP) | Credit-card discount | Numeric | Optional | Monetary sign is preserved |
| Products' Price Paid by Buyer (PHP) | Product portion paid by buyer | Numeric | Optional | Monetary sign is preserved |
| Buyer Paid Shipping Fee | Shipping fee paid by buyer | Numeric | Optional | Monetary sign is preserved |
| Shipping Rebate Estimate | Estimated shipping rebate | Numeric | Optional | Monetary sign is preserved |
| Reverse Shipping Fee | Return/reverse shipping fee | Numeric | Optional | Monetary sign is preserved |
| Service Fee | Shopee service fee | Numeric | Optional | Monetary sign is preserved |
| Grand Total | Order grand total | Numeric | Optional | Monetary sign is preserved |
| Estimated Shipping Fee | Estimated shipping fee | Numeric | Optional | Monetary sign is preserved |
| Username (Buyer) | Buyer username | Text | Optional | Potentially sensitive source attribute |
| Receiver Name | Masked receiver name | Text | Optional | Potentially sensitive source attribute |
| Phone Number | Masked receiver phone | Text | Optional | Identifier; retain as text |
| Delivery Address | Masked delivery address | Text | Optional | Potentially sensitive source attribute |
| Town | Delivery town | Text | Optional | |
| District | Delivery district | Text | Optional | |
| City | Delivery city | Text | Optional | |
| Province | Delivery province/region | Text | Optional | |
| Country | Delivery country code | Text | Optional | Observed value: PH |
| Zip Code | Delivery postal code | Text | Optional | Identifier; leading zeros must not be treated as a measure |
| Remark from buyer | Buyer-entered order remark | Text | Optional | |
| Order Complete Time | Completion timestamp | Datetime | Optional | Datetime-compatible when present |
| Note | Seller/order note | Text | Optional | |
| Invoice request type | Invoice request classification | Text | Optional | |
| Invoice type | Personal/company invoice classification | Text | Optional | |
| Name | Masked invoice name | Text | Optional | Potentially sensitive source attribute |
| Business number | Masked invoice business number | Text | Optional | Identifier; retain as text |
| Address | Masked invoice address | Text | Optional | Potentially sensitive source attribute |

## SKU limitations

`Parent SKU Reference No.` exists in the source schema but is missing in **226,202
rows (99.9987%)**. `SKU Reference No.` also exists but is missing in **225,372
rows (99.6318%)**. Both fields are preserved whenever supplied, but neither is
suitable as the sole historical product identifier. The finalized pipeline uses
a deterministic `product_key` derived from standardized product and variation
values and retains the original names for traceability.

`product_key` is the stable internal product/variation relationship key. Its
technical value does not need to be shown to end users; human-facing dashboards
and reports should primarily display `final_base_product_name`. Shopee SKU values
remain available for traceability where supplied, but their high missingness
makes them unsuitable as the sole historical identifier.

## Final analytical tables

The workbook contains complete sheets for `Prepared_Transactions`, `Fact_Sales`,
`Dim_Product`, `Dim_Date`, `Dim_Order`, `Dim_Shipping`, and `Dim_Payment`, including
lineage, types, examples, and notes. Consult those sheets rather than inferring
field definitions from this source-focused summary.
