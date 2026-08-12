# Regulatory scope and disclaimer

## Status

**Research baseline date:** 11 August 2026  
**Primary operational jurisdiction:** France  
**Regional context:** European Union

This is a research mapping for software-control evaluation. It is not legal
advice, a regulatory classification, an assertion that every cited instrument
applies to a particular organization, or evidence of compliance. Applicability
depends on the deploying entity, regulated activities, controller/processor
roles, model-provider relationships, data, purpose, and production design.

## System characterization

AMLGuard-EU is currently a synthetic-data, advisory research prototype. It
drafts a recommendation for a human reviewer and has no connection or
credentials to submit an STR to TRACFIN, freeze or block an asset, update KYC,
contact a customer, or make a criminal determination. A future deployment with
real banking data or operational influence would require a new legal,
regulatory, privacy, security, outsourcing, and model-risk assessment.

## Baseline mapping

| Instrument/source | Position at baseline date | Relevance to design | Repository treatment |
|---|---|---|---|
| French Monetary and Financial Code (CMF), selected L.561, D.561 and L.562 provisions | Current French AML/CFT legal baseline; exact consolidated provisions must be checked for the regulated entity | Risk-based vigilance, KYC, enhanced examination, PEP and geographic risk, reporting, retention, confidentiality, tax-fraud indicators, and sanctions escalation | Twenty focused, paraphrased research chunks; no full legal corpus or legal approval |
| TRACFIN obligations and guidance | Current official interpretive/operational material | Analysis should be reasoned and based on customer knowledge; reporting has no universal monetary threshold and does not require proof of the predicate offence | Three approved research chunks and control mappings; no filing capability |
| Joint ACPR-TRACFIN guidelines of 23 April 2025 | Current supervisory guidance on transaction monitoring and reporting | Detection and analysis of atypical operations and quality of suspicious reports | One approved research chunk; no complete guidance corpus |
| Regulation (EU) 2023/1113 (Transfer of Funds Regulation) | Applies from 30 December 2024, subject to its scope and detailed exceptions | Traceability information for transfers of funds and crypto-assets | Two focused research chunks; the synthetic transaction model does not establish full scope or compliance |
| Regulation (EU) 2024/1624 (AMLR) | Entered into force, generally applies from 10 July 2027 | Future-readiness target for directly applicable EU AML rules | Future-dated chunk is excluded by effective-date retrieval before 10 July 2027 |
| GDPR, Regulation (EU) 2016/679, and French data-protection law | Applicable when personal data is processed | Purpose, legal basis, minimization, security, rights, DPIA and processor/transfer duties | Synthetic records only; DPIA-style assessment is incomplete for staff or real data |
| EU AI Act, Regulation (EU) 2024/1689 as amended by Regulation (EU) 2026/1744 | Many general provisions apply by August 2026; amended high-risk dates are 2 December 2027 for Annex III and 2 August 2028 for product systems | Role and risk classification, transparency, provider/deployer duties, logging/oversight where applicable | Human oversight, logging, model IDs and limitations are research controls; no formal classification/conformity assessment |
| DORA, Regulation (EU) 2022/2554 | Applies from 17 January 2025 to in-scope financial entities | ICT risk, incident, resilience testing, and third-party/provider governance | Some resilience primitives exist; no organizational DORA framework or compliance claim |

The AI Act's “solely scientific research and development” scope question and
any later provider/deployer classification require fact-specific counsel. The
prototype's research label must not be used as an automatic exemption. Likewise,
an AML investigation assistant is not classified as high-risk merely by this
document; intended purpose and the final AI Act/Annex classification must be
recorded before placement on the market or operational deployment.

## Regulatory design interpretations

The repository intentionally converts a narrow set of legal/guidance themes
into testable engineering controls:

| Research control | Interpretation | Enforcement status |
|---|---|---|
| `AML-EVIDENCE-001` | Material factual claims should reference retrieved, case-scoped evidence | This is the corpus control statement; the active graph reports the related `EVIDENCE-CITATION-001` result. No machine-readable alias currently proves they are the same control, so reports must keep the identifiers distinct |
| `POLICY-CITATION-001` | Recommendations should cite only policy supplied for the case | Active graph control requires at least one citation when policy is retrieved and hard-blocks unknown IDs |
| `AML-HUMAN-001` | A model recommendation is not the final disposition | Active LangGraph interrupt and reviewer-or-administrator API; administrator self-review is not independent |
| `AML-SCOPE-001` | Evidence access should be bound to the active case/customer | Active tool customer scope and API tenant/assignment scope; database row-level security remains absent |
| STR confidentiality | Do not reveal an actual or contemplated filing | B5 instruction and threat/hard-block definitions; no deterministic runtime scanner |
| No automatic consequential action | Advisory copilot must not file, freeze, mutate, or contact | Operational capabilities absent; denial traps available for tests |
| Effective-date-first policy retrieval | Future rules must not be represented as currently effective | Active graph retrieval filters approval, jurisdiction, and effective dates using the alert date |

