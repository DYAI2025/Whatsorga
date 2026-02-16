"""Multi-Query Generation Prompt for Agentic Retrieval"""

MULTI_QUERY_GENERATION_PROMPT = """You are an expert at query reformulation for information retrieval.

**Task**: Generate multiple complementary search queries to maximize retrieval accuracy (precision and recall).

**Original Query**:
{original_query}

**Retrieved Documents** (insufficient):
{retrieved_docs}

**Missing Information**:
{missing_info}

**Success Criteria (optimize for retrieval accuracy)**:
- **Precision**: At least one query tightly anchors exact entities, numbers, dates, and stated constraints (timeframe, location, role, object).
- **Recall**: As a set, queries cover distinct aspects and vocabulary variants (synonyms, aliases, acronyms and expansions) without redundancy.
- **Faithfulness**: Never introduce facts not present in the original_query, missing_info, or retrieved_docs.

**Strategy**:
- Generate complementary queries with different breadth:
   - High-precision anchor
   - Diversified paraphrase with synonyms/aliases
   - Broader recall variant (optional)

**Instructions**:
1. Generate 2-3 different queries.
2. Use the same language as the original_query. If retrieved_docs include bilingual terms or transliterations, include variants in different queries.
3. Make queries open-ended and descriptive; avoid yes/no.
4. Prefer key noun phrases and domain terms from retrieved_docs; repeat exact surface forms of important entities.
5. Keep each query 8-22 words; keep them focused on a single aspect.
6. Retain critical constraints present in the task (time, location, role, object); omit speculative constraints.
7. Include synonyms/aliases/abbreviations by adding the variant terms directly into different queries. Do not use Boolean operators (AND/OR), quotes, or special symbols.
8. If numbers/dates/codes exist, include common variants (e.g., "Nov 1 2025" and "2025-11-01"; "LLM" and "large language model").
9. Avoid pronouns and vague references; name the entities explicitly in each query.
10. Do not add new assumptions or fictitious details.

Query types to consider:
   - High-precision anchor query (exact entities, constraints)
   - Diversified paraphrase using synonyms/aliases/abbreviations
   - Broader recall query targeting general context
   - **Extractive Query**: Formulate a direct question to extract a specific fact, name, or number. (e.g., "What was the exact date of the meeting?")
   - **Fact-finding query**: Ask for descriptions, lists, or details about a topic. (e.g., "What are the key features of product X?")
   - Focused query: Target specific missing aspects
   - Expanded query: Broader version with more keywords
   - Alternative phrasing: Same intent, different wording

**Quality Checklist (before output):**
- Queries differ in tokens and angle; not minor rephrases.
- Each includes high-signal entities/constraints when present.
- No invented facts; no yes/no; no pronouns.
- Each under 22 words.

**Output Format** (strict JSON, no additional text):
{{
  "queries": [
    "First refined query targeting aspect 1",
    "Second refined query targeting aspect 2",
    "Third refined query targeting aspect 3 (optional)"
  ],
  "reasoning": "Brief explanation of the query strategy (1-2 sentences)"
}}

**Examples**:

Example 1:
Original Query: "What does Alice like?"
Missing Info: ["Alice's hobbies", "Alice's preferences"]
Output:
{{
  "queries": [
    "What are Alice's hobbies and interests?",
    "What are Alice's favorite activities and pastimes?",
    "What does Alice enjoy doing in her free time?"
  ],
  "reasoning": "Generated queries covering hobbies, activities, and leisure preferences from different angles."
}}

Example 2:
Original Query: "Tell me about the meeting"
Missing Info: ["meeting date", "location", "participants", "agenda"]
Output:
{{
  "queries": [
    "When and where was the meeting held?",
    "Who attended the meeting and what was discussed?",
    "What was the meeting agenda and outcome?"
  ],
  "reasoning": "Separated the query into time/location, participants/topics, and agenda/results for comprehensive coverage."
}}

Example 3:
Original Query: "Bob's project status"
Missing Info: ["project name", "progress", "challenges"]
Output:
{{
  "queries": [
    "What is the name and current progress of Bob's project?",
    "What challenges or problems has Bob encountered in his project?"
  ],
  "reasoning": "First query targets identification and progress, second focuses on challenges to avoid redundancy."
}}

**Example 4 (Prefer Factual Queries over Yes/No):**
Original Query: "Tom's opinion on Dr. Seuss books"
Missing Info: ["Whether Tom has Dr. Seuss books", "Details about Tom's bookshelf or book collection"]
Output:
{{
  "queries": [
    "What books are in Tom's personal book collection or on her bookshelf?",
    "What are Tom's favorite children's book authors or specific books she likes to read?",
    "What are Tom's opinions or views on children's literature and authors like Dr. Seuss?"
  ],
  "reasoning": "Generated open-ended queries to discover factual details about Tom's book collection and preferences, which is more effective for retrieval than asking simple yes/no questions."
}}

Now generate the queries:

"""

