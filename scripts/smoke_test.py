import os
from dotenv import load_dotenv
from openai import OpenAI
from tavily import TavilyClient

# Load keys from .env (never hardcode them)
load_dotenv()

NEBIUS_API_KEY = os.environ.get("NEBIUS_API_KEY")
TAVILY_API_KEY = os.environ.get("TAVILY_API_KEY")

# --- 2. TAVILY SEARCH (Fixed: using search() instead of deprecated get_search_context) ---
print("="*60)
print("STEP 1: TAVILY SEARCH")
print("="*60)

tavily = TavilyClient(api_key=TAVILY_API_KEY)

search_results = tavily.search(
    query="ROS 2 Nav2 robot recovery behavior when LiDAR sensor returns sparse intermittent data",
    max_results=3,
)

# Manually assemble context from results (this replaces get_search_context)
tavily_context = "\n\n".join([
    f"Source: {r.get('url', 'unknown')}\n{r.get('content', '')}"
    for r in search_results.get("results", [])
])

print(f"✅ Tavily search successful ({len(search_results.get('results', []))} results)")
print(f"   Context length: {len(tavily_context)} chars\n")

# --- 3. NEMOTRON REASONING ---
print("="*60)
print("STEP 2: NEMOTRON CALL")
print("="*60)

client = OpenAI(
    base_url="https://api.tokenfactory.nebius.com/v1/",
    api_key=NEBIUS_API_KEY,
)

prompt = f"""
You are the diagnostics agent for an autonomous rover.
A fault has been detected: The LiDAR sensor is returning sparse, intermittent data.

Retrieved context from Tavily about ROS 2 fault recovery:
{tavily_context}

Based on this context and the fault, decide on exactly one action:
RETRY_NAVIGATION, REVERSE_AND_REPLAN, or HALT.

Respond with the decision on the first line. On the next line, give a 2-sentence rationale.
"""

# Using max_tokens=2048 to allow room for reasoning trace + answer
response = client.chat.completions.create(
    model="nvidia/NVIDIA-Nemotron-3-Nano-30B-A3B",
    messages=[{"role": "user", "content": prompt}],
    max_tokens=2048,
)

message = response.choices[0].message

print("✅ Nemotron call successful\n")

# --- 4. DIAGNOSTIC: INSPECT EVERYTHING ---
print("="*60)
print("STEP 3: FULL DIAGNOSTIC")
print("="*60)

print("\n--- 3a. All message attributes ---")
attrs = [a for a in dir(message) if not a.startswith('_')]
print(attrs)

print("\n--- 3b. Decision (content) ---")
print(repr(message.content))

print("\n--- 3c. reasoning_content field (old name) ---")
print(repr(getattr(message, "reasoning_content", "FIELD NOT PRESENT")))

print("\n--- 3d. reasoning field (new name) ---")
print(repr(getattr(message, "reasoning", "FIELD NOT PRESENT")))

print("\n--- 3e. Finish reason ---")
print(repr(response.choices[0].finish_reason))

print("\n--- 3f. Token usage ---")
if hasattr(response, "usage") and response.usage:
    print(f"  Prompt tokens: {response.usage.prompt_tokens}")
    print(f"  Completion tokens: {response.usage.completion_tokens}")
    print(f"  Total tokens: {response.usage.total_tokens}")
    # Check for reasoning tokens specifically
    if hasattr(response.usage, "completion_tokens_details"):
        print(f"  Completion details: {response.usage.completion_tokens_details}")

print("\n--- 3g. Full response object ---")
print(response)

print("\n" + "="*60)
print("DIAGNOSTIC COMPLETE")
print("="*60)