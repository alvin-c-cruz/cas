"""SAWT + reconciliation over the certificates-received register.

SAWT renders ONLY from the register (certificates in hand). The reconciliation
diffs the register against what our SI/CRV say customers withheld (wht_lines,
payee side, expanded/creditable only). Both aggregate across branches because
withholding-tax filing is company-wide (per-TIN).
"""
from decimal import Decimal

from app.withholding_certificates.models import WithholdingCertificateReceived
from app.vat_settlement.service import quarter_bounds
from app.reports.wht_lines import wht_lines

Z = Decimal('0.00')


def _quarter_certs(year, quarter, branch_id=None):
    qstart, qend = quarter_bounds(year, quarter)
    q = WithholdingCertificateReceived.query.filter(
        WithholdingCertificateReceived.period_to >= qstart,
        WithholdingCertificateReceived.period_from <= qend)
    if branch_id:
        q = q.filter(WithholdingCertificateReceived.branch_id == branch_id)
    return q.all()


def get_sawt(year, quarter, branch_id=None):
    """SAWT rows from the register, grouped by customer + ATC. Register only."""
    groups = {}
    for c in _quarter_certs(year, quarter, branch_id):
        code = c.withholding_tax.code if c.withholding_tax else ''
        g = groups.setdefault((c.customer_id, code), {
            'customer_id': c.customer_id,
            'customer_name': c.customer.name if c.customer else '',
            'customer_tin': (c.customer.tin if c.customer else '') or '',
            'atc_code': code,
            'atc_rate': float(c.withholding_tax.rate) if c.withholding_tax else 0.0,
            'income_payment': Z, 'tax_withheld': Z})
        g['income_payment'] += Decimal(str(c.income_payment or 0))
        g['tax_withheld'] += Decimal(str(c.tax_withheld or 0))
    rows = sorted(groups.values(), key=lambda r: (r['customer_name'], r['atc_code']))
    return {'rows': rows,
            'total_income': sum((r['income_payment'] for r in rows), Z),
            'total_tax': sum((r['tax_withheld'] for r in rows), Z)}


def reconcile_sawt(year, quarter, branch_id=None):
    """Diff booked payee WHT (SI/CRV) against the register. Three discrepancy classes."""
    qstart, qend = quarter_bounds(year, quarter)
    booked = {}
    for l in wht_lines(qstart, qend, 'payee', tax_type='expanded', branch_id=branch_id):
        if not l.tax_withheld or l.tax_withheld <= 0:
            continue
        b = booked.setdefault((l.partner_id, l.atc_code), {
            'customer_name': l.partner_name, 'atc_code': l.atc_code, 'income': Z, 'tax': Z})
        b['income'] += l.income_payment
        b['tax'] += l.tax_withheld

    reg = {(r['customer_id'], r['atc_code']): r for r in get_sawt(year, quarter, branch_id)['rows']}

    booked_no_cert, cert_not_booked, amount_mismatch = [], [], []
    for key, b in booked.items():
        r = reg.get(key)
        if r is None:
            booked_no_cert.append({'customer_name': b['customer_name'],
                                   'atc_code': b['atc_code'], 'booked_tax': b['tax']})
        elif r['tax_withheld'] != b['tax']:
            amount_mismatch.append({'customer_name': b['customer_name'], 'atc_code': b['atc_code'],
                                    'booked_tax': b['tax'], 'cert_tax': r['tax_withheld'],
                                    'delta': b['tax'] - r['tax_withheld']})
    for key, r in reg.items():
        if key not in booked:
            cert_not_booked.append({'customer_name': r['customer_name'],
                                    'atc_code': r['atc_code'], 'cert_tax': r['tax_withheld']})
    return {'booked_no_cert': booked_no_cert, 'cert_not_booked': cert_not_booked,
            'amount_mismatch': amount_mismatch}
