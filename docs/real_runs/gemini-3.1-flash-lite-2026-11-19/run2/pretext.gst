{
  "gst_version": "1.0",
  "state_id": "nych-806d25871808",
  "domain": "general",
  "state": {
    "source_text": "Run the unit tests before tagging a release",
    "roles": {
      "sentence": "Run the unit tests before tagging a release",
      "tokens": [
        "Run",
        "the",
        "unit",
        "tests",
        "before",
        "tagging",
        "a",
        "release"
      ],
      "action": {
        "word": "Run",
        "position": 0,
        "lemma": "run"
      },
      "enumerator": null,
      "object": {
        "word": "the unit tests",
        "start": 1,
        "end": 4
      },
      "tense": {
        "word": "before",
        "position": 4
      },
      "state": {
        "word": "tagging a release",
        "start": 5,
        "end": 8
      }
    }
  },
  "nych_pretext": {
    "analysis": {
      "text": "Run the unit tests before tagging a release",
      "modality": "UNRESOLVED",
      "modality_score": 0,
      "domain": "UNRESOLVED",
      "domain_score": 0,
      "competency": null
    },
    "subdomain": null,
    "tote_match": {
      "loop_id": "code.unit_test_repair",
      "name": "Unit-test repair",
      "domain": "software-engineering",
      "objective": "Make the selected test suite pass without weakening its assertions.",
      "initial_test": "Run the unchanged tests and capture failures.",
      "exit_predicate": "The unchanged selected test suite exits successfully.",
      "max_iterations": 8,
      "epistemic_status": "CANONICAL",
      "gestalts": [
        "bug",
        "fail",
        "pass",
        "repair",
        "test"
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
        "word": "Run",
        "skeleton": "rn",
        "id": "gestalt.rn",
        "skeleton_fallback": false
      },
      {
        "word": "unit",
        "skeleton": "nt",
        "id": "gestalt.nt",
        "skeleton_fallback": false
      },
      {
        "word": "tests",
        "skeleton": "tsts",
        "id": "gestalt.tsts",
        "skeleton_fallback": false
      },
      {
        "word": "before",
        "skeleton": "bfr",
        "id": "gestalt.bfr",
        "skeleton_fallback": false
      },
      {
        "word": "tagging",
        "skeleton": "tgng",
        "id": "gestalt.tgng",
        "skeleton_fallback": false
      },
      {
        "word": "release",
        "skeleton": "rls",
        "id": "gestalt.rls",
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
