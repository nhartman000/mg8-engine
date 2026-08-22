{
  "gst_version": "1.0",
  "state_id": "STATE_EXAMPLE_001",
  "internal": {
    "prior": {"mode": "idle"},
    "current": {"mode": "active"}
  },
  "external": {
    "prior": {"object_detected": false, "confidence": 0.0},
    "current": {"object_detected": true, "confidence": 0.95}
  },
  "continuity": {
    "placeholder": "0,0"
  },
  "intent": "evaluate the current external state",
  "outcome_expectation": "eligible state remains inside the example constraint",
  "constraints": {
    "profile": "example-only",
    "minimum_confidence": 0.9
  }
}
