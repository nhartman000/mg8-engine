{
  "gst_version": "1.0",
  "state_id": "nych-d47dfd4582e3",
  "domain": "general",
  "state": {
    "source_text": "Verify the backup and confirm no errors were reported",
    "roles": {
      "sentence": "Verify the backup and confirm no errors were reported",
      "tokens": [
        "Verify",
        "the",
        "backup",
        "and",
        "confirm",
        "no",
        "errors",
        "were",
        "reported"
      ],
      "action": {
        "word": "Verify",
        "position": 0,
        "lemma": "verify"
      },
      "enumerator": null,
      "object": {
        "word": "the backup and confirm no errors were reported",
        "start": 1,
        "end": 9
      },
      "tense": null,
      "state": null
    }
  },
  "nych_pretext": {
    "analysis": {
      "text": "Verify the backup and confirm no errors were reported",
      "modality": "UNRESOLVED",
      "modality_score": 0,
      "domain": "UNRESOLVED",
      "domain_score": 0,
      "competency": null
    },
    "subdomain": null,
    "tote_match": {
      "loop_id": "MB-B-PG-001",
      "name": "Reacquire and verify a base backup",
      "domain": "database_administration",
      "objective": "Obtain a plain-format base-backup candidate with no reported manifest/file/checksum/required-WAL verification failures.",
      "initial_test": "Use pg_verifybackup to check a pg_basebackup backup against its server-generated backup_manifest.",
      "exit_predicate": "Fresh full verification completes without reported errors (including required WAL parsing); this is not proof of restorability.",
      "max_iterations": 3,
      "epistemic_status": "DERIVED",
      "gestalts": [
        "exit predicate",
        "provenance"
      ]
    },
    "tote_fallback": null,
    "modality_operators": {
      "external_observe": "👀",
      "internal_model": "👁️🧠",
      "operative_intent": "🗯️",
      "execute": "💪"
    },
    "needs_mapping": [
      {
        "word": "Verify",
        "skeleton": "vrfy",
        "id": "gestalt.vrfy",
        "skeleton_fallback": false
      },
      {
        "word": "backup",
        "skeleton": "bckp",
        "id": "gestalt.bckp",
        "skeleton_fallback": false
      },
      {
        "word": "confirm",
        "skeleton": "cnfrm",
        "id": "gestalt.cnfrm",
        "skeleton_fallback": false
      },
      {
        "word": "no",
        "skeleton": "n",
        "id": "gestalt.n",
        "skeleton_fallback": false
      },
      {
        "word": "errors",
        "skeleton": "rrs",
        "id": "gestalt.rrs",
        "skeleton_fallback": false
      },
      {
        "word": "were",
        "skeleton": "wr",
        "id": "gestalt.wr",
        "skeleton_fallback": false
      },
      {
        "word": "reported",
        "skeleton": "rprtd",
        "id": "gestalt.rprtd",
        "skeleton_fallback": false
      }
    ],
    "pinned": [],
    "protected": [],
    "discretion_rules": [
      "Chunk and compress any deterministic findings that can be compressed before rendering symbol matches.",
      "Map each word needing a symbol by the most obvious visual match.",
      "Embed the provided consonant skeleton (word sans vowels and doubled consonants) into the chosen symbol's id string as a disambiguation clue.",
      "The four modality operators are invariant: they are never remapped, and their glyphs are never assigned to any other word.",
      "A word already pinned #temp-invariant this session keeps its existing mapping; do not re-decide it.",
      "Scientific names, names of people, and prescription drug names are NOT rendered into Gestalt symbols: pass them through literally, with no glyph, no skeleton id, and no session pin."
    ],
    "pruning": {
      "dither": 0.1,
      "instructions": [
        "Narrow the problemspace by the factor of the inverse transform using the deterministic findings below as pretext.",
        "Coarse prune by domain first: discard content outside the classified domain (treat UNRESOLVED as no domain constraint).",
        "Fine prune by subdomain within the surviving domain when a subdomain is given.",
        "Apply the competency check within domain: gate content depth to the reported competency score (None means no competency gate).",
        "Apply the dither margin as controlled boundary leakage: allow content within the margin just outside the pruned boundary through, so access widens gradually from novice to expert rather than cliff-edging."
      ]
    }
  }
}
