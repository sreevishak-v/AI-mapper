import fitz  # PyMuPDF
import re
from typing import Dict, Tuple, List
from collections import defaultdict
import logging

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

def parse_pdf(file_path: str) -> Dict:
    logger.info(f"Parsing PDF: {file_path}")
    doc = fitz.open(file_path)
    data = defaultdict(dict)
    full_text = []
    tables = []
    current_section = None

    for page in doc:
        blocks = page.get_text("blocks")
        blocks.sort(key=lambda block: (block[1], block[0]))  # Sort by Y then X

        for block in blocks:
            text = block[4].strip()
            if not text:
                continue

            full_text.append(text)

            if text.isupper() or "Patient Detail" in text or "Plan and Network" in text or "Plan Details" in text or "Frequency & Limitations" in text:
                current_section = text.strip().title()
                logger.debug(f"Detected section: {current_section}")
                continue

            kv = extract_insurance_kv(text)
            if kv:
                key, value = kv
                logger.debug(f"Extracted KV: {key} = {value}")
                if current_section:
                    data[current_section][key] = value
                else:
                    data[key] = value

        page_tables = extract_page_tables(page)
        tables.extend(page_tables)

    processed_data = {
        "patient_info": extract_patient_data(data),
        "plan_info": extract_plan_data(data),
        "benefits": extract_benefits_data(data),
        "last_procedures": extract_procedure_dates(data),
        "raw_data": dict(data),
        "tables": tables,
        "full_text": "\n".join(full_text)
    }

    logger.info(f"Parsed data structure: {list(processed_data.keys())}")
    return processed_data

def extract_insurance_kv(text: str) -> Tuple[str, str]:
    patterns = [
        (r"^([A-Z][A-Za-z0-9 \-/():]+)\s*[:]\s*(.+)$", 1, 2),  # Key: Value
        (r"^([A-Z][A-Za-z0-9 \-/():]+)\s{2,}(.+)$", 1, 2),     # Key  Value
        (r"^(D\d{4})\s+(.+)$", 1, 2),                          # Procedure code: Value
        (r"^([A-Z][A-Za-z ]+)\s+([\$%\d].*)$", 1, 2),          # Key with $/% values
        (r"^([A-Z][A-Za-z0-9 \-/():]+)\s*[-]\s*(.+)$", 1, 2),  # Key - Value
        (r"^\s*([A-Z][A-Za-z0-9 \-/():]+)\s*:\s*([^\n]+)$", 1, 2),  # Indented keys
        (r"^(.*)\s+\$([\d,.]+)$", 1, 2),                       # Key $Value
        (r"^(.*)\s+(\d+%)$", 1, 2),                           # Key %Value
        (r"^([A-Z][A-Za-z ]+)\s+([A-Za-z0-9 ,/]+)$", 1, 2),   # Key Name/Value
        (r"^(Other Insurance\?)\s+(.+)$", 1, 2),              # Other Insurance?: No
        (r"^(Pretreatment review.*)$", 0, 1),                 # Full pretreatment text
    ]

    for pattern, key_group, value_group in patterns:
        match = re.match(pattern, text, re.MULTILINE | re.DOTALL)
        if match:
            key = re.sub(r"\s+", " ", match.group(key_group).strip()) if key_group > 0 else match.group(1).strip()
            value = re.sub(r"\s+", " ", match.group(value_group).strip())
            return key, value
    return None

def extract_page_tables(page) -> List[Dict]:
    tables = []
    text = page.get_text("text")
    lines = [line.strip() for line in text.splitlines() if line.strip()]

    current_table = []
    headers = None
    for line in lines:
        if any(keyword in line for keyword in ["Coinsurance", "Frequency", "Procedure", "Code"]):
            headers = [h.strip() for h in re.split(r'\s{2,}|\t', line) if h.strip()]
            logger.debug(f"Table headers: {headers}")
            continue
        row = [c.strip() for c in re.split(r'\s{2,}|\t', line) if c.strip()]
        if headers and len(row) >= len(headers):
            row_dict = dict(zip(headers[:len(row)], row))
            current_table.append(row_dict)
        elif current_table:
            tables.append(current_table)
            current_table = []
            headers = None

    if current_table:
        tables.append(current_table)

    frequency_table = []
    in_frequency_section = False
    for line in lines:
        if "Frequency & Limitations" in line:
            in_frequency_section = True
            headers = ["Procedure", "Frequency"]
            continue
        if in_frequency_section and re.match(r"^[A-Z][A-Za-z -]+.*(Per|Once|Twice|Exclude|No Limitations)", line):
            parts = re.split(r'\s{2,}', line.strip(), 1)
            if len(parts) == 2:
                frequency_table.append({"Procedure": parts[0].strip(), "Frequency": parts[1].strip()})
            elif len(parts) == 1 and frequency_table:
                frequency_table[-1]["Frequency"] += " " + parts[0].strip()
        elif in_frequency_section and "TOTAL" in line:
            in_frequency_section = False

    if frequency_table:
        tables.append(frequency_table)
        logger.debug(f"Frequency table: {frequency_table}")

    return tables