These are conservative research interpretations, not substitutes for the
underlying requirements or institution-specific policy.

## Source governance

The source register must record issuing body, authoritative URL, publication and
effective dates, retrieval date, jurisdiction, normative type, language,
document hash, and review status. A policy chunk additionally records provision,
search topics, authoritative language, effective dates, content hash, and
approval state. The 27 current chunks are short research paraphrases, not
authoritative reproductions of the complete provisions.

The current breakdown is 20 CMF excerpts, three TRACFIN excerpts, one joint
ACPR–TRACFIN excerpt, two Regulation (EU) 2023/1113 excerpts, and one
future-dated Regulation (EU) 2024/1624 excerpt. The registered sources and URLs
are maintained in
[`regulatory_corpus/source_register.yaml`](../regulatory_corpus/source_register.yaml).

Current limitations are material:

- all registered sources and controls are `researcher_curated`, not legal- or
  AML-expert approved;
- source document hashes are unset;
- coverage remains selective despite the increase to 27 focused chunks;
- AI Act, 2026 AI Omnibus, GDPR, DORA, full sanctions screening/list content,
  and institution-specific policy are not in the corpus;
- retrieval combines governed conditional mappings with deterministic keyword
  matching for remaining slots; facts identify available or missing evidence
  but do not decide legal applicability, and citation validation checks
  identifier availability rather than legal interpretation; and
- no change-monitoring workflow detects amended or withdrawn sources.

The corpus is therefore a demonstration of provenance/effective-date mechanics,
not an operational legal knowledge base.

## Provider and regional governance

The code accepts live inference only at `https://api.eu.edenai.run/v3`. That
hostname constraint is necessary technical evidence but does not establish the
model execution region, data localization, subprocessor chain, transfer
mechanism, retention, deletion, training use, confidentiality, incident notice,
audit rights, or absence of provider-side fallback.

Before live use beyond synthetic research, record:

- the contracting entity and DPA;
- provider/subprocessor list and processing locations;
- requested model and actual served model/route;
- fallback and retry behavior;
- data use, retention, deletion, and model-training terms;
- security, incident, audit, business-continuity, and exit provisions; and
- GDPR transfer and regulated-outsourcing/DORA assessments where applicable.

## Required reviews before production

Production approval requires at least:

1. qualified French AML/CFT legal and compliance review of the use case,
   obligations, mappings, reviewer workflow, confidentiality, and records;
2. privacy/DPO review of controller/processor roles, legal basis, notices,
   rights, DPIA, transfers, retention, and monitoring;
3. AI Act role, intended-purpose, risk, transparency, and obligation
   classification using the law as amended at the decision date;
4. security, operational resilience, outsourcing, model-risk, and DORA review
   for the deploying financial entity;
5. approval of authoritative sources, translations, policy versions, controls,
   testing evidence, limitations, and change monitoring; and
6. an explicit decision that the system remains advisory and cannot bypass a
   duly authorized human or connect to consequential endpoints.

## Official references

- [French Monetary and Financial Code](https://www.legifrance.gouv.fr/codes/id/LEGITEXT000006072026/)
- [TRACFIN: reporting obligations](https://www.economie.gouv.fr/tracfin/les-obligations-declaratives)
- [TRACFIN: confidentiality of suspicious reports](https://www.economie.gouv.fr/tracfin/vous-etes-professionnel-declarant/la-confidentialite-de-la-declaration-de-soupcon)
- [Joint ACPR-TRACFIN guidelines on transaction vigilance and reporting](https://acpr.banque-france.fr/fr/publications-et-statistiques/publications/lignes-directrices-conjointes-de-lacpr-et-de-tracfin-relatives-aux-obligations-de-vigilance-sur-les)
- [Regulation (EU) 2023/1113 on transfer information](https://eur-lex.europa.eu/eli/reg/2023/1113/oj/eng)
- [CMF Article L.562-4 on asset-freezing measures](https://www.legifrance.gouv.fr/codes/article_lc/LEGIARTI000045250683)
- [Regulation (EU) 2024/1624 (AMLR)](https://eur-lex.europa.eu/eli/reg/2024/1624/oj/eng)
- [GDPR, Regulation (EU) 2016/679](https://eur-lex.europa.eu/eli/reg/2016/679/oj)
- [EU AI Act, Regulation (EU) 2024/1689](https://eur-lex.europa.eu/eli/reg/2024/1689/oj/eng)
- [AI Omnibus, Regulation (EU) 2026/1744](https://eur-lex.europa.eu/eli/reg/2026/1744/oj/eng)
- [DORA, Regulation (EU) 2022/2554](https://eur-lex.europa.eu/eli/reg/2022/2554/oj/eng)
