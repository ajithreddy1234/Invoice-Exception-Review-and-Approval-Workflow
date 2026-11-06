# Where AI is used

At runtime, PDF text extraction or local Tesseract OCR produces page text.
Gemini receives that text as untrusted document content and proposes a structured
candidate: invoice fields, line items, page numbers, source quotes and uncertainty.
It receives neither the expected fixture outcome nor PO budgets as answers to copy.

Pydantic validates the shape. Source checks verify quoted text/value support,
payable labels, identifiers and contradictions. Python evaluates nine procurement
checks against versioned references and current commitments. SQL rechecks critical
financial/reference/identity constraints under locks before acceptance. The LLM
does not approve, assign roles, edit references or publish financial decisions.

Source instructions inside an invoice cannot authorize workflow actions. A missing
or blurred value remains unresolved, and a provider error cannot become an acceptance.
Model confidence is not treated as an authorization signal.

One bounded retry handles supported transient errors. Matching original provider
extraction can be reused for the same uploader/bytes and matching versions within
seven days; its source hash, evidence and every current rule still run again.
The UI labels saved extraction. Admin-corrected evidence cannot seed reuse.

AI assistance was also used during development to write and review implementation,
generate synthetic inputs and investigate failures. Regression/native tests and
explicitly labelled live provider checks are the evidence, not a model's rating.
New layout tests record their authoring engine. A simulated photo is not a claimed
real phone capture or a proprietary Zoho/Stripe export.
