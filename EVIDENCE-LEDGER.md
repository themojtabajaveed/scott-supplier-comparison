# Evidence ledger (offline reviewer tool)

An inspection aid for saved evidence, not a product feature, shipping-rule model or completion claim. The examples
below read the invented demo recordings bundled in `demo/recordings/`.

```
python -S scripts/evidence_ledger.py demo/recordings/demo_mill_one-result.json
python -S scripts/evidence_ledger.py demo/recordings/*-result.json --output my-ledger.json
```

The tool reads saved result files and prints JSON. With `--output` it writes a new file instead. It refuses to overwrite an existing file or an input, and it makes no network, model or browser call. The code is `scout/evidence_ledger.py` and the tests are `tests/test_evidence_ledger.py`.

For the delivery charge, free-delivery threshold, delivery time and delivery area claims in each saved row, it shows:

- **One observation per saved claim entry.** Identical duplicates are kept, in their saved order. Claims dropped before the result was saved cannot be recovered.
- **Where each quote occurs in the saved page text.** It lists every exact occurrence as code-point offsets (start inclusive, end exclusive) and never picks one of several. It also shows how the saved text was matched: by the exact address, by the address without its `#fragment` when that is unique, or as several possible texts. A different query string is a different address. The status is one of: located once, repeated, quote not found, source text not saved, empty quote, or more than one possible saved text.
- **`same_quote_span` groups.** These are claims whose quotes each occur exactly once, in the same saved text, at the same span. That is evidence the words were quoted from one place, never that they form one shipping rule.
- **Money tokens with an explicit currency marker** (`money_coverage` in the output lists the recognised forms and the omissions), with exact spans and lines. No roles are assigned. The saved text is shown exactly as saved. Some older store-data texts contain a £ that Scott's own formatting added before 2 November 2026; the data itself states no currency.
- **A SHA-256 of each saved text.** It is not a hash of the original capture. A read date appears only if the result records an explicit `read_date`. Another date, such as `as_of`, is kept under its own label in `recorded_metadata` and is not treated as the read date. Folder names such as `live-30oct` are labels, not capture times.
- **Missing source addresses never match.** A claim or saved text with an absent, empty, whitespace-only or fragment-only address is kept, but it gets `source_identity_missing` (or `source_identity: missing` for a saved text). It is never given a source, location or shared-span group (correction v1.5.1).

It does not claim any of the following: rule membership, applicability, option identity, footnote coverage, source currentness, completeness, net or gross tax or weight, that "free" means a zero total, eligibility, delivered totals, ranking, or buyer validation.
