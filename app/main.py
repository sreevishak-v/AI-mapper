from fastapi import FastAPI, UploadFile, File, HTTPException
from fastapi.middleware.cors import CORSMiddleware
import tempfile
import json
import logging
from typing import Dict
from pdf_parser import parse_pdf
from llm_mapper import hybrid_field_mapper
import os
import time
from datetime import datetime

app = FastAPI()

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

def transform_to_legacy_format(parsed_data: Dict) -> Dict:
    raw_data = {}
    for section, section_data in parsed_data['raw_data'].items():
        if isinstance(section_data, dict):
            raw_data.update(section_data)
        else:
            raw_data[section] = section_data
    return {
        'raw': raw_data,
        'tables': parsed_data.get('tables', [])
    }

def map_eligibility_data(parsed_data: Dict) -> Dict:
    logger.info("Mapping eligibility data")
    legacy_data = transform_to_legacy_format(parsed_data)
    mapped_data = hybrid_field_mapper(legacy_data['raw'], legacy_data['tables'])
    return {
        "mappedFields": mapped_data,
        "rawData": parsed_data['raw_data'],
        "tables": legacy_data['tables'],
        "fullText": parsed_data.get("full_text", "")
    }

@app.post("/parse-pdf/")
async def parse_pdf_endpoint(file: UploadFile = File(...)):
    tmp_path = None
    try:
        logger.info(f"Processing PDF at {datetime.now().strftime('%Y-%m-%d %H:%M:%S %Z')}: {file.filename}")
        with tempfile.NamedTemporaryFile(delete=False, suffix=".pdf") as tmp:
            tmp.write(await file.read())
            tmp_path = tmp.name
        parsed_data = parse_pdf(tmp_path)
        logger.info(f"Raw data extracted from {file.filename}:\n{json.dumps(parsed_data['raw_data'], indent=2)}")
        logger.debug(f"Full parsed data for {file.filename}: {json.dumps(parsed_data, indent=2)}")
        mapped_data = map_eligibility_data(parsed_data)
        logger.debug(f"Mapped data: {json.dumps(mapped_data, indent=2)}")
        return {"status": "success", "data": mapped_data}
    except NameError as e:
        logger.error(f"NameError processing PDF {file.filename}: {str(e)}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"Internal error: {str(e)}")
    except Exception as e:
        logger.error(f"Error processing PDF {file.filename}: {str(e)}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"Failed to process PDF: {str(e)}")
    finally:
        if tmp_path and os.path.exists(tmp_path):
            for attempt in range(3):
                try:
                    os.remove(tmp_path)
                    logger.debug(f"Successfully deleted temporary file: {tmp_path}")
                    break
                except PermissionError as e:
                    logger.warning(f"Attempt {attempt + 1}: Failed to delete {tmp_path}: {str(e)}. Retrying after delay...")
                    time.sleep(1)
                except Exception as e:
                    logger.error(f"Unexpected error deleting {tmp_path}: {str(e)}")
                    break
            else:
                logger.error(f"Failed to delete temporary file after retries: {tmp_path}")