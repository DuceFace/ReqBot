Core idea
  ReqBot should evolve into a compliance tool engine that other agents can
  call, not a general-purpose agent itself.

  Positioning

  - ReqBot = specialist backend for compliance corpus work
  - Claude/ChatGPT/Gemini = planner/orchestrator
  - GUI = human interface
  - API/MCP surface = agent interface

  That means ReqBot should focus on doing a small set of things very reliably
  and structurally.

  Phase concept
  I would treat this as a future phase after GUI expansion and domain
  profiles:

  - Phase 19: GUI capability expansion (search, compare, evidence, docs)
  - Phase 20: domain profile foundation
  - Phase 21 or 22: ReqBot as composable tool server

  Domain profiles (Phase 20) should land before the MCP surface. Once
  list_documents can return semantic metadata (authority type, domain,
  policy level) rather than just counts and dates, the tool surface becomes
  significantly more useful to an orchestrator. An agent that can filter
  by authority_type: "dodi" or domain: "access_control" at query time
  is qualitatively different from one that just sees a flat doc list.

  What ReqBot should expose
  Start with a small tool surface, not a huge one.

  First five tools (maps directly to existing API endpoints):

  1. search_requirements

  - input:
      - question
      - optional document filters
      - optional domain/type filters
      - top_k
  - output:
      - normalized requirement hits
      - scores
      - provenance metadata

  2. trace_requirement

  - input:
      - requirement_id
      - optional include_context
  - output:
      - full requirement detail
      - source quote (verbatim, primary asset)
      - provenance
      - cross-matches
      - context window

  3. compare_documents

  - input:
      - doc_1
      - doc_2
      - topic/control
  - output:
      - both-doc hits
      - doc1-only hits
      - doc2-only hits
      - stable document keys

  4. map_evidence

  - input:
      - topic/control
      - optional filters
      - optional synthesize
  - output:
      - grouped evidence results
      - source groupings
      - optional synthesis text (always a labeled, optional field — never
        the default return; retrieval fields are always structured)
      - provenance

  5. list_documents

  - input:
      - maybe none
  - output:
      - available corpus docs
      - counts
      - dates
      - domain/profile metadata (Phase 20+)

  That is enough for an external orchestrator to do serious work.

  A note on structured output vs. prose
  All five tools already return structured JSON — that is already true of
  the existing API. The one exception is map_evidence with synthesize=true,
  which returns synthesis_text as LLM prose. The rule to preserve:

  - retrieval fields are always structured JSON
  - LLM-generated text is always a clearly labeled, optional field
  - synthesis never replaces structured output; it augments it

  This distinction matters for orchestrators. An agent can parse structured
  output deterministically; it cannot reliably parse conversational prose.

  Good future tools after that
  Only after the basics are stable:

  - generate_checklist_candidates
  - cluster_requirements_by_responsibility
  - find_gaps_across_authorities
  - build_audit_plan
  - export_mict_ready_package

  Those are higher-value composed operations, but they should come after the
  primitives are solid.

  Architecture rules

  - ReqBot should return structured JSON, not conversational prose by default
  - tool outputs should preserve provenance (requirement_id, source_pdf,
    source_quote, source_ref on every result — never strip these)
  - tools should be deterministic/repeatable where possible
  - orchestration stays outside ReqBot
  - ReqBot should not try to become a full autonomous agent framework

  That last point matters a lot.

  Why this is the right split
  Let frontier models do:

  - planning
  - decomposition
  - writing
  - combining outputs

  Let ReqBot do:

  - retrieval
  - mapping
  - traceability
  - corpus-aware compliance operations

  That gives you the best of both.

  A realistic future workflow
  User says:

  "Build me an audit checklist for a workcenter with responsibilities A-E."

  Orchestrator does:

  1. call list_documents (get corpus, filter by relevant authority types)
  2. call search_requirements multiple times for each responsibility
  3. call compare_documents for overlapping authorities
  4. call map_evidence for important control areas
  5. optionally call future generate_checklist_candidates
  6. assemble final checklist with provenance

  That is where ReqBot starts becoming much more valuable.

  What not to do

  - don't build a giant agent framework inside ReqBot
  - don't make every endpoint conversational
  - don't blur backend truth with frontend presentation
  - don't rely on a single mega-endpoint like build_everything_for_me
  - don't strip provenance fields from tool outputs for "simplicity"

  Start with composable tools.

  The ROI argument
  If ReqBot becomes a tool server, its value is:

  - reusable by humans and agents
  - harder to replace with plain chat (corpus-specificity + provenance)
  - useful in GUI, CLI, and integrations without code changes
  - better suited for future enterprise/compliance workflows
  - the same retrieval work benefits every consumer (human, agent, CI/CD)

  That is a much stronger long-term bet than "just another interface."
