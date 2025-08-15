import os
import logging
from datetime import datetime, timedelta
from pathlib import Path
from typing import Dict, Any
from reportlab.lib.pagesizes import letter
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.lib.units import inch
from reportlab.lib.colors import HexColor
from reportlab.platypus import SimpleDocTemplate, Table, TableStyle, Paragraph, Spacer, Image
from reportlab.lib.utils import ImageReader
from reportlab.lib import colors
from reportlab.lib.enums import TA_RIGHT, TA_CENTER

from session_store import get_invoice_data
from database import db

logger = logging.getLogger(__name__)

# Create output directory for PDFs
PDF_OUTPUT_DIR = Path("generated_invoices")
PDF_OUTPUT_DIR.mkdir(exist_ok=True)

def format_currency(amount: float) -> str:
    """Format amount as currency in British Pounds"""
    return f"£{amount:,.2f}"

def calculate_due_date(invoice_date: str, payment_due_days: int) -> str:
    """Calculate payment due date"""
    invoice_dt = datetime.fromisoformat(invoice_date)
    due_dt = invoice_dt + timedelta(days=payment_due_days)
    return due_dt.strftime("%B %d, %Y")

async def generate_invoice_pdf(session: Dict[str, Any], company_info: Dict[str, Any] = None) -> Path:
    """Generate PDF invoice from session data"""
    try:
        # Get invoice data
        session_id = session.get("session_id", "")
        invoice_data = get_invoice_data(session_id)
        
        if not invoice_data:
            raise ValueError("Invalid or incomplete invoice data")
        
        # Create PDF filename
        pdf_filename = f"invoice_{invoice_data.reference_number}_{datetime.now().strftime('%Y%m%d_%H%M%S')}.pdf"
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
        
        # Add Company Header if provided
        if company_info and (company_info.get('name') or company_info.get('logo')):
            # Company header table data
            company_header_data = []
            
            # If we have a logo, create a two-column layout
            if company_info.get('logo'):
                try:
                    import base64
                    import io
                    
                    # Decode base64 logo
                    logo_data = company_info['logo']
                    if logo_data.startswith('data:image'):
                        # Remove data URL prefix
                        logo_data = logo_data.split(',', 1)[1]
                    
                    logo_bytes = base64.b64decode(logo_data)
                    logo_image = ImageReader(io.BytesIO(logo_bytes))
                    
                    # Create logo image with max size constraints
                    logo = Image(logo_image, width=1.5*inch, height=1.5*inch)
                    logo.hAlign = 'LEFT'
                    
                    # Company info text
                    company_text_parts = []
                    if company_info.get('name'):
                        company_text_parts.append(f"<b>{company_info['name']}</b>")
                    if company_info.get('address'):
                        company_text_parts.append(company_info['address'].replace('\n', '<br/>'))
                    if company_info.get('phone'):
                        company_text_parts.append(f"Tel: {company_info['phone']}")
                    if company_info.get('email'):
                        company_text_parts.append(f"Email: {company_info['email']}")
                    if company_info.get('website'):
                        company_text_parts.append(company_info['website'])
                    if company_info.get('vat'):
                        company_text_parts.append(f"VAT No: {company_info['vat']}")
                    if company_info.get('registration'):
                        company_text_parts.append(f"Company Reg: {company_info['registration']}")
                    
                    company_text = Paragraph('<br/>'.join(company_text_parts), normal_style)
                    
                    # Create header table with logo and company info
                    company_header_data = [[logo, company_text]]
                    
                except Exception as e:
                    logger.warning(f"Failed to process company logo: {str(e)}")
                    # Fall back to text-only header
                    company_header_data = None
            
            # If we don't have a logo or logo processing failed, use text-only header
            if not company_header_data and company_info.get('name'):
                company_text_parts = []
                company_text_parts.append(f"<b>{company_info['name']}</b>")
                if company_info.get('address'):
                    company_text_parts.append(company_info['address'].replace('\n', '<br/>'))
                if company_info.get('phone'):
                    company_text_parts.append(f"Tel: {company_info['phone']}")
                if company_info.get('email'):
                    company_text_parts.append(f"Email: {company_info['email']}")
                if company_info.get('website'):
                    company_text_parts.append(company_info['website'])
                if company_info.get('vat'):
                    company_text_parts.append(f"VAT No: {company_info['vat']}")
                if company_info.get('registration'):
                    company_text_parts.append(f"Company Reg: {company_info['registration']}")
                
                company_text = Paragraph('<br/>'.join(company_text_parts), normal_style)
                company_header_data = [[company_text]]
            
            # Add company header table if we have data
            if company_header_data:
                if len(company_header_data[0]) == 2:  # Logo + text layout
                    company_table = Table(company_header_data, colWidths=[2*inch, 4*inch])
                    company_table.setStyle(TableStyle([
                        ('VALIGN', (0, 0), (-1, -1), 'TOP'),
                        ('LEFTPADDING', (0, 0), (-1, -1), 0),
                        ('RIGHTPADDING', (0, 0), (-1, -1), 0),
                        ('TOPPADDING', (0, 0), (-1, -1), 0),
                        ('BOTTOMPADDING', (0, 0), (-1, -1), 12),
                    ]))
                else:  # Text-only layout
                    company_table = Table(company_header_data, colWidths=[6*inch])
                    company_table.setStyle(TableStyle([
                        ('LEFTPADDING', (0, 0), (-1, -1), 0),
                        ('RIGHTPADDING', (0, 0), (-1, -1), 0),
                        ('TOPPADDING', (0, 0), (-1, -1), 0),
                        ('BOTTOMPADDING', (0, 0), (-1, -1), 12),
                    ]))
                
                elements.append(company_table)
                elements.append(Spacer(1, 0.3*inch))
        
        # Add Invoice Title
        elements.append(Paragraph("INVOICE", title_style))
        elements.append(Spacer(1, 0.2*inch))
        
        # Invoice Details Table
        # Use current date as invoice date
        invoice_date = datetime.now()
        invoice_details = [
            ['Invoice Number:', invoice_data.reference_number],
            ['Invoice Date:', invoice_date.strftime("%B %d, %Y")],
            ['Due Date:', invoice_data.details.due_date.strftime("%B %d, %Y")],
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
        
        # Invoice To Section
        elements.append(Paragraph("Invoice To:", heading_style))
        elements.append(Paragraph(invoice_data.client.name, normal_style))
        elements.append(Paragraph(invoice_data.client.address, normal_style))
        elements.append(Spacer(1, 0.3*inch))
        
        # Line Items Table
        elements.append(Paragraph("Items:", heading_style))
        
        # Prepare line items data with enhanced columns
        items_data = [['Description', 'Amount', 'VAT Rate', 'VAT Amount', 'Net Amount']]
        
        subtotal = 0.0
        total_vat = 0.0
        total_cis_deduction = 0.0
        total_retention_deduction = 0.0
        total_discount = 0.0
        
        # Process each item with proper calculations
        for item in invoice_data.items:
            base_amount = item.value
            vat_amount = base_amount * (item.vat_rate / 100) if item.vat_rate > 0 else 0.0
            net_amount = base_amount + vat_amount
            
            # Track deductions for summary section
            cis_deduction = base_amount * (item.cis_rate / 100) if item.cis_rate > 0 else 0.0
            retention_deduction = base_amount * (item.retention_rate / 100) if item.retention_rate > 0 else 0.0
            discount_amount = base_amount * (item.discount_rate / 100) if item.discount_rate > 0 else 0.0
            
            total_cis_deduction += cis_deduction
            total_retention_deduction += retention_deduction
            total_discount += discount_amount
            
            subtotal += base_amount
            total_vat += vat_amount
            
            # Add item row with capitalized description
            vat_display = f"{item.vat_rate:.1f}%" if item.vat_rate > 0 else "0%"
            capitalized_description = item.description.capitalize() if item.description else ""
            items_data.append([
                capitalized_description,
                format_currency(base_amount),
                vat_display,
                format_currency(vat_amount),
                format_currency(net_amount)
            ])
        
        # Calculate totals
        gross_total = subtotal + total_vat
        net_payable = gross_total - total_cis_deduction - total_retention_deduction - total_discount
        
        # Add summary rows
        items_data.append(['', '', '', '', ''])  # Empty row for spacing
        items_data.append(['', '', '', 'Subtotal:', format_currency(subtotal)])
        
        if total_vat > 0:
            items_data.append(['', '', '', 'Total VAT:', format_currency(total_vat)])
        
        items_data.append(['', '', '', 'Gross Total:', format_currency(gross_total)])
        
        # Add deductions
        if total_discount > 0:
            items_data.append(['', '', '', 'Less: Discount:', f'-{format_currency(total_discount)}'])
        
        if total_cis_deduction > 0:
            items_data.append(['', '', '', 'Less: CIS Deduction:', f'-{format_currency(total_cis_deduction)}'])
        
        if total_retention_deduction > 0:
            items_data.append(['', '', '', 'Less: Retention:', f'-{format_currency(total_retention_deduction)}'])
        
        items_data.append(['', '', '', 'Net Payable:', format_currency(net_payable)])
        
        # Create items table with updated column widths
        items_table = Table(items_data, colWidths=[2.5*inch, 1*inch, 0.8*inch, 1*inch, 1.2*inch])
        
        # Calculate row positions for styling
        header_row = 0
        data_start = 1
        summary_start = len(items_data) - (
            7 +  # Base summary rows (empty, subtotal, vat, gross, net payable)
            (1 if total_discount > 0 else 0) +
            (1 if total_cis_deduction > 0 else 0) +
            (1 if total_retention_deduction > 0 else 0)
        )
        net_payable_row = len(items_data) - 1
        
        items_table.setStyle(TableStyle([
            # Header row
            ('BACKGROUND', (0, header_row), (-1, header_row), HexColor('#E5E9F0')),
            ('FONTNAME', (0, header_row), (-1, header_row), 'Helvetica-Bold'),
            ('FONTSIZE', (0, header_row), (-1, header_row), 10),
            ('ALIGN', (0, header_row), (-1, header_row), 'CENTER'),
            
            # Data rows
            ('FONTNAME', (0, data_start), (-1, summary_start-1), 'Helvetica'),
            ('FONTSIZE', (0, data_start), (-1, summary_start-1), 9),
            ('ALIGN', (1, data_start), (-1, summary_start-1), 'RIGHT'),
            ('ALIGN', (0, data_start), (0, summary_start-1), 'LEFT'),
            
            # Summary section
            ('FONTNAME', (3, summary_start), (-1, -1), 'Helvetica-Bold'),
            ('FONTSIZE', (3, summary_start), (-1, -1), 9),
            ('ALIGN', (3, summary_start), (-1, -1), 'RIGHT'),
            ('ALIGN', (4, summary_start), (-1, -1), 'RIGHT'),
            
            # Net Payable row (make it prominent)
            ('BACKGROUND', (3, net_payable_row), (-1, net_payable_row), HexColor('#E5E9F0')),
            ('FONTSIZE', (3, net_payable_row), (-1, net_payable_row), 11),
            ('LINEABOVE', (3, net_payable_row), (-1, net_payable_row), 2, colors.black),
            
            # Grid lines
            ('GRID', (0, header_row), (-1, summary_start-1), 0.5, HexColor('#D8DEE9')),
            ('BOX', (0, header_row), (-1, -1), 1, HexColor('#2E3440')),
            ('LINEABOVE', (3, summary_start+1), (-1, summary_start+1), 1, colors.black),
        ]))
        
        elements.append(items_table)
        elements.append(Spacer(1, 0.5*inch))
        
        # Payment Terms
        elements.append(Paragraph("Payment Terms:", heading_style))
        # Calculate days until due
        days_until_due = (invoice_data.details.due_date - datetime.now().date()).days
        payment_terms_text = f"Payment due within {days_until_due} days."
        
        # Add notes about deductions if applicable (each on new line)
        if total_cis_deduction > 0 or total_retention_deduction > 0 or total_discount > 0:
            payment_terms_text += "<br/><br/><strong>Notes:</strong><br/>"
            
            if total_cis_deduction > 0:
                payment_terms_text += f"• CIS deduction of {format_currency(total_cis_deduction)} applied<br/>"
            if total_retention_deduction > 0:
                payment_terms_text += f"• Retention of {format_currency(total_retention_deduction)} held<br/>"
            if total_discount > 0:
                payment_terms_text += f"• Discount of {format_currency(total_discount)} applied<br/>"
        
        elements.append(Paragraph(payment_terms_text, normal_style))
        
        # Build PDF
        doc.build(elements)
        
        # Save invoice to database
        db.save_invoice(session_id, invoice_data.model_dump(mode='json'), str(pdf_path))
        
        logger.info(f"Generated PDF invoice: {pdf_path}")
        return pdf_path
        
    except Exception as e:
        logger.error(f"Error generating PDF: {str(e)}")
        raise