import enum
import logging

from sqlalchemy import Column, Date, Enum, Float, Integer, String
from sqlalchemy.orm import declarative_base

# Initialize logging context
logger = logging.getLogger(__name__)

Base = declarative_base()

class VatCompany(enum.Enum):
    """Enum representing the company holding the VAT."""
    KIT = "KIT"
    S16 = "S16"
    NONE = "NONE"

class VatStatus(enum.Enum):
    """Enum representing the current inventory status of the VAT."""
    AVAILABLE = "AVAILABLE"
    USED = "USED"

class VatInventory(Base):
    """Represents the complete lifecycle of a VAT product (Inbound and Outbound)."""
    __tablename__ = "vat_inventory"

    id = Column(Integer, primary_key=True, index=True)
    
    # --- Inbound Data (From Purchase File) ---
    receive_date = Column(Date, nullable=False)
    model = Column(String(255), nullable=False)
    imei = Column(String(100), unique=True, nullable=False, index=True)
    supplier_name = Column(String(255), nullable=False)
    vat_company = Column(Enum(VatCompany), nullable=False, default=VatCompany.NONE)
    cost = Column(Float, nullable=False, default=0.0)

    # --- Manual Data Entry (From UI) ---
    inbound_payment_method = Column(String(100), nullable=True)
    inbound_bank_or_company = Column(String(100), nullable=True)

    # --- Outbound Data (From Sales File) ---
    status = Column(Enum(VatStatus), nullable=False, default=VatStatus.AVAILABLE)
    used_date = Column(Date, nullable=True)
    customer_name = Column(String(255), nullable=True)
