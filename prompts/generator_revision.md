This is a revision/rebuttal turn. Use only permitted situation data and the explicit history of this case. The Judge can be wrong. For every current feedback_id, return exactly one responses_to_feedback entry with decision ACCEPT, CONTEST, or PARTIALLY_ACCEPT, a concise auditable explanation, and verbatim situation_evidence_quotes. CONTEST and PARTIALLY_ACCEPT require supporting evidence. If allow_contest=false, contesting has been disabled by configuration. Keep issues, their text components, and explanations in Vietnamese.

Feedback contains error_code, action, issue_ids, and verified situation excerpts. Reread situation to decide how to respond:
- INVALID_FORMAT: check the three components, allowed opening, component order, and metadata alignment.
- UNSUPPORTED_FACT: remove or revise unsupported details.
- WRONG_LIABILITY: check whether situation supports the selected liability type.
- MISSING_CORE_ISSUE: identify a core issue supported by the quoted situation evidence.
- DUPLICATE / NON_ATOMIC: assess semantic duplication and whether questions can be evaluated independently.
- LOW_RELEVANCE: reassess relevance to the actual questions requiring resolution.
- PREMATURE_CONCLUSION: express a question requiring legal resolution instead of asserting its answer.
- SUPPORTING_FACT: integrate the supported material circumstance into the related core issue's decisive fact where appropriate, and remove its standalone issue.
- ANCILLARY_ISSUE / OUT_OF_SCOPE: reassess whether situation establishes a necessary independent legal determination or a distinctive procedural question, instead of an ordinary ancillary matter or a merely mentioned person/act. An express dispute between parties is not required for CORE status.
- UNSUPPORTED_ISSUE: remove or contest a legal question lacking sufficient support in situation; a fact's presence alone does not establish an independent legal issue.

Revise only issues that need revision. Preserve issue_id for retained issues and assign new IDs when adding issues. ACCEPT must result in a corresponding correction or explain why the current version already satisfies the feedback. Do not treat feedback as new facts, and do not add facts absent from situation. Return the ENTIRE current issue list, including unchanged issues.

Apply the same shared definitions, all five CORE criteria, and the independence removal test to the revised list. Retain only CORE_ISSUE candidates with importance=CORE. A supporting fact can be true and legally relevant without being an independent issue. Preserve the Vietnamese noun-phrase format; never replace labels with questions, legal analysis, or conclusions.
