"""Render an engine prompt template with a tenant's config (ENGINE-PLAN step 3).

  python engine/render_prompt.py discovery --tenant tenants/josh-ig-gigs/config.json
  python engine/render_prompt.py comments  --tenant tenants/josh-linkedin/config.json

{{dotted.keys}} resolve into the tenant config; lists join with " · "; missing keys
render as empty and are listed on stderr so a bad template can't fail silently.
"""
import json, re, sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent


def flatten(obj, prefix=""):
    out = {}
    if isinstance(obj, dict):
        for k, v in obj.items():
            out.update(flatten(v, f"{prefix}{k}."))
    else:
        key = prefix[:-1]
        if isinstance(obj, list):
            out[key] = " · ".join(str(x) for x in obj)
        else:
            out[key] = str(obj)
    return out


def main():
    args = sys.argv[1:]
    if "--tenant" in args:
        i = args.index("--tenant")
        tenant_path = Path(args[i + 1])
        del args[i:i + 2]
    else:
        tenant_path = ROOT / "tenants" / "josh-linkedin" / "config.json"
    module = args[0] if args else "discovery"
    if not tenant_path.is_absolute():
        tenant_path = ROOT / tenant_path
    cfg = flatten(json.loads(tenant_path.read_text(encoding="utf-8")))
    template = (ROOT / "engine" / module / "PROMPT.md").read_text(encoding="utf-8")
    missing = []

    def sub(m):
        key = m.group(1).strip()
        if key not in cfg:
            missing.append(key)
            return ""
        return cfg[key]

    rendered = re.sub(r"\{\{([^}]+)\}\}", sub, template)
    sys.stdout.buffer.write(rendered.encode("utf-8"))
    if missing:
        print(f"\nWARNING missing keys: {sorted(set(missing))}", file=sys.stderr)


if __name__ == "__main__":
    main()
