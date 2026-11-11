Benchmark scope: gold labels cover ONLY legal questions that the court directly addresses in the judgment's reasoning and/or operative decision. Every gold issue must simultaneously (1) be inferable from situation, (2) concern a party's actual request or a legal determination the court must make, (3) be verifiable against the court's reasoning/decision when the Judge has access to the judgment, and (4) express a legal question, not a fact, a cited provision, or an already-announced outcome.

Apply these distinctions semantically, not by keyword bans:
- CORE: an independent, directly adjudicated legal question supported by situation. Only CORE issues may appear as standalone gold labels.
- SUPPORTING_FACT: a factual circumstance or subordinate consideration supporting a CORE issue. Integrate it into that issue's decisive fact where material; do not create a separate issue.
- IRRELEVANT: an unsupported, hypothetical, merely mentioned, ancillary, or unadjudicated legal question outside the actual dispute.
- DUPLICATE: the same legal question already covered by another CORE issue, even when phrased from a different perspective.

Exclude routine court fees, ordinary appeal rights, standard procedures, and ordinary aggravating/mitigating circumstances unless the situation and judgment establish a genuinely independent disputed request or a distinctive legal question requiring resolution. An allowed PROCEDURE opening does not make a routine procedural step a core issue. Do not reject an exceptional procedural dispute merely because its opening is procedural.

Examples of the intended scope:
- Divorce: dissolution of the marriage, custody, support, and common property ONLY when actually resolved. Domestic violence used solely to assess the marital relationship is a qualifying fact, not a separate liability issue without an independent request/decision.
- Criminal cases: the defendant's liability and compensation when directly adjudicated. Do not create a separate liability issue for a mentioned person whom the court does not examine. Ordinary sentencing factors qualify the liability/sentencing question rather than becoming standalone issues.
- Contract disputes: performance, payment, interest, damages, or validity when actually resolved. Do not generate questions from every clause, fact, or citation.

The Judge uses markdown to verify the scope of adjudication, NOT to supply new facts to the Generator. The Generator and blind discovery only have situation: propose questions supported by its facts and actual requests, without guessing the judgment. If a decisive fact exists only in markdown, record a material omission through situation_audit/situation_error; never require a gold issue whose facts cannot be inferred from situation. A verified situation_error=true does not itself invalidate otherwise correct, complete, situation-grounded issues.

Legal Relevance, Coverage, Grounding, and Format must all pass. Correct format alone is never sufficient. Classifications and scope judgments require semantic reasoning with evidence; exact quotation checks validate provenance, not the correctness of the legal assessment. Keep all source excerpts verbatim and provide concise auditable explanations, not chain-of-thought.
