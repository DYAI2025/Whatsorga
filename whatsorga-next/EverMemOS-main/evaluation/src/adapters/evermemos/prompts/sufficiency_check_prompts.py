"""Sufficiency Check Prompt for Agentic Retrieval"""

SUFFICIENCY_CHECK_PROMPT = """You are a meticulous and detail-oriented expert in information retrieval evaluation. Your task is to critically assess whether a set of retrieved documents contains sufficient information to provide a direct and complete answer to a user's query.

**User Query**:
{query}

**Retrieved Documents**:
{retrieved_docs}

**Instructions**:
Follow these steps to ensure an accurate evaluation:

1.  **Deconstruct the Query**: Break down the user's query into its core informational needs (e.g., who, what, where, when, why, how). Identify all key entities and concepts.
2.  **Scan for Keywords**: Quickly scan the documents for the key entities and concepts from the query. This is a preliminary check for relevance.
3.  **Detailed Analysis**: Read the relevant parts of the documents carefully. Determine if they contain explicit facts that directly answer *all aspects* of the query. Do not rely on making significant inferences or assumptions. The answer should be explicitly stated or very easily pieced together from the text.
4.  **Sufficiency Judgment**:
    *   If all parts of the query are directly and explicitly answered, the documents are **sufficient**.
    *   If any significant part of the query is not answered, the documents are **insufficient**.
    *   If you are uncertain, err on the side of caution and label it as **insufficient**. Do not guess.
5.  **Formulate Reasoning**: Based on your analysis, write a brief (1-2 sentences) explanation for your judgment.
6.  **Identify Missing Information**: If the documents are insufficient, list the specific pieces of information that are missing to fully answer the query.

**Output Format** (strict JSON, no additional text before or after the JSON block):
{{
  "is_sufficient": true or false,
  "reasoning": "Brief, clear explanation for your decision (1-2 sentences).",
  "missing_information": ["list", "of", "specific", "missing", "information"]
}}

**Examples**:

Example 1 (Sufficient):
Query: "What is Alice's favorite hobby?"
Documents:
  Document 1: "Alice mentioned she loves painting. She spends weekends at art galleries."
  Document 2: "Alice's work involves creative projects."
Output:
{{
  "is_sufficient": true,
  "reasoning": "Document 1 explicitly states that Alice's hobby is painting.",
  "missing_information": []
}}

Example 2 (Insufficient - Missing Detail):
Query: "Where did Bob go on vacation last year?"
Documents:
  Document 1: "Bob talked about his work project deadline around June."
  Document 2: "Bob likes to travel and explore new places. He recently came back from a trip."
Output:
{{
  "is_sufficient": false,
  "reasoning": "The documents mention Bob likes to travel and recently took a trip, but do not specify where he went or if it was last year.",
  "missing_information": ["specific vacation destination", "confirmation the trip was 'last year'"]
}}

Example 3 (Insufficient - Tangential Information):
Query: "What are the specs of the new 'Galaxy Z' phone?"
Documents:
  Document 1: "The Galaxy Z is rumored to be released next month."
  Document 2: "Tech enthusiasts are excited about the upcoming Galaxy Z launch event."
Output:
{{
  "is_sufficient": false,
  "reasoning": "The documents mention the phone's upcoming release but provide no specific technical specifications.",
  "missing_information": ["screen size", "processor type", "camera resolution", "battery capacity", "etc."]
}}

Now evaluate:
"""

