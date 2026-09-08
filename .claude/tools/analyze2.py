import json, os, collections, re
p = os.path.expanduser("~/.claude/projects/C--Users-123-projects-reels-factory/7a795adc-e6b1-4521-b8d3-d7dfc19c267d.jsonl")
id2name = {}; id2inp = {}
big_by_tool = collections.Counter(); big_chars_by_tool = collections.Counter()
restart_prompts = []
agent_prompts = []
baseline = []  # context right after compaction
prev_compact = False
ctx_series = []
first_usage = None
with open(p, encoding="utf-8", errors="replace") as f:
    for line in f:
        try: d = json.loads(line)
        except Exception: continue
        m = d.get("message") or {}
        t = d.get("type"); ts = d.get("timestamp")
        if d.get("isCompactSummary"): prev_compact = True
        if t == "assistant":
            u = m.get("usage")
            if u:
                c = u.get("input_tokens",0)+u.get("cache_read_input_tokens",0)+u.get("cache_creation_input_tokens",0)
                ctx_series.append((ts, c))
                if first_usage is None: first_usage = (ts, c)
                if prev_compact: baseline.append((ts, c)); prev_compact = False
            for x in m.get("content") or []:
                if isinstance(x, dict) and x.get("type") == "tool_use":
                    id2name[x["id"]] = x["name"]; id2inp[x["id"]] = x.get("input") or {}
                    if x["name"] == "Agent":
                        pr = (x.get("input") or {}).get("prompt","")
                        agent_prompts.append((ts, pr))
                        if re.match(r"\s*(Продолж|Continue|Resume|Возобнов)", pr, re.I) or "предыдущ" in pr[:400].lower() or "previous agent" in pr[:400].lower():
                            restart_prompts.append((ts, pr[:120].replace("\n"," ")))
        if t == "user":
            c = m.get("content")
            if isinstance(c, list):
                for x in c:
                    if isinstance(x, dict) and x.get("type") == "tool_result":
                        L = len(json.dumps(x.get("content") or ""))
                        name = id2name.get(x.get("tool_use_id"), "?")
                        if L > 20000:
                            big_by_tool[name] += 1; big_chars_by_tool[name] += L
                            if L > 300000:
                                inp = id2inp.get(x.get("tool_use_id"), {})
                                print("BIG", ts, name, L, str(inp)[:160].replace("\n"," "))
print("big results by tool:", big_by_tool)
print("big chars by tool:", big_chars_by_tool)
print("first usage", first_usage)
print("baseline after compaction:", baseline)
print("restart-by-prompt agent launches:", len(restart_prompts))
for r in restart_prompts: print("  ", r)
# how many agent prompts mention a prior agent's result verbatim (pasted context)?
long = [a for a in agent_prompts if len(a[1]) > 5000]
print("agent prompts >5000 chars:", len(long))
# distinct-description repeats: same description launched more than once
descs = collections.Counter()
