# Reviewer walkthrough

This walkthrough demonstrates an automatic acceptance, a duplicate, a
purchase order balance hold, an admin acceptance and an unreadable scan. It uses
the [hosted app](https://asa-invoice-review.onrender.com/) and
[Pack B](../tests/fixtures/demo_packs/B/invoice-demo-B.zip). Extract the ZIP so the
individual PDFs are ready to upload.

## Sign in

Use **Recruiter Admin** from the private reviewer handoff. That account can
complete every step below, including uploads and the manual review. To
demonstrate the two roles, optionally sign in as **Recruiter User** in a separate
browser session, use it for uploads, then switch to **Recruiter Admin** for review.

On the admin **Dashboard**, find **Purchase order balances**. The unused demo
orders `PO-DEMO-B-FULL`, `PO-DEMO-B-PARTIAL`, `PO-DEMO-B-AMBIG-A`,
`PO-DEMO-B-AMBIG-B` and `PO-DEMO-B-SCAN` each have ₹10,000 authorized.
Look for the expected available amounts before recording. An acceptance in this
shared workspace consumes the associated balance. The host may need to wake up
when first opened.

## 1. Accept a clean invoice

Open **Upload invoice**, choose
[01_clean_invoice.pdf](../tests/fixtures/demo_packs/B/01_clean_invoice.pdf) and click
**Upload & verify**. The run should progress through reading, extraction and
verification. Open **Source evidence** and point to the quote for the printed
payable. Expect **Accepted**, **PO commitment · Recorded**, and ₹10,000
committed on `PO-DEMO-B-FULL`.

Note the acceptance ID on the result. **Spreadsheet report** shows the status of
the separate publication job. After it shows **Published**, a reviewer with
Google Sheet access can search `AcceptedInvoices` for `INV-DEMO-B-FULL-01`
and match the acceptance ID in column A, the PO in F and the amount in H.
App accounts and Google Sheet sharing are managed separately. The backend uses
a Google service account to read procurement data and publish the report.

## 2. Block a duplicate

Upload [02_duplicate_invoice.pdf](../tests/fixtures/demo_packs/B/02_duplicate_invoice.pdf)
after step 1. It contains the same invoice bytes under another filename. Show
**Blocked duplicate** and **PO commitment · Not recorded**. If available to
your account, follow **Inspect prior accepted invoice**. The first acceptance
remains the only commitment on the order. The application also checks the
normalized vendor and invoice identity when a file is re-exported.

## 3. Compare an invoice with the remaining balance

1. Upload [03_partial_6000.pdf](../tests/fixtures/demo_packs/B/03_partial_6000.pdf).
   Expect ₹6,000 accepted for six hours on `PO-DEMO-B-PARTIAL`. Show ₹4,000
   and four hours left on that order.
2. Upload
   [04_partial_over_4500.pdf](../tests/fixtures/demo_packs/B/04_partial_over_4500.pdf).
   Expect **Needs review**. In **Validation checks → Remaining PO balance**,
   show that the requested ₹4,500 exceeds the remaining ₹4,000. The held
   invoice records no commitment.
3. If you want to verify the exact boundary after that example, upload
   [05_partial_remainder_4000.pdf](../tests/fixtures/demo_packs/B/05_partial_remainder_4000.pdf).
   It should accept the ₹4,000 remainder and bring the available balance to ₹0.

## 4. Resolve an ambiguous purchase order as admin

1. Upload
   [06_ambiguous_po.pdf](../tests/fixtures/demo_packs/B/06_ambiguous_po.pdf).
   Wait for **Needs review**. The original lists five hours of website design
   at ₹1,000 per hour and omits a PO number.
2. In the admin window, go to **Invoices**. Set **Status** to **Review queue**
   and search for `INV-DEMO-B-AMB-01`. Open it. The **Purchase order match**
   check should identify `PO-DEMO-B-AMBIG-A` and `PO-DEMO-B-AMBIG-B` as
   exact candidates.
3. Expand **Correct extraction & resolve PO**. Near the top, open
   **Purchase order selection** and choose `PO-DEMO-B-AMBIG-A`. For this
   synthetic example, treat that as the order the buyer confirmed. Leave the
   separate **PO reference** text field empty because no PO is printed.
4. In **Review reason**, enter the text below and click **Save & rerun checks**.

   > For this demo, the buyer confirmed PO-DEMO-B-AMBIG-A. The original bills five hours of website design at INR 1,000 per hour.

5. Once the checks pass, show **PO commitment · Not recorded**. In
   **Review actions → Decision reason**, enter the text below and click
   **Accept with reason**.

   > Confirmed the selected purchase order and verified the INR 5,000 amount.

6. Show **Accepted** and the new ₹5,000 commitment. Under
   **Extraction & review history → Saved revision**, inspect the admin
   correction and review reason. Order A has ₹5,000 remaining. This invoice
   uses its own order, separate from the partial order in step 3.

## 5. Handle an unreadable payable

Upload
[07_blurred_total.pdf](../tests/fixtures/demo_packs/B/07_blurred_total.pdf).
This PDF uses a raster scan. The payable is unreadable and the invoice should
stay in **Needs review** with no commitment. In the admin review queue, find
`INV-DEMO-B-SCAN-01` and open **Original document**. Enter the reason below
in **Review actions** and click **Request clearer invoice**.

> The payable total on page 1 is unreadable. Please provide a clearer copy.

The app records the request in the review history. The scan PO still has its
full ₹10,000 balance.

## Verify the result on the dashboard

Open **Dashboard → Purchase order balances**. After the main walkthrough, the
partial order shows ₹10,000 authorized, ₹6,000 committed and ₹4,000 available
unless you used the optional remainder invoice. The admin-resolved order shows
its own ₹5,000 commitment. Use the outcome counts and **Invoices** history to
trace each result. [Metric definitions](METRICS.md)

## Reruns and troubleshooting

- **The clean sample shows Blocked duplicate.** Open the earlier acceptance.
  If you need a fresh run, use an unused pack with its matching PO rows
  imported into the workspace.
- **The PO dropdown is missing.** Confirm the record is
  `INV-DEMO-B-AMB-01`, that you are signed in as admin, and that the invoice
  shows two exact candidates. The over-balance sample prints its own PO and
  remains on that order.
- **Extraction reports a provider error.** Use **Re-run verification** for
  the affected unaccepted submission once processing is available. A reused
  extraction is labeled **Using saved extraction** and the checks run again.
- **An acceptance is recorded and the report is pending.** Check the
  publication status separately. Retry and reconciliation guidance are in
  the [operations guide](OPERATIONS.md).

For an isolated workspace, an authorized operator can generate a new set of
invoice and PO identities, preview its reference changes, then apply them.

```sh
.venv/bin/python tools/generate_fixtures.py --pack REVIEW2
.venv/bin/python scripts/prepare_demo.py --packs REVIEW2
.venv/bin/python scripts/prepare_demo.py --packs REVIEW2 --apply
```

[Pack D's line-mapping example](../tests/fixtures/demo_packs/D/08_admin_line_review.pdf)
and the [varied layout samples](../tests/fixtures/layouts/README.md) give further
cases to try with their matching procurement references.
