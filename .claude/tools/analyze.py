import json, sys, collections, os, re, glob
p = os.path.expanduser("~/.claude/projects/C--Users-123-projects-reels-factory/7a795adc-e6b1-4521-b8d3-d7dfc19c267d.jsonl")
agents = []            # (ts, subagent_type, model, len(prompt), run_in_background, first 80 chars)
sendmsg = []
skills = collections.Counter()
compacts = []
usage = []             # (ts, input, cache_read, cache_create, output)
tools = collections.Counter()
user_turns = 0
bigres = []
n = 0
first_ts = last_ts = None
with open(p, encoding="utf-8", errors="replace") as f:
    for line in f:
        n += 1
        try: d = json.loads(line)
        except Exception: continue
        ts = d.get("timestamp")
        if ts:
            first_ts = first_ts or ts; last_ts = ts
        t = d.get("type")
        if d.get("isCompactSummary"): compacts.append(ts)
        m = d.get("message") or {}
        if t == "user" and not d.get("isMeta"):
            c = m.get("content")
            if isinstance(c, str): user_turns += 1
            elif isinstance(c, list):
                if any(x.get("type") == "text" for x in c if isinstance(x, dict)): user_turns += 1
                for x in c:
                    if isinstance(x, dict) and x.get("type") == "tool_result":
                        cc = x.get("content")
                        L = len(json.dumps(cc)) if cc else 0
                        if L > 20000: bigres.append((ts, L))
        if t == "assistant":
            u = m.get("usage")
            if u: usage.append((ts, u.get("input_tokens",0), u.get("cache_read_input_tokens",0), u.get("cache_creation_input_tokens",0), u.get("output_tokens",0)))
            for x in m.get("content") or []:
                if not isinstance(x, dict) or x.get("type") != "tool_use": continue
                name = x.get("name"); inp = x.get("input") or {}
                tools[name] += 1
                if name == "Agent":
                    agents.append((ts, inp.get("subagent_type"), inp.get("model"), len(inp.get("prompt","")), inp.get("run_in_background"), (inp.get("description") or "")[:60]))
                if name == "SendMessage": sendmsg.append((ts, inp.get("to"), (inp.get("summary") or "")[:60]))
                if name == "Skill": skills[inp.get("skill")] += 1
print("lines", n, "first", first_ts, "last", last_ts)
print("user turns", user_turns, "assistant msgs", len(usage))
print("compactions", len(compacts), compacts)
print("Agent calls", len(agents));
print(" by type:", collections.Counter(a[1] for a in agents))
print(" by model:", collections.Counter(a[2] for a in agents))
print(" background:", collections.Counter(a[4] for a in agents))
print(" prompt len: avg", sum(a[3] for a in agents)//max(1,len(agents)), "max", max((a[3] for a in agents), default=0))
print("SendMessage calls", len(sendmsg), collections.Counter(s[1] for s in sendmsg).most_common(10))
print("Skill calls", skills)
print("tools", tools.most_common(25))
tot_in = sum(u[1] for u in usage); tot_cr = sum(u[2] for u in usage); tot_cc = sum(u[3] for u in usage); tot_out = sum(u[4] for u in usage)
print("tokens: fresh_in", tot_in, "cache_read", tot_cr, "cache_create", tot_cc, "out", tot_out)
# context size trajectory: cache_read+cache_create+input per assistant msg = current context
ctx = [(u[0], u[1]+u[2]+u[3]) for u in usage]
peaks = sorted(ctx, key=lambda x: -x[1])[:5]
print("context peaks", peaks)
# per day context resets / peaks
byday = collections.defaultdict(list)
for ts, c in ctx: byday[ts[:10]].append(c)
for day in sorted(byday): print(day, "msgs", len(byday[day]), "max ctx", max(byday[day]), "median", sorted(byday[day])[len(byday[day])//2])
print("big tool results >20k chars:", len(bigres), "total chars", sum(b[1] for b in bigres), sorted(bigres, key=lambda x:-x[1])[:8])
print("--- agent list (last 40)")
for a in agents[-40:]: print(a)
# subagent dir sizes
sub = os.path.expanduser("~/.claude/projects/C--Users-123-projects-reels-factory/7a795adc-e6b1-4521-b8d3-d7dfc19c267d/subagents")
files = glob.glob(sub + "/*.jsonl")
sizes = sorted(((os.path.getsize(f), os.path.basename(f)) for f in files), reverse=True)
print("subagent files", len(files), "total MB", sum(s[0] for s in sizes)/1e6, "top", sizes[:5])
