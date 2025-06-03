import re
import json
import logging
from sentence_transformers import SentenceTransformer, util
import requests
from typing import Dict, List
import uuid

logger = logging.getLogger(__name__)
logging.basicConfig(level=logging.INFO)

model = SentenceTransformer('all-MiniLM-L6-v2')

USE_LLM = True

form_keys = {
    "patientName": ["Name", "Patient Name"],
    "patientDateOfBirth": ["Date of Birth", "Patient DOB"],
    "gender": ["Gender"],
    "subscriberName": ["Subscriber", "Subscriber Name"],
    "subscriberId": ["Patient ID", "Subscriber ID"],
    "subscriberDateOfBirth": ["Date of Birth", "Subscriber DOB"],
    "subscriberRelationship": ["Relationship", "Subscriber Relationship"],
    "address": ["Address"],
    "payorName": ["Account Name", "Group Name", "Insurance Provider"],
    "payorTel": ["Claim Address", "Payor Tel. No"],
    "payerId": ["Electronic Payer ID"],
    "planName": ["Plan", "Plan Type"],
    "groupNumber": ["Group Number", "Account #"],
    "employerName": ["Group Name", "Account Name", "Employer Name"],
    "effectiveDate": ["Coverage From", "Initial Coverage Date", "Effective Date"],
    "terminationDate": ["Coverage To", "Termination Date"],
    "planType": ["Plan Type"],
    "cob": ["Other Insurance?", "Other Insurance"],
    "planResetDate": ["Plan Renews"],
    "individualDeductible": ["Individual Calendar Year Deductible", "Deductible"],
    "familyDeductible": ["Family Calendar Year Deductible", "Family Deductible"],
    "individualMaximum": ["Individual Calendar Year Maximum", "Maximum"],
    "orthodonticsMaximum": ["Individual Lifetime Maximum", "Orthodontics Maximum"],
    "coinsurance": {
        "diagnostic": ["Diagnostic and Preventive"],
        "basicRestorative": ["Basic Restorative"],
        "majorRestorative": ["Major Restorative"],
        "orthodontics": ["Orthodontics"]
    },
    "frequencies": {
        "oralExam": ["Oral Exam"],
        "fullMouthXRays": ["Full Mouth X-Rays", "FMX/Pano Frequency"],
        "bitewingXRays": ["Bitewing X-Rays"],
        "adultCleaning": ["Adult Cleaning", "Prophy Frequency"],
        "topicalFluoride": ["Topical Fluoride"],
        "topicalSealant": ["Topical Sealant Application", "Topical Sealant"],
        "crown": ["Crown"],
        "bridgeWork": ["Bridge Work"]
    },
    "preAuthRequired": ["Pretreatment review is available", "Predetermination", "Pre Auth Required"]
}

def extract_json_from_llm(text: str) -> dict:
    try:
        text = re.sub(r'```json\n|```', '', text).strip()
        text = re.sub(r'//.*?\n|/\*.*?\*/', '', text, flags=re.DOTALL)
        if not text.startswith('{'):
            json_match = re.search(r'\{.*\}', text, re.DOTALL)
            if json_match:
                text = json_match.group(0)
            else:
                logger.error(f"No JSON-like content found in response: {text[:100]}...")
                return {}
        text = re.sub(r',\s*([}\]])', r'\1', text)
        text = re.sub(r'[^\x00-\x7F]+', '', text)
        text = re.sub(r'(\w+):', r'"\1":', text)
        text = re.sub(r':\s*([^"{[0-9][^,\]}]*)', r': "\1"', text)
        parsed_json = json.loads(text)
        if not isinstance(parsed_json, dict):
            logger.error("Parsed LLM response is not a dictionary.")
            return {}
        logger.debug(f"Parsed LLM JSON: {parsed_json}")
        return parsed_json
    except json.JSONDecodeError as e:
        logger.error(f"JSON Decode Error: {e}\nText: {text[:100]}...")
        return {}
    except Exception as e:
        logger.error(f"Unexpected error parsing JSON: {e}")
        return {}

