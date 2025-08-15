import os
import logging
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, Any
from reportlab.lib.pagesizes import letter
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.lib.units import inch
from reportlab.lib.colors import HexColor
from reportlab.platypus import SimpleDocTemplate, Table, TableStyle, Paragraph, Spacer
from reportlab.lib import colors
from reportlab.lib.enums import TA_RIGHT, TA_CENTER

from session_store_aligned import get_invoice_data
from models import Invoice
from database import db

logger = logging.getLogger(__name__)

# Create output directory for PDFs
PDF_OUTPUT_DIR = Path("generated_invoices")
PDF_OUTPUT_DIR.mkdir(exist_ok=True)

def format_currency(amount: float) -> str:
    """Format amount as currency"""
    return f"£{amount:,.2f}"

def calculate_item_net(item: dict) -> float:
    """Calculate net amount for an item after discount"""
    value = item["value"]
    discount_rate = item.get("discount_rate", 0.0)
    discount_amount = value * (discount_rate / 100)
    return value - discount_amount

def calculate_item_deductions(item: dict, net_amount: float) -> dict:
    """Calculate all deductions for an item"""
    vat_rate = item.get("vat_rate", 0.0)
    cis_rate = item.get("cis_rate", 0.0)
    retention_rate = item.get("retention_rate", 0.0)
    
    vat_amount = net_amount * (vat_rate / 100)
    cis_amount = net_amount * (cis_rate / 100)
    retention_amount = net_amount * (retention_rate / 100)
    
    return {
        "vat": vat_amount,
        "cis": cis_amount,
        "retention": retention_amount,
        "gross": net_amount + vat_amount,
        "payable": net_amount + vat_amount - cis_amount - retention_amount
    }

async def generate_invoice_pdf(session: Dict[str, Any]) -> Path:
    """Generate PDF invoice from session data"""
    try:
        # Get invoice data
        session_id = session.get("session_id", "")
        invoice = get_invoice_data(session_id)
        
        if not invoice:
            raise ValueError("Invalid or incomplete invoice data")
        
        # Create PDF filename
        pdf_filename = f"{invoice.reference_number}_{datetime.now(timezone.utc).strftime('%Y%m%d_%H%M%S')}.pdf"
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
        
        # Add Invoice Title
        invoice_type_title = "DEPOSIT INVOICE" if invoice.details.type == "deposit" else "INVOICE"
        elements.append(Paragraph(invoice_type_title, title_style))
        elements.append(Spacer(1, 0.2*inch))
        
        # Invoice Details Table
        invoice_details = [
            ['Invoice Number:', invoice.reference_number],
            ['Invoice Date:', datetime.now(timezone.utc).strftime("%d %B %Y")],
            ['Due Date:', invoice.details.due_date.strftime("%d %B %Y")],
            ['Invoice Type:', invoice.details.type.replace("_", " ").title()],
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
        elements.append(Paragraph(invoice.client.name, normal_style))
        for line in invoice.client.address.split('\n'):
            elements.append(Paragraph(line.strip(), normal_style))
        elements.append(Spacer(1, 0.3*inch))
        
        # Items Table
        elements.append(Paragraph("Invoice Items:", heading_style))
        
        # Prepare items data with calculations
        items_data = [['Description', 'Value', 'Discount', 'Net', 'VAT', 'Gross']]
        
        total_net = 0.0
        total_vat = 0.0
        total_cis = 0.0
        total_retention = 0.0
        
        for item_dict in invoice.items:
            item = item_dict if isinstance(item_dict, dict) else item_dict.dict()
            
            net_amount = calculate_item_net(item)
            deductions = calculate_item_deductions(item, net_amount)
            
            total_net += net_amount
            total_vat += deductions["vat"]
            total_cis += deductions["cis"]
            total_retention += deductions["retention"]
            
            discount_text = f"{item.get('discount_rate', 0)}%" if item.get('discount_rate', 0) > 0 else "-"
            vat_text = f"{item.get('vat_rate', 0)}%" if item.get('vat_rate', 0) > 0 else "-"
            
            items_data.append([
                item["description"],
                format_currency(item["value"]),
                discount_text,
                format_currency(net_amount),
                vat_text,
                format_currency(deductions["gross"])
            ])
        
        # Calculate totals
        total_gross = total_net + total_vat
        total_deductions = total_cis + total_retention
        total_payable = total_gross - total_deductions
        
        # Add summary rows
        items_data.append(['', '', '', 'Subtotal:', '', format_currency(total_net)])
        if total_vat > 0:
            items_data.append(['', '', '', 'VAT:', '', format_currency(total_vat)])
        items_data.append(['', '', '', 'Gross Total:', '', format_currency(total_gross)])
        
        if total_cis > 0:
            items_data.append(['', '', '', 'Less CIS:', '', f'({format_currency(total_cis)})'])
        if total_retention > 0:
            items_data.append(['', '', '', 'Less Retention:', '', f'({format_currency(total_retention)})'])
        
        items_data.append(['', '', '', 'Amount Payable:', '', format_currency(total_payable)])
        
        # Create items table
        items_table = Table(items_data, colWidths=[2.5*inch, 0.9*inch, 0.8*inch, 0.9*inch, 0.7*inch, 1*inch])
        items_table.setStyle(TableStyle([
            # Header row
            ('BACKGROUND', (0, 0), (-1, 0), HexColor('#E5E9F0')),
            ('FONTNAME', (0, 0), (-1, 0), 'Helvetica-Bold'),
            ('FONTSIZE', (0, 0), (-1, 0), 10),
            ('ALIGN', (0, 0), (0, 0), 'LEFT'),
            ('ALIGN', (1, 0), (-1, 0), 'CENTER'),
            
            # Data rows
            ('FONTNAME', (0, 1), (-1, -7), 'Helvetica'),
            ('FONTSIZE', (0, 1), (-1, -1), 9),
            ('ALIGN', (1, 1), (-1, -1), 'RIGHT'),
            ('ALIGN', (0, 1), (0, -1), 'LEFT'),
            
            # Summary rows
            ('FONTNAME', (3, -6), (-1, -1), 'Helvetica-Bold'),
            ('LINEABOVE', (3, -6), (-1, -6), 1, colors.black),
            
            # Final total
            ('FONTNAME', (3, -1), (-1, -1), 'Helvetica-Bold'),
            ('FONTSIZE', (3, -1), (-1, -1), 11),
            ('LINEABOVE', (3, -1), (-1, -1), 2, colors.black),
            
            # Grid
            ('GRID', (0, 0), (-1, len(items_data) - 7), 0.5, HexColor('#D8DEE9')),
            ('BOX', (0, 0), (-1, -1), 1, HexColor('#2E3440')),
        ]))
        
        elements.append(items_table)
        elements.append(Spacer(1, 0.5*inch))
        
        # Payment Terms
        elements.append(Paragraph("Payment Terms:", heading_style))
        payment_text = f"Payment due by {invoice.details.due_date.strftime('%d %B %Y')}"
        elements.append(Paragraph(payment_text, normal_style))
        
        if invoice.details.type == "deposit":
            elements.append(Paragraph("This is a deposit invoice.", normal_style))
        
        # Build PDF
        doc.build(elements)
        
        # Save invoice to database
        db.save_invoice(session_id, invoice.dict(), str(pdf_path))
        
        logger.info(f"Generated PDF invoice: {pdf_path}")
        return pdf_path
        
    except Exception as e:
        logger.error(f"Error generating PDF: {str(e)}")
        raise