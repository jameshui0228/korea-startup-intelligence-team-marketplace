"""Compile user-supplied taxonomy and a metadata-only research index. No network."""
import argparse
import hashlib
import json
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def parse_taxonomy(text):
    domains, compressed, current = [], [], None
    in_compressed = False
    for number, raw in enumerate(text.splitlines(), 1):
        line = raw.strip()
        if not line:
            continue
        if line == "[최상위 압축 분류]":
            in_compressed = True
            continue
        if in_compressed:
            compressed.append(line)
            continue
        match = re.fullmatch(r"(\d+)\.\s+(.+)", line)
        if match:
            index = int(match[1])
            if index != len(domains) + 1:
                raise ValueError(f"Non-contiguous domain at line {number}")
            current = {"id": f"KR-{index:03d}", "number": index,
                       "name": match[2], "source_line": number, "subfields": [], "notes": []}
            domains.append(current)
        elif line.startswith("- ") and current:
            current["subfields"].append({"id": f"{current['id']}-{len(current['subfields']) + 1:03d}",
                                           "name": line[2:], "source_line": number})
        elif line.startswith("※") and current:
            current["notes"].append({"text": line, "source_line": number})
        elif line != "[한국 사회 전체 분야 MASTER LIST]":
            raise ValueError(f"Unparsed taxonomy content at line {number}")
    if not domains or any(not d["subfields"] for d in domains):
        raise ValueError("Empty taxonomy or domain")
    return {"schema_version": 1, "domain_count": len(domains),
            "subfield_count": sum(len(d["subfields"]) for d in domains),
            "compressed_categories": compressed, "domains": domains,
            "boundary": "A coverage taxonomy, not proof of expertise or complete market coverage. Labels may overlap; IDs preserve the original."}


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--taxonomy", type=Path, required=True)
    parser.add_argument("--mission", type=Path, required=True)
    parser.add_argument("--research", type=Path, required=True)
    parser.add_argument("--trend-mission", type=Path)
    args = parser.parse_args()
    dest = ROOT / "assets"
    inputs = dest / "user_inputs"
    inputs.mkdir(parents=True, exist_ok=True)
    manifest = {}
    for name, src in (("korea_domains.txt", args.taxonomy), ("master_mission.txt", args.mission)):
        data = src.read_bytes()
        (inputs / name).write_bytes(data)
        manifest[name] = {"sha256": hashlib.sha256(data).hexdigest(), "bytes": len(data),
                          "origin": "user supplied attachment", "copied_verbatim": True}
    if args.trend_mission:
        data = args.trend_mission.read_bytes()
        (inputs / "trend_mission.txt").write_bytes(data)
        manifest["trend_mission.txt"] = {"sha256": hashlib.sha256(data).hexdigest(), "bytes": len(data),
                                        "origin": "user supplied follow-up request", "copied_verbatim": True}
    taxonomy = parse_taxonomy(args.taxonomy.read_text())
    (dest / "taxonomy.json").write_text(json.dumps(taxonomy, ensure_ascii=False, indent=2) + "\n")
    research = json.loads(args.research.read_text())
    index = [{"repository": r["fullName"], "url": r["url"], "category": r["category"],
              "candidate_use": r["candidateUse"], "license_metadata": r.get("licenseSpdx") or "UNKNOWN",
              "metadata_as_of": "2026-09-17", "pushed_at": r.get("pushedAt"),
              "archived": r.get("archived"), "evidence_scope": "Repository metadata / author README claims; execution and licensing dependencies not audited"}
             for r in research]
    if len({r["repository"] for r in index}) != len(index):
        raise ValueError("Duplicate research repositories")
    (dest / "research_index.json").write_text(json.dumps(index, ensure_ascii=False, indent=2) + "\n")
    (dest / "input_manifest.json").write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + "\n")
    print(json.dumps({"domains": taxonomy["domain_count"], "subfields": taxonomy["subfield_count"],
                      "compressed": len(taxonomy["compressed_categories"]), "research_references": len(index)}))


if __name__ == "__main__":
    main()