def map_fields_with_vectors(raw_data: Dict) -> Dict:
    mapped = {
        "coinsurance": {},
        "frequencies": {}
    }
    raw_keys = list(raw_data.keys())
    if not raw_keys:
        logger.warning("No raw keys found for vector mapping")
        return mapped

    raw_embeddings = model.encode(raw_keys)

    for target, aliases in form_keys.items():
        if target in ["coinsurance", "frequencies"]:
            for sub_target, sub_aliases in aliases.items():
                alias_embeddings = model.encode(sub_aliases)
                best_score, best_match = -1, None
                for alias_emb in alias_embeddings:
                    for i, raw_emb in enumerate(raw_embeddings):
                        score = util.cos_sim(alias_emb, raw_emb).item()
                        if score > best_score:
                            best_score = score
                            best_match = raw_keys[i]
                threshold = 0.7  # Increased for accuracy
                if best_score > threshold and best_match in raw_data:
                    mapped[target][sub_target] = raw_data[best_match]
                    logger.debug(f"Mapped {target}.{sub_target} to {best_match} (score: {best_score})")
        else:
            alias_embeddings = model.encode(aliases)
            best_score, best_match = -1, None
            for alias_emb in alias_embeddings:
                for i, raw_emb in enumerate(raw_embeddings):
                    score = util.cos_sim(alias_emb, raw_emb).item()
                    if score > best_score:
                        best_score = score
                        best_match = raw_keys[i]
            threshold = 0.7
            if best_score > threshold and best_match in raw_data:
                mapped[target] = raw_data[best_match]
                logger.debug(f"Mapped {target} to {best_match} (score: {best_score})")
            else:
                mapped[target] = ""

    return mapped

def map_fields_with_llm(raw_data: Dict, tables: List[Dict]) -> Dict:
    if not USE_LLM:
        logger.info("Skipping LLM mapping (USE_LLM = False)")
        return {}

    try:
        simplified_tables = []
        for table in tables[:3]:
            simplified = []
            for row in table:
                row_data = {k: v for k, v in row.items() if k and v and len(str(v)) < 50}
                if row_data:
                    simplified.append(row_data)
            if simplified:
                simplified_tables.append(simplified)

        prompt = f"""You are an assistant that extracts field values from insurance raw data.
Return a JSON object mapping the provided data to the specified fields. Only include fields with non-empty values. Structure coinsurance and frequencies as nested objects. Ensure 'patientName' is extracted as a proper name (e.g., 'Jazmin Angel'), not an ID. Use exact values from the data without modification. For 'individualDeductible', 'familyDeductible', 'individualMaximum', and 'orthodonticsMaximum', extract dollar amounts (e.g., '$50.00', '$1,500.00') from 'Total' or related fields. Map 'cob' to 'No' if 'Other Insurance?: No' is present. Extract the full 'Pretreatment review' text for 'preAuthRequired'.

Raw Data:
{json.dumps(raw_data, indent=2)}

Tables:
{json.dumps(simplified_tables, indent=2)}

Map to these fields:
{json.dumps(form_keys, indent=2)}

Example output:
{{
  "patientName": "Jazmin Angel",
  "subscriberId": "U93162770 01",
  "effectiveDate": "10/01/2024",
  "terminationDate": "Present",
  "gender": "Female",
  "payorName": "DELI MANAGEMENT, INC. DBA JASON'S DELI",
  "cob": "No",
  "individualDeductible": "$50.00",
  "coinsurance": {{
    "diagnostic": "0%",
    "basicRestorative": "20%"
  }},
  "frequencies": {{
    "oralExam": "Twice Per Calendar Year"
  }},
  "preAuthRequired": "Pretreatment review is available on a voluntary basis when dental work in excess of $200 is proposed by the provider."
}}
"""

        logger.info("Sending prompt to LLM")
        response = requests.post(
            "http://localhost:11434/api/generate",
            json={
                "model": "phi",
                "prompt": prompt,
                "stream": False,
                "options": {
                    "temperature": 0.3,
                    "num_ctx": 4096
                }
            },
            timeout=60
        )

        if response.status_code != 200:
            logger.error(f"LLM API Error: {response.status_code} - {response.text}")
            return {}

        raw_response = response.json().get("response", "").strip()
        logger.debug(f"LLM response: {raw_response[:200]}...")
        return extract_json_from_llm(raw_response)

    except Exception as e:
        logger.error(f"LLM Mapping failed: {e}", exc_info=True)
        return {}

def hybrid_field_mapper(raw_data: Dict, tables: List[Dict]) -> Dict:
    logger.info("Starting hybrid field mapping")
    mapped = map_fields_with_vectors(raw_data)

    if USE_LLM:
        missing_fields = [k for k, v in mapped.items() if not v or (isinstance(v, dict) and not any(v.values()))]
        if missing_fields:
            logger.info(f"Missing fields for LLM mapping: {missing_fields}")
            llm_result = map_fields_with_llm(raw_data, tables)
            for field in missing_fields:
                if field in llm_result:
                    mapped[field] = llm_result[field]

    for key, value in mapped.items():
        if isinstance(value, str):
            mapped[key] = value.strip()
            if "N/A" in mapped[key] or not mapped[key]:
                mapped[key] = ""
        elif isinstance(value, dict):
            for sub_key, sub_value in value.items():
                if isinstance(sub_value, str):
                    value[sub_key] = sub_value.strip()
                    if "N/A" in sub_value or not sub_value:
                        value[sub_key] = ""

    logger.debug(f"Final mapped data: {mapped}")
    return mapped