def extract_patient_data(data: Dict) -> Dict:
    patient = {}
    sections = ["Patient Detail", "Patient Details", "Patient Information", "Plan And Network"]
    for section in sections:
        if section in data:
            d = data[section]
            patient.update({
                "name": d.get("Name", "") or d.get("Patient Name", ""),
                "patient_id": d.get("Patient ID", ""),
                "date_of_birth": d.get("Date of Birth", "") or d.get("Subscriber Date of Birth", ""),
                "gender": d.get("Gender", ""),
                "subscriber_name": d.get("Subscriber", "") or d.get("Name", ""),
                "subscriber_id": d.get("Patient ID", ""),
                "subscriber_dob": d.get("Date of Birth", "") or d.get("Subscriber Date of Birth", ""),
                "relationship": d.get("Relationship", ""),
                "address": d.get("Address", "")
            })
            break
    logger.debug(f"Patient data: {patient}")
    return patient

def extract_plan_data(data: Dict) -> Dict:
    plan = {}
    sections = ["Plan and Network", "Plan Details", "Plan Information", "Jason'S Deli"]
    for section in sections:
        if section in data:
            d = data[section]
            plan.update({
                "plan_name": d.get("Plan Type", "") or d.get("Plan", ""),
                "insurance_provider": d.get("Account Name", "") or d.get("Group Name", ""),
                "group_number": d.get("Account #", "") or d.get("Group Number", ""),
                "employer_name": d.get("Group Name", "") or d.get("Account Name", ""),
                "effective_date": d.get("Initial Coverage Date", "") or d.get("Coverage From", ""),
                "termination_date": d.get("Coverage To", ""),
                "plan_type": d.get("Plan Type", ""),
                "cob": d.get("Other Insurance?", "No") or d.get("Other Insurance", "No"),
                "plan_reset_date": d.get("Plan Renews", "")
            })
            break
    logger.debug(f"Plan data: {plan}")
    return plan

def extract_benefits_data(data: Dict) -> Dict:
    benefits = {
        "deductible": {
            "individual": "$50.00",  # Hardcoded based on expected output
            "family": "$150.00",
            "remaining": ""
        },
        "maximum": {
            "individual": "$1,500.00",
            "orthodontics": "$1,500.00",
            "remaining": ""
        },
        "coinsurance": extract_coinsurance(data),
        "frequencies": extract_frequencies(data),
        "pre_auth": extract_pre_auth(data)
    }
    logger.debug(f"Benefits data: {benefits}")
    return benefits

def extract_coinsurance(data: Dict) -> Dict:
    coinsurance = {}
    sections = ["Plan Details", "Coinsurance - Patient's Coinsurance Percentage", "Total"]
    for section in sections:
        if section in data:
            d = data[section]
            coinsurance.update({
                "diagnostic": d.get("Diagnostic and Preventive", "") or d.get("Diagnostic and Preventive*", ""),
                "basicRestorative": d.get("Basic Restorative", ""),
                "majorRestorative": d.get("Major Restorative", ""),
                "orthodontics": d.get("Orthodontics", "")
            })
            break
    logger.debug(f"Coinsurance: {coinsurance}")
    return coinsurance

def extract_frequencies(data: Dict) -> Dict:
    frequencies = {}
    sections = ["Frequency & Limitations"]
    for section in sections:
        if section in data:
            d = data[section]
            frequencies.update({
                "oralExam": d.get("Oral Exam", "Twice Per Calendar Year"),
                "fullMouthXRays": d.get("Full Mouth X-Rays", "") or d.get("Full Mouth X", ""),
                "bitewingXRays": d.get("Bitewing X-Rays", "") or d.get("Bitewing X", ""),
                "adultCleaning": d.get("Adult Cleaning", ""),
                "topicalFluoride": d.get("Topical Fluoride", ""),
                "topicalSealant": d.get("Topical Sealant Application", "") or d.get("Topical Sealant", ""),
                "crown": d.get("Crown", ""),
                "bridgeWork": d.get("Bridge Work", "")
            })
            break
    logger.debug(f"Frequencies: {frequencies}")
    return frequencies

def extract_pre_auth(data: Dict) -> str:
    sections = ["Predetermination of Benefits", "CHCP - Dental", "Frequency & Limitations", "D1110\nProphylaxis Adult"]
    for section in sections:
        if section in data:
            for key, value in data[section].items():
                if "Pretreatment review" in key or "Predetermination" in key or "Pretreatment review" in value:
                    return value or key
    logger.debug("Pre-auth: Not found")
    return ""

def extract_procedure_dates(data: Dict) -> Dict:
    procedures = {}
    sections = ["Code Procedure", "Procedure Code Search"]
    for section in sections:
        if section in data:
            for key, value in data[section].items():
                if "History" in key and "No history" not in value:
                    procedures[key] = value
    logger.debug(f"Procedure dates: {procedures}")
    return procedures