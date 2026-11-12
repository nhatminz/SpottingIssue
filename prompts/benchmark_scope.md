Shared definitions: Legal Issue and Legal Issue Spotting

A Legal Issue is a specific legal question arising from legally significant facts of a case that requires considering or applying law to determine rights, duties, liability, legal validity, or the appropriate legal disposition.

Legal Issue Spotting is the process of identifying, distinguishing, and selecting legal questions that actually arise from the situation. Listing facts, potentially relevant provisions, or steps in legal analysis is not issue spotting. This task performs the Issue step of IRAC, not the Application or Conclusion steps. A question is the underlying meaning; the benchmark representation remains a Vietnamese noun phrase, never an interrogative sentence or a predicted outcome.

These definitions synthesize legal-writing guidance from the American Bar Association, Australian National University, Monash University, and Suffolk University Law School. The following CORE-only scope is a benchmark-specific operational restriction, not a claim that all academic issue spotting excludes sub-issues.

Benchmark scope: gold labels cover ONLY Core Legal Issues arising from situation, tied to the requested legal disposition or a legal determination necessary to it, and directly resolved in substance by the court's reasoning and/or operative decision. Each gold issue must satisfy ALL FIVE criteria:
1. Legal Question: express a specific legal question requiring resolution, rather than merely describing an event, fact, or provision.
2. Fact Grounding: be inferable from situation, including the decisive circumstances that give rise to the question.
3. Judicial Relevance: fall within the court's direct substantive adjudication, verifiable against the judgment by the Judge in Stage B.
4. Independence: identify a distinct legal question, not merely a condition, legal premise, evidentiary assessment, or reasoning step supporting another issue.
5. Non-conclusiveness: identify what must be determined without asserting the final legal answer or who wins.

An explicit disagreement between parties is NOT required. An uncontested legal question that the court must independently determine to decide the case can still be CORE. Distinguish such a necessary independent determination from a routine procedural check or a premise already covered by another issue. Before viewing the judgment, the Generator and Stage A assess the likely scope using situation only; they must not pretend that judicial confirmation is already available.

Apply these distinctions semantically, not by keyword bans:
- CORE_ISSUE: an independent, directly adjudicated legal question supported by situation. Keep as a standalone gold label; its existing JSON classification is CORE.
- SUPPORTING_FACT: a factual circumstance or subordinate consideration supporting a CORE issue. Integrate it into that issue's decisive fact where material; do not create a separate issue.
- ROUTINE_PROCEDURAL: an ordinary procedural check without a distinctive legal question requiring independent resolution. Exclude as a standalone gold issue; in the existing review schema use classification=IRRELEVANT with error_code=ANCILLARY_ISSUE. Do not introduce a new classification enum.
- IRRELEVANT: an unsupported, hypothetical, merely mentioned, ancillary, or unadjudicated legal question outside the case's actual adjudicative scope.
- DUPLICATE: the same legal question already covered by another CORE issue, even when phrased from a different perspective.

Exclude routine court fees, ordinary appeal rights, standard procedures, and ordinary aggravating/mitigating circumstances unless situation and judgment establish a genuinely independent legal determination or a distinctive question requiring resolution. An allowed PROCEDURE opening does not make a routine procedural step a core issue. Exceptional procedural questions may be CORE when the court actually needs to resolve them independently; they do not require an express objection by a party. A supporting premise does not become independent merely because the court discusses it in its reasoning.

Independence removal test: if this issue were removed, would the list lose a distinct legal question that the court actually needed to resolve? If another issue already captures the question and this item adds only a premise, condition, supporting fact, or reasoning step, integrate material qualifiers and remove the standalone item. If it repeats a covered question, merge or remove the duplicate. If an independent question would be lost, retain it when the other four criteria also pass. Reassess both precision (no extra issues) and coverage (no missing core issues).

Examples of the intended scope:
- Divorce: dissolution of the marriage, custody, support, and common property ONLY when actually resolved. Domestic violence used solely to assess the marital relationship is a qualifying fact, not a separate liability issue without an independent request/decision.
- Criminal cases: the defendant's liability and compensation when directly adjudicated. Do not create a separate liability issue for a mentioned person whom the court does not examine. Ordinary sentencing factors qualify the liability/sentencing question rather than becoming standalone issues.
- Contract disputes: performance, payment, interest, damages, or validity when actually resolved. Do not generate questions from every clause, fact, or citation.

The Judge uses markdown to verify the scope of adjudication, NOT to supply new facts to the Generator. The Generator and blind discovery only have situation: propose questions supported by its facts and actual requests, without guessing the judgment. If a decisive fact exists only in markdown, record a material omission through situation_audit/situation_error; never require a gold issue whose facts cannot be inferred from situation. A verified situation_error=true does not itself invalidate otherwise correct, complete, situation-grounded issues.

Legal Relevance, Coverage, Grounding, and Format must all pass. Correct format alone is never sufficient. Classifications and scope judgments require semantic reasoning with evidence; exact quotation checks validate provenance, not the correctness of the legal assessment. Keep all source excerpts verbatim and provide concise auditable explanations, not chain-of-thought.

Reference guidance for these definitions (context, not additional case evidence; do not fetch these pages during inference):
- American Bar Association, case briefing: https://www.americanbar.org/groups/law_students/resources/student-lawyer/student-essentials/guide-to-case-briefing-in-law-school/
- Australian National University, IRAC/HIRAC: https://www.anu.edu.au/students/academic-skills/writing-assessment/other-assessments/writing-in-law
- Monash University, identifying specific legal issues rather than factual problems: https://www.monash.edu/student-academic-success/excel-at-writing/annotated-assessment-samples/law/law-legal-problem-solving/issue-identify-and-state-the-issues
- Suffolk University Law School, issue spotting and issue statements: https://lawguides.suffolk.edu/research-toolkit/researchplan
