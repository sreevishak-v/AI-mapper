import re
import json
import logging
from sentence_transformers import SentenceTransformer, util
import requests
from typing import Dict, List

logger = logging.getLogger(__name__)
logging.basicConfig(level=logging.INFO)

model = SentenceTransformer('all-MiniLM-L6-v2')

USE_LLM = True

form_keys = {
    "patientName": ["Name", "Patient Name", "Subscriber"],
    "patientDateOfBirth": ["Date of Birth", "Patient DOB", "DOB"],
    "gender": ["Gender", "Sex"],
    "subscriberName": ["Subscriber", "Subscriber Name", "Insured Name"],
    "subscriberId": ["Patient ID", "Subscriber ID", "Member ID"],
    "subscriberDateOfBirth": ["Date of Birth", "Subscriber DOB", "DOB"],
    "subscriberRelationship": ["Relationship", "Subscriber Relationship"],
    "address": ["Address"],
    "payorName": ["Account Name", "Group Name", "Insurance Provider", "Carrier Name"],
    "payorTel": ["Claim Address", "Payor Tel. No"],
    "payerId": ["Electronic Payer ID"],
    "planName": ["Plan", "Plan Type", "Plan Name"],
    "groupNumber": ["Group Number", "Account #"],
    "insuranceType": ["Insurance Type", "Plan Type", "Type"],
    "employer": ["Group Name", "Account Name", "Employer Name"],
    "planResetDate": ["Plan Renews", "Reset Date"],
    "planType": ["Plan Type", "Type"],
    "benefitsCoordinationMethod": ["Other Insurance?", "Other Insurance", "COB", "Benefits Coordination"],
    "verifiedDate": ["Verification Date", "Verified Date"],
    "participationType": ["Participation Type", "Network Type", "Participation"],
    "effectiveDate": ["Coverage From", "Initial Coverage Date", "Effective Date"],
    "terminationDate": ["Coverage To", "Termination Date"],
    "familyMaximum": ["Family Maximum", "Family Calendar Year Maximum"],
    "familyMaxRemaining": ["Family Max. Remaining", "Family Maximum Remaining"],
    "individualMaximum": ["Individual Maximum", "Individual Calendar Year Maximum"],
    "individualMaxRemaining": ["Individual Max. Remaining", "Individual Maximum Remaining"],
    "familyDeductible": ["Family Deductible", "Family Calendar Year Deductible"],
    "familyDeductibleRemaining": ["Family Deductible Remaining"],
    "individualDeductible": ["Individual Deductible", "Individual Calendar Year Deductible"],
    "individualDeductibleRemaining": ["Individual Deductible Remaining"],
    "coinsurance": {
        "diagnostic": ["Diagnostic and Preventive"],
        "basicRestorative": ["Basic Restorative"],
        "majorRestorative": ["Major Restorative"],
        "orthodontics": ["Orthodontics"]
    },
    "frequencies": {
        "oralExam": ["Oral Exam", "Oral Examination"],
        "fullMouthXRays": ["Full Mouth X-Rays", "FMX/Pano Frequency", "FMX", "Full Mouth X"],
        "bitewingXRays": ["Bitewing X-Rays", "Bitewing X"],
        "adultCleaning": ["Adult Cleaning", "Prophy Frequency", "Prophy"],
        "topicalFluoride": ["Topical Fluoride"],
        "topicalSealant": ["Topical Sealant Application", "Topical Sealant", "Sealant"],
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
                threshold = 0.6
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
            threshold = 0.6
            if best_score > threshold and best_match in raw_data:
                mapped[target] = raw_data[best_match]
                logger.debug(f"Mapped {target} to {best_match} (score: {best_score})")
            else:
                mapped[target] = ""

    logger.debug(f"Vector mapping result: {json.dumps(mapped, indent=2)}")
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
Return a JSON object mapping the provided data to the specified fields. Only include fields with non-empty values. Structure coinsurance and frequencies as nested objects. Ensure 'patientName' is extracted as a proper name (e.g., 'Jazmin Angel'), not an ID. Use exact values from the data without modification. For 'familyMaximum', 'individualMaximum', 'familyDeductible', and 'individualDeductible', extract dollar amounts (e.g., '$1,500.00', '$50.00') from 'Total', 'Plan Details', or related fields, or from raw_data.benefits.maximum.family, raw_data.benefits.maximum.individual, raw_data.benefits.deductible.family, raw_data.benefits.deductible.individual if available. For 'familyMaxRemaining', 'individualMaxRemaining', 'familyDeductibleRemaining', and 'individualDeductibleRemaining', extract dollar amounts from bold text, related fields, or from raw_data.benefits.maximum.family_remaining, raw_data.benefits.maximum.individual_remaining, raw_data.benefits.deductible.family_remaining, raw_data.benefits.deductible.individual_remaining if available. Map 'benefitsCoordinationMethod' to 'No' if 'Other Insurance?: No' is present. Extract the full 'Pretreatment review' or 'Predetermination' text for 'preAuthRequired' exactly as it appears. For 'insuranceType', use the simplified plan type (e.g., 'PPO' from 'DENTAL PPO') if available.

Raw Data:
{json.dumps(raw_data, indent=2)}

Tables:
{json.dumps(simplified_tables, indent=2)}

Map to these fields:
{json.dumps(form_keys, indent=2)}

Example output:
{{
  "subscriberId": "U93162774 01",
  "effectiveDate": "10/01/2024",
  "terminationDate": "Present",
  "payorName": "DELI MANAGEMENT, INC. DBA JASON'S DELI",
  "patientName": "Jazmi Angel",
  "subscriberDateOfBirth": "01/26/2001",
  "gender": "Female",
  "subscriberRelationship": "Self",
  "planName": "DENTAL PPO",
  "groupNumber": "3327706",
  "insuranceType": "PPO",
  "employer": "DELI MANAGEMENT, INC.",
  "planResetDate": "",
  "planType": "DENTAL PPO",
  "benefitsCoordinationMethod": "No",
  "verifiedDate": "",
  "participationType": "",
  "familyMaximum": "$1,500.00",
  "familyMaxRemaining": "$1,500.00",
  "individualMaximum": "$2,500.00",
  "individualMaxRemaining": "$2,200.00",
  "familyDeductible": "$150.00",
  "familyDeductibleRemaining": "$50.00",
  "individualDeductible": "$50.00",
  "individualDeductibleRemaining": "$0.00",
  "coinsurance": {{
    "diagnostic": "0%",
    "basicRestorative": "20%",
    "majorRestorative": "50%",
    "orthodontics": "50%"
  }},
  "frequencies": {{
    "oralExam": "Twice Per Calendar Year",
    "fullMouthXRays": "Once Every 3 Years",
    "bitewingXRays": "Once Per Calendar Year",
    "adultCleaning": "Twice Per Calendar Year",
    "topicalFluoride": "Twice Per Calendar Year",
    "topicalSealant": "Once Per Year",
    "crown": "Once Per 60 Consecutive Months",
    "bridgeWork": "Once Per 60 Consecutive Months"
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
        response.raise_for_status()
        raw_response = response.json().get("response", "").strip()
        logger.debug(f"Raw LLM response: {raw_response[:200]}...")
        parsed_response = extract_json_from_llm(raw_response)
        logger.debug(f"LLM mapping result: {json.dumps(parsed_response, indent=2)}")
        return parsed_response
    except requests.RequestException as e:
        logger.error(f"LLM API request failed: {e}")
        return {}
    except Exception as e:
        logger.error(f"LLM Mapping failed: {e}", exc_info=True)
        return {}

def hybrid_field_mapper(raw_data: Dict, tables: List[Dict]) -> Dict:
    logger.info("Starting hybrid field mapping")
    logger.debug(f"Raw data: {json.dumps(raw_data, indent=2)}")
    logger.debug(f"Tables: {json.dumps(tables, indent=2)}")
    mapped = map_fields_with_vectors(raw_data)

    if USE_LLM:
        missing_fields = [k for k, v in mapped.items() if not v or (isinstance(v, dict) and not any(v.values()))]
        logger.debug(f"Missing fields before LLM mapping: {missing_fields}")
        if missing_fields:
            logger.info(f"Missing fields for LLM mapping: {missing_fields}")
            llm_result = map_fields_with_llm(raw_data, tables)
            for field in missing_fields:
                if field in llm_result:
                    mapped[field] = llm_result[field]
                    logger.debug(f"LLM filled field {field}: {mapped[field]}")

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
    logger.debug(f"Final mapped data: {json.dumps(mapped, indent=2)}")
    return mapped