"""Build an inference-only transfer index from the already authorized sources.

Only source paths, byte commitments, and source-rights provenance are copied.
Evaluation cohort indices, reference geometry, and expected outcomes are not read.
The caller retains the provider credential and binds each captured task manifest.
"""
from __future__ import annotations

from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path


ROOT = Path("/tmp/marinaframe-v04-independent")
NPS_COLLECTION = "https://www.nps.gov/subjects/heritagedocumentation/collection.htm"
NPS_COPYRIGHT = "https://www.nps.gov/subjects/heritagedocumentation/copyright-guidance.htm"
RIGHTS = {
    "r_73b91d2a": {
        "rights_code": "US-federal-public-domain-formal-HAER-documentation",
        "source_title": "Balclutha, HAER CA-54, Section at Frame 108",
        "basis": "This source is a formal HAER measured-drawing sheet. NPS states that materials created for formal HABS/HAER/HALS documentation are public domain. The item record identifies the exact sheet; the basis is not a blanket assumption about all Library of Congress content.",
        "citations": ["https://www.loc.gov/resource/hhh.ca1493.sheet/?sp=48", NPS_COLLECTION, NPS_COPYRIGHT],
    },
    "r_85ac0f61": {
        "rights_code": "PD-US-expired",
        "source_title": "USS Monitor general plan, 1862, NH 50954",
        "basis": "The source item is explicitly marked PD-US-expired and identifies publication in 1862. The acquired Commons raster is a documented caption-cropped/shadow-adjusted derivative. NHHC corroborates the archival item identity.",
        "citations": ["https://commons.wikimedia.org/wiki/File:USSMonitorPlan1862.ws.jpg", "https://www.history.navy.mil/content/history/nhhc/our-collections/photography/numerical-list-of-images/nhhc-series/nh-series/NH-50000/NH-50954.html"],
    },
    "r_09d3ea47": {
        "rights_code": "PD-US-NPS",
        "source_title": "Wapama, HAER CA-67, As-Is Lines body plans, sheet 5",
        "basis": "The source item is explicitly marked PD-US-NPS and credits Richard K. Anderson Jr., 2011, as official-duty documentation. The acquired original TIFF digest was checked against the item record; this inference input is its recorded raster preview. NPS also identifies formal HAER documentation as public domain.",
        "citations": ["https://www.loc.gov/resource/hhh.ca1521.sheet/?sp=5&st=text", "https://commons.wikimedia.org/wiki/File:As-Is_Lines-_Body_Plans,_Stations_0-5_and_Stations_5-10,_Looking_Aft_-_Steam_Schooner_WAPAMA,_Kaiser_Shipyard_No._3_(Shoal_Point),_Richmond,_Contra_Costa_County,_CA_HAER_CAL,21-SAUS,1-_(sheet_5_of_22).tif", NPS_COLLECTION, NPS_COPYRIGHT],
    },
}


def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def main():
    index_path = ROOT / "public_v2/implementation_inputs.json"
    index = json.loads(index_path.read_text())
    input_root = Path(index["input_root"])
    cases = []
    for case in index["cases"]:
        spec_path = input_root / case["input"]
        image_path = input_root / case["drawing"]
        spec = json.loads(spec_path.read_text())
        source_hash = sha(image_path)
        if spec["source"].get("sha256") != source_hash:
            raise ValueError("Declared source image digest mismatch")
        if (spec_path.parent / spec["source"]["file"]).resolve() != image_path.resolve():
            raise ValueError("Input index does not name the specification's source")
        if case["case_id"] in RIGHTS:
            rights = RIGHTS[case["case_id"]]
        else:
            if "CC0-1.0" not in spec["source"].get("license", ""):
                raise ValueError("Source rights lack an allowlisted basis")
            rights = {
                "rights_code": "CC0-1.0-author-declaration",
                "source_title": "Original evaluator-authored source drawing",
                "basis": "The independent source author created this raster drawing and declared CC0-1.0 in its supplied source metadata. The source bytes and original calibration metadata are included in the existing user-authorized research task.",
                "citations": ["https://creativecommons.org/publicdomain/zero/1.0/"],
            }
        spec_hash = sha(spec_path)
        basis = (
            f"Existing user-authorized MarinaFrame OpenCode Go DeepSeek research. "
            f"Case {case['case_id']}; source SHA-256 {source_hash}; "
            f"spec SHA-256 {spec_hash}; source rights {rights['rights_code']}. "
            "Only this task's inference inputs and their source-bound tool evidence."
        )
        cases.append({
            "case_id": case["case_id"],
            "input": case["input"],
            "drawing": case["drawing"],
            "spec_sha256": spec_hash,
            "source_sha256": source_hash,
            "spec_bytes": spec_path.stat().st_size,
            "source_bytes": image_path.stat().st_size,
            "source_rights": rights,
            "specification_rights": "Evaluator-authored deployment metadata supplied under the same user-authorized research task.",
            "provider_transfer_basis": basis,
        })
    result = {
        "schema_version": "marinaframe-v04-inference-transfer-authorization-1",
        "created_utc": datetime.now(timezone.utc).isoformat(),
        "authorization_basis": "Existing user authorization for the MarinaFrame research campaign using the provisioned OpenCode Go DeepSeek account; this record narrows the data scope, and does not create a new purchase or provider authorization.",
        "provider": "OpenCode Go",
        "model": "deepseek-v4.1-flash",
        "input_root": str(input_root),
        "input_tree_sha256": index["input_tree_sha256"],
        "implementation_index_sha256": sha(index_path),
        "input_seal_receipt_sha256": sha(ROOT / "public_v2/seal_receipt.json"),
        "permitted_transfer": [
            "The exact deployment specification and source image bytes identified for the selected opaque case.",
            "Bounded crops, overlays, current-task candidate images and tool observations generated by the frozen runtime from those authorized inputs.",
        ],
        "excluded_transfer": [
            "Evaluation indices or case-level cohort/expected-outcome labels.",
            "Reference geometry, scoring tools or outputs, and other arms' results.",
            "Credentials, unrelated local files, and unlisted or restricted source material.",
        ],
        "capture_binding": "The root launcher must verify the listed input digests, capture the chosen source-only task, and bind the resulting source-manifest digest before live transfer. A changed source or substantive spec change requires a new mapping. A capture-only path relocation must preserve every substantive spec field and the exact source image bytes.",
        "credential_handling": "Credential is retained by the root launcher; this evaluator does not read or forward it.",
        "rights_provenance_verified_utc": "2026-11-06T18:25:53.044863+00:00",
        "case_count": len(cases),
        "cases": cases,
    }
    output = ROOT / "public_v2/provider_transfer_authorization.json"
    output.write_text(json.dumps(result, indent=2, sort_keys=True) + "\n")
    print(json.dumps({"output": str(output), "sha256": sha(output), "case_count": len(cases)}))


if __name__ == "__main__":
    main()
