# Acceptable Use Policy (AUP) · 可接受使用政策

_Last updated: 2026-06-24_

This Acceptable Use Policy governs the responsible use of **Lens (聆诉)** and any
artifacts derived from it. It complements the project licenses:

| Asset | License | Status of this AUP |
| :--- | :--- | :--- |
| **Source code** (pipeline + app) | Apache License 2.0 | Good-faith request (not an additional license term) |
| **Model weights** (if/when released) | OpenRAIL-M | **Binding** behavioral use restrictions |
| **Datasets** (if/when released) | CC BY-NC-SA 4.0 | Binding license terms + this AUP |

> For the source code, this AUP does **not** add any field-of-use restriction
> on top of Apache 2.0. It states the project's intended use and the conduct we
> ask of the community. For model weights released under OpenRAIL-M, equivalent
> use restrictions are legally binding under that license.

---

## 1. Intended purpose · 适用范围

Lens is a **research, personal-data-organization, and relationship-reflection**
tool. It helps individuals normalize their own communication history, reflect on
relational and communication patterns, and study AI methods for affective and
relational text.

**Lens is NOT** a medical device, and is **not** intended for:

- medical, psychiatric, or psychological **diagnosis**;
- **treatment** of any mental-health or relational condition;
- **psychotherapy** or licensed counseling;
- **crisis intervention**, suicide-risk management, or emergency response.

If you or someone else may be in danger, contact local emergency services or a
crisis hotline. Do not rely on Lens for safety-critical decisions.

---

## 2. Prohibited uses · 禁止用途

You agree **not** to use Lens, its outputs, or any derivative model/dataset to:

### 2.1 Health & safety
- present, market, or deploy it as a medical device, diagnosis, treatment, or
  substitute for a qualified clinician or licensed counselor;
- provide automated mental-health or relationship "advice" to third parties
  without clear, prominent disclosure that the output is AI-generated and not
  professional care;
- act as a sole or primary crisis-response, self-harm, or suicide-risk system.

### 2.2 Privacy & consent
- analyze, profile, or infer information about **another identifiable person**
  from their private communications **without their informed consent**, except
  for your own lawful personal review of your own conversations;
- conduct covert surveillance, stalking, or monitoring of a partner, family
  member, employee, or any individual;
- attempt to re-identify, de-anonymize, or extract personal data from released
  datasets or model weights.

### 2.3 Manipulation & harm
- generate content intended to **deceive, coerce, gaslight, manipulate,
  emotionally abuse, harass, or control** any person, including in intimate or
  family relationships;
- impersonate a real person, a licensed professional, or a crisis service;
- produce disinformation, defamation, or content that promotes self-harm,
  violence, or discrimination.

### 2.4 Vulnerable groups
- target or process the data of **minors** without verifiable guardian consent
  and appropriate safeguards;
- exploit the vulnerabilities of people experiencing mental-health crises,
  grief, or relational distress.

### 2.5 Legal & rights
- violate any applicable law or regulation (including data-protection law and,
  where relevant, the PRC Mental Health Law / 《精神卫生法》);
- make fully automated decisions that produce legal or similarly significant
  effects on a person (e.g., custody, employment, eligibility) without
  qualified human review.

---

## 3. Required safeguards · 使用者应保障的事项

If you build on Lens or deploy any derivative, you should:

1. **Disclose AI involvement** clearly to end users (no "human therapist" framing).
2. **Keep a human in the loop** for any consequential or clinically adjacent use.
3. **Preserve crisis routing**: keep emergency / hotline referral and the safety
   guardrails intact; do not remove or weaken them.
4. **Obtain consent** for any data concerning other people, and honor deletion
   requests.
5. **Pass this AUP downstream**: include it (or equivalent terms) when you
   redistribute model weights or datasets.

---

## 4. Research & publication use · 科研与发表

Lens is suitable for academic study. When using it in research with human data:

- obtain **ethics review / IRB approval** and informed consent where required;
- prefer **synthetic or fully anonymized** data for any public release;
- do not use a single individual's private messages (or a third party's
  messages) as a public dataset without consent and ethics clearance.

---

## 5. Reporting & enforcement · 报告与处理

To report misuse or a safety concern, open a confidential issue or contact the
maintainers via the channel listed in `SECURITY.md`.

For source code, the project cannot revoke Apache 2.0 rights based on this AUP.
For model weights and datasets, violation of the corresponding binding terms
(OpenRAIL-M / CC BY-NC-SA 4.0) may terminate your license to those artifacts.

---

## 6. Disclaimer · 免责声明

Lens is provided "AS IS", without warranties of any kind. The authors and
contributors are not liable for any use of the software, its outputs, or any
derivative, and assume no responsibility for clinical, relational, legal, or
other outcomes arising from its use. Use of Lens is at your own risk.
