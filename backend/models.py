
from sqlalchemy import MetaData, Table

from database import engine

metadata = MetaData()


def get_table(table_name: str) -> Table:
    return Table(
        table_name,
        metadata,
        autoload_with=engine,
        extend_existing=True,
    )


Account = get_table("ACCOUNT")
Patient = get_table("PATIENT")
Visit = get_table("VISIT")
VisitStatusHistory = get_table("VISIT_STATUS_HISTORY")
CaseRecord = get_table("CASE_RECORD")

PatientPrescription = get_table("PATIENT_PRESP")
PrescriptionVersion = get_table("PATIENT_PRESP_VERSION")
PrescriptionDelivery = get_table("PRESP_DELIVERY")
PrescriptionPrintHistory = get_table("PRESP_PRINT_HISTORY")

Invitation = get_table("INVITATION")
ChatMessage = get_table("CHAT_MESSAGE")
