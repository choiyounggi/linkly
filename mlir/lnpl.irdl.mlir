// The `lnpl` dialect — RFC-0004 S4.
//
// Loaded into stock `mlir-opt` with `--irdl-file`, so registering it needs no
// C++ TableGen build and no cmake. The issue that deferred S4 assumed such a
// build was required; it is not, and the development libraries it worried about
// turned out to be present anyway.
//
// Only `lnpl.node_id` is declared, which makes it *required* and *string-typed*:
// an op with no node id, or with a non-string one, fails verification. That is
// RFC-0004's traceability invariant (§dialect 변환 이후의 역추적), enforced by
// the verifier rather than merely asserted by a test.
//
// Every other attribute the emitter attaches — lnpl.name, lnpl.index,
// lnpl.kind, lnpl.step, lnpl.guard_mode, lnpl.guard_condition,
// lnpl.unroll_round — rides along as a discardable attribute and is
// deliberately left unconstrained here. Undeclared attributes are accepted by
// IRDL, so the dialect stays open to new compile decisions without a schema
// change, while the one invariant that matters stays closed.
//
// The ops carry no operands and no results, and sit flat in the module body:
// `builtin.module` has the NoTerminator trait, so no region or terminator
// plumbing is needed. Guards are attributes rather than regions because
// `_steps_in_order` has already flattened and unrolled them before S4 sees them.
irdl.dialect @lnpl {
  // One workflow step. `lnpl.index` is its 1-based position in the flattened
  // execution order; `lnpl.unroll_round` is present only when an unrolled guard
  // (`until`, `repeat`) emitted this node more than once.
  irdl.operation @step {
    %id = irdl.base "#builtin.string"
    irdl.operands()
    irdl.results()
    irdl.attributes {"lnpl.node_id" = %id}
  }

  // One effect owned by the step named in `lnpl.step`. `lnpl.kind` is the
  // Semantic IR node kind (Validation, RepositoryCall, CacheAccess, ...).
  irdl.operation @effect {
    %id = irdl.base "#builtin.string"
    irdl.operands()
    irdl.results()
    irdl.attributes {"lnpl.node_id" = %id}
  }

  // RFC-0004 ③/④: flat structural marker ops. `_steps_in_order` flattens the
  // Guard/Concurrency/Pipeline nodes out of the step stream, so before these ops
  // their ids never reached the module (③) and a `parallel` workflow was
  // byte-identical to its sequential form (④). Each marker carries its own
  // `lnpl.node_id` plus a discardable `lnpl.children` (the ordered immediate
  // child node ids) and a `lnpl.mode`/`lnpl.name`/`lnpl.guard_condition`/
  // `lnpl.count` as applicable. They are flat, not region-bearing: IRDL cannot
  // declare a terminator or the NoTerminator trait, so a region op would have to
  // embed a foreign terminator (`omp.terminator`); the child-id list avoids that
  // coupling while still distinguishing parallel from sequential.
  irdl.operation @concurrency {
    %id = irdl.base "#builtin.string"
    irdl.operands()
    irdl.results()
    irdl.attributes {"lnpl.node_id" = %id}
  }

  irdl.operation @pipeline {
    %id = irdl.base "#builtin.string"
    irdl.operands()
    irdl.results()
    irdl.attributes {"lnpl.node_id" = %id}
  }

  irdl.operation @guard {
    %id = irdl.base "#builtin.string"
    irdl.operands()
    irdl.results()
    irdl.attributes {"lnpl.node_id" = %id}
  }
}
