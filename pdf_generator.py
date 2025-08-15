import os
import logging
from datetime import datetime, timedelta
from pathlib import Path
from typing import Dict, Any
from reportlab.lib.pagesizes import letter
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.lib.units import inch
from reportlab.lib.colors import HexColor
from reportlab.platypus import SimpleDocTemplate, Table, TableStyle, Paragraph, Spacer
from reportlab.lib import colors
from reportlab.lib.enums import TA_RIGHT, TA_CENTER

from session_store_improved import get_invoice_data
from database import db

logger = logging.getLogger(__name__)

# Create output directory for PDFs
PDF_OUTPUT_DIR = Path("generated_invoices")
PDF_OUTPUT_DIR.mkdir(exist_ok=True)

def format_currency(amount: float) -> str:
    """Format amount as currency"""
    return f"${amount:,.2f}"

def calculate_due_date(invoice_date: str, payment_due_days: int) -> str:
    """Calculate payment due date"""
    invoice_dt = datetime.fromisoformat(invoice_date)
    due_dt = invoice_dt + timedelta(days=payment_due_days)
    return due_dt.strftime("%B %d, %Y")

async def generate_invoice_pdf(session: Dict[str, Any]) -> Path:
    """Generate PDF invoice from session data"""
    try:
        # Get invoice data
        session_id = session.get("session_id", "")
        invoice_data = get_invoice_data(session_id)
        
        if not invoice_data:
            raise ValueError("Invalid or incomplete invoice data")
        
        # Create PDF filename
        pdf_filename = f"invoice_{invoice_data.invoice_number}_{datetime.now().strftime('%Y%m%d_%H%M%S')}.pdf"
        pdf_path = PDF_OUTPUT_DIR / pdf_filename
        
        # Create PDF document
        doc = SimpleDocTemplate(
            str(pdf_path),
            pagesize=letter,
            rightMargin=72,
            leftMargin=72,
            topMargin=72,
            bottomMargin=18,
        )
        
        # Container for the 'Flowable' objects
        elements = []
        
        # Define styles
        styles = getSampleStyleSheet()
        title_style = ParagraphStyle(
            'CustomTitle',
            parent=styles['Heading1'],
            fontSize=24,
            textColor=HexColor('#2E3440'),
            spaceAfter=30,
            alignment=TA_CENTER
        )
        
        heading_style = ParagraphStyle(
            'CustomHeading',
            parent=styles['Heading2'],
            fontSize=14,
            textColor=HexColor('#2E3440'),
            spaceAfter=12,
        )
        
        normal_style = styles['Normal']
        right_style = ParagraphStyle(
            'RightAlign',
            parent=styles['Normal'],
            alignment=TA_RIGHT
        )
        
        # Add Invoice Title
        elements.append(Paragraph("INVOICE", title_style))
        elements.append(Spacer(1, 0.2*inch))
        
        # Invoice Details Table
        invoice_details = [
            ['Invoice Number:', invoice_data.invoice_number],
            ['Invoice Date:', datetime.fromisoformat(invoice_data.invoice_date).strftime("%B %d, %Y")],
            ['Due Date:', calculate_due_date(invoice_data.invoice_date, invoice_data.payment_due_days)],
        ]
        
        details_table = Table(invoice_details, colWidths=[2*inch, 3*inch])
        details_table.setStyle(TableStyle([
            ('ALIGN', (0, 0), (0, -1), 'RIGHT'),
            ('ALIGN', (1, 0), (1, -1), 'LEFT'),
            ('FONTNAME', (0, 0), (0, -1), 'Helvetica-Bold'),
            ('FONTSIZE', (0, 0), (-1, -1), 10),
            ('BOTTOMPADDING', (0, 0), (-1, -1), 8),
        ]))
        elements.append(details_table)
        elements.append(Spacer(1, 0.3*inch))
        
        # Bill To Section
        elements.append(Paragraph("Bill To:", heading_style))
        elements.append(Paragraph(invoice_data.client_name, normal_style))
        elements.append(Paragraph(invoice_data.client_address, normal_style))
        if invoice_data.client_email:
            elements.append(Paragraph(invoice_data.client_email, normal_style))
        if invoice_data.client_phone:
            elements.append(Paragraph(invoice_data.client_phone, normal_style))
        elements.append(Spacer(1, 0.3*inch))
        
        # Line Items Table
        elements.append(Paragraph("Items:", heading_style))
        
        # Prepare line items data
        items_data = [['Description', 'Quantity', 'Unit', 'Unit Price', 'Total']]
        subtotal = 0.0
        
        for item in invoice_data.items:
            total = item.quantity * item.unit_price
            subtotal += total
            items_data.append([
                item.description,
                str(item.quantity),
                item.unit,
                format_currency(item.unit_price),
                format_currency(total)
            ])
        
        # Add subtotal, tax, and total rows
        tax_rate = 0.0  # Can be made configurable
        tax_amount = subtotal * tax_rate
        total = subtotal + tax_amount
        
        items_data.append(['', '', '', 'Subtotal:', format_currency(subtotal)])
        if tax_rate > 0:
            items_data.append(['', '', '', f'Tax ({tax_rate*100}%):', format_currency(tax_amount)])
        items_data.append(['', '', '', 'Total:', format_currency(total)])
        
        # Create items table
        items_table = Table(items_data, colWidths=[3*inch, 0.75*inch, 0.75*inch, 1*inch, 1*inch])
        items_table.setStyle(TableStyle([
            # Header row
            ('BACKGROUND', (0, 0), (-1, 0), HexColor('#E5E9F0')),
            ('FONTNAME', (0, 0), (-1, 0), 'Helvetica-Bold'),
            ('FONTSIZE', (0, 0), (-1, 0), 10),
            ('ALIGN', (0, 0), (-1, 0), 'CENTER'),
            
            # Data rows
            ('FONTNAME', (0, 1), (-1, -4), 'Helvetica'),
            ('FONTSIZE', (0, 1), (-1, -1), 9),
            ('ALIGN', (1, 1), (2, -1), 'CENTER'),
            ('ALIGN', (3, 1), (4, -1), 'RIGHT'),
            
            # Totals rows
            ('FONTNAME', (3, -3), (-1, -1), 'Helvetica-Bold'),
            ('LINEABOVE', (3, -3), (-1, -3), 1, colors.black),
            
            # Grid
            ('GRID', (0, 0), (-1, -4), 0.5, HexColor('#D8DEE9')),
            ('BOX', (0, 0), (-1, -1), 1, HexColor('#2E3440')),
        ]))
        
        elements.append(items_table)
        elements.append(Spacer(1, 0.5*inch))
        
        # Payment Terms
        elements.append(Paragraph("Payment Terms:", heading_style))
        payment_terms_text = f"Payment due within {invoice_data.payment_due_days} days"
        if invoice_data.late_fee_percentage:
            payment_terms_text += f". Late fee of {invoice_data.late_fee_percentage}% will apply after due date."
        elements.append(Paragraph(payment_terms_text, normal_style))
        
        # Build PDF
        doc.build(elements)
        
        # Save invoice to database
        db.save_invoice(session_id, invoice_data.dict(), str(pdf_path))
        
        logger.info(f"Generated PDF invoice: {pdf_path}")
        return pdf_path
        
    except Exception as e:
        logger.error(f"Error generating PDF: {str(e)}")
        raise