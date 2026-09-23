from enum import Enum
from typing import List, Optional

from pydantic import BaseModel


class DocumentType(str, Enum):
    receipt = "receipt"
    invoice = "invoice"
    prescription = "prescription"
    id_card = "id_card"
    form = "form"
    unknown = "unknown"


class ExtractedField(BaseModel):
    key: str
    label: str
    value: str
    confidence: float


class ExtractionResult(BaseModel):
    document_type: DocumentType
    fields: List[ExtractedField]
    raw_text: str
    overall_confidence: float
    source: str


class ValidationFlag(BaseModel):
    rule: str
    severity: str
    message: str


class ValidationReport(BaseModel):
    status: str
    flags: List[ValidationFlag]


class ProcessDocumentResponse(BaseModel):
    pending_id: str
    extraction: ExtractionResult
    validation: ValidationReport


class ConfirmAndFileRequest(BaseModel):
    pending_id: str
    fields: List[ExtractedField]


class ConfirmAndFileResponse(BaseModel):
    filed: bool
    sheet_row: Optional[int] = None
    filing_error: Optional[str] = None
    validation: ValidationReport
    edited: bool
