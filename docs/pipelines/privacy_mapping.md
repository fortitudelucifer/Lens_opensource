# Privacy & Identity Mapping Guide

This project includes a robust system for anonymizing and protecting sensitive personal information (PII) in chat datasets. This guide explains how the identity mapping works and how to configure it for your own data.

## Overview

The pipeline supports two levels of privacy protection:

*   **L1 (Local)**: Reversible anonymization. Names are replaced with generic placeholders (e.g., `ME`, `OTHER`), but a local mapping file is kept to reverse the process if needed. Timestamps are preserved.
*   **L2 (Cloud)**: Irreversible anonymization. PII is scrubbed without mapping, and timestamps are shifted/generalized to prevent temporal correlation. This is suitable for training models in cloud environments.

## Configuration

The core configuration lives in `configs/anonymization.yaml`. This file defines who the primary participants are and how they should be mapped.

### 1. Identity Mapping (`me_names` & `other_names`)

You need to tell the system which names in the chat logs correspond to "You" (`ME`) and which correspond to the "Other Person" (`OTHER`).

**Example `configs/anonymization.yaml`:**

```yaml
# List of names/nicknames that identify YOU
me_names:
  - "Alice"
  - "Alice Smith"
  - "Ali"

# List of names/nicknames that identify the OTHER person
other_names:
  - "Bob"
  - "Bob Jones"
  - "Bobby"

# Aliases used in the output dataset
me_alias: "ME"
other_alias: "OTHER"
```

**How it works:**
*   The system scans text for these specific strings.
*   If "Alice" is found, it is replaced with "ME" (or `me_alias`).
*   If "Bob" is found, it is replaced with "OTHER" (or `other_alias`).
*   This ensures that the model learns relationships between abstract entities rather than specific people.

### 2. Exclusion List (`exclude_patterns`)

Some words might look like names but shouldn't be anonymized (e.g., public figures, common nouns that look like names). Add them here to prevent false positives.

```yaml
exclude_patterns:
  - "Einstein"
  - "New York"
  - "Teacher"
```

### 3. Location Mapping (L2 Only)

For L2 anonymization, you can map specific real-world locations to generic ones to preserve privacy while maintaining semantic consistency.

```yaml
location_mapping:
  "New York": "Metropolis"
  "San Francisco": "Coastal City"
  "London": "Capital"
```

### 4. Timestamp Shifting (L2 Only)

To prevent identifying specific events by their exact time, L2 data allows shifting all timestamps by a random or fixed offset.

```yaml
l2_cloud:
  timestamp_shift:
    enabled: true
    shift_days: 100  # Shift all dates back by 100 days
```

## Two-Stage PII Detection

The project uses a sophisticated two-stage approach for detecting Personal Identifiable Information (PII):

1.  **Stage 1: Scanning**: The system scans the dataset using NLP rules and optional LLM-based recognition to find potential names, phone numbers, and addresses.
2.  **Stage 2: Confirmation**: A list of detected entities is generated for your review (in `configs/confirmed_names.yaml`). You verify which ones are real PII.
3.  **Application**: The pipeline uses the confirmed list to perform high-precision scrubbing.

## Identity Map Storage

For L1 (Local) anonymization, the mapping between real names and their anonymized versions is stored in:
`local_secrets/identity_map.json`

**SECURITY WARNING**: This file contains the keys to de-anonymize your data. **NEVER** commit this file to version control or share it if you intend to keep the data private. The project's `.gitignore` is configured to exclude this file by default.
