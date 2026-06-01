/* ─── Data ─────────────────────────────────────────────────── */

const ACCOUNTS = [
  // ── ASSETS ──────────────────────────────────────────────────────
  { code:'1000', name:'Cash',                        type:'Asset',     classification:'Current',     nb:'Debit',  balance:     0.00, isMain:true,  parent:null   },
  { code:'1001', name:'Cash on Hand',                type:'Asset',     nb:'Debit',  balance:   200.00, isMain:false, parent:'1000' },
  { code:'1002', name:'Petty Cash Fund',             type:'Asset',     nb:'Debit',  balance:   500.00, isMain:false, parent:'1000' },
  { code:'1003', name:'BDO Checking Account',        type:'Asset',     nb:'Debit',  balance: 45000.00, isMain:false, parent:'1000' },

  { code:'1100', name:'Accounts Receivable',         type:'Asset',     classification:'Current',     nb:'Debit',  balance:     0.00, isMain:true,  parent:null   },
  { code:'1101', name:'AR — Trade',                  type:'Asset',     nb:'Debit',  balance: 57750.00, isMain:false, parent:'1100' },

  { code:'1200', name:'Inventory',                   type:'Asset',     classification:'Current',     nb:'Debit',  balance:     0.00, isMain:true,  parent:null   },
  { code:'1201', name:'Merchandise Inventory',       type:'Asset',     nb:'Debit',  balance: 15400.00, isMain:false, parent:'1200' },

  { code:'1300', name:'Other Current Assets',        type:'Asset',     classification:'Current',     nb:'Debit',  balance:     0.00, isMain:true,  parent:null   },
  { code:'1301', name:'Prepaid Expenses',            type:'Asset',     nb:'Debit',  balance:  2400.00, isMain:false, parent:'1300' },
  { code:'1302', name:'Input Tax',                   type:'Asset',     nb:'Debit',  balance:     0.00, isMain:false, parent:'1300' },
  { code:'1303', name:'Creditable Withholding Tax',  type:'Asset',     nb:'Debit',  balance:     0.00, isMain:false, parent:'1300' },

  { code:'1500', name:'Property & Equipment',        type:'Asset',     classification:'Non-Current', nb:'Debit',  balance:     0.00, isMain:true,  parent:null   },
  { code:'1501', name:'Equipment',                   type:'Asset',     nb:'Debit',  balance: 85000.00, isMain:false, parent:'1500' },
  { code:'1502', name:'Accum. Depreciation',         type:'Asset',     nb:'Credit', balance: 12500.00, isMain:false, parent:'1500' },

  // ── LIABILITIES ─────────────────────────────────────────────────
  { code:'2000', name:'Accounts Payable',            type:'Liability', classification:'Current',     nb:'Credit', balance:     0.00, isMain:true,  parent:null   },
  { code:'2001', name:'AP — Trade',                  type:'Liability', nb:'Credit', balance: 31980.00, isMain:false, parent:'2000' },

  { code:'2100', name:'Accrued Liabilities',         type:'Liability', classification:'Current',     nb:'Credit', balance:     0.00, isMain:true,  parent:null   },
  { code:'2101', name:'Accrued Expenses',            type:'Liability', nb:'Credit', balance:  5200.00, isMain:false, parent:'2100' },
  { code:'2102', name:'EWT Payable',                 type:'Liability', nb:'Credit', balance:     0.00, isMain:false, parent:'2100' },
  { code:'2103', name:'Output VAT Payable',          type:'Liability', nb:'Credit', balance:     0.00, isMain:false, parent:'2100' },

  { code:'2200', name:'Notes Payable',               type:'Liability', classification:'Non-Current', nb:'Credit', balance:     0.00, isMain:true,  parent:null   },
  { code:'2201', name:'Long-term Notes Payable',     type:'Liability', nb:'Credit', balance: 25000.00, isMain:false, parent:'2200' },

  // ── EQUITY ──────────────────────────────────────────────────────
  { code:'3000', name:"Owner's Equity",              type:'Equity',    nb:'Credit', balance:     0.00, isMain:true,  parent:null   },
  { code:'3001', name:'Common Stock',                type:'Equity',    nb:'Credit', balance:100000.00, isMain:false, parent:'3000' },
  { code:'3002', name:'Retained Earnings',           type:'Equity',    nb:'Credit', balance: 23970.00, isMain:false, parent:'3000' },
  { code:'3003', name:'Current Year Net Income',     type:'Equity',    nb:'Credit', balance:  7600.00, isMain:false, parent:'3000' },

  // ── REVENUE ─────────────────────────────────────────────────────
  { code:'4000', name:'Revenue',                     type:'Revenue',   nb:'Credit', balance:     0.00, isMain:true,  parent:null   },
  { code:'4001', name:'Sales Revenue',               type:'Revenue',   nb:'Credit', balance: 85000.00, isMain:false, parent:'4000' },
  { code:'4002', name:'Service Revenue',             type:'Revenue',   nb:'Credit', balance: 12500.00, isMain:false, parent:'4000' },

  // ── EXPENSES ────────────────────────────────────────────────────
  { code:'5000', name:'Cost of Sales',               type:'Expense',   nb:'Debit',  balance:     0.00, isMain:true,  parent:null   },
  { code:'5001', name:'Cost of Goods Sold',          type:'Expense',   nb:'Debit',  balance: 52000.00, isMain:false, parent:'5000' },

  { code:'5100', name:'Operating Expenses',          type:'Expense',   nb:'Debit',  balance:     0.00, isMain:true,  parent:null   },
  { code:'5101', name:'Salaries Expense',            type:'Expense',   nb:'Debit',  balance: 24000.00, isMain:false, parent:'5100' },
  { code:'5102', name:'Rent Expense',                type:'Expense',   nb:'Debit',  balance:  9600.00, isMain:false, parent:'5100' },
  { code:'5103', name:'Utilities Expense',           type:'Expense',   nb:'Debit',  balance:  1800.00, isMain:false, parent:'5100' },
  { code:'5104', name:'Depreciation Expense',        type:'Expense',   nb:'Debit',  balance:  2500.00, isMain:false, parent:'5100' },
];

const JOURNAL_ENTRIES = [
  { id:'26-05-00001', date:'2026-05-01', ref:'26-05-00001', desc:'Initial Capital Investment', status:'Approved',
    lines:[{acct:'1003',acctName:'BDO Checking Account',desc:'Cash invested',dr:100000,cr:0},{acct:'3001',acctName:'Common Stock',desc:'Owner equity',dr:0,cr:100000}]},
  { id:'26-05-00002', date:'2026-05-05', ref:'26-05-00002', desc:'Purchase of Equipment',    status:'Approved',
    lines:[{acct:'1501',acctName:'Equipment',desc:'Office equipment',dr:85000,cr:0},{acct:'2201',acctName:'Long-term Notes Payable',desc:'Loan payable',dr:0,cr:85000}]},
  { id:'26-05-00003', date:'2026-05-10', ref:'26-05-00003', desc:'Purchase of Inventory',    status:'Approved',
    lines:[{acct:'1201',acctName:'Merchandise Inventory',desc:'Goods for resale',dr:20000,cr:0},{acct:'2001',acctName:'AP — Trade',desc:'Supplier invoice',dr:0,cr:20000}]},
  { id:'26-05-00004', date:'2026-05-15', ref:'26-05-00004', desc:'Sales Invoice 26-05-00001', status:'Approved',
    lines:[{acct:'1101',acctName:'AR — Trade',desc:'Robinsons Builders',dr:15000,cr:0},{acct:'4001',acctName:'Sales Revenue',desc:'Sales revenue',dr:0,cr:15000}]},
  { id:'26-05-00005', date:'2026-05-15', ref:'26-05-00005', desc:'COGS — 26-05-00001',       status:'Approved',
    lines:[{acct:'5001',acctName:'Cost of Goods Sold',desc:'Cost of goods sold',dr:9000,cr:0},{acct:'1201',acctName:'Merchandise Inventory',desc:'Inventory decrease',dr:0,cr:9000}]},
  { id:'26-05-00006', date:'2026-05-20', ref:'26-05-00006', desc:'Sales Invoice 26-05-00002', status:'Approved',
    lines:[{acct:'1101',acctName:'AR — Trade',desc:'Metro Construction',dr:28500,cr:0},{acct:'4001',acctName:'Sales Revenue',desc:'Sales revenue',dr:0,cr:28500}]},
  { id:'26-05-00007', date:'2026-05-25', ref:'26-05-00007', desc:'Monthly Salaries Payment', status:'Approved',
    lines:[{acct:'5101',acctName:'Salaries Expense',desc:'May salaries',dr:8000,cr:0},{acct:'1003',acctName:'BDO Checking Account',desc:'Cash paid',dr:0,cr:8000}]},
  { id:'26-05-00008', date:'2026-05-28', ref:'26-05-00008', desc:'Monthly Rent Payment',     status:'Approved',
    lines:[{acct:'5102',acctName:'Rent Expense',desc:'Office rent',dr:3200,cr:0},{acct:'1003',acctName:'BDO Checking Account',desc:'Cash paid',dr:0,cr:3200}]},
  { id:'26-05-00009', date:'2026-05-28', ref:'26-05-00009', desc:'Customer Payment Received', status:'Approved',
    lines:[{acct:'1003',acctName:'BDO Checking Account',desc:'Payment from Robinsons',dr:12000,cr:0},{acct:'1101',acctName:'AR — Trade',desc:'AR cleared',dr:0,cr:12000}]},
  { id:'26-05-00010', date:'2026-05-30', ref:'26-05-00010', desc:'Utilities Accrual',        status:'Draft',
    lines:[{acct:'5103',acctName:'Utilities Expense',desc:'May utilities',dr:480,cr:0},{acct:'2101',acctName:'Accrued Expenses',desc:'Accrued utilities',dr:0,cr:480}]},
  { id:'26-05-00011', date:'2026-05-30', ref:'26-05-00011', desc:'Utilities Bill Payment — Power & Light Corp.', status:'Approved',
    lines:[{acct:'5103',acctName:'Utilities Expense',desc:'Monthly electricity bill — actual',dr:800,cr:0},{acct:'1003',acctName:'BDO Checking Account',desc:'Bank payment',dr:0,cr:800}]},
  { id:'26-05-00012', date:'2026-05-30', ref:'26-05-00012', desc:'Supplier Payments — May 30', status:'Approved',
    lines:[
      {acct:'2001',acctName:'AP — Trade',desc:'Steel Supply Co. — partial payment',dr:18270,cr:0},
      {acct:'1301',acctName:'Prepaid Expenses',desc:'Advance payment — Construction Supplies',dr:36730,cr:0},
      {acct:'1003',acctName:'BDO Checking Account',desc:'Bank disbursement',dr:0,cr:55000}
    ]},
  { id:'26-05-00013', date:'2026-05-20', ref:'26-05-00013', desc:'Sales Invoice 26-05-00003 — Pacific Developers', status:'Approved',
    lines:[{acct:'1101',acctName:'AR — Trade',desc:'Pacific Developers',dr:8750,cr:0},{acct:'4001',acctName:'Sales Revenue',desc:'Sales revenue',dr:0,cr:8750}]},
  { id:'26-05-00014', date:'2026-05-25', ref:'26-05-00014', desc:'Sales Invoice 26-05-00004 — City Contractors', status:'Approved',
    lines:[{acct:'1101',acctName:'AR — Trade',desc:'City Contractors',dr:12000,cr:0},{acct:'4001',acctName:'Sales Revenue',desc:'Sales revenue',dr:0,cr:12000}]},
  { id:'26-05-00015', date:'2026-05-28', ref:'26-05-00015', desc:'Sales Invoice 26-05-00005 — Sunrise Properties', status:'Approved',
    lines:[{acct:'1101',acctName:'AR — Trade',desc:'Sunrise Properties',dr:5500,cr:0},{acct:'4001',acctName:'Sales Revenue',desc:'Sales revenue',dr:0,cr:5500}]},
  { id:'26-05-00016', date:'2026-05-03', ref:'26-05-00016', desc:'Bill — Steel Supply Co. 26-05-00001', status:'Approved',
    lines:[{acct:'1201',acctName:'Merchandise Inventory',desc:'Raw materials purchase',dr:18300,cr:0},{acct:'2001',acctName:'AP — Trade',desc:'Steel Supply Co. invoice',dr:0,cr:18300}]},
  { id:'26-05-00017', date:'2026-05-12', ref:'26-05-00017', desc:'Bill — Office Depot 26-05-00002', status:'Approved',
    lines:[{acct:'5103',acctName:'Utilities Expense',desc:'Office supplies — Office Depot',dr:1250,cr:0},{acct:'2001',acctName:'AP — Trade',desc:'Office Depot invoice',dr:0,cr:1250}]},
  { id:'26-05-00018', date:'2026-05-12', ref:'26-05-00018', desc:'Payment — Office Depot', status:'Approved',
    lines:[{acct:'2001',acctName:'AP — Trade',desc:'Payment — Office Depot',dr:1250,cr:0},{acct:'1003',acctName:'BDO Checking Account',desc:'Bank payment',dr:0,cr:1250}]},
  { id:'26-05-00019', date:'2026-05-22', ref:'26-05-00019', desc:'Bill — Construction Supplies Inc. 26-05-00004', status:'Approved',
    lines:[{acct:'1201',acctName:'Merchandise Inventory',desc:'Construction materials',dr:8750,cr:0},{acct:'2001',acctName:'AP — Trade',desc:'Construction Supplies Inc. bill',dr:0,cr:8750}]},
  { id:'26-05-00020', date:'2026-05-28', ref:'26-05-00020', desc:'Bill — Maintenance Services 26-05-00005', status:'Approved',
    lines:[{acct:'5103',acctName:'Utilities Expense',desc:'Maintenance and repair services',dr:3200,cr:0},{acct:'2001',acctName:'AP — Trade',desc:'Maintenance Services bill',dr:0,cr:3200}]},
  { id:'26-05-00021', date:'2026-05-30', ref:'26-05-00021', desc:'Service Revenue — Consulting Project', status:'Approved',
    lines:[{acct:'1101',acctName:'AR — Trade',desc:'Consulting project receivable',dr:15250,cr:0},{acct:'4001',acctName:'Sales Revenue',desc:'Consulting services rendered',dr:0,cr:15250}]},
  { id:'26-05-00022', date:'2026-05-10', ref:'26-05-00022', desc:'Salaries — First Fortnight', status:'Approved',
    lines:[{acct:'5101',acctName:'Salaries Expense',desc:'May 1–15 salaries',dr:8000,cr:0},{acct:'1003',acctName:'BDO Checking Account',desc:'Bank payment',dr:0,cr:8000}]},
  { id:'26-05-00023', date:'2026-05-31', ref:'26-05-00023', desc:'Salaries — Month-end Bonus', status:'Approved',
    lines:[{acct:'5101',acctName:'Salaries Expense',desc:'May performance bonus',dr:8000,cr:0},{acct:'1003',acctName:'BDO Checking Account',desc:'Bank payment',dr:0,cr:8000}]},
];

const LEDGER = {
  '1003': [
    { date:'2026-05-01', desc:'Initial Capital Investment', ref:'26-05-00001', dr:100000, cr:0,     bal:100000 },
    { date:'2026-05-25', desc:'Salaries Payment',           ref:'26-05-00007', dr:0,      cr:8000,  bal:92000  },
    { date:'2026-05-28', desc:'Rent Payment',               ref:'26-05-00008', dr:0,      cr:3200,  bal:88800  },
    { date:'2026-05-28', desc:'Customer Payment Received',  ref:'26-05-00009', dr:12000,  cr:0,     bal:100800 },
    { date:'2026-05-30', desc:'Utilities Payment',          ref:'26-05-00011', dr:0,      cr:800,   bal:100000 },
    { date:'2026-05-30', desc:'Supplier Payment',           ref:'26-05-00012', dr:0,      cr:55000, bal:45000  },
  ],
  '1101': [
    { date:'2026-05-15', desc:'Sales Invoice 26-05-00001 — Robinsons Builders', ref:'26-05-00004', dr:15000, cr:0,     bal:15000 },
    { date:'2026-05-20', desc:'Sales Invoice 26-05-00002 — Metro Construction', ref:'26-05-00006', dr:28500, cr:0,     bal:43500 },
    { date:'2026-05-20', desc:'Sales Invoice 26-05-00003 — Pacific Developers', ref:'26-05-00013', dr:8750,  cr:0,     bal:52250 },
    { date:'2026-05-25', desc:'Sales Invoice 26-05-00004 — City Contractors',   ref:'26-05-00014', dr:12000, cr:0,     bal:64250 },
    { date:'2026-05-28', desc:'Customer Payment — Robinsons Builders',          ref:'26-05-00009', dr:0,     cr:12000, bal:52250 },
    { date:'2026-05-28', desc:'Sales Invoice 26-05-00005 — Sunrise Properties', ref:'26-05-00015', dr:5500,  cr:0,     bal:57750 },
  ],
  '2001': [
    { date:'2026-05-03', desc:'Steel Supply Co. 26-05-00001',       ref:'26-05-00016', dr:0,     cr:18300, bal:18300 },
    { date:'2026-05-10', desc:'Purchase of Inventory',             ref:'26-05-00003', dr:0,     cr:20000, bal:38300 },
    { date:'2026-05-12', desc:'Office Depot 26-05-00002',          ref:'26-05-00017', dr:0,     cr:1250,  bal:39550 },
    { date:'2026-05-12', desc:'Payment to Office Depot',           ref:'26-05-00018', dr:1250,  cr:0,     bal:38300 },
    { date:'2026-05-22', desc:'Construction Supplies 26-05-00004', ref:'26-05-00019', dr:0,     cr:8750,  bal:47050 },
    { date:'2026-05-28', desc:'Maintenance Services 26-05-00005',  ref:'26-05-00020', dr:0,     cr:3200,  bal:50250 },
    { date:'2026-05-30', desc:'Partial supplier payment',          ref:'26-05-00012', dr:18270, cr:0,     bal:31980 },
  ],
  '4001': [
    { date:'2026-05-15', desc:'Sales Invoice 26-05-00001 — Robinsons Builders', ref:'26-05-00004', dr:0, cr:15000, bal:15000 },
    { date:'2026-05-20', desc:'Sales Invoice 26-05-00002 — Metro Construction', ref:'26-05-00006', dr:0, cr:28500, bal:43500 },
    { date:'2026-05-20', desc:'Sales Invoice 26-05-00003 — Pacific Developers', ref:'26-05-00013', dr:0, cr:8750,  bal:52250 },
    { date:'2026-05-25', desc:'Sales Invoice 26-05-00004 — City Contractors',   ref:'26-05-00014', dr:0, cr:12000, bal:64250 },
    { date:'2026-05-28', desc:'Sales Invoice 26-05-00005 — Sunrise Properties', ref:'26-05-00015', dr:0, cr:5500,  bal:69750 },
    { date:'2026-05-30', desc:'Service Revenue — Consulting Project',            ref:'26-05-00021', dr:0, cr:15250, bal:85000 },
  ],
  '5101': [
    { date:'2026-05-10', desc:'Salaries — first fortnight',  ref:'26-05-00022', dr:8000, cr:0, bal:8000  },
    { date:'2026-05-25', desc:'Salaries — second fortnight', ref:'26-05-00007', dr:8000, cr:0, bal:16000 },
    { date:'2026-05-31', desc:'Salaries — month-end bonus',  ref:'26-05-00023', dr:8000, cr:0, bal:24000 },
  ],
};

const INVOICES = [
  { num:'26-05-00001', customer:'Robinsons Builders',  date:'2026-05-10', due:'2026-05-25', amount:15000, paid:12000, status:'Partial', lifecycle:'Approved' },
  { num:'26-05-00002', customer:'Metro Construction',  date:'2026-05-15', due:'2026-05-30', amount:28500, paid:0,     status:'Open',    lifecycle:'Approved' },
  { num:'26-05-00003', customer:'Pacific Developers',  date:'2026-05-20', due:'2026-06-04', amount:8750,  paid:0,     status:'Open',    lifecycle:'Approved' },
  { num:'26-05-00004', customer:'City Contractors',    date:'2026-05-25', due:'2026-06-09', amount:12000, paid:0,     status:'Open',    lifecycle:'Approved' },
  { num:'26-05-00005', customer:'Sunrise Properties',  date:'2026-05-28', due:'2026-06-12', amount:5500,  paid:0,     status:'Open',    lifecycle:'Approved' },
  { num:'26-05-00006', customer:'Robinsons Builders',  date:'2026-05-29', due:'2026-06-13', amount:8200,  paid:0,     status:'Open',    lifecycle:'Submitted' },
  { num:'26-05-00007', customer:'Pacific Developers',  date:'2026-05-30', due:'2026-06-14', amount:9400,  paid:0,     status:'Open',    lifecycle:'Draft' },
];

const CUSTOMERS = [
  { code:'C001', name:'Robinsons Builders',          contact:'John Santos',    phone:'09171234567', email:'jsantos@robinsons.ph',   address:'Quezon City, Metro Manila',     postalCode:'1108', tin:'111-222-333-000', terms:'Net 30', defaultVat:'VATSG', defaultWt:['WC100'],         status:'Active' },
  { code:'C002', name:'Metro Construction',          contact:'Maria Reyes',    phone:'09281234567', email:'mreyes@metro.ph',        address:'Makati City, Metro Manila',     postalCode:'1226', tin:'222-333-444-000', terms:'Net 30', defaultVat:'VATSG', defaultWt:['WC100'],         status:'Active' },
  { code:'C003', name:'Pacific Developers',          contact:'Carlos Tan',     phone:'09391234567', email:'ctan@pacific.ph',        address:'Pasig City, Metro Manila',      postalCode:'1600', tin:'333-444-555-000', terms:'Net 45', defaultVat:'VATSS', defaultWt:['WC160'],         status:'Active' },
  { code:'C004', name:'City Contractors',            contact:'Ana Cruz',       phone:'09451234567', email:'acruz@citycon.ph',       address:'Mandaluyong, Metro Manila',     postalCode:'1550', tin:'444-555-666-000', terms:'Net 30', defaultVat:'VATSG', defaultWt:['WC100','WC158'], status:'Active' },
  { code:'C005', name:'Sunrise Properties',          contact:'Ben Lopez',      phone:'09561234567', email:'blopez@sunrise.ph',      address:'Taguig City, Metro Manila',     postalCode:'1630', tin:'555-666-777-000', terms:'Net 60', defaultVat:'VATSG', defaultWt:['WC100'],         status:'Active' },
];

const VENDORS = [
  { code:'V001', name:'Steel Supply Co.',            contact:'Pedro Dela Cruz',  phone:'09121234567', email:'pdc@steelsupply.ph',     address:'Caloocan City, Metro Manila',   postalCode:'1400', tin:'123-456-789-000', terms:'Net 30', defaultVat:'VATOG', defaultWt:['WC158'],         status:'Active' },
  { code:'V002', name:'Office Depot',                contact:'Linda Santos',     phone:'09231234567', email:'lsantos@officedepot.ph', address:'Ortigas, Pasig City',           postalCode:'1605', tin:'234-567-890-000', terms:'Net 15', defaultVat:'VATOG', defaultWt:['WC158'],         status:'Active' },
  { code:'V003', name:'Power & Light Corp.',         contact:'Ramon Garcia',     phone:'09341234567', email:'rgarcia@powerlight.ph',  address:'Makati City, Metro Manila',     postalCode:'1226', tin:'345-678-901-000', terms:'Net 30', defaultVat:'VATSV', defaultWt:['WC160'],         status:'Active' },
  { code:'V004', name:'Construction Supplies Inc.',  contact:'Teresa Bautista',  phone:'09451234567', email:'tbautista@csi.ph',       address:'Valenzuela City, Metro Manila', postalCode:'1440', tin:'456-789-012-000', terms:'Net 45', defaultVat:'VATOG', defaultWt:['WC158','WC100'], status:'Active' },
  { code:'V005', name:'Maintenance Services',        contact:'Jose Mendoza',     phone:'09561234567', email:'jmendoza@maintenance.ph',address:'Quezon City, Metro Manila',     postalCode:'1100', tin:'567-890-123-000', terms:'Net 30', defaultVat:'VATSV', defaultWt:['WC160'],         status:'Active' },
];

// Input VAT categories — used on AP (bills/vendor side, buyer's perspective)
const VAT_TYPES = [
  { code: 'VATCG', name: 'Capital Goods',  rate: '12%', inputTaxAccount: '1302' },
  { code: 'VATOG', name: 'Other Goods',    rate: '12%', inputTaxAccount: '1302' },
  { code: 'VATSV', name: 'Services',       rate: '12%', inputTaxAccount: '1302' },
  { code: 'VATIM', name: 'Importations',   rate: '12%', inputTaxAccount: '1302' },
  { code: 'VATEX', name: 'VAT Exempt',     rate: '0%',  inputTaxAccount: null   },
  { code: 'VATZ',  name: 'Zero Rated',     rate: '0%',  inputTaxAccount: null   },
  { code: 'INVAL', name: 'Invalid',        rate: 'N/A', inputTaxAccount: null   },
];

// Output VAT categories — used on AR (invoices/customer side, seller's perspective)
const OUTPUT_VAT_TYPES = [
  { code: 'VATSG',  name: 'Sale of Goods',      rate: '12%', outputTaxAccount: '2103' },
  { code: 'VATSS',  name: 'Sale of Services',   rate: '12%', outputTaxAccount: '2103' },
  { code: 'VATSZ',  name: 'Zero-Rated Sales',   rate: '0%',  outputTaxAccount: null   },
  { code: 'VATSE',  name: 'VAT-Exempt Sales',   rate: '0%',  outputTaxAccount: null   },
  { code: 'VATSGV', name: 'Govt. Agency Sales', rate: '0%',  outputTaxAccount: null   },
];

const EWT_PAYABLE_ACCOUNT    = '2102';
const OUTPUT_VAT_ACCOUNT     = '2103';
const CWT_RECEIVABLE_ACCOUNT = '1303';

const WITHHOLDING_TAXES = [
  { code: 'WC010', name: 'Prof. Fees — Individuals',   rate: '10%' },
  { code: 'WC011', name: 'Prof. Fees — Corporations',  rate: '15%' },
  { code: 'WC100', name: 'Contractors & Subcontractors', rate: '2%' },
  { code: 'WC158', name: 'Purchases of Goods',         rate: '1%'  },
  { code: 'WC160', name: 'Purchases of Services',      rate: '2%'  },
  { code: 'WC180', name: 'Rental — Real Property',     rate: '5%'  },
  { code: 'WI010', name: 'Interest on Loans',          rate: '20%' },
  { code: 'WR010', name: 'Royalties',                  rate: '10%' },
];

const BILLS = [
  { num:'26-05-00001', vendor:'Steel Supply Co.',          date:'2026-05-03', due:'2026-05-20', amount:18300, paid:0,    status:'Overdue', lifecycle:'Approved' },
  { num:'26-05-00002', vendor:'Office Depot',              date:'2026-05-12', due:'2026-05-27', amount:1250,  paid:1250, status:'Paid',    lifecycle:'Approved' },
  { num:'26-05-00003', vendor:'Power & Light Corp.',       date:'2026-05-18', due:'2026-06-02', amount:480,   paid:0,    status:'Open',    lifecycle:'Approved' },
  { num:'26-05-00004', vendor:'Construction Supplies Inc.',date:'2026-05-22', due:'2026-06-06', amount:8750,  paid:0,    status:'Open',    lifecycle:'Approved' },
  { num:'26-05-00005', vendor:'Maintenance Services',      date:'2026-05-28', due:'2026-06-12', amount:3200,  paid:0,    status:'Open',    lifecycle:'Approved' },
  { num:'26-05-00006', vendor:'Construction Supplies Inc.',date:'2026-05-29', due:'2026-06-13', amount:3500,  paid:0,    status:'Open',    lifecycle:'Submitted' },
  { num:'26-05-00007', vendor:'Power & Light Corp.',       date:'2026-05-30', due:'2026-06-14', amount:920,   paid:0,    status:'Open',    lifecycle:'Draft' },
];

const ACCOUNT_CHANGE_REQUESTS = [];

/* Cancellation requests — Staff cannot cancel directly, they file a request
   the Accountant approves or rejects. See docs/roles-permissions.md § Request Cancel. */
const CANCEL_REQUESTS = [];
let _cancelReqCounter = 0;
function nextCancelReqId() { return ++_cancelReqCounter; }

const USERS = [
  { name:'Maria Santos',   email:'maria.santos@cas.demo',    role:'Accountant', initials:'MS', color:'#2563eb' },
  { name:'Juan Dela Cruz', email:'juan.delacruz@cas.demo',   role:'Staff',      initials:'JD', color:'#16a34a' },
  { name:'Ana Garcia',     email:'ana.garcia@cas.demo',      role:'Viewer',     initials:'AG', color:'#9333ea' },
];
let _currentUserIdx = 0;
let _currentUser    = USERS[0];
let _isAuthenticated = false;

const COLLECTIONS = [
  { id:'26-05-C001', customer:'Robinsons Builders', date:'2026-05-28', amount:12000, method:'Bank Transfer', ref:'REC-001', acctCode:'1003', lifecycle:'Approved', invoiceLines:[{invoiceNum:'26-05-00001', amount:12000}] },
];

const PAYMENTS = [
  { id:'26-05-P001', vendor:'Office Depot', date:'2026-05-27', amount:1250, method:'Bank Transfer', ref:'PMT-001', acctCode:'1003', lifecycle:'Approved', billLines:[{billNum:'26-05-00002', amount:1250}] },
];

/* ─── Auth (login / register / logout) ────────────────────────
   Mockup behavior:
   - Login matches by email; any password is accepted (placeholder).
   - Register pushes a new entry to USERS and signs them in.
   - Logout clears _isAuthenticated and shows the login screen.
   Real implementation: see docs/auth.md.
   ─────────────────────────────────────────────────────────── */

function toggleUserMenu() {
  document.getElementById('user-menu')?.classList.toggle('open');
}
function closeUserMenu() {
  document.getElementById('user-menu')?.classList.remove('open');
}
document.addEventListener('click', e => {
  if (!e.target.closest('.user-menu-wrap')) closeUserMenu();
});

function showAuthPanel(name) {
  ['login','register','forgot'].forEach(p => {
    const el = document.getElementById('auth-' + p);
    if (el) el.style.display = p === name ? '' : 'none';
  });
  // Reset error messages
  document.querySelectorAll('.auth-error').forEach(el => el.style.display = 'none');
  document.querySelectorAll('.auth-success').forEach(el => el.style.display = 'none');
}

function _authError(panelId, message) {
  const el = document.getElementById(`auth-${panelId}-error`);
  if (el) { el.textContent = message; el.style.display = ''; }
}

function _enterApp(user) {
  _isAuthenticated = true;
  // Position user at their slot in USERS so cycleUser still works
  const idx = USERS.findIndex(u => u.email === user.email);
  _currentUserIdx = idx >= 0 ? idx : 0;
  _currentUser    = user;

  document.getElementById('auth-screen').style.display = 'none';
  document.getElementById('app-layout').style.display  = '';
  // Sync topbar
  const avatar = document.getElementById('user-avatar');
  const name   = document.getElementById('user-name');
  const role   = document.getElementById('user-role-label');
  if (avatar) { avatar.textContent = user.initials; avatar.style.background = user.color; }
  if (name)   name.textContent = user.name;
  if (role)   role.textContent = user.role;
  updateUIForRole();
  renderActionsWidget();
  renderActionsPage();

  // Audit
  logAudit({ category:'login', event:'login_success' });
}

function doLogin() {
  const email = (document.getElementById('auth-email').value || '').trim().toLowerCase();
  const pw    = document.getElementById('auth-password').value;
  if (!email || !pw) { _authError('login', 'Please enter your email and password.'); return; }

  const user = USERS.find(u => u.email.toLowerCase() === email);
  if (!user) {
    AUDIT_LOG.push({ id: nextAuditId(), ts: _auditTs(), actor: '(unknown)', category:'login', event:'login_failed', note:`Email: ${email}` });
    _authError('login', 'No account matches that email.');
    return;
  }
  _enterApp(user);
}

function doRegister() {
  const name  = document.getElementById('reg-name').value.trim();
  const email = document.getElementById('reg-email').value.trim().toLowerCase();
  const pw    = document.getElementById('reg-password').value;
  const pw2   = document.getElementById('reg-password2').value;
  const role  = document.getElementById('reg-role').value;
  const tos   = document.getElementById('reg-tos').checked;

  if (!name || !email || !pw)   { _authError('register', 'Name, email and password are required.'); return; }
  if (pw.length < 6)             { _authError('register', 'Password must be at least 6 characters.'); return; }
  if (pw !== pw2)                { _authError('register', "Passwords don't match."); return; }
  if (!tos)                      { _authError('register', 'Please accept the terms of service.'); return; }
  if (USERS.find(u => u.email.toLowerCase() === email)) { _authError('register', 'An account with that email already exists.'); return; }

  const parts = name.split(/\s+/);
  const initials = (parts[0][0] + (parts[parts.length-1][0] || '')).toUpperCase();
  const palette  = ['#2563eb','#16a34a','#9333ea','#dc2626','#ea580c','#0891b2'];
  const color    = palette[USERS.length % palette.length];

  const newUser = { name, email, role, initials, color };
  USERS.push(newUser);
  logAudit({ category:'coa',  recordType:'User', recordId:email, event:'created', note:`Self-registered as ${role}` });

  _enterApp(newUser);
}

function doForgotPassword() {
  const email = document.getElementById('forgot-email').value.trim().toLowerCase();
  if (!email) return;
  const msg = document.getElementById('auth-forgot-msg');
  msg.textContent = `If an account exists for ${email}, a reset link has been sent.`;
  msg.style.display = '';
}

function doLogout() {
  logAudit({ category:'login', event:'logout' });
  _isAuthenticated = false;
  document.getElementById('app-layout').style.display  = 'none';
  document.getElementById('auth-screen').style.display = '';
  showAuthPanel('login');
  document.getElementById('auth-password').value = '';
  document.getElementById('auth-email').value    = '';
}

// Enter key submits the active auth panel
document.addEventListener('keydown', e => {
  if (e.key !== 'Enter' || _isAuthenticated) return;
  if (document.getElementById('auth-login').style.display !== 'none')         doLogin();
  else if (document.getElementById('auth-register').style.display !== 'none') doRegister();
  else if (document.getElementById('auth-forgot').style.display !== 'none')   doForgotPassword();
});

/* ─── Audit Trail ─────────────────────────────────────────────
   Append-only log of every lifecycle transition, login event,
   field edit on a Draft, and CoA change. See docs/audit-trail.md.
   Each entry: { id, category, ts, actor, recordType, recordId,
                 event, fromState, toState, note, changes }
   ─────────────────────────────────────────────────────────── */
const AUDIT_LOG = [
  // Seed history. `category` = the specific event for lifecycle items (create/submit/approve/disapprove/cancel)
  // or the audit family for non-lifecycle items (login/field/coa).
  { id:1,  category:'create',  ts:'2026-05-01 09:14', actor:'Maria Santos',   recordType:'JournalEntry', recordId:'26-05-00001', fromState:'(none)', toState:'Draft' },
  { id:2,  category:'approve', ts:'2026-05-01 09:15', actor:'Maria Santos',   recordType:'JournalEntry', recordId:'26-05-00001', fromState:'Draft',  toState:'Approved' },
  { id:3,  category:'create',  ts:'2026-05-10 08:30', actor:'Juan Dela Cruz', recordType:'Invoice',      recordId:'26-05-00001', fromState:'(none)', toState:'Draft' },
  { id:4,  category:'submit',  ts:'2026-05-10 11:02', actor:'Juan Dela Cruz', recordType:'Invoice',      recordId:'26-05-00001', fromState:'Draft',  toState:'Submitted' },
  { id:5,  category:'approve', ts:'2026-05-10 14:17', actor:'Maria Santos',   recordType:'Invoice',      recordId:'26-05-00001', fromState:'Submitted', toState:'Approved' },
  { id:6,  category:'field',   ts:'2026-05-10 10:45', actor:'Juan Dela Cruz', recordType:'Invoice',      recordId:'26-05-00001', changes:{amount:{from:14500, to:15000}} },
  { id:7,  category:'create',  ts:'2026-05-28 09:20', actor:'Juan Dela Cruz', recordType:'Collection',   recordId:'26-05-C001',  fromState:'(none)', toState:'Draft' },
  { id:8,  category:'approve', ts:'2026-05-28 09:25', actor:'Maria Santos',   recordType:'Collection',   recordId:'26-05-C001',  fromState:'Draft',  toState:'Approved' },
  { id:9,  category:'create',  ts:'2026-05-30 10:00', actor:'Juan Dela Cruz', recordType:'JournalEntry', recordId:'26-05-00010', fromState:'(none)', toState:'Draft', note:'Utilities accrual — pending review' },
  { id:10, category:'login',   ts:'2026-05-30 08:55', actor:'Maria Santos',                                                       event:'login_success' },
  { id:11, category:'login',   ts:'2026-05-30 08:42', actor:'(unknown)',                                                          event:'login_failed',  note:'Email: notauser@test.ph' },
  { id:12, category:'coa',     ts:'2026-05-15 11:30', actor:'Maria Santos',   recordType:'Account',      recordId:'5104',        event:'created', changes:{name:{from:null, to:'Depreciation Expense'}} },
];

// Human-readable label for a category code
const AUDIT_CAT_LABEL = {
  create:'Create', submit:'Submit', approve:'Approve', disapprove:'Disapprove', cancel:'Cancel',
  login:'Login', field:'Field Edit', coa:'CoA Change',
};

let _auditCounter = AUDIT_LOG.length;
function nextAuditId() { return ++_auditCounter; }

// Current timestamp in mock-friendly format (uses TODAY_STR + current clock)
function _auditTs() {
  const d = new Date();
  const hh = String(d.getHours()).padStart(2, '0');
  const mm = String(d.getMinutes()).padStart(2, '0');
  return `${TODAY_STR} ${hh}:${mm}`;
}

function logAudit(entry) {
  AUDIT_LOG.push({ id: nextAuditId(), ts: _auditTs(), actor: _currentUser.name, ...entry });
  // Refresh the audit page if visible
  if (typeof renderAuditLog === 'function') renderAuditLog();
}

/* ─── Helpers ──────────────────────────────────────────────── */
const fmt  = n => n.toLocaleString('en-US', { minimumFractionDigits:2, maximumFractionDigits:2 });
const fmtP = n => n < 0 ? `(${fmt(Math.abs(n))})` : fmt(n);
const parseAmt = v => parseFloat(String(v).replace(/,/g, '')) || 0;

/* Amount field formatting — applies to all inputs with class="amt" */
document.addEventListener('focusin', e => {
  if (!e.target.matches('input.amt')) return;
  const raw = parseAmt(e.target.value);
  e.target.value = raw === 0 ? '' : raw.toFixed(2);
  e.target.select();
});
document.addEventListener('focusout', e => {
  if (!e.target.matches('input.amt')) return;
  const raw = parseAmt(e.target.value);
  e.target.value = raw === 0 ? '' : fmt(raw);
});

/* ─── Navigation ───────────────────────────────────────────── */
const pageTitles = {
  dashboard:  'Dashboard',
  accounts:   'Chart of Accounts',
  journal:    'Journal Entries',
  ledger:     'General Ledger',
  receivables:'Accounts Receivable',
  collections:'Collections',
  payables:   'Accounts Payable',
  payments:   'Payments',
  reports:    'Reports',
  customers:         'Customer Maintenance',
  'customer-detail': 'Customer Sales',
  vendors:           'Vendor Maintenance',
  'vendor-detail':   'Vendor Purchases',
  bir:               'BIR Reports',
  audit:             'Audit Log',
  'action-items':    'Action Items',
  users:             'User Management',
};

const pageAliases = {
  collections: { section:'receivables', tabGroup:'ar', tab:'receipts'  },
  payments:    { section:'payables',    tabGroup:'ap', tab:'payments' },
};

/* ─── + New dropdown ───────────────────────────────────────── */
function toggleNewMenu() {
  document.getElementById('new-dropdown').classList.toggle('open');
}
function closeNewMenu() {
  document.getElementById('new-dropdown').classList.remove('open');
}
document.addEventListener('click', e => {
  if (!e.target.closest('.new-btn-wrap')) closeNewMenu();
});

function navigate(page) {
  const alias  = pageAliases[page];
  const target = alias ? alias.section : page;

  document.querySelectorAll('.page-section').forEach(s => s.classList.remove('active'));
  document.querySelectorAll('.nav-item').forEach(n => n.classList.remove('active'));
  document.getElementById(target).classList.add('active');
  document.querySelectorAll(`[data-page="${page}"]`).forEach(n => n.classList.add('active'));
  document.getElementById('page-title').textContent = pageTitles[page] || page;

  if (alias) {
    document.querySelectorAll(`[data-tab-group="${alias.tabGroup}"]`).forEach(t => t.classList.remove('active'));
    document.querySelectorAll(`[data-tab-panel="${alias.tabGroup}"]`).forEach(p => p.classList.remove('active'));
    document.querySelector(`.tab[data-tab-group="${alias.tabGroup}"][data-tab="${alias.tab}"]`)?.classList.add('active');
    document.getElementById(`${alias.tabGroup}-${alias.tab}`)?.classList.add('active');
  }
}

document.querySelectorAll('.nav-item[data-page]').forEach(item => {
  item.addEventListener('click', () => navigate(item.dataset.page));
});

/* ─── Customer / Vendor Maintenance ───────────────────────── */
function nextCustomerCode() {
  const nums = CUSTOMERS.map(c => parseInt(c.code.replace('C', ''), 10));
  return `C${String(Math.max(...nums) + 1).padStart(3, '0')}`;
}

function nextVendorCode() {
  const nums = VENDORS.map(v => parseInt(v.code.replace('V', ''), 10));
  return `V${String(Math.max(...nums) + 1).padStart(3, '0')}`;
}

function renderCustomers(filter = '') {
  const fl    = filter.toLowerCase();
  const tbody = document.getElementById('customers-tbody');
  if (!tbody) return;
  const hits = CUSTOMERS.filter(c =>
    !fl || c.code.toLowerCase().includes(fl) || c.name.toLowerCase().includes(fl) ||
    c.contact.toLowerCase().includes(fl) || c.tin.toLowerCase().includes(fl)
  );
  tbody.innerHTML = hits.length
    ? hits.map(c => {
        const vatInfo  = OUTPUT_VAT_TYPES.find(t => t.code === c.defaultVat);
        const vatBadge = vatInfo
          ? `<span class="badge" style="background:#f0fdf4;color:#15803d;font-size:11px">${vatInfo.code} ${vatInfo.rate}</span>`
          : '<span style="color:var(--text-3);font-size:12px">—</span>';
        const wtBadges = (c.defaultWt || []).map(code => {
          const wt = WITHHOLDING_TAXES.find(w => w.code === code);
          return wt ? `<span class="badge" style="background:#eff6ff;color:#1d4ed8;font-size:11px">${wt.code}</span>` : '';
        }).join(' ');
        return `
          <tr class="clickable-row" onclick="openCustomerDetail('${c.code}')">
            <td><code>${c.code}</code></td>
            <td class="fw-6">${c.name}</td>
            <td>${c.contact}</td>
            <td class="mono text-sm">${c.phone}</td>
            <td class="mono text-sm">${c.tin}</td>
            <td>${c.terms}</td>
            <td>${vatBadge}</td>
            <td>${wtBadges || '<span style="color:var(--text-3);font-size:12px">—</span>'}</td>
            <td><span class="badge badge-${c.status.toLowerCase()}">${c.status}</span></td>
            <td><button class="btn btn-ghost btn-sm" onclick="event.stopPropagation();openEditCustomer('${c.code}')">Edit</button></td>
          </tr>`;
      }).join('')
    : `<tr><td colspan="10" style="text-align:center;color:var(--text-3);padding:24px">No customers found</td></tr>`;
}

function renderVendors(filter = '') {
  const fl    = filter.toLowerCase();
  const tbody = document.getElementById('vendors-tbody');
  if (!tbody) return;
  const hits = VENDORS.filter(v =>
    !fl || v.code.toLowerCase().includes(fl) || v.name.toLowerCase().includes(fl) ||
    v.contact.toLowerCase().includes(fl) || v.tin.toLowerCase().includes(fl)
  );
  tbody.innerHTML = hits.length
    ? hits.map(v => {
        const vatInfo  = VAT_TYPES.find(t => t.code === v.defaultVat);
        const vatBadge = vatInfo
          ? `<span class="badge" style="background:#f0fdf4;color:#15803d;font-size:11px">${vatInfo.code} ${vatInfo.rate}</span>`
          : '<span style="color:var(--text-3);font-size:12px">—</span>';
        const wtBadges = (v.defaultWt || []).map(code => {
          const wt = WITHHOLDING_TAXES.find(w => w.code === code);
          return wt ? `<span class="badge" style="background:#eff6ff;color:#1d4ed8;font-size:11px">${wt.code}</span>` : '';
        }).join(' ');
        return `
          <tr class="clickable-row" onclick="openVendorDetail('${v.code}')">
            <td><code>${v.code}</code></td>
            <td class="fw-6">${v.name}</td>
            <td>${v.contact}</td>
            <td class="mono text-sm">${v.phone}</td>
            <td class="mono text-sm">${v.tin}</td>
            <td>${v.terms}</td>
            <td>${vatBadge}</td>
            <td>${wtBadges || '<span style="color:var(--text-3);font-size:12px">—</span>'}</td>
            <td><span class="badge badge-${v.status.toLowerCase()}">${v.status}</span></td>
            <td><button class="btn btn-ghost btn-sm" onclick="event.stopPropagation();openEditVendor('${v.code}')">Edit</button></td>
          </tr>`;
      }).join('')
    : `<tr><td colspan="10" style="text-align:center;color:var(--text-3);padding:24px">No vendors found</td></tr>`;
}

/* ─── Modals ───────────────────────────────────────────────── */
function nextInvoiceNumber(dateStr) {
  const d = dateStr ? new Date(dateStr + 'T00:00:00') : new Date('2026-05-30');
  const yy = String(d.getFullYear()).slice(2);
  const mm = String(d.getMonth() + 1).padStart(2, '0');
  const count = INVOICES.filter(inv => {
    const id = new Date(inv.date + 'T00:00:00');
    return String(id.getFullYear()).slice(2) === yy &&
           String(id.getMonth() + 1).padStart(2, '0') === mm;
  }).length;
  return `${yy}-${mm}-${String(count + 1).padStart(5, '0')}`;
}

function nextJENumber(dateStr) {
  const d = dateStr ? new Date(dateStr + 'T00:00:00') : new Date('2026-05-30');
  const yy = String(d.getFullYear()).slice(2);
  const mm = String(d.getMonth() + 1).padStart(2, '0');
  const count = JOURNAL_ENTRIES.filter(je => {
    const jd = new Date(je.date + 'T00:00:00');
    return String(jd.getFullYear()).slice(2) === yy &&
           String(jd.getMonth() + 1).padStart(2, '0') === mm;
  }).length;
  return `${yy}-${mm}-${String(count + 1).padStart(5, '0')}`;
}

function nextVoucherNumber(dateStr) {
  const d = dateStr ? new Date(dateStr + 'T00:00:00') : new Date('2026-05-30');
  const yy = String(d.getFullYear()).slice(2);
  const mm = String(d.getMonth() + 1).padStart(2, '0');
  const count = BILLS.filter(b => {
    const bd = new Date(b.date + 'T00:00:00');
    return String(bd.getFullYear()).slice(2) === yy &&
           String(bd.getMonth() + 1).padStart(2, '0') === mm;
  }).length;
  return `${yy}-${mm}-${String(count + 1).padStart(5, '0')}`;
}

function openModal(id) {
  const el = document.getElementById(id);
  const already = document.querySelectorAll('.overlay.open').length;
  el.style.zIndex = already > 0 ? 400 : '';
  el.classList.add('open');
  if (id === 'modal-je') {
    const jeDateInput = document.getElementById('je-date');
    const jeNumInput  = document.getElementById('je-number');
    if (!jeDateInput.value) jeDateInput.value = '2026-05-30';
    if (!jeNumInput.value) jeNumInput.value = nextJENumber(jeDateInput.value);
    jeDateInput.onchange = () => {
      jeNumInput.placeholder = nextJENumber(jeDateInput.value);
    };
  }
  if (id === 'modal-invoice') {
    invActiveCustomer = null;
    const invDateInput = document.getElementById('inv-date');
    const invNumInput  = document.getElementById('inv-number');
    if (!invDateInput.value) invDateInput.value = '2026-05-30';
    if (!invNumInput.value) invNumInput.value = nextInvoiceNumber(invDateInput.value);
    invDateInput.onchange = () => {
      invNumInput.placeholder = nextInvoiceNumber(invDateInput.value);
    };
    if (!document.getElementById('inv-lines').children.length)
      addInvLine();
  }
  if (id === 'modal-bill') {
    billActiveVendor = null;
    const dateInput = document.getElementById('bill-date');
    if (!dateInput.value) dateInput.value = '2026-05-30';
    document.getElementById('bill-number').textContent = nextVoucherNumber(dateInput.value);
    dateInput.onchange = () => {
      document.getElementById('bill-number').textContent = nextVoucherNumber(dateInput.value);
    };
    if (!document.getElementById('bill-lines').children.length)
      addBillLine();
  }
  if (id === 'modal-add-customer') {
    _editingCustomerCode = null;
    document.getElementById('modal-add-customer-title').textContent = 'Add Customer';
    document.getElementById('new-cust-code').value    = nextCustomerCode();
    document.getElementById('new-cust-name').value    = '';
    document.getElementById('new-cust-contact').value = '';
    document.getElementById('new-cust-phone').value   = '';
    document.getElementById('new-cust-email').value   = '';
    document.getElementById('new-cust-tin').value     = '';
    document.getElementById('new-cust-terms').value   = 'Net 30';
    document.getElementById('new-cust-status').value  = 'Active';
    document.getElementById('new-cust-address').value = '';
    document.getElementById('new-cust-postal').value  = '';
    document.getElementById('new-cust-vat').value     = 'VATSG';
    document.querySelectorAll('#new-cust-wt-checks input').forEach(cb => cb.checked = false);
  }
  if (id === 'modal-add-vendor') {
    _editingVendorCode = null;
    document.getElementById('modal-add-vendor-title').textContent = 'Add Vendor';
    document.getElementById('new-vend-code').value    = nextVendorCode();
    document.getElementById('new-vend-name').value    = '';
    document.getElementById('new-vend-contact').value = '';
    document.getElementById('new-vend-phone').value   = '';
    document.getElementById('new-vend-email').value   = '';
    document.getElementById('new-vend-tin').value     = '';
    document.getElementById('new-vend-terms').value   = 'Net 30';
    document.getElementById('new-vend-status').value  = 'Active';
    document.getElementById('new-vend-address').value = '';
    document.getElementById('new-vend-postal').value  = '';
    document.getElementById('new-vend-vat').value         = 'VATOG';
    document.getElementById('new-vend-check-payee').value = '';
    document.querySelectorAll('#new-vend-wt-checks input').forEach(cb => cb.checked = false);
  }
  if (id === 'modal-add-account') {
    // Only initialise SearchSelectTag once; reuse on subsequent opens
    const wrap = document.getElementById('new-acct-parent-wrap');
    if (wrap && !wrap.querySelector('input')) {
      createSearchSelectTag(wrap, ACCOUNTS.filter(a => a.isMain), {
        inputClass: 'form-control',
        placeholder: 'Search main account…',
        onSelect: a => {
          document.getElementById('new-acct-type').value = a.type;
          updateNewAcctClassification();
        },
      });
    }
    // Reset to "Add New Account" defaults
    _editingAccountCode = null;
    _accountModalMode   = 'add';
    document.getElementById('modal-add-account-title').textContent = 'Add New Account';
    document.getElementById('new-acct-level').value = 'sub';
    document.getElementById('new-acct-code').value  = '';
    document.getElementById('new-acct-code').readOnly = false;
    document.getElementById('new-acct-code').style.background = '';
    document.getElementById('new-acct-name').value  = '';
    document.getElementById('new-acct-type').value  = '';
    document.getElementById('new-acct-nb').value    = 'Debit';
    document.getElementById('new-acct-desc').value  = '';
    document.getElementById('new-acct-reason').value = '';
    document.getElementById('new-acct-used-banner').style.display  = 'none';
    document.getElementById('new-acct-reason-group').style.display = 'none';
    document.getElementById('modal-acct-save-btn').textContent = 'Save Account';
    toggleNewAcctLevel('sub');
    updateNewAcctClassification();
  }
}

let _editingAccountCode = null;
let _accountModalMode   = 'add'; // 'add' | 'edit-direct' | 'edit-approval'

function toggleNewAcctLevel(level) {
  const parentGroup = document.getElementById('new-acct-parent-group');
  const typeSelect  = document.getElementById('new-acct-type');
  if (level === 'main') {
    parentGroup.style.display = 'none';
    typeSelect.disabled = false;
  } else {
    parentGroup.style.display = '';
    typeSelect.disabled = true;
  }
  updateNewAcctClassification();
}

function updateNewAcctClassification() {
  const level = document.getElementById('new-acct-level')?.value;
  const type  = document.getElementById('new-acct-type')?.value;
  const group = document.getElementById('new-acct-class-group');
  if (!group) return;
  group.style.display = (level === 'main' && (type === 'Asset' || type === 'Liability')) ? '' : 'none';

  // Auto-set Normal Balance from type (user may override for contra accounts)
  const nbSel = document.getElementById('new-acct-nb');
  if (nbSel && type && _accountModalMode === 'add') {
    nbSel.value = (type === 'Asset' || type === 'Expense') ? 'Debit' : 'Credit';
  }
}
function closeModal(id) {
  const el = document.getElementById(id);
  el.classList.remove('open');
  el.style.zIndex = '';
}

document.querySelectorAll('[data-open-modal]').forEach(btn => {
  btn.addEventListener('click', () => openModal(btn.dataset.openModal));
});
document.querySelectorAll('[data-close-modal]').forEach(btn => {
  btn.addEventListener('click', () => closeModal(btn.dataset.closeModal));
});

/* ─── Journal Entry Form ───────────────────────────────────── */
let jeLines = 0;

function buildAccountOptions(selected='') {
  return ACCOUNTS.map(a =>
    `<option value="${a.code}" ${a.code===selected?'selected':''}>${a.code} — ${a.name}</option>`
  ).join('');
}

function addJELine() {
  jeLines++;
  const tbody = document.getElementById('je-lines-body');
  const tr = document.createElement('tr');
  tr.dataset.line = jeLines;

  const acctTd   = document.createElement('td');
  const descTd   = document.createElement('td');
  const drTd     = document.createElement('td');
  const crTd     = document.createElement('td');
  const removeTd = document.createElement('td');

  descTd.innerHTML   = `<input class="line-input" type="text" placeholder="Description">`;
  drTd.innerHTML     = `<input class="line-input amt" type="text" inputmode="decimal" placeholder="0.00" oninput="updateJETotals()">`;
  crTd.innerHTML     = `<input class="line-input amt" type="text" inputmode="decimal" placeholder="0.00" oninput="updateJETotals()">`;
  removeTd.innerHTML = `<button class="btn btn-ghost btn-sm" onclick="removeJELine(this)" title="Remove line">✕</button>`;

  tr.append(acctTd, descTd, drTd, crTd, removeTd);
  tbody.appendChild(tr);

  createSearchSelectTag(acctTd, ACCOUNTS.filter(a => !a.isMain), { placeholder: 'Search account…' });
  updateJETotals();
}

function removeJELine(btn) {
  btn.closest('tr').remove();
  updateJETotals();
}

function updateJETotals() {
  let totalDr = 0, totalCr = 0;
  document.querySelectorAll('#je-lines-body tr').forEach(tr => {
    const inputs = tr.querySelectorAll('input.amt');
    totalDr += parseAmt(inputs[0]?.value);
    totalCr += parseAmt(inputs[1]?.value);
  });
  document.getElementById('je-total-dr').textContent = fmt(totalDr);
  document.getElementById('je-total-cr').textContent = fmt(totalCr);
  const balanced = Math.abs(totalDr - totalCr) < 0.005;
  const drEl = document.getElementById('je-total-dr');
  const crEl = document.getElementById('je-total-cr');
  const msg   = document.getElementById('je-balance-msg');
  const postBtn = document.getElementById('je-post-btn');
  if (balanced && totalDr > 0) {
    drEl.className = 'tot-value tot-balanced';
    crEl.className = 'tot-value tot-balanced';
    msg.className  = 'balance-msg balance-ok';
    msg.textContent= '✓ Balanced';
    postBtn.disabled = false;
  } else {
    drEl.className = 'tot-value tot-unbalanced';
    crEl.className = 'tot-value tot-unbalanced';
    msg.className  = 'balance-msg balance-err';
    msg.textContent= totalDr > 0 || totalCr > 0 ? '✗ Not balanced' : '';
    postBtn.disabled = true;
  }
}

function switchJEParty() {
  const val = document.querySelector('input[name="je-party-type"]:checked')?.value || 'none';
  document.getElementById('je-party-customer-wrap').style.display = val === 'customer' ? '' : 'none';
  document.getElementById('je-party-vendor-wrap').style.display   = val === 'vendor'   ? '' : 'none';
}

function resetJEForm() {
  document.getElementById('je-form').reset();
  document.getElementById('je-number').value = '';
  document.getElementById('je-lines-body').innerHTML = '';
  document.getElementById('je-party-none').checked = true;
  switchJEParty();
  jeLines = 0;
  updateJETotals();
  addJELine(); addJELine();
}

function postJE(asDraft) {
  const status = asDraft ? 'Draft' : (_currentUser.role === 'Accountant' ? 'Approved' : 'Submitted');
  const ref    = document.getElementById('je-number').value.trim()
              || nextJENumber(document.getElementById('je-date').value);
  const date   = document.getElementById('je-date').value || '2026-05-30';
  const desc   = document.getElementById('je-desc').value.trim() || '(no description)';

  const lines = [];
  document.querySelectorAll('#je-lines-body tr').forEach(tr => {
    const inputs   = tr.querySelectorAll('input');
    const acctCode = inputs[0]?.dataset.code || '';
    const acct     = ACCOUNTS.find(a => a.code === acctCode);
    const dr       = parseAmt(inputs[2]?.value);
    const cr       = parseAmt(inputs[3]?.value);
    if (dr > 0 || cr > 0)
      lines.push({ acct: acctCode, acctName: acct?.name || '—', desc: inputs[1]?.value || '', dr, cr });
  });

  JOURNAL_ENTRIES.push({ id: ref, date, ref, desc, status, lines });
  renderJournalEntries();
  closeModal('modal-je');
  resetJEForm();
}

/* ─── Toast notification ────────────────────────────────────── */
function showToast(msg, type = 'success') {
  let el = document.getElementById('app-toast');
  if (!el) {
    el = document.createElement('div');
    el.id = 'app-toast';
    el.style.cssText = 'position:fixed;bottom:24px;right:24px;padding:10px 18px;border-radius:8px;font-size:13px;font-weight:600;color:#fff;z-index:9999;opacity:0;transition:opacity .25s;pointer-events:none';
    document.body.appendChild(el);
  }
  el.textContent = msg;
  el.style.background = type === 'success' ? '#15803d' : type === 'warn' ? '#d97706' : '#dc2626';
  el.style.opacity = '1';
  clearTimeout(el._t);
  el._t = setTimeout(() => { el.style.opacity = '0'; }, 3000);
}

/* ─── Chart of Accounts — COA edit/save/approval ────────────── */
function isAccountUsed(code) {
  return JOURNAL_ENTRIES.some(je => je.lines.some(l => l.acct === code));
}

function openEditAccount(code) {
  const acct = ACCOUNTS.find(a => a.code === code);
  if (!acct) return;

  const used = isAccountUsed(code);

  openModal('modal-add-account'); // resets state vars and form fields

  // Now override the reset for edit mode
  _editingAccountCode = code;
  _accountModalMode   = used ? 'edit-approval' : 'edit-direct';

  document.getElementById('modal-add-account-title').textContent =
    used ? 'Request Account Change' : 'Edit Account';

  document.getElementById('new-acct-level').value = acct.isMain ? 'main' : 'sub';
  toggleNewAcctLevel(acct.isMain ? 'main' : 'sub');
  document.getElementById('new-acct-code').value  = acct.code;
  document.getElementById('new-acct-name').value  = acct.name;
  document.getElementById('new-acct-type').value  = acct.type;
  document.getElementById('new-acct-nb').value    = acct.nb;
  document.getElementById('new-acct-desc').value  = acct.description || '';
  if (acct.classification) {
    document.getElementById('new-acct-classification').value = acct.classification;
  }
  updateNewAcctClassification();  // show/hide classification row

  if (used) {
    document.getElementById('new-acct-code').readOnly = true;
    document.getElementById('new-acct-code').style.background = '#f1f5f9';
    document.getElementById('new-acct-used-banner').style.display  = '';
    document.getElementById('new-acct-reason-group').style.display = '';
    document.getElementById('modal-acct-save-btn').textContent = 'Submit for Approval';
  }
}

function saveAccount() {
  const level = document.getElementById('new-acct-level').value;
  const code  = document.getElementById('new-acct-code').value.trim();
  const name  = document.getElementById('new-acct-name').value.trim();
  const type  = document.getElementById('new-acct-type').value;
  const nb    = document.getElementById('new-acct-nb').value;
  const desc  = document.getElementById('new-acct-desc').value.trim();
  const classification = document.getElementById('new-acct-classification').value;

  if (!code) { alert('Account Code is required.'); return; }
  if (!name) { alert('Account Name is required.'); return; }
  if (!type) { alert('Account Type is required.'); return; }

  // ── Approval submission for used accounts ────────────────────
  if (_accountModalMode === 'edit-approval') {
    const reason = document.getElementById('new-acct-reason').value.trim();
    if (!reason) { alert('Please provide a reason for this change.'); return; }

    const acct = ACCOUNTS.find(a => a.code === _editingAccountCode);
    const changedFields = [];
    if (name !== acct.name)                   changedFields.push({ field:'Name',           from:acct.name,           to:name });
    if (type !== acct.type)                   changedFields.push({ field:'Type',           from:acct.type,           to:type });
    if (nb   !== acct.nb)                     changedFields.push({ field:'Normal Balance', from:acct.nb,             to:nb   });
    if ((acct.classification||'') !== classification && document.getElementById('new-acct-class-group').style.display !== 'none')
                                              changedFields.push({ field:'Classification', from:acct.classification, to:classification });
    if (desc !== (acct.description||''))      changedFields.push({ field:'Description',    from:acct.description||'(none)', to:desc||'(none)' });

    if (!changedFields.length) { showToast('No changes detected.', 'warn'); return; }

    const reqId = Date.now();
    ACCOUNT_CHANGE_REQUESTS.push({
      id: reqId,
      accountCode: _editingAccountCode,
      accountName: acct.name,
      submittedBy: _currentUser.name,
      submittedDate: TODAY_STR,
      changedFields,
      reason,
      status: 'Pending',
    });

    logAudit({ category:'coa', recordType:'Account', recordId:_editingAccountCode, event:'change_requested', changes: Object.fromEntries(changedFields.map(c => [c.field, {from:c.from, to:c.to}])), note:reason });

    closeModal('modal-add-account');
    renderPendingApprovals();
    renderActionsWidget();
    renderActionsPage();
    showToast('Change request submitted for accountant approval.', 'warn');
    return;
  }

  // ── Direct save (new account or unused account edit) ─────────
  const isMain   = level === 'main';
  const parentEl = document.querySelector('#new-acct-parent-wrap input');
  const parent   = isMain ? null : (parentEl?.dataset.code || null);

  if (!isMain && !parent) { alert('Please select a parent account.'); return; }

  if (_accountModalMode === 'add') {
    if (ACCOUNTS.find(a => a.code === code)) { alert(`Account code "${code}" already exists.`); return; }
    ACCOUNTS.push({ code, name, type, nb, classification: isMain ? classification : undefined,
                    balance: 0, isMain, parent, description: desc || undefined });
    logAudit({ category:'coa', recordType:'Account', recordId:code, event:'created', changes:{name:{from:null, to:name}, type:{from:null, to:type}, nb:{from:null, to:nb}} });
  } else {
    const idx = ACCOUNTS.findIndex(a => a.code === _editingAccountCode);
    if (idx !== -1) {
      const before = { name: ACCOUNTS[idx].name, type: ACCOUNTS[idx].type, nb: ACCOUNTS[idx].nb, classification: ACCOUNTS[idx].classification, description: ACCOUNTS[idx].description };
      Object.assign(ACCOUNTS[idx], { name, type, nb, description: desc || undefined,
        classification: isMain ? classification : undefined });
      const after = { name, type, nb, classification: isMain ? classification : undefined, description: desc || undefined };
      const changes = {};
      Object.keys(after).forEach(k => { if (before[k] !== after[k]) changes[k] = { from: before[k] ?? null, to: after[k] ?? null }; });
      if (Object.keys(changes).length) {
        logAudit({ category:'coa', recordType:'Account', recordId:_editingAccountCode, event:'edited', changes });
      }
    }
  }

  closeModal('modal-add-account');
  renderCOA(document.getElementById('coa-type-filter').value || 'All');
  showToast(_accountModalMode === 'add' ? 'Account created.' : 'Account updated.');
}

function approveChangeRequest(id) {
  const req = ACCOUNT_CHANGE_REQUESTS.find(r => r.id === id);
  if (!req || req.status !== 'Pending') return;

  const acct = ACCOUNTS.find(a => a.code === req.accountCode);
  const changes = {};
  if (acct) {
    req.changedFields.forEach(cf => {
      const fieldMap = { 'Name':'name', 'Type':'type', 'Normal Balance':'nb', 'Classification':'classification', 'Description':'description' };
      const key = fieldMap[cf.field];
      if (key) {
        changes[key] = { from: cf.from, to: cf.to };
        acct[key] = (cf.field === 'Description' && cf.to === '(none)') ? undefined : cf.to;
      }
    });
  }
  req.status = 'Approved';
  req.decidedBy = _currentUser.name;
  req.decidedAt = _auditTs();

  logAudit({ category:'coa', recordType:'Account', recordId:req.accountCode, event:'change_approved', changes, note:`Request #${req.id} — ${req.reason}` });

  renderCOA(document.getElementById('coa-type-filter').value || 'All');
  renderPendingApprovals();
  renderTrialBalance();
  renderIncomeStatement();
  renderBalanceSheet();
  renderActionsWidget();
  renderActionsPage();
  showToast('Change approved and applied.');
}

function rejectChangeRequest(id) {
  const req = ACCOUNT_CHANGE_REQUESTS.find(r => r.id === id);
  if (!req || req.status !== 'Pending') return;
  req.status = 'Rejected';
  req.decidedBy = _currentUser.name;
  req.decidedAt = _auditTs();

  logAudit({ category:'coa', recordType:'Account', recordId:req.accountCode, event:'change_rejected', note:`Request #${req.id} — ${req.reason}` });

  renderPendingApprovals();
  renderActionsWidget();
  renderActionsPage();
  showToast('Change request rejected.', 'error');
}

function renderPendingApprovals() {
  const pending = ACCOUNT_CHANGE_REQUESTS.filter(r => r.status === 'Pending');
  const section = document.getElementById('coa-pending-section');
  const list    = document.getElementById('coa-pending-list');
  const badge   = document.getElementById('coa-pending-badge');
  if (!section) return;

  if (!pending.length) { section.style.display = 'none'; return; }

  section.style.display = '';
  badge.textContent = pending.length;

  list.innerHTML = pending.map(req => `
    <div style="padding:12px 16px;border-bottom:1px solid #fde68a;display:grid;grid-template-columns:1fr auto;gap:12px;align-items:start">
      <div>
        <div style="font-weight:600;font-size:13px;margin-bottom:6px">
          <code style="background:#f1f5f9;padding:1px 6px;border-radius:4px;font-size:12px">${req.accountCode}</code>
          ${req.accountName}
        </div>
        ${req.changedFields.map(cf => `
          <div style="font-size:12px;color:#374151;margin-bottom:2px">
            <span style="font-weight:600">${cf.field}:</span>
            <span style="color:#6b7280;text-decoration:line-through;margin:0 4px">${cf.from}</span>
            <span style="color:#15803d">→ ${cf.to}</span>
          </div>`).join('')}
        <div style="font-size:12px;color:#6b7280;margin-top:6px">
          <span style="font-weight:600;color:#92400e">Reason:</span> ${req.reason}
          &nbsp;&nbsp;<span style="color:#9ca3af">${req.submittedDate}</span>
        </div>
      </div>
      <div style="display:flex;gap:8px;flex-shrink:0;padding-top:2px">
        <button class="btn btn-success btn-sm" onclick="approveChangeRequest(${req.id})">Approve</button>
        <button class="btn btn-danger btn-sm" onclick="rejectChangeRequest(${req.id})">Reject</button>
      </div>
    </div>`).join('');
}

/* ─── Chart of Accounts — filter & render ──────────────────── */
function mainAcctBalance(main) {
  return ACCOUNTS.filter(a => a.parent === main.code).reduce((sum, sub) =>
    sum + (sub.nb === main.nb ? sub.balance : -sub.balance), 0);
}

function renderCOA(filterType='All') {
  const types = ['Asset','Liability','Equity','Revenue','Expense'];
  const display = filterType === 'All' ? types : [filterType];
  const tbody = document.getElementById('coa-tbody');
  tbody.innerHTML = '';

  // Map of accounts with a pending change request (for badge display)
  const pendingCodes = new Set(
    ACCOUNT_CHANGE_REQUESTS.filter(r => r.status === 'Pending').map(r => r.accountCode)
  );

  display.forEach(type => {
    const mains = ACCOUNTS.filter(a => a.type === type && a.isMain);
    if (!mains.length) return;

    const groupRow = document.createElement('tr');
    groupRow.className = 'group-header';
    groupRow.innerHTML = `<td colspan="7">${type}s</td>`;
    tbody.appendChild(groupRow);

    const cls = `type-${type.toLowerCase()}`;

    mains.forEach(main => {
      const bal = mainAcctBalance(main);
      const balDisplay = `<span class="${main.nb === 'Credit' ? 'cr' : 'dr'}">${fmt(bal)}</span>`;
      const mainTr = document.createElement('tr');
      mainTr.className = `${cls} main-acct-row`;
      const classLabel = main.classification ? `<span class="badge badge-classification-${main.classification.toLowerCase().replace('-','')}">${main.classification}</span>` : '';
      mainTr.innerHTML = `
        <td class="fw-7 mono">${main.code}</td>
        <td class="fw-7">${main.name}</td>
        <td><span class="badge badge-${type.toLowerCase()}">${type}</span></td>
        <td>${classLabel}</td>
        <td class="text-2">—</td>
        <td class="r">${balDisplay}</td>
        <td></td>`;
      tbody.appendChild(mainTr);

      ACCOUNTS.filter(a => a.parent === main.code).forEach(sub => {
        const subBal = `<span class="${sub.nb === 'Credit' ? 'cr' : 'dr'}">${fmt(sub.balance)}</span>`;
        const hasPending = pendingCodes.has(sub.code);
        const pendingBadge = hasPending
          ? `<span style="font-size:10px;background:#f59e0b;color:#fff;padding:1px 6px;border-radius:999px;margin-left:4px;vertical-align:middle">Pending</span>`
          : '';
        const subTr = document.createElement('tr');
        subTr.className = `${cls} sub-acct-row`;
        subTr.innerHTML = `
          <td class="sub-code">${sub.code}</td>
          <td class="sub-name">${sub.name}${pendingBadge}</td>
          <td></td>
          <td></td>
          <td class="text-2 text-sm">${sub.nb}</td>
          <td class="r">${subBal}</td>
          <td style="text-align:right;padding-right:12px">
            <button class="btn btn-ghost btn-sm" onclick="openEditAccount('${sub.code}')">Edit</button>
          </td>`;
        tbody.appendChild(subTr);
      });
    });
  });
}

document.getElementById('coa-type-filter')?.addEventListener('change', e => renderCOA(e.target.value));

/* ─── General Ledger — render ──────────────────────────────── */
function renderLedger(code) {
  if (code === undefined) {
    const inp = document.querySelector('#ledger-acct-wrap input');
    code = inp?.dataset.code || '';
  }
  const acct = ACCOUNTS.find(a => a.code === code);
  const rows  = LEDGER[code] || [];
  const info  = document.getElementById('ledger-acct-info');
  const tbody = document.getElementById('ledger-tbody');
  const foot  = document.getElementById('ledger-foot');

  if (!acct) { info.textContent = ''; tbody.innerHTML = ''; return; }

  info.innerHTML = `
    <span class="badge badge-${acct.type.toLowerCase()}">${acct.type}</span>
    <span class="text-sm text-2 ml-1">${acct.name} — Normal Balance: <strong>${acct.nb}</strong></span>`;

  tbody.innerHTML = rows.map(r => `
    <tr>
      <td>${r.date}</td>
      <td>${r.desc}</td>
      <td class="text-3 text-sm">${r.ref}</td>
      <td class="dr">${r.dr > 0 ? fmt(r.dr) : '—'}</td>
      <td class="cr">${r.cr > 0 ? fmt(r.cr) : '—'}</td>
      <td class="num fw-7">${fmt(r.bal)}</td>
    </tr>`).join('');

  const totalDr = rows.reduce((s,r)=>s+r.dr,0);
  const totalCr = rows.reduce((s,r)=>s+r.cr,0);
  foot.innerHTML = `
    <tr class="tfoot-row">
      <td colspan="3" class="fw-7">Closing Balance</td>
      <td class="dr">${fmt(totalDr)}</td>
      <td class="cr">${fmt(totalCr)}</td>
      <td class="num fw-7">${fmt(acct.balance)}</td>
    </tr>`;
}

// ledger account selector is wired via SearchSelectTag onSelect in DOMContentLoaded

/* ─── Tabs ─────────────────────────────────────────────────── */
document.querySelectorAll('.tabs').forEach(tabGroup => {
  tabGroup.querySelectorAll('.tab').forEach(tab => {
    tab.addEventListener('click', () => {
      const group = tab.dataset.tabGroup;
      const target = tab.dataset.tab;
      document.querySelectorAll(`[data-tab-group="${group}"]`).forEach(t => t.classList.remove('active'));
      document.querySelectorAll(`[data-tab-panel="${group}"]`).forEach(p => p.classList.remove('active'));
      tab.classList.add('active');
      document.getElementById(`${group}-${target}`)?.classList.add('active');
    });
  });
});

/* ─── SearchSelectTag ───────────────────────────────────────── */
function createSearchSelectTag(container, data, options = {}) {
  const inputClass  = options.inputClass  || 'line-input acct-input';
  const placeholder = options.placeholder || 'Search…';
  const onSelect    = options.onSelect    || null;
  const actions     = options.actions     || [];

  const wrap = document.createElement('div');
  wrap.className = 'acct-wrap';

  const input = document.createElement('input');
  input.className = inputClass;
  input.type = 'text';
  input.placeholder = placeholder;
  input.autocomplete = 'off';
  input.dataset.code = '';

  // Dropdown appended to body so it escapes overflow:hidden containers
  const dropdown = document.createElement('div');
  dropdown.className = 'acct-dropdown';
  document.body.appendChild(dropdown);

  let activeIdx = -1;

  function position() {
    const r = input.getBoundingClientRect();
    dropdown.style.top   = `${r.bottom + 2}px`;
    dropdown.style.left  = `${r.left}px`;
    dropdown.style.width = `${Math.max(r.width, 240)}px`;
  }

  function getOpts() {
    return [...dropdown.querySelectorAll('.acct-option:not(.acct-no-result)')];
  }

  function setActive(idx) {
    const opts = getOpts();
    opts.forEach(o => o.classList.remove('active'));
    activeIdx = Math.max(0, Math.min(idx, opts.length - 1));
    if (opts[activeIdx]) {
      opts[activeIdx].classList.add('active');
      opts[activeIdx].scrollIntoView({ block: 'nearest' });
    }
  }

  function selectAccount(a) {
    input.value        = `${a.code} — ${a.name}`;
    input.dataset.code = a.code;
    hide();
    if (onSelect) onSelect(a);
  }

  function build(q = '') {
    const ql = q.toLowerCase();
    const hits = data.filter(a =>
      !ql || a.code.toLowerCase().startsWith(ql) || a.name.toLowerCase().includes(ql)
    );
    dropdown.innerHTML = '';
    activeIdx = -1;

    // Action items — always shown at the top
    actions.forEach(action => {
      const opt = document.createElement('div');
      opt.className = 'acct-option acct-action';
      opt.innerHTML = `<span class="acct-action-label">${action.label}</span>`;
      opt._actionFn = action.onAction;
      opt.addEventListener('mousedown', e => { e.preventDefault(); action.onAction(); hide(); });
      dropdown.appendChild(opt);
    });

    if (!hits.length) {
      if (!actions.length) { hide(); return; }
      dropdown.style.display = 'block';
      return;
    }
    if (hits.length === 1 && !actions.length) {
      selectAccount(hits[0]);
      return;
    }
    if (actions.length) {
      const sep = document.createElement('div');
      sep.className = 'acct-action-sep';
      dropdown.appendChild(sep);
    }
    hits.forEach(a => {
      const opt = document.createElement('div');
      opt.className = 'acct-option';
      opt.dataset.code = a.code;
      const rateBadge = a.rate != null ? `<span class="acct-opt-rate">${a.rate}</span>` : '';
      opt.innerHTML = `<span class="acct-opt-code">${a.code}</span><span class="acct-opt-name">${a.name}</span>${rateBadge}`;
      opt.addEventListener('mousedown', e => { e.preventDefault(); selectAccount(a); });
      dropdown.appendChild(opt);
    });
  }

  function show() {
    position();
    build(input.value);
    dropdown.style.display = 'block';
  }

  function hide() {
    dropdown.style.display = 'none';
    activeIdx = -1;
  }

  input.addEventListener('focus', () => { input.select(); show(); });

  input.addEventListener('input', () => {
    input.dataset.code = '';
    build(input.value);
    position();
    dropdown.style.display = 'block';
  });

  input.addEventListener('blur', () => setTimeout(hide, 150));

  input.addEventListener('keydown', e => {
    const opts = getOpts();
    if (e.key === 'ArrowDown') {
      e.preventDefault();
      setActive(activeIdx < 0 ? 0 : activeIdx + 1);
    } else if (e.key === 'ArrowUp') {
      e.preventDefault();
      setActive(activeIdx - 1);
    } else if (e.key === 'Enter') {
      e.preventDefault();
      const opt = opts[activeIdx];
      if (opt) {
        if (opt._actionFn) { opt._actionFn(); hide(); }
        else { const a = data.find(a => a.code === opt.dataset.code); if (a) selectAccount(a); }
      }
    } else if (e.key === 'Escape') {
      hide();
      input.blur();
    }
  });

  // Remove dropdown from body when the row is deleted
  const observer = new MutationObserver(() => {
    if (!document.body.contains(input)) { dropdown.remove(); observer.disconnect(); }
  });
  observer.observe(document.body, { childList: true, subtree: true });

  wrap.appendChild(input);
  container.appendChild(wrap);
  return input;
}

/* ─── Invoice / Bill modals ─────────────────────────────────── */
let invLines = 0;

// Active customer/vendor context for invoice and bill modals
let invActiveCustomer = null;
let billActiveVendor  = null;
let _wtPickerCb       = null;

function setSearchSelectValue(input, item) {
  if (!input || !item) return;
  input.value        = `${item.code} — ${item.name}`;
  input.dataset.code = item.code;
}

function showWtPicker(wtCodes, callback) {
  _wtPickerCb = callback;
  const body = document.getElementById('wt-picker-body');
  body.innerHTML = wtCodes.map((code, i) => {
    const wt = WITHHOLDING_TAXES.find(w => w.code === code);
    if (!wt) return '';
    return `<label class="wt-check-item" style="padding:10px 8px">
      <input type="radio" name="wt-pick" value="${code}" ${i === 0 ? 'checked' : ''}>
      <span class="wt-code">${wt.code}</span>
      <span class="wt-name" style="flex:1">${wt.name}</span>
      <span class="wt-rate">${wt.rate}</span>
    </label>`;
  }).join('');
  openModal('modal-wt-picker');
}

function confirmWtPick() {
  const sel = document.querySelector('#wt-picker-body input[name=wt-pick]:checked');
  closeModal('modal-wt-picker');
  if (sel && _wtPickerCb) _wtPickerCb(sel.value);
  _wtPickerCb = null;
}

function applyCustomerDefaults(customer) {
  const vtCode  = customer.defaultVat;
  const wtCodes = customer.defaultWt || [];

  const applyToAllLines = wtCode => {
    document.getElementById('inv-lines')?.querySelectorAll('tr').forEach(tr => {
      const tags = [...tr.querySelectorAll('input[data-code]')];
      if (tags.length < 3) return;
      if (vtCode) { const v = OUTPUT_VAT_TYPES.find(v => v.code === vtCode); if (v) setSearchSelectValue(tags[1], v); }
      if (wtCode) { const w = WITHHOLDING_TAXES.find(w => w.code === wtCode); if (w) setSearchSelectValue(tags[2], w); }
    });
    buildInvEntry();
  };

  if (wtCodes.length > 1) showWtPicker(wtCodes, applyToAllLines);
  else applyToAllLines(wtCodes[0] || null);
}

function applyVendorDefaults(vendor) {
  const vtCode  = vendor.defaultVat;
  const wtCodes = vendor.defaultWt || [];

  const applyToAllLines = wtCode => {
    document.getElementById('bill-lines')?.querySelectorAll('tr').forEach(tr => {
      const tags = [...tr.querySelectorAll('input[data-code]')];
      if (tags.length < 3) return;
      if (vtCode) { const v = VAT_TYPES.find(v => v.code === vtCode); if (v) setSearchSelectValue(tags[1], v); }
      if (wtCode) { const w = WITHHOLDING_TAXES.find(w => w.code === wtCode); if (w) setSearchSelectValue(tags[2], w); }
    });
    buildBillEntry();
  };

  if (wtCodes.length > 1) showWtPicker(wtCodes, applyToAllLines);
  else applyToAllLines(wtCodes[0] || null);
}
function addInvLine() {
  const revenueAccounts = ACCOUNTS.filter(a => !a.isMain);
  const tbody = document.getElementById('inv-lines');
  const tr = document.createElement('tr');

  const descTd   = document.createElement('td');
  const acctTd   = document.createElement('td');
  const vtTd     = document.createElement('td');
  const wtTd     = document.createElement('td');
  const amtTd    = document.createElement('td');
  const removeTd = document.createElement('td');

  amtTd.className = 'num';

  descTd.innerHTML   = `<input class="line-input" type="text" placeholder="Description" style="width:100%">`;
  amtTd.innerHTML    = `<input class="line-input amt" type="text" inputmode="decimal" placeholder="0.00" oninput="calcInvTotal()">`;
  removeTd.innerHTML = `<button class="btn btn-ghost btn-sm" onclick="this.closest('tr').remove();calcInvTotal()" title="Remove line">✕</button>`;

  tr.append(descTd, acctTd, vtTd, wtTd, amtTd, removeTd);
  tbody.appendChild(tr);

  createSearchSelectTag(acctTd, revenueAccounts, { placeholder: 'Search account…', onSelect: () => buildInvEntry() });
  const vtInput = createSearchSelectTag(vtTd, OUTPUT_VAT_TYPES,  { placeholder: 'VAT type…', onSelect: () => buildInvEntry() });
  const wtInput = createSearchSelectTag(wtTd, WITHHOLDING_TAXES, { placeholder: 'ATC code…', onSelect: () => buildInvEntry() });

  if (invActiveCustomer) {
    const vtCode  = invActiveCustomer.defaultVat;
    const wtCodes = invActiveCustomer.defaultWt || [];
    const applyLine = wtCode => {
      if (vtCode) { const v = OUTPUT_VAT_TYPES.find(v => v.code === vtCode); if (v) setSearchSelectValue(vtInput, v); }
      if (wtCode) { const w = WITHHOLDING_TAXES.find(w => w.code === wtCode); if (w) setSearchSelectValue(wtInput, w); }
      buildInvEntry();
    };
    if (wtCodes.length > 1) showWtPicker(wtCodes, applyLine);
    else applyLine(wtCodes[0] || null);
  }
}

function calcInvTotal() {
  let total = 0;
  document.getElementById('inv-lines')?.querySelectorAll('tr').forEach(tr => {
    const amt = tr.querySelector('input.amt');
    if (amt) total += parseAmt(amt.value);
  });
  const el = document.getElementById('inv-total');
  if (el) el.textContent = fmt(total);
  buildInvEntry();
}

function addBillLine() {
  const expenseAccounts = ACCOUNTS.filter(a => a.type === 'Expense' && !a.isMain);
  const tbody = document.getElementById('bill-lines');
  const tr = document.createElement('tr');

  const descTd   = document.createElement('td');
  const acctTd   = document.createElement('td');
  const vtTd     = document.createElement('td');
  const wtTd     = document.createElement('td');
  const amtTd    = document.createElement('td');
  const removeTd = document.createElement('td');

  amtTd.className = 'num';

  descTd.innerHTML   = `<input class="line-input" type="text" placeholder="Description" style="width:100%">`;
  amtTd.innerHTML    = `<input class="line-input amt" type="text" inputmode="decimal" placeholder="0.00" oninput="calcBillTotal()">`;
  removeTd.innerHTML = `<button class="btn btn-ghost btn-sm" onclick="this.closest('tr').remove();calcBillTotal()" title="Remove line">✕</button>`;

  tr.append(descTd, acctTd, vtTd, wtTd, amtTd, removeTd);
  tbody.appendChild(tr);

  createSearchSelectTag(acctTd, expenseAccounts, { placeholder: 'Search account…', onSelect: () => buildBillEntry() });
  const vtInput = createSearchSelectTag(vtTd, VAT_TYPES,         { placeholder: 'VAT type…', onSelect: () => buildBillEntry() });
  const wtInput = createSearchSelectTag(wtTd, WITHHOLDING_TAXES, { placeholder: 'ATC code…', onSelect: () => buildBillEntry() });

  if (billActiveVendor) {
    const vtCode  = billActiveVendor.defaultVat;
    const wtCodes = billActiveVendor.defaultWt || [];
    const applyLine = wtCode => {
      if (vtCode) { const v = VAT_TYPES.find(v => v.code === vtCode); if (v) setSearchSelectValue(vtInput, v); }
      if (wtCode) { const w = WITHHOLDING_TAXES.find(w => w.code === wtCode); if (w) setSearchSelectValue(wtInput, w); }
      buildBillEntry();
    };
    if (wtCodes.length > 1) showWtPicker(wtCodes, applyLine);
    else applyLine(wtCodes[0] || null);
  }
}

function calcBillTotal() {
  let total = 0;
  document.getElementById('bill-lines')?.querySelectorAll('tr').forEach(tr => {
    const amt = tr.querySelector('input.amt');
    if (amt) total += parseAmt(amt.value);
  });
  const el = document.getElementById('bill-total');
  if (el) el.textContent = fmt(total);
  buildBillEntry();
}

function buildBillEntry() {
  const section = document.getElementById('bill-entry-section');
  const tbody   = document.getElementById('bill-entry-body');
  if (!section || !tbody) return;

  const expenseMap  = {};  // acctCode → { code, name, base }
  const inputTaxMap = {};  // inputTaxAcctCode → amount
  let totalEWT   = 0;
  let totalGross = 0;

  document.getElementById('bill-lines')?.querySelectorAll('tr').forEach(tr => {
    const amtInput  = tr.querySelector('input.amt');
    const tagInputs = [...tr.querySelectorAll('input[data-code]')];
    if (!amtInput) return;

    const gross = parseAmt(amtInput.value);
    if (!gross) return;

    const acctCode = tagInputs[0]?.dataset.code || '';
    const vtCode   = tagInputs[1]?.dataset.code || '';
    const wtCode   = tagInputs[2]?.dataset.code || '';

    const vtItem = VAT_TYPES.find(v => v.code === vtCode);
    const wtItem = WITHHOLDING_TAXES.find(w => w.code === wtCode);

    const hasVAT = !!vtItem?.inputTaxAccount;
    const base   = hasVAT ? gross / 1.12 : gross;
    const vat    = hasVAT ? gross - base  : 0;

    // Expense debit — grouped by account code
    const key      = acctCode || '__none__';
    const acctName = acctCode
      ? (ACCOUNTS.find(a => a.code === acctCode)?.name || acctCode)
      : '(account not selected)';
    if (!expenseMap[key]) expenseMap[key] = { code: acctCode, name: acctName, base: 0 };
    expenseMap[key].base += base;

    // Input VAT debit — grouped by input tax account
    if (vat > 0) {
      const itCode = vtItem.inputTaxAccount;
      inputTaxMap[itCode] = (inputTaxMap[itCode] || 0) + vat;
    }

    // EWT — on the VAT-exclusive base
    if (wtItem) {
      const rate = parseFloat(wtItem.rate) / 100;
      totalEWT += base * rate;
    }

    totalGross += gross;
  });

  section.style.display = totalGross > 0 ? '' : 'none';
  if (!totalGross) return;

  const netAP = totalGross - totalEWT;
  const rows  = [];

  // Debit rows — expense accounts
  Object.values(expenseMap).forEach(({ code, name, base }) => {
    rows.push({ label: code ? `${code} — ${name}` : name, dr: base, cr: 0, indent: false });
  });

  // Debit rows — input tax (grouped by input tax account)
  Object.entries(inputTaxMap).forEach(([code, amount]) => {
    const name = ACCOUNTS.find(a => a.code === code)?.name || 'Input Tax';
    rows.push({ label: `${code} — ${name}`, dr: amount, cr: 0, indent: false });
  });

  // Credit rows
  if (totalEWT > 0) {
    const name = ACCOUNTS.find(a => a.code === EWT_PAYABLE_ACCOUNT)?.name || 'EWT Payable';
    rows.push({ label: `${EWT_PAYABLE_ACCOUNT} — ${name}`, dr: 0, cr: totalEWT, indent: true });
  }
  const apName = ACCOUNTS.find(a => a.code === '2001')?.name || 'AP — Trade';
  rows.push({ label: `2001 — ${apName}`, dr: 0, cr: netAP, indent: true });

  tbody.innerHTML = rows.map(r => `
    <tr>
      <td class="${r.indent ? 'be-cr-label' : ''}">${r.label}</td>
      <td class="r num">${r.dr > 0 ? fmt(r.dr) : ''}</td>
      <td class="r num">${r.cr > 0 ? fmt(r.cr) : ''}</td>
    </tr>`).join('');

  const totalDr = rows.reduce((s, r) => s + r.dr, 0);
  const totalCr = rows.reduce((s, r) => s + r.cr, 0);
  document.getElementById('bill-entry-dr').textContent = fmt(totalDr);
  document.getElementById('bill-entry-cr').textContent = fmt(totalCr);
}

function buildInvEntry() {
  const section = document.getElementById('inv-entry-section');
  const tbody   = document.getElementById('inv-entry-body');
  if (!section || !tbody) return;

  const revenueMap   = {};
  const outputVatMap = {};
  let totalGross = 0;
  let totalEWT   = 0;

  document.getElementById('inv-lines')?.querySelectorAll('tr').forEach(tr => {
    const amtInput  = tr.querySelector('input.amt');
    const tagInputs = [...tr.querySelectorAll('input[data-code]')];
    if (!amtInput) return;

    const gross = parseAmt(amtInput.value);
    if (!gross) return;

    const acctCode = tagInputs[0]?.dataset.code || '';
    const vtCode   = tagInputs[1]?.dataset.code || '';
    const wtCode   = tagInputs[2]?.dataset.code || '';

    const vtItem = OUTPUT_VAT_TYPES.find(v => v.code === vtCode);
    const hasVAT = !!vtItem?.outputTaxAccount;
    const base   = hasVAT ? gross / 1.12 : gross;
    const vat    = hasVAT ? gross - base  : 0;

    const wtItem = WITHHOLDING_TAXES.find(w => w.code === wtCode);
    const ewt    = wtItem ? base * parseFloat(wtItem.rate) / 100 : 0;

    const key      = acctCode || '__none__';
    const acctName = acctCode
      ? (ACCOUNTS.find(a => a.code === acctCode)?.name || acctCode)
      : '(account not selected)';
    if (!revenueMap[key]) revenueMap[key] = { code: acctCode, name: acctName, base: 0 };
    revenueMap[key].base += base;

    if (vat > 0) outputVatMap[OUTPUT_VAT_ACCOUNT] = (outputVatMap[OUTPUT_VAT_ACCOUNT] || 0) + vat;

    totalGross += gross;
    totalEWT   += ewt;
  });

  section.style.display = totalGross > 0 ? '' : 'none';
  if (!totalGross) return;

  const rows = [];

  const arNet  = totalGross - totalEWT;
  const arName = ACCOUNTS.find(a => a.code === '1101')?.name || 'AR — Trade';
  rows.push({ label: `1101 — ${arName}`, dr: arNet, cr: 0, indent: false });

  if (totalEWT > 0) {
    const cwtName = ACCOUNTS.find(a => a.code === CWT_RECEIVABLE_ACCOUNT)?.name || 'Creditable Withholding Tax';
    rows.push({ label: `${CWT_RECEIVABLE_ACCOUNT} — ${cwtName}`, dr: totalEWT, cr: 0, indent: false });
  }

  Object.values(revenueMap).forEach(({ code, name, base }) => {
    rows.push({ label: code ? `${code} — ${name}` : name, dr: 0, cr: base, indent: true });
  });

  Object.entries(outputVatMap).forEach(([code, amount]) => {
    const name = ACCOUNTS.find(a => a.code === code)?.name || 'Output VAT Payable';
    rows.push({ label: `${code} — ${name}`, dr: 0, cr: amount, indent: true });
  });

  tbody.innerHTML = rows.map(r => `
    <tr>
      <td class="${r.indent ? 'be-cr-label' : ''}">${r.label}</td>
      <td class="r num">${r.dr > 0 ? fmt(r.dr) : ''}</td>
      <td class="r num">${r.cr > 0 ? fmt(r.cr) : ''}</td>
    </tr>`).join('');

  const totalDr = rows.reduce((s, r) => s + r.dr, 0);
  const totalCr = rows.reduce((s, r) => s + r.cr, 0);
  document.getElementById('inv-entry-dr').textContent = fmt(totalDr);
  document.getElementById('inv-entry-cr').textContent = fmt(totalCr);
}

function openPayBillModal(voucherNum, vendorName) {
  // Show all open/overdue vouchers for this vendor
  const vendorBills = BILLS.filter(b => b.vendor === vendorName && b.status !== 'Paid' && (b.lifecycle || 'Approved') === 'Approved');

  document.getElementById('pay-bill-vendor').textContent = vendorName;

  const listEl = document.getElementById('pay-bill-voucher-list');
  listEl.innerHTML = vendorBills.map(b => {
    const balance   = b.amount - b.paid;
    const isOverdue = b.status === 'Overdue';
    const checked   = b.num === voucherNum;
    return `
      <div style="display:flex;align-items:center;gap:10px;padding:9px 14px;border-bottom:1px solid var(--border)">
        <label style="display:flex;align-items:center;gap:10px;flex:1;cursor:pointer;margin:0">
          <input type="checkbox" value="${b.num}" data-balance="${balance}"
            ${checked ? 'checked' : ''} onchange="onPayLineCheck(this)">
          <code style="min-width:108px;font-size:12px">${b.num}</code>
          <span class="badge ${isOverdue ? 'badge-overdue' : 'badge-open'}" style="font-size:10px">${b.status}</span>
          <span style="font-size:11px;color:var(--text-3)">Bal: ₱${fmt(balance)}</span>
        </label>
        <input type="text" class="amt pay-line-amt" inputmode="decimal"
          value="${checked ? fmt(balance) : ''}" ${checked ? '' : 'disabled'}
          style="width:110px;text-align:right;font-family:monospace;font-size:13px;font-weight:600;padding:4px 8px;border:1px solid var(--border);border-radius:4px;background:white"
          oninput="updatePayTotal()">
      </div>`;
  }).join('');

  document.getElementById('pay-bill-date').value        = '2026-05-30';
  document.getElementById('pay-bill-check-date').value  = '';
  document.getElementById('pay-bill-payee-name').value  = '';
  document.getElementById('pay-bill-ref').value         = '';
  document.getElementById('pay-bill-method').value      = 'Bank Transfer';
  toggleCheckDate();

  const acctInput = document.querySelector('#pay-bill-acct-wrap input');
  if (acctInput && !acctInput.dataset.code) {
    const bdo = ACCOUNTS.find(a => a.code === '1003');
    if (bdo) setSearchSelectValue(acctInput, bdo);
  }

  updatePayTotal();
  openModal('modal-pay-bill');
}

function onPayLineCheck(cb) {
  const amtInput = cb.closest('div')?.querySelector('input.pay-line-amt');
  if (!amtInput) return;
  if (cb.checked) {
    amtInput.disabled = false;
    amtInput.value = fmt(parseFloat(cb.dataset.balance));
  } else {
    amtInput.disabled = true;
    amtInput.value = '';
  }
  updatePayTotal();
}

function updatePayTotal() {
  let total = 0;
  document.querySelectorAll('#pay-bill-voucher-list .pay-line-amt:not([disabled])').forEach(inp => {
    total += parseAmt(inp.value);
  });
  const totEl = document.getElementById('pay-bill-selected-total');
  if (totEl) totEl.textContent = `₱${fmt(total)}`;
  document.getElementById('pay-bill-amount').value = fmt(total);
  buildPayEntry();
}

function buildPayEntry() {
  const tbody = document.getElementById('pay-entry-body');
  const drEl  = document.getElementById('pay-entry-dr');
  const crEl  = document.getElementById('pay-entry-cr');
  if (!tbody) return;

  const amount    = parseAmt(document.getElementById('pay-bill-amount')?.value);
  const acctInput = document.querySelector('#pay-bill-acct-wrap input');
  const acctCode  = acctInput?.dataset.code || '';
  const acctName  = acctCode
    ? (ACCOUNTS.find(a => a.code === acctCode)?.name || acctCode)
    : '(account not selected)';
  const apName = ACCOUNTS.find(a => a.code === '2001')?.name || 'AP — Trade';

  if (!amount) {
    tbody.innerHTML  = '';
    drEl.textContent = '—';
    crEl.textContent = '—';
    return;
  }

  tbody.innerHTML = `
    <tr>
      <td>2001 — ${apName}</td>
      <td class="r num">${fmt(amount)}</td>
      <td class="r num"></td>
    </tr>
    <tr>
      <td class="be-cr-label">${acctCode ? `${acctCode} — ${acctName}` : '(account not selected)'}</td>
      <td class="r num"></td>
      <td class="r num">${fmt(amount)}</td>
    </tr>`;

  drEl.textContent = fmt(amount);
  crEl.textContent = fmt(amount);
}

function printSalesInvoice() {
  const invNum    = document.getElementById('inv-number').value || '—';
  const custVal   = document.querySelector('#inv-customer-wrap input')?.value || '—';
  const custPO    = document.getElementById('inv-cust-po').value;
  const invDate   = document.getElementById('inv-date').value;
  const dueDate   = document.getElementById('inv-due').value;
  const notes     = document.getElementById('inv-notes').value;
  const invTotal  = document.getElementById('inv-total').textContent;

  const fmtDate = d => d
    ? new Date(d + 'T00:00').toLocaleDateString('en-PH', { year:'numeric', month:'long', day:'numeric' })
    : '—';

  const entryRows = [...document.querySelectorAll('#inv-entry-body tr')].map(tr => {
    const tds = tr.querySelectorAll('td');
    return {
      label:    tds[0]?.textContent || '',
      dr:       tds[1]?.textContent || '',
      cr:       tds[2]?.textContent || '',
      isCredit: tds[0]?.classList.contains('be-cr-label'),
    };
  });

  const entryDr = document.getElementById('inv-entry-dr')?.textContent || '—';
  const entryCr = document.getElementById('inv-entry-cr')?.textContent || '—';

  const entryHTML = entryRows.map(r => `
    <tr>
      <td class="${r.isCredit ? 'cr-label' : ''}">${r.label}</td>
      <td class="r mono">${r.dr}</td>
      <td class="r mono">${r.cr}</td>
    </tr>`).join('');

  const html = `<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<title>SI — ${invNum}</title>
<style>
  *{box-sizing:border-box;margin:0;padding:0}
  body{font-family:Arial,sans-serif;font-size:12px;color:#111;background:#fff;padding:28px}
  .btn-print{display:block;margin:0 0 14px auto;padding:7px 18px;font-size:12px;font-weight:600;cursor:pointer;border:1px solid #333;background:#111;color:#fff;border-radius:4px}
  @media print{.btn-print{display:none}}
  h2{font-size:18px;font-weight:800;margin-bottom:2px}
  .doc-type{font-size:11px;font-weight:700;text-transform:uppercase;letter-spacing:1px;color:#666;margin-bottom:20px}
  .meta-table{width:100%;border-collapse:collapse;margin-bottom:20px}
  .meta-table td{padding:4px 8px;font-size:12px;vertical-align:top}
  .meta-table td:first-child{font-weight:700;width:140px;color:#444}
  .meta-table td:last-child{font-weight:600}
  .inv-num{font-size:22px;font-weight:800;font-family:monospace;color:#1a56db}
  .entry-table{width:100%;border-collapse:collapse;font-size:12px;margin-top:20px}
  .entry-table th{padding:5px 8px;background:#f1f5f9;font-size:10px;text-transform:uppercase;letter-spacing:.5px;border-bottom:2px solid #cbd5e1}
  .entry-table td{padding:5px 8px;border-bottom:1px solid #e2e8f0}
  .entry-table tfoot td{padding:5px 8px;font-weight:700;background:#f8fafc;border-top:2px solid #cbd5e1}
  .r{text-align:right}.mono{font-family:monospace}
  .cr-label{padding-left:24px;color:#666}
  .v-notes{margin-top:12px;padding:10px 12px;background:#f8fafc;border:1px solid #e2e8f0;border-radius:4px;font-size:12px;white-space:pre-wrap;min-height:40px}
  .sigs{display:flex;gap:40px;margin-top:32px}
  .sig{flex:1}.sig-line{border-bottom:1px solid #333;margin-bottom:4px;height:32px}
  .sig-lbl{font-size:10px;color:#666;text-align:center}
  hr{border:none;border-top:1px solid #ddd;margin:16px 0}
</style>
</head>
<body>
<button class="btn-print" onclick="window.print()">Print / Save PDF</button>
<h2>Company Name</h2>
<div class="doc-type">Sales Invoice</div>
<table class="meta-table">
  <tr><td>Invoice #</td><td class="inv-num">${invNum}</td></tr>
  <tr><td>Customer</td><td>${custVal}</td></tr>
  ${custPO ? `<tr><td>Customer PO #</td><td>${custPO}</td></tr>` : ''}
  <tr><td>Invoice Date</td><td>${fmtDate(invDate)}</td></tr>
  <tr><td>Due Date</td><td>${fmtDate(dueDate)}</td></tr>
  <tr><td>Total Amount</td><td class="mono" style="font-weight:800">₱${invTotal}</td></tr>
</table>
<hr>
<strong style="font-size:11px;text-transform:uppercase;letter-spacing:.5px;color:#555">Particulars</strong>
<div class="v-notes">${notes || ''}</div>
<table class="entry-table">
  <thead><tr><th>Account</th><th class="r">Debit</th><th class="r">Credit</th></tr></thead>
  <tbody>${entryHTML}</tbody>
  <tfoot><tr><td>Total</td><td class="r mono">${entryDr}</td><td class="r mono">${entryCr}</td></tr></tfoot>
</table>
<div class="sigs">
  <div class="sig"><div class="sig-line"></div><div class="sig-lbl">Prepared by</div></div>
  <div class="sig"><div class="sig-line"></div><div class="sig-lbl">Checked by</div></div>
  <div class="sig"><div class="sig-line"></div><div class="sig-lbl">Approved by</div></div>
</div>
</body>
</html>`;

  const win = window.open('', '_blank', 'width=900,height=720');
  win.document.write(html);
  win.document.close();
}

function printBillVoucher() {
  const billNum    = document.getElementById('bill-number').textContent;
  const vendorVal  = document.querySelector('#bill-vendor-wrap input')?.value || '—';
  const billDate   = document.getElementById('bill-date').value;
  const dueDate    = document.getElementById('bill-due').value;
  const vendorInv  = document.getElementById('bill-vendor-inv').value || '—';
  const notes      = document.getElementById('bill-notes').value;
  const billTotal  = document.getElementById('bill-total').textContent;

  const fmtDate = d => d
    ? new Date(d + 'T00:00').toLocaleDateString('en-PH', { year:'numeric', month:'long', day:'numeric' })
    : '—';

  const entryRows = [...document.querySelectorAll('#bill-entry-body tr')].map(tr => {
    const tds = tr.querySelectorAll('td');
    return {
      label:    tds[0]?.textContent || '',
      dr:       tds[1]?.textContent || '',
      cr:       tds[2]?.textContent || '',
      isCredit: tds[0]?.classList.contains('be-cr-label'),
    };
  });

  const entryDr = document.getElementById('bill-entry-dr')?.textContent || '—';
  const entryCr = document.getElementById('bill-entry-cr')?.textContent || '—';

  const entryHTML = entryRows.map(r => `
    <tr>
      <td class="${r.isCredit ? 'cr-label' : ''}">${r.label}</td>
      <td class="r mono">${r.dr}</td>
      <td class="r mono">${r.cr}</td>
    </tr>`).join('');

  const html = `<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<title>APV — ${billNum}</title>
<style>
  *{box-sizing:border-box;margin:0;padding:0}
  body{font-family:Arial,sans-serif;font-size:12px;color:#111;background:#fff;padding:28px}
  .btn-print{display:block;margin:0 0 14px auto;padding:7px 18px;font-size:12px;font-weight:600;cursor:pointer;border:1px solid #333;background:#111;color:#fff;border-radius:4px}
  @media print{.btn-print{display:none}}
  h2{font-size:18px;font-weight:800;margin-bottom:2px}
  .doc-type{font-size:11px;font-weight:700;text-transform:uppercase;letter-spacing:1px;color:#666;margin-bottom:20px}
  .meta-table{width:100%;border-collapse:collapse;margin-bottom:20px}
  .meta-table td{padding:4px 8px;font-size:12px;vertical-align:top}
  .meta-table td:first-child{font-weight:700;width:140px;color:#444}
  .meta-table td:last-child{font-weight:600}
  .voucher-num{font-size:22px;font-weight:800;font-family:monospace;color:#1a56db}
  .entry-table{width:100%;border-collapse:collapse;font-size:12px;margin-top:20px}
  .entry-table th{padding:5px 8px;background:#f1f5f9;font-size:10px;text-transform:uppercase;letter-spacing:.5px;border-bottom:2px solid #cbd5e1}
  .entry-table td{padding:5px 8px;border-bottom:1px solid #e2e8f0}
  .entry-table tfoot td{padding:5px 8px;font-weight:700;background:#f8fafc;border-top:2px solid #cbd5e1}
  .r{text-align:right}.mono{font-family:monospace}
  .cr-label{padding-left:24px;color:#666}
  .v-notes{margin-top:12px;padding:10px 12px;background:#f8fafc;border:1px solid #e2e8f0;border-radius:4px;font-size:12px;white-space:pre-wrap;min-height:40px}
  .sec-label{font-size:11px;font-weight:700;text-transform:uppercase;letter-spacing:.5px;color:#555}
  .sigs{display:flex;gap:40px;margin-top:32px}
  .sig{flex:1}.sig-line{border-bottom:1px solid #333;margin-bottom:4px;height:32px}
  .sig-lbl{font-size:10px;color:#666;text-align:center}
  hr{border:none;border-top:1px solid #ddd;margin:16px 0}
</style>
</head>
<body>
<button class="btn-print" onclick="window.print()">Print / Save PDF</button>
<h2>Company Name</h2>
<div class="doc-type">Accounts Payable Voucher</div>
<table class="meta-table">
  <tr><td>Voucher No.</td><td class="voucher-num">${billNum}</td></tr>
  <tr><td>Pay To</td><td>${vendorVal}</td></tr>
  <tr><td>Voucher Date</td><td>${fmtDate(billDate)}</td></tr>
  <tr><td>Due Date</td><td>${fmtDate(dueDate)}</td></tr>
  <tr><td>Vendor Invoice</td><td>${vendorInv}</td></tr>
  <tr><td>Total Amount</td><td class="mono" style="font-weight:800">₱${billTotal}</td></tr>
</table>
<hr>
<strong class="sec-label">Particulars</strong>
<div class="v-notes">${notes || ''}</div>
<table class="entry-table">
  <thead><tr><th>Account</th><th class="r">Debit</th><th class="r">Credit</th></tr></thead>
  <tbody>${entryHTML}</tbody>
  <tfoot><tr><td>Total</td><td class="r mono">${entryDr}</td><td class="r mono">${entryCr}</td></tr></tfoot>
</table>
<div class="sigs">
  <div class="sig"><div class="sig-line"></div><div class="sig-lbl">Prepared by</div></div>
  <div class="sig"><div class="sig-line"></div><div class="sig-lbl">Checked by</div></div>
  <div class="sig"><div class="sig-line"></div><div class="sig-lbl">Approved by</div></div>
</div>
</body>
</html>`;

  const win = window.open('', '_blank', 'width=900,height=720');
  win.document.write(html);
  win.document.close();
}

function toggleCheckDate() {
  const method      = document.getElementById('pay-bill-method')?.value;
  const isCheck     = method === 'Check';
  const dateGroup   = document.getElementById('pay-bill-check-date-group');
  const payeeGroup  = document.getElementById('pay-bill-payee-group');
  const btnPrint    = document.getElementById('btn-print-check');
  if (dateGroup)  dateGroup.style.display  = isCheck ? '' : 'none';
  if (payeeGroup) payeeGroup.style.display = isCheck ? '' : 'none';
  if (btnPrint)   btnPrint.style.display   = isCheck ? '' : 'none';
  if (!isCheck) {
    document.getElementById('pay-bill-check-date').value  = '';
    document.getElementById('pay-bill-payee-name').value  = '';
  } else {
    const payeeInput  = document.getElementById('pay-bill-payee-name');
    if (!payeeInput.value) {
      const vName  = document.getElementById('pay-bill-vendor')?.textContent?.trim() || '';
      const vendor = VENDORS.find(v => v.name === vName);
      payeeInput.value = vendor?.checkPayee || vName;
    }
  }
}

function printPaymentVoucher() {
  const vendorName = document.getElementById('pay-bill-vendor')?.textContent || '—';
  const payDate    = document.getElementById('pay-bill-date')?.value || '';
  const checkDate  = document.getElementById('pay-bill-check-date')?.value || '';
  const method     = document.getElementById('pay-bill-method')?.value || '—';
  const ref        = document.getElementById('pay-bill-ref')?.value || '—';
  const amount     = document.getElementById('pay-bill-amount')?.value || '0.00';
  const acctInput  = document.querySelector('#pay-bill-acct-wrap input');
  const acctName   = acctInput?.value || '—';

  const fmtDate = d => d
    ? new Date(d + 'T00:00').toLocaleDateString('en-PH', { year:'numeric', month:'long', day:'numeric' })
    : '—';

  const checkedVouchers = [...document.querySelectorAll('#pay-bill-voucher-list input[type=checkbox]:checked')];
  const voucherRows = checkedVouchers.map(cb => {
    const row = cb.closest('div');
    const num = row?.querySelector('code')?.textContent || cb.value;
    const amt = parseAmt(row?.querySelector('input.pay-line-amt')?.value || cb.dataset.balance);
    return `<tr><td class="mono">${num}</td><td class="r mono">${fmt(amt)}</td></tr>`;
  }).join('');

  const entryRows = [...document.querySelectorAll('#pay-entry-body tr')].map(tr => {
    const tds = tr.querySelectorAll('td');
    return {
      label:    tds[0]?.textContent || '',
      dr:       tds[1]?.textContent || '',
      cr:       tds[2]?.textContent || '',
      isCredit: tds[0]?.classList.contains('be-cr-label'),
    };
  });
  const entryDr = document.getElementById('pay-entry-dr')?.textContent || '—';
  const entryCr = document.getElementById('pay-entry-cr')?.textContent || '—';
  const entryHTML = entryRows.map(r => `
    <tr>
      <td class="${r.isCredit ? 'cr-label' : ''}">${r.label}</td>
      <td class="r mono">${r.dr}</td>
      <td class="r mono">${r.cr}</td>
    </tr>`).join('');

  const html = `<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<title>Payment Voucher — ${vendorName}</title>
<style>
  *{box-sizing:border-box;margin:0;padding:0}
  body{font-family:Arial,sans-serif;font-size:12px;color:#111;background:#fff;padding:28px}
  .btn-print{display:block;margin:0 0 14px auto;padding:7px 18px;font-size:12px;font-weight:600;cursor:pointer;border:1px solid #333;background:#111;color:#fff;border-radius:4px}
  @media print{.btn-print{display:none}}
  h2{font-size:18px;font-weight:800;margin-bottom:2px}
  .doc-type{font-size:11px;font-weight:700;text-transform:uppercase;letter-spacing:1px;color:#666;margin-bottom:20px}
  .meta-table{width:100%;border-collapse:collapse;margin-bottom:20px}
  .meta-table td{padding:4px 8px;font-size:12px;vertical-align:top}
  .meta-table td:first-child{font-weight:700;width:140px;color:#444}
  .meta-table td:last-child{font-weight:600}
  .entry-table{width:100%;border-collapse:collapse;font-size:12px;margin-top:20px}
  .entry-table th{padding:5px 8px;background:#f1f5f9;font-size:10px;text-transform:uppercase;letter-spacing:.5px;border-bottom:2px solid #cbd5e1}
  .entry-table td{padding:5px 8px;border-bottom:1px solid #e2e8f0}
  .entry-table tfoot td{padding:5px 8px;font-weight:700;background:#f8fafc;border-top:2px solid #cbd5e1}
  .r{text-align:right}.mono{font-family:monospace}
  .cr-label{padding-left:24px;color:#666}
  .sec-label{font-size:11px;font-weight:700;text-transform:uppercase;letter-spacing:.5px;color:#555}
  .sigs{display:flex;gap:40px;margin-top:32px}
  .sig{flex:1}.sig-line{border-bottom:1px solid #333;margin-bottom:4px;height:32px}
  .sig-lbl{font-size:10px;color:#666;text-align:center}
  hr{border:none;border-top:1px solid #ddd;margin:16px 0}
</style>
</head>
<body>
<button class="btn-print" onclick="window.print()">Print / Save PDF</button>
<h2>Company Name</h2>
<div class="doc-type">Payment Voucher</div>
<table class="meta-table">
  <tr><td>Pay To</td><td>${vendorName}</td></tr>
  <tr><td>Voucher Date</td><td>${fmtDate(payDate)}</td></tr>
  <tr><td>Payment Method</td><td>${method}</td></tr>
  ${checkDate ? `<tr><td>Check Date</td><td>${fmtDate(checkDate)}</td></tr>` : ''}
  <tr><td>Bank / Cash Account</td><td>${acctName}</td></tr>
  <tr><td>Reference #</td><td>${ref}</td></tr>
  <tr><td>Total Payment</td><td class="mono" style="font-weight:800">₱${amount}</td></tr>
</table>
<hr>
<strong class="sec-label">Vouchers Covered</strong>
<table class="entry-table" style="margin-top:8px">
  <thead><tr><th>Voucher No.</th><th class="r">Amount</th></tr></thead>
  <tbody>${voucherRows}</tbody>
  <tfoot><tr><td>Total</td><td class="r mono">₱${amount}</td></tr></tfoot>
</table>
<table class="entry-table">
  <thead><tr><th>Account</th><th class="r">Debit</th><th class="r">Credit</th></tr></thead>
  <tbody>${entryHTML}</tbody>
  <tfoot><tr><td>Total</td><td class="r mono">${entryDr}</td><td class="r mono">${entryCr}</td></tr></tfoot>
</table>
<div class="sigs">
  <div class="sig"><div class="sig-line"></div><div class="sig-lbl">Prepared by</div></div>
  <div class="sig"><div class="sig-line"></div><div class="sig-lbl">Checked by</div></div>
  <div class="sig"><div class="sig-line"></div><div class="sig-lbl">Approved by</div></div>
  <div class="sig"><div class="sig-line"></div><div class="sig-lbl">Received by</div></div>
</div>
</body>
</html>`;

  const win = window.open('', '_blank', 'width=900,height=720');
  win.document.write(html);
  win.document.close();
}

function numberToWords(n) {
  if (n === 0) return 'ZERO';
  const ones = ['','ONE','TWO','THREE','FOUR','FIVE','SIX','SEVEN','EIGHT','NINE',
                 'TEN','ELEVEN','TWELVE','THIRTEEN','FOURTEEN','FIFTEEN','SIXTEEN',
                 'SEVENTEEN','EIGHTEEN','NINETEEN'];
  const tens = ['','','TWENTY','THIRTY','FORTY','FIFTY','SIXTY','SEVENTY','EIGHTY','NINETY'];
  function below1000(x) {
    if (x === 0) return '';
    if (x < 20) return ones[x];
    if (x < 100) return tens[Math.floor(x/10)] + (x%10 ? '-' + ones[x%10] : '');
    return ones[Math.floor(x/100)] + ' HUNDRED' + (x%100 ? ' ' + below1000(x%100) : '');
  }
  let result = '';
  if (n >= 1000000) {
    result += below1000(Math.floor(n/1000000)) + ' MILLION ';
    n %= 1000000;
  }
  if (n >= 1000) {
    result += below1000(Math.floor(n/1000)) + ' THOUSAND ';
    n %= 1000;
  }
  if (n > 0) result += below1000(n);
  return result.trim();
}

function amountInWords(amount) {
  const total = Math.round(amount * 100);
  const pesos = Math.floor(total / 100);
  const centavos = total % 100;
  const pesoWords = numberToWords(pesos) + (pesos === 1 ? ' PESO' : ' PESOS');
  return centavos > 0
    ? pesoWords + ' AND ' + String(centavos).padStart(2,'0') + '/100'
    : pesoWords + ' ONLY';
}

function printCheck() {
  const vendorName = document.getElementById('pay-bill-vendor')?.textContent?.trim() || '—';
  const payeeName  = document.getElementById('pay-bill-payee-name')?.value?.trim() || vendorName;
  const checkDate  = document.getElementById('pay-bill-check-date')?.value ||
                     document.getElementById('pay-bill-date')?.value || '';
  const ref        = document.getElementById('pay-bill-ref')?.value || '';
  const amountStr  = document.getElementById('pay-bill-amount')?.value || '0';
  const amount     = parseAmt(amountStr);

  // Account the payment is drawn from
  const acctInput = document.querySelector('#pay-bill-acct-wrap input');
  const acctCode  = acctInput?.dataset.code || '';
  const acctName  = acctInput?.value?.trim() || '';

  // 8 digits MMDDYYYY, no slashes
  const parseDateDigits = d => {
    if (!d) return Array(8).fill('_');
    const dt = new Date(d + 'T00:00');
    return (String(dt.getMonth()+1).padStart(2,'0') +
            String(dt.getDate()).padStart(2,'0') +
            dt.getFullYear()).split('');
  };

  const fmtAmt = n => '**' + n.toLocaleString('en-PH', { minimumFractionDigits:2, maximumFractionDigits:2 }) + '**';
  const words  = amountInWords(amount);

  const DATE_LEFTS = [578, 591, 614, 627, 650, 663, 676, 689];
  const dateDigits = parseDateDigits(checkDate);

  const DEFAULTS = {
    payee:       { top: 111, left: 125 },
    'amt-num':   { top: 111, left: 580 },
    'amt-words': { top: 152, left: 50  },
    memo:        { top: 240, left: 50  },
  };
  DATE_LEFTS.forEach((left, i) => { DEFAULTS[`d${i}`] = { top: 67, left }; });

  const fieldData = {
    payee:       payeeName,
    'amt-num':   fmtAmt(amount),
    'amt-words': words,
    memo:        ref || '—',
  };
  dateDigits.forEach((ch, i) => { fieldData[`d${i}`] = ch; });

  const fieldDivs = Object.entries(fieldData).map(([id, text]) =>
    `<div class="cf" data-id="${id}">${text}</div>`
  ).join('\n    ');

  const html = `<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<title>Print Check — ${vendorName}</title>
<style>
  *{box-sizing:border-box;margin:0;padding:0}
  body{background:#d1d5db;font-family:Arial,sans-serif}
  #toolbar{
    display:flex;align-items:center;gap:6px;flex-wrap:wrap;
    padding:8px 14px;background:#1e293b;color:#fff;font-size:12px;min-height:44px;
  }
  #toolbar button{
    padding:5px 11px;font-size:11px;font-weight:600;cursor:pointer;
    border:1px solid #475569;border-radius:3px;background:#334155;color:#fff;white-space:nowrap;
  }
  #toolbar button:hover{background:#475569}
  #toolbar button:disabled{opacity:.4;cursor:default}
  #toolbar button.danger:hover{background:#7f1d1d;border-color:#991b1b}
  #toolbar .sep{width:1px;height:20px;background:#475569;margin:0 2px;flex-shrink:0}
  #toolbar label{color:#94a3b8;font-size:11px;white-space:nowrap}
  #layout-sel{
    padding:4px 6px;font-size:11px;border-radius:3px;border:1px solid #475569;
    background:#0f172a;color:#fff;max-width:160px;cursor:pointer;
  }
  #acct-label{
    font-size:11px;font-weight:600;color:#e2e8f0;white-space:nowrap;
    background:#0f172a;border:1px solid #334155;border-radius:3px;padding:4px 8px;
  }
  #link-ind{font-size:11px;white-space:nowrap}
  #link-ind.linked{color:#86efac}
  #link-ind.unlinked{color:#64748b}
  #coords{margin-left:auto;font-size:11px;color:#94a3b8;font-family:monospace;min-width:180px;text-align:right}
  #check-wrap{padding:20px;display:flex;justify-content:center}
  #check-area{
    position:relative;width:816px;height:336px;background:#fff;
    box-shadow:0 4px 24px rgba(0,0,0,.3);
    background-image:
      linear-gradient(rgba(100,116,139,.12) 1px,transparent 1px),
      linear-gradient(90deg,rgba(100,116,139,.12) 1px,transparent 1px);
    background-size:96px 96px;
    overflow:hidden;cursor:default;
  }
  .cf{
    position:absolute;
    font-family:'Courier New',Courier,monospace;font-size:12pt;color:#000;
    cursor:move;white-space:nowrap;
    padding:2px 4px;border-radius:2px;
    border:1.5px dashed transparent;
  }
  .cf:hover{border-color:rgba(99,102,241,.55);background:rgba(99,102,241,.05)}
  .cf.dragging{border-color:rgba(99,102,241,.8);background:rgba(99,102,241,.08);z-index:10}
  .cf[data-id="amt-num"]{font-weight:700;letter-spacing:.04em}
  .cf[data-id^="d"]{min-width:18px;text-align:center;padding:2px 2px}
  @media print{
    *{box-sizing:border-box;margin:0;padding:0}
    body{background:transparent}
    #toolbar,#check-wrap > :not(#check-area){display:none}
    #check-wrap{padding:0;display:block}
    #check-area{box-shadow:none;background:transparent;background-image:none;width:8.5in;height:3.5in}
    .cf{border:none !important;background:transparent !important;padding:0;cursor:default}
    @page{size:8.5in 3.5in;margin:0}
  }
</style>
</head>
<body>
<div id="toolbar">
  <button onclick="window.print()">&#128424; Print</button>
  <div class="sep"></div>
  <label>Layout:</label>
  <select id="layout-sel" onchange="onLayoutSelect()"><option value="">(defaults)</option></select>
  <button id="btn-save"   onclick="saveLayout()"   title="Overwrite selected layout">Save</button>
  <button id="btn-saveas" onclick="saveLayoutAs()" title="Save as new layout">Save As&hellip;</button>
  <button id="btn-delete" onclick="deleteLayout()" class="danger" title="Delete layout">Delete</button>
  <div class="sep"></div>
  <button onclick="resetToDefaults()">&#8635; Reset</button>
  <div class="sep"></div>
  <span id="acct-label">&#128196; ${acctName || '(no account)'}</span>
  <span id="link-ind" class="unlinked">no layout linked</span>
  <button id="btn-link"   onclick="linkLayout()"   title="Link selected layout to this account">&#128279; Link</button>
  <button id="btn-unlink" onclick="unlinkLayout()" title="Remove layout link for this account">&#215; Unlink</button>
  <div id="coords"></div>
</div>
<div id="check-wrap">
  <div id="check-area">
    ${fieldDivs}
  </div>
</div>
<script>
  const LAYOUTS_KEY  = 'cas_check_layouts';
  const LAST_KEY     = 'cas_check_last_layout';
  const ACCT_MAP_KEY = 'cas_check_account_layouts';
  const DEFAULTS     = ${JSON.stringify(DEFAULTS)};
  const ACCT_CODE    = ${JSON.stringify(acctCode)};

  function allLayouts() {
    try { return JSON.parse(localStorage.getItem(LAYOUTS_KEY)) || {}; } catch(e) { return {}; }
  }
  function saveLayouts(obj) { localStorage.setItem(LAYOUTS_KEY, JSON.stringify(obj)); }

  function acctMap() {
    try { return JSON.parse(localStorage.getItem(ACCT_MAP_KEY)) || {}; } catch(e) { return {}; }
  }
  function saveAcctMap(obj) { localStorage.setItem(ACCT_MAP_KEY, JSON.stringify(obj)); }

  function readPositions() {
    const pos = {};
    document.querySelectorAll('.cf').forEach(el => {
      pos[el.dataset.id] = { top: parseInt(el.style.top), left: parseInt(el.style.left) };
    });
    return pos;
  }
  function applyPositions(pos) {
    document.querySelectorAll('.cf').forEach(el => {
      const p = (pos && pos[el.dataset.id]) || DEFAULTS[el.dataset.id];
      el.style.top  = p.top  + 'px';
      el.style.left = p.left + 'px';
    });
  }

  function updateLinkIndicator() {
    const linked    = ACCT_CODE ? acctMap()[ACCT_CODE] : null;
    const ind       = document.getElementById('link-ind');
    const layouts   = allLayouts();
    const hasLayout = !!document.getElementById('layout-sel').value;
    const hasAcct   = !!ACCT_CODE;
    if (linked && layouts[linked]) {
      ind.textContent = '→ ' + linked;
      ind.className   = 'linked';
    } else {
      ind.textContent = 'no layout linked';
      ind.className   = 'unlinked';
    }
    document.getElementById('btn-link').disabled   = !hasLayout || !hasAcct;
    document.getElementById('btn-unlink').disabled = !linked || !hasAcct;
  }

  function linkLayout() {
    const name = document.getElementById('layout-sel').value;
    if (!name || !ACCT_CODE) return;
    const map = acctMap();
    map[ACCT_CODE] = name;
    saveAcctMap(map);
    updateLinkIndicator();
  }

  function unlinkLayout() {
    if (!ACCT_CODE) return;
    const map = acctMap();
    delete map[ACCT_CODE];
    saveAcctMap(map);
    updateLinkIndicator();
  }

  function refreshDropdown(selectName) {
    const sel     = document.getElementById('layout-sel');
    const layouts = allLayouts();
    const names   = Object.keys(layouts);
    sel.innerHTML = '<option value="">(defaults)</option>' +
      names.map(n => \`<option value="\${n}"\${n === selectName ? ' selected' : ''}>\${n}</option>\`).join('');
    const has = !!selectName && names.includes(selectName);
    document.getElementById('btn-save').disabled   = !has;
    document.getElementById('btn-delete').disabled = !has;
    updateLinkIndicator();
  }

  function onLayoutSelect() {
    const name = document.getElementById('layout-sel').value;
    if (name) {
      applyPositions(allLayouts()[name] || null);
      localStorage.setItem(LAST_KEY, name);
    } else {
      applyPositions(null);
      localStorage.removeItem(LAST_KEY);
    }
    refreshDropdown(name);
  }

  function saveLayout() {
    const name = document.getElementById('layout-sel').value;
    if (!name) return;
    const layouts = allLayouts();
    layouts[name] = readPositions();
    saveLayouts(layouts);
    refreshDropdown(name);
  }

  function saveLayoutAs() {
    const raw = prompt('Layout name (e.g. BDO Checking, BPI Savings):');
    if (!raw || !raw.trim()) return;
    const name = raw.trim();
    const layouts = allLayouts();
    layouts[name] = readPositions();
    saveLayouts(layouts);
    localStorage.setItem(LAST_KEY, name);
    refreshDropdown(name);
  }

  function deleteLayout() {
    const name = document.getElementById('layout-sel').value;
    if (!name) return;
    if (!confirm('Delete layout "' + name + '"?')) return;
    const layouts = allLayouts();
    delete layouts[name];
    saveLayouts(layouts);
    // remove from account map if linked
    const map = acctMap();
    Object.keys(map).forEach(k => { if (map[k] === name) delete map[k]; });
    saveAcctMap(map);
    localStorage.removeItem(LAST_KEY);
    refreshDropdown('');
    applyPositions(null);
  }

  function resetToDefaults() {
    applyPositions(null);
    document.getElementById('layout-sel').value = '';
    refreshDropdown('');
  }

  // drag
  let active = null, ox = 0, oy = 0;
  const coordsEl = document.getElementById('coords');
  document.querySelectorAll('.cf').forEach(el => {
    el.addEventListener('mousedown', e => {
      active = el;
      el.classList.add('dragging');
      const r = el.getBoundingClientRect();
      ox = e.clientX - r.left;
      oy = e.clientY - r.top;
      e.preventDefault();
    });
  });
  document.addEventListener('mousemove', e => {
    if (!active) return;
    const ar = document.getElementById('check-area').getBoundingClientRect();
    let left = Math.max(0, Math.min(e.clientX - ar.left - ox, ar.width  - active.offsetWidth));
    let top  = Math.max(0, Math.min(e.clientY - ar.top  - oy, ar.height - active.offsetHeight));
    active.style.left = left + 'px';
    active.style.top  = top  + 'px';
    coordsEl.textContent = active.dataset.id + ': ' + (left/96).toFixed(2) + '" L, ' + (top/96).toFixed(2) + '" T';
  });
  document.addEventListener('mouseup', () => {
    if (!active) return;
    active.classList.remove('dragging');
    active = null;
    coordsEl.textContent = '';
  });

  // init — auto-load layout linked to this account, else last-used, else defaults
  (function init() {
    const layouts = allLayouts();
    const linked  = ACCT_CODE ? acctMap()[ACCT_CODE] : null;
    if (linked && layouts[linked]) {
      refreshDropdown(linked);
      applyPositions(layouts[linked]);
    } else {
      const last = localStorage.getItem(LAST_KEY);
      if (last && layouts[last]) {
        refreshDropdown(last);
        applyPositions(layouts[last]);
      } else {
        refreshDropdown('');
        applyPositions(null);
      }
    }
  })();
<\/script>
</body>
</html>`;

  const win = window.open('', '_blank', 'width=960,height=520');
  win.document.write(html);
  win.document.close();
}

function openCollectModal(invoiceNum, customerName) {
  const customerInvoices = INVOICES.filter(inv =>
    inv.customer === customerName && inv.status !== 'Paid' && (inv.lifecycle || 'Approved') === 'Approved'
  );

  document.getElementById('collect-customer').textContent = customerName;

  const listEl = document.getElementById('collect-invoice-list');
  listEl.innerHTML = customerInvoices.map(inv => {
    const balance    = inv.amount - inv.paid;
    const isOverdue  = inv.status === 'Overdue';
    const isPartial  = inv.status === 'Partial';
    const badgeClass = isOverdue ? 'badge-overdue' : isPartial ? 'badge-partial' : 'badge-open';
    const checked    = inv.num === invoiceNum;
    return `
      <div style="display:flex;align-items:center;gap:10px;padding:9px 14px;border-bottom:1px solid var(--border)">
        <label style="display:flex;align-items:center;gap:10px;flex:1;cursor:pointer;margin:0">
          <input type="checkbox" value="${inv.num}" data-balance="${balance}"
            ${checked ? 'checked' : ''} onchange="onCollectLineCheck(this)">
          <code style="min-width:108px;font-size:12px">${inv.num}</code>
          <span class="badge ${badgeClass}" style="font-size:10px">${inv.status}</span>
          <span style="font-size:11px;color:var(--text-3)">Bal: ₱${fmt(balance)}</span>
        </label>
        <input type="text" class="amt collect-line-amt" inputmode="decimal"
          value="${checked ? fmt(balance) : ''}" ${checked ? '' : 'disabled'}
          style="width:110px;text-align:right;font-family:monospace;font-size:13px;font-weight:600;padding:4px 8px;border:1px solid var(--border);border-radius:4px;background:white"
          oninput="updateCollectTotal()">
      </div>`;
  }).join('');

  document.getElementById('collect-date').value   = '2026-05-30';
  document.getElementById('collect-ref').value    = '';

  const acctInput = document.querySelector('#collect-acct-wrap input');
  if (acctInput && !acctInput.dataset.code) {
    const bdo = ACCOUNTS.find(a => a.code === '1003');
    if (bdo) setSearchSelectValue(acctInput, bdo);
  }

  updateCollectTotal();
  openModal('modal-collect');
}

function onCollectLineCheck(cb) {
  const amtInput = cb.closest('div')?.querySelector('input.collect-line-amt');
  if (!amtInput) return;
  if (cb.checked) {
    amtInput.disabled = false;
    amtInput.value = fmt(parseFloat(cb.dataset.balance));
  } else {
    amtInput.disabled = true;
    amtInput.value = '';
  }
  updateCollectTotal();
}

function updateCollectTotal() {
  let total = 0;
  document.querySelectorAll('#collect-invoice-list .collect-line-amt:not([disabled])').forEach(inp => {
    total += parseAmt(inp.value);
  });
  const totEl = document.getElementById('collect-selected-total');
  if (totEl) totEl.textContent = `₱${fmt(total)}`;
  document.getElementById('collect-amount').value = fmt(total);
  buildCollectEntry();
}

function buildCollectEntry() {
  const section  = document.getElementById('collect-entry-section');
  const tbody    = document.getElementById('collect-entry-body');
  const drEl     = document.getElementById('collect-entry-dr');
  const crEl     = document.getElementById('collect-entry-cr');
  if (!section || !tbody) return;

  const amount    = parseAmt(document.getElementById('collect-amount')?.value);
  const acctInput = document.querySelector('#collect-acct-wrap input');
  const acctCode  = acctInput?.dataset.code || '';
  const acctName  = acctCode
    ? (ACCOUNTS.find(a => a.code === acctCode)?.name || acctCode)
    : '(account not selected)';
  const arName = ACCOUNTS.find(a => a.code === '1101')?.name || 'AR — Trade';

  section.style.display = amount > 0 ? '' : 'none';
  if (!amount) return;

  tbody.innerHTML = `
    <tr>
      <td>${acctCode ? acctCode + ' — ' : ''}${acctName}</td>
      <td class="r num">${fmt(amount)}</td>
      <td class="r num"></td>
    </tr>
    <tr>
      <td class="be-cr-label">1101 — ${arName}</td>
      <td class="r num"></td>
      <td class="r num">${fmt(amount)}</td>
    </tr>`;

  drEl.textContent = fmt(amount);
  crEl.textContent = fmt(amount);
}

function printCollectionReceipt() {
  const customerName = document.getElementById('collect-customer')?.textContent || '—';
  const collectDate  = document.getElementById('collect-date')?.value || '';
  const method       = document.getElementById('collect-method')?.value || '—';
  const ref          = document.getElementById('collect-ref')?.value || '—';
  const amount       = document.getElementById('collect-amount')?.value || '0.00';
  const acctInput    = document.querySelector('#collect-acct-wrap input');
  const acctName     = acctInput?.value || '—';

  const fmtDate = d => d
    ? new Date(d + 'T00:00').toLocaleDateString('en-PH', { year:'numeric', month:'long', day:'numeric' })
    : '—';

  const checkedInvoices = [...document.querySelectorAll('#collect-invoice-list input[type=checkbox]:checked')];
  const invoiceRows = checkedInvoices.map(cb => {
    const row = cb.closest('div');
    const num = row?.querySelector('code')?.textContent || cb.value;
    const amt = parseAmt(row?.querySelector('input.collect-line-amt')?.value || cb.dataset.balance);
    return `<tr><td class="mono">${num}</td><td class="r mono">${fmt(amt)}</td></tr>`;
  }).join('');

  const entryRows = [...document.querySelectorAll('#collect-entry-body tr')].map(tr => {
    const tds = tr.querySelectorAll('td');
    return {
      label:    tds[0]?.textContent || '',
      dr:       tds[1]?.textContent || '',
      cr:       tds[2]?.textContent || '',
      isCredit: tds[0]?.classList.contains('be-cr-label'),
    };
  });
  const entryDr   = document.getElementById('collect-entry-dr')?.textContent || '—';
  const entryCr   = document.getElementById('collect-entry-cr')?.textContent || '—';
  const entryHTML = entryRows.map(r => `
    <tr>
      <td class="${r.isCredit ? 'cr-label' : ''}">${r.label}</td>
      <td class="r mono">${r.dr}</td>
      <td class="r mono">${r.cr}</td>
    </tr>`).join('');

  const html = `<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<title>Collection Receipt — ${customerName}</title>
<style>
  *{box-sizing:border-box;margin:0;padding:0}
  body{font-family:Arial,sans-serif;font-size:12px;color:#111;background:#fff;padding:28px}
  .btn-print{display:block;margin:0 0 14px auto;padding:7px 18px;font-size:12px;font-weight:600;cursor:pointer;border:1px solid #333;background:#111;color:#fff;border-radius:4px}
  @media print{.btn-print{display:none}}
  h2{font-size:18px;font-weight:800;margin-bottom:2px}
  .doc-type{font-size:11px;font-weight:700;text-transform:uppercase;letter-spacing:1px;color:#666;margin-bottom:20px}
  .meta-table{width:100%;border-collapse:collapse;margin-bottom:20px}
  .meta-table td{padding:4px 8px;font-size:12px;vertical-align:top}
  .meta-table td:first-child{font-weight:700;width:140px;color:#444}
  .meta-table td:last-child{font-weight:600}
  .entry-table{width:100%;border-collapse:collapse;font-size:12px;margin-top:20px}
  .entry-table th{padding:5px 8px;background:#f1f5f9;font-size:10px;text-transform:uppercase;letter-spacing:.5px;border-bottom:2px solid #cbd5e1}
  .entry-table td{padding:5px 8px;border-bottom:1px solid #e2e8f0}
  .entry-table tfoot td{padding:5px 8px;font-weight:700;background:#f8fafc;border-top:2px solid #cbd5e1}
  .r{text-align:right}.mono{font-family:monospace}
  .cr-label{padding-left:24px;color:#666}
  .sec-label{font-size:11px;font-weight:700;text-transform:uppercase;letter-spacing:.5px;color:#555}
  .sigs{display:flex;gap:40px;margin-top:32px}
  .sig{flex:1}.sig-line{border-bottom:1px solid #333;margin-bottom:4px;height:32px}
  .sig-lbl{font-size:10px;color:#666;text-align:center}
  hr{border:none;border-top:1px solid #ddd;margin:16px 0}
</style>
</head>
<body>
<button class="btn-print" onclick="window.print()">Print / Save PDF</button>
<h2>Company Name</h2>
<div class="doc-type">Collection Receipt</div>
<table class="meta-table">
  <tr><td>Received From</td><td>${customerName}</td></tr>
  <tr><td>Collection Date</td><td>${fmtDate(collectDate)}</td></tr>
  <tr><td>Payment Method</td><td>${method}</td></tr>
  <tr><td>Deposited To</td><td>${acctName}</td></tr>
  <tr><td>Reference #</td><td>${ref}</td></tr>
  <tr><td>Amount Received</td><td class="mono" style="font-weight:800">₱${amount}</td></tr>
</table>
<hr>
<strong class="sec-label">Invoices Covered</strong>
<table class="entry-table" style="margin-top:8px">
  <thead><tr><th>Invoice No.</th><th class="r">Amount</th></tr></thead>
  <tbody>${invoiceRows}</tbody>
  <tfoot><tr><td>Total</td><td class="r mono">₱${amount}</td></tr></tfoot>
</table>
<table class="entry-table">
  <thead><tr><th>Account</th><th class="r">Debit</th><th class="r">Credit</th></tr></thead>
  <tbody>${entryHTML}</tbody>
  <tfoot><tr><td>Total</td><td class="r mono">${entryDr}</td><td class="r mono">${entryCr}</td></tr></tfoot>
</table>
<div class="sigs">
  <div class="sig"><div class="sig-line"></div><div class="sig-lbl">Prepared by</div></div>
  <div class="sig"><div class="sig-line"></div><div class="sig-lbl">Checked by</div></div>
  <div class="sig"><div class="sig-line"></div><div class="sig-lbl">Approved by</div></div>
  <div class="sig"><div class="sig-line"></div><div class="sig-lbl">Received by</div></div>
</div>
</body>
</html>`;

  const win = window.open('', '_blank', 'width=900,height=720');
  win.document.write(html);
  win.document.close();
}

/* ─── SLSP & Alphalist ──────────────────────────────────────── */
const QUARTER_LABELS = ['', 'Q1 (Jan–Mar)', 'Q2 (Apr–Jun)', 'Q3 (Jul–Sep)', 'Q4 (Oct–Dec)'];

function quarterRange(year, quarter) {
  const starts = ['01-01','04-01','07-01','10-01'];
  const ends   = ['03-31','06-30','09-30','12-31'];
  const q = parseInt(quarter) - 1;
  return [`${year}-${starts[q]}`, `${year}-${ends[q]}`];
}

function renderSLSP() {
  const quarter = document.getElementById('slsp-quarter')?.value || '2';
  const year    = document.getElementById('slsp-year')?.value    || '2026';
  const [qStart, qEnd] = quarterRange(year, quarter);
  const label = `${QUARTER_LABELS[quarter]} ${year}`;

  // ── SLS ─────────────────────────────────────────────────────
  document.getElementById('sls-period-label').textContent = label;
  const slsMap = {};
  INVOICES.filter(inv => inv.date >= qStart && inv.date <= qEnd).forEach(inv => {
    const cust   = CUSTOMERS.find(c => c.name === inv.customer);
    if (!cust) return;
    const vt     = OUTPUT_VAT_TYPES.find(v => v.code === cust.defaultVat);
    const is12   = vt && parseFloat(vt.rate) === 12;
    const isZero = vt && (vt.code === 'VATSZ' || vt.code === 'VATSGV');
    const gross  = inv.amount;
    let taxable  = 0, vat = 0, zeroRated = 0, exempt = 0;
    if (is12)     { taxable = gross / 1.12; vat = gross - taxable; }
    else if (isZero) { zeroRated = gross; }
    else          { exempt = gross; }
    if (!slsMap[cust.tin]) slsMap[cust.tin] = { name: cust.name, tin: cust.tin, taxable:0, vat:0, zeroRated:0, exempt:0, gross:0 };
    const r = slsMap[cust.tin];
    r.taxable += taxable; r.vat += vat; r.zeroRated += zeroRated; r.exempt += exempt; r.gross += gross;
  });
  const slsList = Object.values(slsMap).sort((a, b) => a.name.localeCompare(b.name));
  const slsTbody = document.getElementById('sls-tbody');
  const slsTfoot = document.getElementById('sls-tfoot');
  if (slsTbody) {
    slsTbody.innerHTML = slsList.length
      ? slsList.map((r, i) => `
          <tr>
            <td class="text-2 text-sm">${i + 1}</td>
            <td class="fw-6">${r.name}</td>
            <td class="mono text-sm">${r.tin}</td>
            <td class="r num">${r.taxable > 0 ? fmt(r.taxable) : '—'}</td>
            <td class="r num cr">${r.vat > 0 ? fmt(r.vat) : '—'}</td>
            <td class="r num">${r.zeroRated > 0 ? fmt(r.zeroRated) : '—'}</td>
            <td class="r num">${r.exempt > 0 ? fmt(r.exempt) : '—'}</td>
            <td class="r num fw-7">₱${fmt(r.gross)}</td>
          </tr>`).join('')
      : `<tr><td colspan="8" style="text-align:center;color:var(--text-3);padding:24px">No sales transactions in this period</td></tr>`;
    const t = slsList.reduce((s, r) => ({ taxable: s.taxable+r.taxable, vat: s.vat+r.vat, zeroRated: s.zeroRated+r.zeroRated, exempt: s.exempt+r.exempt, gross: s.gross+r.gross }), { taxable:0, vat:0, zeroRated:0, exempt:0, gross:0 });
    slsTfoot.innerHTML = `
      <tr class="tfoot-row">
        <td colspan="3" class="fw-7">TOTAL — ${slsList.length} buyer${slsList.length !== 1 ? 's' : ''}</td>
        <td class="r num fw-7">${t.taxable > 0 ? fmt(t.taxable) : '—'}</td>
        <td class="r num fw-7 cr">${t.vat > 0 ? fmt(t.vat) : '—'}</td>
        <td class="r num fw-7">${t.zeroRated > 0 ? fmt(t.zeroRated) : '—'}</td>
        <td class="r num fw-7">${t.exempt > 0 ? fmt(t.exempt) : '—'}</td>
        <td class="r num fw-7">₱${fmt(t.gross)}</td>
      </tr>`;
  }

  // ── SLP ─────────────────────────────────────────────────────
  document.getElementById('slp-period-label').textContent = label;
  const slpMap = {};
  BILLS.filter(b => b.date >= qStart && b.date <= qEnd).forEach(b => {
    const vend   = VENDORS.find(v => v.name === b.vendor);
    if (!vend) return;
    const vt     = VAT_TYPES.find(v => v.code === vend.defaultVat);
    const is12   = vt && parseFloat(vt.rate) === 12;
    const gross  = b.amount;
    let taxable  = 0, inputVat = 0, nonVatable = 0;
    if (is12) { taxable = gross / 1.12; inputVat = gross - taxable; }
    else       { nonVatable = gross; }
    if (!slpMap[vend.tin]) slpMap[vend.tin] = { name: vend.name, tin: vend.tin, taxable:0, inputVat:0, nonVatable:0, gross:0 };
    const r = slpMap[vend.tin];
    r.taxable += taxable; r.inputVat += inputVat; r.nonVatable += nonVatable; r.gross += gross;
  });
  const slpList = Object.values(slpMap).sort((a, b) => a.name.localeCompare(b.name));
  const slpTbody = document.getElementById('slp-tbody');
  const slpTfoot = document.getElementById('slp-tfoot');
  if (slpTbody) {
    slpTbody.innerHTML = slpList.length
      ? slpList.map((r, i) => `
          <tr>
            <td class="text-2 text-sm">${i + 1}</td>
            <td class="fw-6">${r.name}</td>
            <td class="mono text-sm">${r.tin}</td>
            <td class="r num">${r.taxable > 0 ? fmt(r.taxable) : '—'}</td>
            <td class="r num dr">${r.inputVat > 0 ? fmt(r.inputVat) : '—'}</td>
            <td class="r num">${r.nonVatable > 0 ? fmt(r.nonVatable) : '—'}</td>
            <td class="r num fw-7">₱${fmt(r.gross)}</td>
          </tr>`).join('')
      : `<tr><td colspan="7" style="text-align:center;color:var(--text-3);padding:24px">No purchase transactions in this period</td></tr>`;
    const t = slpList.reduce((s, r) => ({ taxable: s.taxable+r.taxable, inputVat: s.inputVat+r.inputVat, nonVatable: s.nonVatable+r.nonVatable, gross: s.gross+r.gross }), { taxable:0, inputVat:0, nonVatable:0, gross:0 });
    slpTfoot.innerHTML = `
      <tr class="tfoot-row">
        <td colspan="3" class="fw-7">TOTAL — ${slpList.length} supplier${slpList.length !== 1 ? 's' : ''}</td>
        <td class="r num fw-7">${t.taxable > 0 ? fmt(t.taxable) : '—'}</td>
        <td class="r num fw-7 dr">${t.inputVat > 0 ? fmt(t.inputVat) : '—'}</td>
        <td class="r num fw-7">${t.nonVatable > 0 ? fmt(t.nonVatable) : '—'}</td>
        <td class="r num fw-7">₱${fmt(t.gross)}</td>
      </tr>`;
  }
}

function renderAlphalist() {
  const year  = document.getElementById('al-year')?.value || '2026';
  const tbody = document.getElementById('al-tbody');
  const tfoot = document.getElementById('al-tfoot');
  const label = document.getElementById('al-year-label');
  if (label) label.textContent = `Taxable Year ${year}`;
  if (!tbody) return;

  const byPayeeATC = {};
  BILLS.filter(b => b.date.startsWith(year)).forEach(b => {
    const vend = VENDORS.find(v => v.name === b.vendor);
    if (!vend || !vend.defaultWt?.length) return;
    const vt   = VAT_TYPES.find(v => v.code === vend.defaultVat);
    const is12 = vt && parseFloat(vt.rate) === 12;
    const base = is12 ? b.amount / 1.12 : b.amount;
    // use primary ATC only (each bill would have one ATC in a real system)
    const wtCode = vend.defaultWt[0];
    const wt = WITHHOLDING_TAXES.find(w => w.code === wtCode);
    if (!wt) return;
    const rate = parseFloat(wt.rate) / 100;
    const key  = `${vend.tin}|${wtCode}`;
    if (!byPayeeATC[key]) byPayeeATC[key] = { name: vend.name, tin: vend.tin, atc: wtCode, atcName: wt.name, rateStr: wt.rate, rate, gross: 0, ewt: 0 };
    byPayeeATC[key].gross += base;
    byPayeeATC[key].ewt   += base * rate;
  });

  const list = Object.values(byPayeeATC).sort((a, b) => a.name.localeCompare(b.name));
  tbody.innerHTML = list.length
    ? list.map((r, i) => `
        <tr>
          <td class="text-2 text-sm">${i + 1}</td>
          <td class="fw-6">${r.name}</td>
          <td class="mono text-sm">${r.tin}</td>
          <td><code>${r.atc}</code></td>
          <td class="text-sm">${r.atcName}</td>
          <td class="r num">₱${fmt(r.gross)}</td>
          <td class="r num">${r.rateStr}</td>
          <td class="r num fw-7 dr">₱${fmt(r.ewt)}</td>
        </tr>`).join('')
    : `<tr><td colspan="8" style="text-align:center;color:var(--text-3);padding:24px">No withholding tax transactions in this year</td></tr>`;

  const totalGross = list.reduce((s, r) => s + r.gross, 0);
  const totalEWT   = list.reduce((s, r) => s + r.ewt,   0);
  tfoot.innerHTML = `
    <tr class="tfoot-row">
      <td colspan="5" class="fw-7">TOTAL — ${list.length} payee${list.length !== 1 ? 's' : ''}</td>
      <td class="r num fw-7">₱${fmt(totalGross)}</td>
      <td></td>
      <td class="r num fw-7 dr">₱${fmt(totalEWT)}</td>
    </tr>`;
}

/* ─── Customer / Vendor edit state ─────────────────────────── */
let _editingCustomerCode = null;
let _editingVendorCode   = null;

/* ─── Journal Entry Rendering ──────────────────────────────── */
function renderJournalEntries() {
  const from   = document.getElementById('je-filter-from')?.value || '';
  const to     = document.getElementById('je-filter-to')?.value   || '';
  const status = document.getElementById('je-filter-status')?.value || '';
  const search = (document.getElementById('je-search')?.value || '').toLowerCase();

  const hits = JOURNAL_ENTRIES.filter(je => {
    if (from && je.date < from) return false;
    if (to   && je.date > to)   return false;
    if (status && status !== 'All Statuses' && je.status !== status) return false;
    if (search && !je.ref.toLowerCase().includes(search) && !je.desc.toLowerCase().includes(search)) return false;
    return true;
  });

  const tbody = document.getElementById('journal-tbody');
  const tfoot = document.getElementById('journal-tfoot');
  if (!tbody) return;

  tbody.innerHTML = hits.map(je => {
    const totalDr = je.lines.reduce((s, l) => s + l.dr, 0);
    const totalCr = je.lines.reduce((s, l) => s + l.cr, 0);
    const statusBadge = `<span class="badge badge-${je.status.toLowerCase()}">${je.status}</span>`;
    const role = _currentUser.role;
    const jeBtns = [];
    if (je.status === 'Draft' && role !== 'Viewer') {
      jeBtns.push(`<button class="btn btn-sm btn-primary" style="padding:3px 10px;font-size:11px" onclick="lcTransition('je','${je.id}','Submitted')">Submit</button>`);
      if (role === 'Accountant')
        jeBtns.push(`<button class="btn btn-sm btn-success" style="padding:3px 10px;font-size:11px" onclick="lcTransition('je','${je.id}','Approved')">Approve</button>`);
    } else if (je.status === 'Submitted' && role === 'Accountant') {
      jeBtns.push(`<button class="btn btn-sm btn-success" style="padding:3px 10px;font-size:11px" onclick="lcTransition('je','${je.id}','Approved')">Approve</button>`);
      jeBtns.push(`<button class="btn btn-sm btn-ghost"   style="padding:3px 10px;font-size:11px" onclick="lcTransition('je','${je.id}','Draft')">Disapprove</button>`);
    }
    return `
      <tr>
        <td class="text-sm">${je.date}</td>
        <td><code style="cursor:pointer;color:var(--blue)" onclick="openJEDetail('${je.id}')">${je.ref}</code></td>
        <td>${je.desc}</td>
        <td class="dr r">${fmt(totalDr)}</td>
        <td class="cr r">${fmt(totalCr)}</td>
        <td>${statusBadge}</td>
        <td style="display:flex;gap:6px;align-items:center;flex-wrap:wrap">
          <button class="btn btn-ghost btn-sm" onclick="openJEDetail('${je.id}')">View</button>
          ${jeBtns.join(' ')}
        </td>
      </tr>`;
  }).join('') || `<tr><td colspan="7" style="text-align:center;color:var(--text-3);padding:24px">No entries match the filter</td></tr>`;

  const grandDr = hits.reduce((s, je) => s + je.lines.reduce((ss, l) => ss + l.dr, 0), 0);
  const grandCr = hits.reduce((s, je) => s + je.lines.reduce((ss, l) => ss + l.cr, 0), 0);
  tfoot.innerHTML = `
    <tr class="tfoot-row">
      <td colspan="3" class="fw-7">${hits.length} entr${hits.length === 1 ? 'y' : 'ies'}</td>
      <td class="dr r fw-7">${fmt(grandDr)}</td>
      <td class="cr r fw-7">${fmt(grandCr)}</td>
      <td colspan="2"></td>
    </tr>`;
}

function openJEDetail(id) {
  const je = JOURNAL_ENTRIES.find(e => e.id === id);
  if (!je) return;

  document.getElementById('je-detail-title').textContent = `Journal Entry — ${je.ref}`;
  document.getElementById('je-detail-ref').textContent   = je.ref;
  document.getElementById('je-detail-date').textContent  = je.date;
  document.getElementById('je-detail-desc').textContent  = je.desc;
  document.getElementById('je-detail-status').innerHTML  =
    `<span class="badge badge-${je.status.toLowerCase()}">${je.status}</span>`;
  document.getElementById('je-detail-party-row').style.display = 'none';

  const totalDr = je.lines.reduce((s, l) => s + l.dr, 0);
  const totalCr = je.lines.reduce((s, l) => s + l.cr, 0);

  document.getElementById('je-detail-tbody').innerHTML = je.lines.map(l => `
    <tr>
      <td class="mono text-sm">${l.acct} — ${l.acctName}</td>
      <td class="text-sm text-2">${l.desc || ''}</td>
      <td class="r num">${l.dr > 0 ? fmt(l.dr) : ''}</td>
      <td class="r num">${l.cr > 0 ? fmt(l.cr) : ''}</td>
    </tr>`).join('');

  document.getElementById('je-detail-tfoot').innerHTML = `
    <tr class="tfoot-row">
      <td colspan="2" class="fw-7">Total</td>
      <td class="r num fw-7">${fmt(totalDr)}</td>
      <td class="r num fw-7">${fmt(totalCr)}</td>
    </tr>`;

  document.getElementById('je-detail-audit').innerHTML = renderAuditFootprint(je, 'JournalEntry', je.id);
  openModal('modal-je-detail');
}

function postJEEntry(id) {
  const je = JOURNAL_ENTRIES.find(e => e.id === id);
  if (je) { je.status = 'Approved'; renderJournalEntries(); }
}

/* ─── Dashboard ─────────────────────────────────────────────── */
function renderDashboard() {
  const arByCustomer = {};
  INVOICES.filter(inv => inv.status !== 'Paid' && (inv.lifecycle || 'Approved') === 'Approved').forEach(inv => {
    const bal = inv.amount - inv.paid;
    if (bal > 0) arByCustomer[inv.customer] = (arByCustomer[inv.customer] || 0) + bal;
  });
  const arSorted = Object.entries(arByCustomer).sort((a, b) => b[1] - a[1]);
  const arTop    = arSorted.slice(0, 5);
  const arOthers = arSorted.slice(5).reduce((s, [, v]) => s + v, 0);
  const arTotal  = arSorted.reduce((s, [, v]) => s + v, 0);

  const arEl = document.getElementById('dashboard-ar');
  if (arEl) {
    arEl.innerHTML =
      arTop.map(([name, bal]) => `
        <div style="display:flex;justify-content:space-between;padding:8px 16px;border-bottom:1px solid var(--border);font-size:13px">
          <span>${name}</span><span class="fw-7 mono">₱${fmt(bal)}</span>
        </div>`).join('')
      + (arOthers > 0 ? `
        <div style="display:flex;justify-content:space-between;padding:8px 16px;border-bottom:1px solid var(--border);font-size:13px;color:var(--text-2)">
          <span>Others</span><span class="fw-7 mono">₱${fmt(arOthers)}</span>
        </div>` : '')
      + `<div style="display:flex;justify-content:space-between;padding:8px 16px;font-size:13px;font-weight:700;margin-top:2px">
          <span>Total Outstanding</span><span class="mono" style="color:var(--blue)">₱${fmt(arTotal)}</span>
        </div>`;
  }

  const apByVendor = {};
  BILLS.filter(b => b.status !== 'Paid' && (b.lifecycle || 'Approved') === 'Approved').forEach(b => {
    const bal = b.amount - b.paid;
    if (bal > 0) apByVendor[b.vendor] = (apByVendor[b.vendor] || 0) + bal;
  });
  const apSorted = Object.entries(apByVendor).sort((a, b) => b[1] - a[1]);
  const apTop    = apSorted.slice(0, 5);
  const apOthers = apSorted.slice(5).reduce((s, [, v]) => s + v, 0);
  const apTotal  = apSorted.reduce((s, [, v]) => s + v, 0);

  const apEl = document.getElementById('dashboard-ap');
  if (apEl) {
    apEl.innerHTML =
      apTop.map(([name, bal]) => `
        <div style="display:flex;justify-content:space-between;padding:8px 16px;border-bottom:1px solid var(--border);font-size:13px">
          <span>${name}</span><span class="fw-7 mono">₱${fmt(bal)}</span>
        </div>`).join('')
      + (apOthers > 0 ? `
        <div style="display:flex;justify-content:space-between;padding:8px 16px;border-bottom:1px solid var(--border);font-size:13px;color:var(--text-2)">
          <span>Others</span><span class="fw-7 mono">₱${fmt(apOthers)}</span>
        </div>` : '')
      + `<div style="display:flex;justify-content:space-between;padding:8px 16px;font-size:13px;font-weight:700;margin-top:2px">
          <span>Total Outstanding</span><span class="mono" style="color:var(--red)">₱${fmt(apTotal)}</span>
        </div>`;
  }
}

/* ─── Trial Balance ─────────────────────────────────────────── */
function renderTrialBalance() {
  const tbody = document.getElementById('tb-tbody');
  if (!tbody) return;

  // 3003 (Current Year Net Income) is a computed equity memo account; exclude it from
  // the pre-closing TB to avoid double-counting revenue/expense balances.
  const excluded = new Set(['3003']);

  const mains = ACCOUNTS.filter(a => a.isMain);
  let rows = '';
  let totalDr = 0, totalCr = 0;

  mains.forEach(main => {
    const subs = ACCOUNTS.filter(a => a.parent === main.code && a.balance !== 0 && !excluded.has(a.code));
    if (!subs.length) return;
    rows += `<tr class="group-header"><td><code>${main.code}</code></td><td colspan="3">${main.name}</td></tr>`;
    let mainDr = 0, mainCr = 0;
    subs.forEach(sub => {
      const dr = sub.nb === 'Debit'  ? sub.balance : 0;
      const cr = sub.nb === 'Credit' ? sub.balance : 0;
      mainDr += dr;
      mainCr += cr;
      totalDr += dr;
      totalCr += cr;
      rows += `
        <tr>
          <td class="sub-code">${sub.code}</td>
          <td class="sub-name">${sub.name}</td>
          <td class="r num">${dr > 0 ? fmt(dr) : ''}</td>
          <td class="r num">${cr > 0 ? fmt(cr) : ''}</td>
        </tr>`;
    });
    rows += `
      <tr class="tb-main-subtotal">
        <td></td>
        <td style="font-weight:700">Total ${main.name}</td>
        <td class="r num fw-7">${mainDr > 0 ? fmt(mainDr) : ''}</td>
        <td class="r num fw-7">${mainCr > 0 ? fmt(mainCr) : ''}</td>
      </tr>`;
  });
  tbody.innerHTML = rows;

  const drEl = document.getElementById('tb-total-dr');
  const crEl = document.getElementById('tb-total-cr');
  if (drEl) drEl.textContent = fmt(totalDr);
  if (crEl) crEl.textContent = fmt(totalCr);
}

/* ─── AR / AP Aging reports ──────────────────────────────────
   Buckets: Current / 1-30 / 31-60 / 61-90 / 90+ based on days past due
   relative to TODAY_STR. Only Approved + non-fully-paid records count.
   ─────────────────────────────────────────────────────────── */
function _ageBucket(dueDate) {
  if (!dueDate || dueDate >= TODAY_STR) return 'current';
  const today = new Date(TODAY_STR + 'T00:00');
  const due   = new Date(dueDate + 'T00:00');
  const days  = Math.floor((today - due) / 86400000);
  if (days <= 30) return 'd1_30';
  if (days <= 60) return 'd31_60';
  if (days <= 90) return 'd61_90';
  return 'd90_plus';
}

function _renderAging(records, partyField, contentId, partyLabel) {
  const root = document.getElementById(contentId);
  if (!root) return;
  const open = records.filter(r => (r.lifecycle || 'Approved') === 'Approved' && r.paid < r.amount);
  const byParty = {};
  open.forEach(r => {
    const key = r[partyField];
    if (!byParty[key]) byParty[key] = { current:0, d1_30:0, d31_60:0, d61_90:0, d90_plus:0, total:0 };
    const bal = r.amount - r.paid;
    byParty[key][_ageBucket(r.due)] += bal;
    byParty[key].total += bal;
  });
  const parties = Object.keys(byParty).sort();
  const totals  = { current:0, d1_30:0, d31_60:0, d61_90:0, d90_plus:0, total:0 };
  parties.forEach(p => Object.keys(totals).forEach(k => totals[k] += byParty[p][k]));

  const fmtCell = v => v > 0 ? fmt(v) : '—';
  const rows = parties.map(p => {
    const b = byParty[p];
    return `<tr>
      <td>${p}</td>
      <td class="num">${fmtCell(b.current)}</td>
      <td class="num">${fmtCell(b.d1_30)}</td>
      <td class="num">${fmtCell(b.d31_60)}</td>
      <td class="num">${fmtCell(b.d61_90)}</td>
      <td class="num">${fmtCell(b.d90_plus)}</td>
      <td class="num fw-7">${fmt(b.total)}</td>
    </tr>`;
  }).join('') || `<tr><td colspan="7" style="text-align:center;color:var(--text-3);padding:24px">No outstanding balances</td></tr>`;

  root.innerHTML = `
    <table>
      <thead>
        <tr>
          <th>${partyLabel}</th>
          <th class="r">Current</th>
          <th class="r">1–30 days</th>
          <th class="r">31–60 days</th>
          <th class="r">61–90 days</th>
          <th class="r">90+ days</th>
          <th class="r">Total Outstanding</th>
        </tr>
      </thead>
      <tbody>${rows}</tbody>
      <tfoot>
        <tr class="tfoot-row">
          <td class="fw-7">${parties.length} ${partyLabel.toLowerCase()}${parties.length !== 1 ? 's' : ''}</td>
          <td class="num fw-7">${fmtCell(totals.current)}</td>
          <td class="num fw-7">${fmtCell(totals.d1_30)}</td>
          <td class="num fw-7">${fmtCell(totals.d31_60)}</td>
          <td class="num fw-7">${fmtCell(totals.d61_90)}</td>
          <td class="num fw-7">${fmtCell(totals.d90_plus)}</td>
          <td class="num fw-7">${fmt(totals.total)}</td>
        </tr>
      </tfoot>
    </table>`;
}

function renderARAging() { _renderAging(INVOICES, 'customer', 'ar-aging-content', 'Customer'); }
function renderAPAging() { _renderAging(BILLS,    'vendor',   'ap-aging-content', 'Vendor');   }

/* ─── BIR 2550Q — Quarterly VAT Return ────────────────────────
   Source: Approved invoices (Output VAT) − Approved bills (Input VAT) for
   the selected quarter. Mockup lacks per-line VAT type, so we treat all
   gross as 12% VATable (net = gross/1.12, VAT = gross − net).
   ─────────────────────────────────────────────────────────── */
function _quarterRange(year, quarter) {
  const startMonth = (quarter - 1) * 3 + 1;
  const endMonth   = startMonth + 2;
  const start = `${year}-${String(startMonth).padStart(2,'0')}-01`;
  const lastDay = new Date(year, endMonth, 0).getDate();
  const end   = `${year}-${String(endMonth).padStart(2,'0')}-${String(lastDay).padStart(2,'0')}`;
  return { start, end };
}

function render2550Q() {
  const root = document.getElementById('q2550-content');
  if (!root) return;
  const year    = parseInt(document.getElementById('q2550-year')?.value || '2026', 10);
  const quarter = parseInt(document.getElementById('q2550-quarter')?.value || '2', 10);
  const { start, end } = _quarterRange(year, quarter);

  document.getElementById('q2550-period-label').textContent = `${start} → ${end}`;

  const inv = INVOICES.filter(i => i.lifecycle === 'Approved' && i.date >= start && i.date <= end);
  const bil = BILLS.filter(b => b.lifecycle === 'Approved' && b.date >= start && b.date <= end);

  const grossSales     = inv.reduce((s, i) => s + i.amount, 0);
  const netSales       = grossSales / 1.12;
  const outputVAT      = grossSales - netSales;
  const grossPurchases = bil.reduce((s, b) => s + b.amount, 0);
  const netPurchases   = grossPurchases / 1.12;
  const inputVAT       = grossPurchases - netPurchases;
  const vatPayable     = outputVAT - inputVAT;

  const line = (label, value, opts = {}) => `
    <div style="display:flex;justify-content:space-between;padding:${opts.bold ? '8' : '5'}px 0;${opts.border ? 'border-top:1px solid var(--border);margin-top:4px' : ''}">
      <span style="${opts.bold ? 'font-weight:700' : ''}">${label}</span>
      <span class="num ${opts.bold ? 'fw-7' : ''}" style="font-family:var(--mono)">${value < 0 ? `(${fmt(Math.abs(value))})` : fmt(value)}</span>
    </div>`;

  root.innerHTML = `
    <div style="font-size:11px;color:var(--text-3);margin-bottom:14px">All amounts in PHP. Assumes 12% VAT on all taxable transactions; refine when per-line VAT types are tracked.</div>
    <div style="font-weight:700;font-size:13px;text-transform:uppercase;letter-spacing:.5px;color:var(--text-2);margin-bottom:10px">Sales / Output</div>
    ${line('Gross Sales', grossSales)}
    ${line('Less: VAT (12%)', outputVAT)}
    ${line('Net Sales', netSales, {border:true})}
    ${line('OUTPUT VAT', outputVAT, {bold:true, border:true})}

    <div style="font-weight:700;font-size:13px;text-transform:uppercase;letter-spacing:.5px;color:var(--text-2);margin:20px 0 10px">Purchases / Input</div>
    ${line('Gross Purchases', grossPurchases)}
    ${line('Less: VAT (12%)', inputVAT)}
    ${line('Net Purchases', netPurchases, {border:true})}
    ${line('INPUT VAT', inputVAT, {bold:true, border:true})}

    <div class="rpt-row net-income" style="margin-top:24px">
      <span>${vatPayable >= 0 ? 'VAT PAYABLE' : 'EXCESS INPUT VAT (Refundable)'}</span>
      <span class="rpt-num" style="font-size:16px">${vatPayable < 0 ? `(${fmt(Math.abs(vatPayable))})` : fmt(vatPayable)}</span>
    </div>`;
}

/* ─── BIR 0619-E — Monthly EWT Remittance ────────────────────
   Filed for the FIRST and SECOND months of each quarter
   (Jan/Feb, Apr/May, Jul/Aug, Oct/Nov). The third month rolls up
   into 1601-EQ. Source: Approved bills dated in the selected month.
   ─────────────────────────────────────────────────────────── */
function _monthRange(year, month) {
  const start = `${year}-${String(month).padStart(2,'0')}-01`;
  const last = new Date(year, month, 0).getDate();
  const end  = `${year}-${String(month).padStart(2,'0')}-${String(last).padStart(2,'0')}`;
  return { start, end };
}

function render0619E() {
  const root = document.getElementById('e0619-content');
  if (!root) return;
  const year  = parseInt(document.getElementById('e0619-year')?.value || '2026', 10);
  const month = parseInt(document.getElementById('e0619-month')?.value || '4', 10);
  const { start, end } = _monthRange(year, month);
  document.getElementById('e0619-period-label').textContent = `${start} → ${end}`;

  const bills = BILLS.filter(b => b.lifecycle === 'Approved' && b.date >= start && b.date <= end);
  const byAtc = {};
  bills.forEach(b => {
    const vendor = VENDORS.find(v => v.name === b.vendor);
    const atc = (vendor?.defaultWt || ['WC100'])[0];
    const wht = WITHHOLDING_TAXES.find(w => w.code === atc) || { name:atc, rate:'2%' };
    const rate = parseFloat(wht.rate) / 100 || 0;
    const netOfVat = b.amount / 1.12;
    const ewt = netOfVat * rate;
    if (!byAtc[atc]) byAtc[atc] = { name:wht.name, rate:wht.rate, income:0, ewt:0, count:0 };
    byAtc[atc].income += netOfVat;
    byAtc[atc].ewt    += ewt;
    byAtc[atc].count  += 1;
  });

  const atcs = Object.keys(byAtc).sort();
  const totalIncome = atcs.reduce((s, a) => s + byAtc[a].income, 0);
  const totalEwt    = atcs.reduce((s, a) => s + byAtc[a].ewt, 0);

  const rows = atcs.map(c => {
    const b = byAtc[c];
    return `<tr><td><code>${c}</code></td><td>${b.name}</td><td class="r">${b.rate}</td><td class="r">${b.count}</td><td class="num">${fmt(b.income)}</td><td class="num">${fmt(b.ewt)}</td></tr>`;
  }).join('') || `<tr><td colspan="6" style="text-align:center;color:var(--text-3);padding:24px">No EWT transactions for this month</td></tr>`;

  root.innerHTML = `
    <div style="font-size:11px;color:var(--text-3);margin-bottom:14px">
      Filed by the 10th of the following month using eFPS/eBIRForms. The 3rd month of every quarter is consolidated in 1601-EQ.
    </div>
    <table>
      <thead>
        <tr><th>ATC</th><th>Nature of Payment</th><th class="r">Rate</th><th class="r">Bills</th><th class="r">Income (net)</th><th class="r">EWT</th></tr>
      </thead>
      <tbody>${rows}</tbody>
      <tfoot>
        <tr class="tfoot-row">
          <td colspan="4" class="fw-7">${atcs.length} ATC group${atcs.length !== 1 ? 's' : ''}</td>
          <td class="num fw-7">${fmt(totalIncome)}</td>
          <td class="num fw-7">${fmt(totalEwt)}</td>
        </tr>
      </tfoot>
    </table>
    <div class="rpt-row net-income" style="margin-top:24px">
      <span>TOTAL EWT REMITTABLE FOR ${start.slice(0,7)}</span>
      <span class="rpt-num" style="font-size:16px">${fmt(totalEwt)}</span>
    </div>`;
}

/* ─── BIR 2307 — Certificate of Creditable Tax Withheld ───────
   Per-vendor certificate listing income paid + EWT withheld in the
   quarter. We (the buyer) issue one to each vendor within 20 days
   after the quarter ends, so they can claim the EWT against ITR.
   ─────────────────────────────────────────────────────────── */

// Issued certs registry: keyed by `${year}-Q${q}-${vendorCode}-${atc}`
const CERT_2307_ISSUED = {};
let _current2307Key = null;

function _vendorCertData(year, quarter) {
  const { start, end } = _quarterRange(year, quarter);
  const bills = BILLS.filter(b => b.lifecycle === 'Approved' && b.date >= start && b.date <= end);
  // Group bills per vendor + ATC
  const groups = {};
  bills.forEach(b => {
    const vendor = VENDORS.find(v => v.name === b.vendor);
    if (!vendor) return;
    const atc = (vendor.defaultWt || ['WC100'])[0];
    const wht = WITHHOLDING_TAXES.find(w => w.code === atc) || { name:atc, rate:'2%' };
    const rate = parseFloat(wht.rate) / 100 || 0;
    const netOfVat = b.amount / 1.12;
    const ewt = netOfVat * rate;
    const key = `${vendor.code}-${atc}`;
    if (!groups[key]) groups[key] = { vendor, atc, atcName:wht.name, rate:wht.rate, bills:[], income:0, ewt:0 };
    groups[key].bills.push(b);
    groups[key].income += netOfVat;
    groups[key].ewt    += ewt;
  });
  return { groups, start, end };
}

function render2307List() {
  const tbody = document.getElementById('cert2307-tbody');
  const tfoot = document.getElementById('cert2307-tfoot');
  if (!tbody) return;
  const year    = parseInt(document.getElementById('cert2307-year')?.value || '2026', 10);
  const quarter = parseInt(document.getElementById('cert2307-quarter')?.value || '2', 10);
  const { groups, start, end } = _vendorCertData(year, quarter);
  document.getElementById('cert2307-period-label').textContent = `${start} → ${end}`;

  const rows = Object.entries(groups);
  let totalIncome = 0, totalEwt = 0;
  tbody.innerHTML = rows.map(([key, g]) => {
    totalIncome += g.income; totalEwt += g.ewt;
    const certKey = `${year}-Q${quarter}-${key}`;
    const issued  = CERT_2307_ISSUED[certKey];
    return `<tr>
      <td>${g.vendor.name}</td>
      <td><code>${g.vendor.tin || '—'}</code></td>
      <td><code>${g.atc}</code> ${g.atcName}</td>
      <td class="num">${fmt(g.income)}</td>
      <td class="num">${fmt(g.ewt)}</td>
      <td class="r">${issued ? `<span class="badge badge-paid">Issued ${issued.date}</span>` : `<span class="badge badge-draft">Pending</span>`}</td>
      <td style="white-space:nowrap;display:flex;gap:4px">
        <button class="btn btn-sm btn-primary" onclick="open2307Cert('${year}','${quarter}','${key}')">View / Print</button>
      </td>
    </tr>`;
  }).join('') || `<tr><td colspan="7" style="text-align:center;color:var(--text-3);padding:24px">No EWT transactions in this period</td></tr>`;

  tfoot.innerHTML = `<tr class="tfoot-row">
    <td colspan="3" class="fw-7">${rows.length} certificate${rows.length !== 1 ? 's' : ''}</td>
    <td class="num fw-7">${fmt(totalIncome)}</td>
    <td class="num fw-7">${fmt(totalEwt)}</td>
    <td colspan="2"></td>
  </tr>`;
}

function open2307Cert(year, quarter, key) {
  const { groups, start, end } = _vendorCertData(parseInt(year, 10), parseInt(quarter, 10));
  const g = groups[key];
  if (!g) return;
  _current2307Key = `${year}-Q${quarter}-${key}`;
  const issued = CERT_2307_ISSUED[_current2307Key];

  const fmtD = d => new Date(d + 'T00:00').toLocaleDateString('en-PH', { month:'short', day:'numeric', year:'numeric' });
  const body = document.getElementById('cert2307-body');
  body.innerHTML = `
    <div style="border:1px solid var(--border);padding:16px;border-radius:6px;margin-bottom:14px">
      <div style="text-align:center;margin-bottom:14px">
        <div style="font-weight:700;font-size:14px">CERTIFICATE OF CREDITABLE TAX WITHHELD AT SOURCE</div>
        <div style="font-size:12px;color:var(--text-3)">For the period ${fmtD(start)} – ${fmtD(end)} (Q${quarter} ${year})</div>
      </div>
      <div class="form-row-2" style="margin-bottom:12px">
        <div>
          <div class="form-label">Payor (Withholding Agent)</div>
          <div class="fw-7">Company Name</div>
          <div class="text-sm text-2">TIN: 000-000-000-000</div>
        </div>
        <div>
          <div class="form-label">Payee (Vendor)</div>
          <div class="fw-7">${g.vendor.name}</div>
          <div class="text-sm text-2">TIN: ${g.vendor.tin || '—'}</div>
          <div class="text-sm text-2">${g.vendor.address || ''}</div>
        </div>
      </div>
      <table>
        <thead>
          <tr>
            <th>ATC</th>
            <th>Nature of Income Payment</th>
            <th class="r">Income Payments (₱)</th>
            <th class="r">Rate</th>
            <th class="r">Tax Withheld (₱)</th>
          </tr>
        </thead>
        <tbody>
          <tr>
            <td><code>${g.atc}</code></td>
            <td>${g.atcName}</td>
            <td class="num">${fmt(g.income)}</td>
            <td class="r">${g.rate}</td>
            <td class="num">${fmt(g.ewt)}</td>
          </tr>
        </tbody>
        <tfoot>
          <tr class="tfoot-row">
            <td colspan="2" class="fw-7">Totals</td>
            <td class="num fw-7">${fmt(g.income)}</td>
            <td></td>
            <td class="num fw-7">${fmt(g.ewt)}</td>
          </tr>
        </tfoot>
      </table>
      <div style="font-size:11px;color:var(--text-3);margin-top:10px">
        Source bills: ${g.bills.map(b => b.num).join(', ')}
      </div>
      <div style="display:grid;grid-template-columns:1fr 1fr;gap:24px;margin-top:30px">
        <div style="text-align:center"><div style="border-top:1px solid var(--text);padding-top:6px">Authorised Signatory (Payor)</div></div>
        <div style="text-align:center"><div style="border-top:1px solid var(--text);padding-top:6px">Received by (Payee)</div></div>
      </div>
    </div>
    ${issued ? `<div class="auth-success" style="margin-bottom:0">Already issued ${issued.date} by ${issued.by}</div>` : ''}
  `;
  openModal('modal-2307');
}

function mark2307Issued() {
  if (!_current2307Key) return;
  CERT_2307_ISSUED[_current2307Key] = { date: TODAY_STR, by: _currentUser.name };
  logAudit({ category:'coa', recordType:'BIR2307', recordId:_current2307Key, event:'cert_issued' });
  closeModal('modal-2307');
  render2307List();
  showToast('Certificate marked as issued.');
}

/* ─── BIR 1601-EQ — Quarterly EWT Remittance ──────────────────
   Source: Approved bills in the quarter, grouped by vendor.
   Uses vendor.defaultWt as proxy ATC for the demo since per-line WT
   isn't tracked yet.
   ─────────────────────────────────────────────────────────── */
function render1601EQ() {
  const root = document.getElementById('eq1601-content');
  if (!root) return;
  const year    = parseInt(document.getElementById('eq1601-year')?.value || '2026', 10);
  const quarter = parseInt(document.getElementById('eq1601-quarter')?.value || '2', 10);
  const { start, end } = _quarterRange(year, quarter);

  document.getElementById('eq1601-period-label').textContent = `${start} → ${end}`;

  const bills = BILLS.filter(b => b.lifecycle === 'Approved' && b.date >= start && b.date <= end);
  const byAtc = {};
  bills.forEach(b => {
    const vendor = VENDORS.find(v => v.name === b.vendor);
    const atcs = vendor?.defaultWt || ['WC100'];   // fallback
    const atc  = atcs[0];
    const wht  = WITHHOLDING_TAXES.find(w => w.code === atc) || { name:atc, rate:'2%' };
    const rate = parseFloat(wht.rate) / 100 || 0;
    const netOfVat = b.amount / 1.12;
    const ewt = netOfVat * rate;
    if (!byAtc[atc]) byAtc[atc] = { name:wht.name, rate:wht.rate, income:0, ewt:0, count:0 };
    byAtc[atc].income += netOfVat;
    byAtc[atc].ewt    += ewt;
    byAtc[atc].count  += 1;
  });

  const atcs = Object.keys(byAtc).sort();
  const totalIncome = atcs.reduce((s, a) => s + byAtc[a].income, 0);
  const totalEwt    = atcs.reduce((s, a) => s + byAtc[a].ewt, 0);

  const rows = atcs.map(code => {
    const b = byAtc[code];
    return `<tr>
      <td><code>${code}</code></td>
      <td>${b.name}</td>
      <td class="r">${b.rate}</td>
      <td class="r">${b.count}</td>
      <td class="num">${fmt(b.income)}</td>
      <td class="num">${fmt(b.ewt)}</td>
    </tr>`;
  }).join('') || `<tr><td colspan="6" style="text-align:center;color:var(--text-3);padding:24px">No EWT transactions in this period</td></tr>`;

  root.innerHTML = `
    <div style="font-size:11px;color:var(--text-3);margin-bottom:14px">All amounts in PHP. EWT base = bill gross ÷ 1.12 (net of VAT). Refine when per-line ATC is tracked.</div>
    <table>
      <thead>
        <tr><th>ATC</th><th>Nature of Payment</th><th class="r">Rate</th><th class="r">Bills</th><th class="r">Income Payment (net)</th><th class="r">EWT Withheld</th></tr>
      </thead>
      <tbody>${rows}</tbody>
      <tfoot>
        <tr class="tfoot-row">
          <td colspan="4" class="fw-7">${atcs.length} ATC group${atcs.length !== 1 ? 's' : ''}</td>
          <td class="num fw-7">${fmt(totalIncome)}</td>
          <td class="num fw-7">${fmt(totalEwt)}</td>
        </tr>
      </tfoot>
    </table>

    <div class="rpt-row net-income" style="margin-top:24px">
      <span>TOTAL EWT REMITTABLE</span>
      <span class="rpt-num" style="font-size:16px">${fmt(totalEwt)}</span>
    </div>`;
}

/* ─── Hierarchical report helpers ──────────────────────────── */
// Sum sub-account balances under a Main, respecting nb (contra accounts subtract).
function _mainBalance(main) {
  const subs = ACCOUNTS.filter(a => a.parent === main.code);
  return subs.reduce((s, a) => s + (a.nb === main.nb ? a.balance : -a.balance), 0);
}

function _subDisplay(sub, mainNb) {
  // Returns { amount, negative } — contra accounts (opposite nb to Main) render as parentheses.
  const isContra = sub.nb !== mainNb;
  return { amount: sub.balance, negative: isContra };
}

function _renderMainBlock(main, opts = {}) {
  const subs = ACCOUNTS.filter(a => a.parent === main.code);
  if (!subs.length) return { html: '', total: 0 };
  const subRows = subs.map(sub => {
    const { amount, negative } = _subDisplay(sub, main.nb);
    const cls = negative ? 'rpt-num rpt-neg' : 'rpt-num';
    const disp = negative ? `(${fmt(amount)})` : fmt(amount);
    return `<div class="rpt-row indent">
      <span><span style="font-family:var(--mono);color:var(--text-3);font-size:12px;margin-right:8px">${sub.code}</span>${sub.name}</span>
      <span class="${cls}">${disp}</span>
    </div>`;
  }).join('');
  const total = _mainBalance(main);
  const totalDisp = total < 0 ? `(${fmt(Math.abs(total))})` : fmt(total);
  const totalCls  = total < 0 ? 'rpt-num rpt-neg' : 'rpt-num';
  const html = `
    <div class="rpt-section">
      <div class="rpt-section-title">${main.name} <span style="font-weight:400;color:var(--text-3);font-size:11px">${main.code}</span></div>
      ${subRows}
      <div class="rpt-row subtotal">
        <span>${opts.subtotalLabel || `Total ${main.name}`}</span>
        <span class="${totalCls}">${totalDisp}</span>
      </div>
    </div>`;
  return { html, total };
}

function renderIncomeStatement() {
  const root = document.getElementById('is-content');
  if (!root) return;

  const revMains = ACCOUNTS.filter(a => a.isMain && a.type === 'Revenue');
  const expMains = ACCOUNTS.filter(a => a.isMain && a.type === 'Expense');

  let html = '';
  let totalRev = 0, totalExp = 0, totalCogs = 0;

  // Revenue
  revMains.forEach(m => {
    const { html: block, total } = _renderMainBlock(m);
    html += block;
    totalRev += total;
  });
  html += `<div class="rpt-row subtotal" style="background:#eff6ff">
    <span>Total Revenue</span><span class="rpt-num">${fmt(totalRev)}</span>
  </div>`;

  // Cost of Sales (code 5000) — special: show Gross Profit row after
  const cosMain = expMains.find(m => m.code === '5000');
  if (cosMain) {
    const { html: block, total } = _renderMainBlock(cosMain);
    html += block;
    totalCogs = total;
    totalExp += total;
    const grossProfit = totalRev - totalCogs;
    html += `<div class="rpt-row subtotal" style="background:#f0fdf4">
      <span>Gross Profit</span>
      <span class="rpt-num fw-7">${fmt(grossProfit)}</span>
    </div>`;
  }

  // Other expense mains (operating, etc.)
  expMains.filter(m => m.code !== '5000').forEach(m => {
    const { html: block, total } = _renderMainBlock(m);
    html += block;
    totalExp += total;
  });

  if (expMains.length > 1) {
    html += `<div class="rpt-row subtotal" style="background:#fef2f2">
      <span>Total Expenses</span><span class="rpt-num">${fmt(totalExp)}</span>
    </div>`;
  }

  const netIncome = totalRev - totalExp;
  const niDisp = netIncome < 0 ? `(${fmt(Math.abs(netIncome))})` : fmt(netIncome);
  html += `<div class="rpt-row net-income">
    <span>NET INCOME</span>
    <span class="rpt-num" style="font-size:16px">${niDisp}</span>
  </div>`;

  root.innerHTML = html;
}

function renderBalanceSheet() {
  const root = document.getElementById('bs-content');
  if (!root) return;

  // Exclude 3003 from equity — the current-year net income is computed separately to avoid
  // double-counting with the Income Statement when it's brought across.
  const excludedEquity = new Set(['3003']);

  const assetMains   = ACCOUNTS.filter(a => a.isMain && a.type === 'Asset');
  const liabMains    = ACCOUNTS.filter(a => a.isMain && a.type === 'Liability');
  const equityMains  = ACCOUNTS.filter(a => a.isMain && a.type === 'Equity');
  const revenueMains = ACCOUNTS.filter(a => a.isMain && a.type === 'Revenue');
  const expenseMains = ACCOUNTS.filter(a => a.isMain && a.type === 'Expense');

  const computedNI = revenueMains.reduce((s,m) => s + _mainBalance(m), 0)
                   - expenseMains.reduce((s,m) => s + _mainBalance(m), 0);

  function renderClassifiedGroup(mains, classification, label) {
    const inClass = mains.filter(m => m.classification === classification);
    if (!inClass.length) return { html: '', total: 0 };
    let inner = '';
    let total = 0;
    inClass.forEach(m => {
      const { html: block, total: t } = _renderMainBlock(m);
      inner += block;
      total += t;
    });
    inner += `<div class="rpt-row subtotal" style="background:#f1f5f9">
      <span>${label}</span><span class="rpt-num fw-7">${fmt(total)}</span>
    </div>`;
    return { html: inner, total };
  }

  function sectionHeader(label) {
    return `<div style="font-size:13px;font-weight:800;letter-spacing:.5px;text-transform:uppercase;color:var(--text-2);margin:18px 0 8px;border-bottom:2px solid var(--text);padding-bottom:4px">${label}</div>`;
  }

  // ASSETS
  let html = sectionHeader('Assets');
  const curA   = renderClassifiedGroup(assetMains, 'Current',     'Total Current Assets');
  const nonCurA= renderClassifiedGroup(assetMains, 'Non-Current', 'Total Non-Current Assets');
  html += curA.html + nonCurA.html;
  const totalAssets = curA.total + nonCurA.total;
  html += `<div class="rpt-row total"><span>TOTAL ASSETS</span><span class="rpt-num">${fmt(totalAssets)}</span></div>`;

  // LIABILITIES
  html += sectionHeader('Liabilities');
  const curL   = renderClassifiedGroup(liabMains, 'Current',     'Total Current Liabilities');
  const nonCurL= renderClassifiedGroup(liabMains, 'Non-Current', 'Total Non-Current Liabilities');
  html += curL.html + nonCurL.html;
  const totalLiab = curL.total + nonCurL.total;
  html += `<div class="rpt-row total"><span>TOTAL LIABILITIES</span><span class="rpt-num">${fmt(totalLiab)}</span></div>`;

  // EQUITY — show 3001/3002, then a synthetic Current Year Net Income row from the IS
  html += sectionHeader('Equity');
  let totalEquity = 0;
  equityMains.forEach(m => {
    const subs = ACCOUNTS.filter(a => a.parent === m.code && !excludedEquity.has(a.code));
    if (!subs.length && m.code !== '3000') return;
    const subRows = subs.map(sub => {
      const { amount, negative } = _subDisplay(sub, m.nb);
      const cls = negative ? 'rpt-num rpt-neg' : 'rpt-num';
      const disp = negative ? `(${fmt(amount)})` : fmt(amount);
      return `<div class="rpt-row indent">
        <span><span style="font-family:var(--mono);color:var(--text-3);font-size:12px;margin-right:8px">${sub.code}</span>${sub.name}</span>
        <span class="${cls}">${disp}</span>
      </div>`;
    }).join('');
    const subTotal = subs.reduce((s,a) => s + (a.nb === m.nb ? a.balance : -a.balance), 0);
    // Inject Current Year Net Income under Owner's Equity (3000)
    const niRow = m.code === '3000' ? `<div class="rpt-row indent">
        <span><span style="font-family:var(--mono);color:var(--text-3);font-size:12px;margin-right:8px">—</span>Net Income — Current Period</span>
        <span class="rpt-num">${fmt(computedNI)}</span>
      </div>` : '';
    const mainTotal = subTotal + (m.code === '3000' ? computedNI : 0);
    totalEquity += mainTotal;
    html += `<div class="rpt-section">
      <div class="rpt-section-title">${m.name} <span style="font-weight:400;color:var(--text-3);font-size:11px">${m.code}</span></div>
      ${subRows}
      ${niRow}
      <div class="rpt-row subtotal"><span>Total ${m.name}</span><span class="rpt-num fw-7">${fmt(mainTotal)}</span></div>
    </div>`;
  });
  html += `<div class="rpt-row total"><span>TOTAL EQUITY</span><span class="rpt-num">${fmt(totalEquity)}</span></div>`;

  // Grand total
  html += `<div class="rpt-row total" style="background:#dbeafe;border-top:2px solid var(--blue);color:#1d4ed8">
    <span>TOTAL LIABILITIES &amp; EQUITY</span><span class="rpt-num">${fmt(totalLiab + totalEquity)}</span>
  </div>`;

  // Out-of-balance warning
  if (Math.abs(totalAssets - (totalLiab + totalEquity)) > 0.005) {
    html = `<div style="background:#fee2e2;color:#b91c1c;padding:10px 14px;border-radius:6px;font-weight:700;margin-bottom:14px">
      ⚠ Balance Sheet is out of balance by ${fmt(Math.abs(totalAssets - (totalLiab + totalEquity)))}
    </div>` + html;
  }

  root.innerHTML = html;
}

/* ─── Customer / Vendor Edit & Save ─────────────────────────── */
function openEditCustomer(code) {
  const c = CUSTOMERS.find(c => c.code === code);
  if (!c) return;
  openModal('modal-add-customer');
  _editingCustomerCode = code;
  document.getElementById('modal-add-customer-title').textContent = 'Edit Customer';
  document.getElementById('new-cust-code').value    = c.code;
  document.getElementById('new-cust-name').value    = c.name;
  document.getElementById('new-cust-contact').value = c.contact;
  document.getElementById('new-cust-phone').value   = c.phone;
  document.getElementById('new-cust-email').value   = c.email;
  document.getElementById('new-cust-tin').value     = c.tin;
  document.getElementById('new-cust-terms').value   = c.terms;
  document.getElementById('new-cust-status').value  = c.status;
  document.getElementById('new-cust-address').value = c.address;
  document.getElementById('new-cust-postal').value  = c.postalCode;
  document.getElementById('new-cust-vat').value     = c.defaultVat || '';
  document.querySelectorAll('#new-cust-wt-checks input').forEach(cb => {
    cb.checked = (c.defaultWt || []).includes(cb.value);
  });
}

function saveCustomer() {
  const name = document.getElementById('new-cust-name').value.trim();
  if (!name) { alert('Customer name is required.'); return; }

  const record = {
    code:       document.getElementById('new-cust-code').value,
    name,
    contact:    document.getElementById('new-cust-contact').value.trim(),
    phone:      document.getElementById('new-cust-phone').value.trim(),
    email:      document.getElementById('new-cust-email').value.trim(),
    tin:        document.getElementById('new-cust-tin').value.trim(),
    terms:      document.getElementById('new-cust-terms').value,
    status:     document.getElementById('new-cust-status').value,
    address:    document.getElementById('new-cust-address').value.trim(),
    postalCode: document.getElementById('new-cust-postal').value.trim(),
    defaultVat: document.getElementById('new-cust-vat').value,
    defaultWt:  [...document.querySelectorAll('#new-cust-wt-checks input:checked')].map(cb => cb.value),
  };

  if (_editingCustomerCode) {
    const idx = CUSTOMERS.findIndex(c => c.code === _editingCustomerCode);
    if (idx !== -1) CUSTOMERS[idx] = record;
    _editingCustomerCode = null;
  } else {
    CUSTOMERS.push(record);
  }
  renderCustomers();
  closeModal('modal-add-customer');
}

let _detailCustomerCode = null;

function openCustomerDetail(code) {
  const c = CUSTOMERS.find(c => c.code === code);
  if (!c) return;
  _detailCustomerCode = code;

  document.getElementById('cd-name').textContent    = c.name;
  document.getElementById('cd-code').textContent    = c.code;
  document.getElementById('cd-contact').textContent = c.contact   || '—';
  document.getElementById('cd-phone').textContent   = c.phone     || '—';
  document.getElementById('cd-tin').textContent     = c.tin       || '—';
  document.getElementById('cd-terms').textContent   = c.terms     || '—';
  document.getElementById('cd-status').innerHTML    =
    `<span class="badge badge-${c.status.toLowerCase()}">${c.status}</span>`;

  const invoices   = INVOICES.filter(i => i.customer === c.name);
  const totalAmt   = invoices.reduce((s, i) => s + i.amount, 0);
  const totalPaid  = invoices.reduce((s, i) => s + i.paid,   0);
  const totalBal   = totalAmt - totalPaid;

  document.getElementById('cd-total-sales').textContent   = fmt(totalAmt);
  document.getElementById('cd-total-collected').textContent = fmt(totalPaid);
  document.getElementById('cd-total-balance').textContent = fmt(totalBal);

  const fmtDate = d => d
    ? new Date(d + 'T00:00').toLocaleDateString('en-PH', { month:'short', day:'numeric', year:'numeric' })
    : '—';

  const tbody = document.getElementById('cd-inv-tbody');
  tbody.innerHTML = invoices.length
    ? invoices.map(inv => {
        const balance  = inv.amount - inv.paid;
        const isUnpaid = inv.status !== 'Paid';
        return `<tr>
          <td><code>${inv.num}</code></td>
          <td>${fmtDate(inv.date)}</td>
          <td style="color:${inv.status === 'Overdue' ? 'var(--red)' : 'inherit'}">${fmtDate(inv.due)}</td>
          <td class="r num">${fmt(inv.amount)}</td>
          <td class="r num">${fmt(inv.paid)}</td>
          <td class="r num${balance > 0 ? ' cr' : ''}">${fmt(balance)}</td>
          <td><span class="badge badge-${inv.status.toLowerCase()}">${inv.status}</span></td>
          <td>${isUnpaid
            ? `<button class="btn btn-ghost btn-sm" onclick="openCollectModal('${inv.num}','${c.name}')">Collect</button>`
            : ''}</td>
        </tr>`;
      }).join('')
    : `<tr><td colspan="8" style="text-align:center;color:var(--text-3);padding:20px">No sales history</td></tr>`;

  document.getElementById('cd-foot-amount').textContent  = fmt(totalAmt);
  document.getElementById('cd-foot-collected').textContent = fmt(totalPaid);
  document.getElementById('cd-foot-balance').textContent = fmt(totalBal);

  const hasUnpaid = invoices.some(i => i.status !== 'Paid');
  document.getElementById('cd-collect-btn').disabled = !hasUnpaid;

  navigate('customer-detail');
  document.getElementById('page-title').textContent = c.name;
}

function openEditCustomerFromDetail() {
  const code = _detailCustomerCode;
  if (code) openEditCustomer(code);
}

function openCollectFromDetail() {
  const c = _detailCustomerCode ? CUSTOMERS.find(c => c.code === _detailCustomerCode) : null;
  if (!c) return;
  openCollectModal(null, c.name);
}

let _detailVendorCode = null;

function openVendorDetail(code) {
  const v = VENDORS.find(v => v.code === code);
  if (!v) return;
  _detailVendorCode = code;

  document.getElementById('vd-name').textContent        = v.name;
  document.getElementById('vd-code').textContent        = v.code;
  document.getElementById('vd-contact').textContent     = v.contact || '—';
  document.getElementById('vd-phone').textContent       = v.phone   || '—';
  document.getElementById('vd-tin').textContent         = v.tin     || '—';
  document.getElementById('vd-terms').textContent       = v.terms   || '—';
  document.getElementById('vd-check-payee').textContent = v.checkPayee || '(same as vendor name)';
  document.getElementById('vd-status').innerHTML =
    `<span class="badge badge-${v.status.toLowerCase()}">${v.status}</span>`;

  const bills = BILLS.filter(b => b.vendor === v.name);
  const totalAmt     = bills.reduce((s, b) => s + b.amount, 0);
  const totalPaid    = bills.reduce((s, b) => s + b.paid, 0);
  const totalBalance = totalAmt - totalPaid;

  document.getElementById('vd-total-purchases').textContent = fmt(totalAmt);
  document.getElementById('vd-total-paid').textContent      = fmt(totalPaid);
  document.getElementById('vd-total-balance').textContent   = fmt(totalBalance);

  const fmtDate = d => d ? new Date(d + 'T00:00').toLocaleDateString('en-PH', { month:'short', day:'numeric', year:'numeric' }) : '—';

  const tbody = document.getElementById('vd-bills-tbody');
  tbody.innerHTML = bills.length
    ? bills.map(b => {
        const balance  = b.amount - b.paid;
        const isUnpaid = b.status !== 'Paid';
        return `<tr>
          <td><code>${b.num}</code></td>
          <td>${fmtDate(b.date)}</td>
          <td style="color:${b.status === 'Overdue' ? 'var(--red)' : 'inherit'}">${fmtDate(b.due)}</td>
          <td class="r num">${fmt(b.amount)}</td>
          <td class="r num">${fmt(b.paid)}</td>
          <td class="r num${balance > 0 ? ' cr' : ''}">${fmt(balance)}</td>
          <td><span class="badge badge-${b.status.toLowerCase()}">${b.status}</span></td>
          <td>${isUnpaid
            ? `<button class="btn btn-ghost btn-sm" onclick="openPayBillModal('${b.num}','${v.name}')">Pay</button>`
            : ''}</td>
        </tr>`;
      }).join('')
    : `<tr><td colspan="8" style="text-align:center;color:var(--text-3);padding:20px">No purchase history</td></tr>`;

  document.getElementById('vd-foot-amount').textContent  = fmt(totalAmt);
  document.getElementById('vd-foot-paid').textContent    = fmt(totalPaid);
  document.getElementById('vd-foot-balance').textContent = fmt(totalBalance);

  const hasUnpaid = bills.some(b => b.status !== 'Paid');
  document.getElementById('vd-pay-btn').disabled = !hasUnpaid;

  navigate('vendor-detail');
  document.getElementById('page-title').textContent = v.name;
}

function openEditVendorFromDetail() {
  const code = _detailVendorCode;
  if (code) openEditVendor(code);
}

function openPayFromDetail() {
  const v = _detailVendorCode ? VENDORS.find(v => v.code === _detailVendorCode) : null;
  if (!v) return;
  openPayBillModal(null, v.name);
}

function openEditVendor(code) {
  const v = VENDORS.find(v => v.code === code);
  if (!v) return;
  openModal('modal-add-vendor');
  _editingVendorCode = code;
  document.getElementById('modal-add-vendor-title').textContent = 'Edit Vendor';
  document.getElementById('new-vend-code').value    = v.code;
  document.getElementById('new-vend-name').value    = v.name;
  document.getElementById('new-vend-contact').value = v.contact;
  document.getElementById('new-vend-phone').value   = v.phone;
  document.getElementById('new-vend-email').value   = v.email;
  document.getElementById('new-vend-tin').value     = v.tin;
  document.getElementById('new-vend-terms').value   = v.terms;
  document.getElementById('new-vend-status').value  = v.status;
  document.getElementById('new-vend-address').value = v.address;
  document.getElementById('new-vend-postal').value  = v.postalCode;
  document.getElementById('new-vend-vat').value        = v.defaultVat  || '';
  document.getElementById('new-vend-check-payee').value = v.checkPayee || '';
  document.querySelectorAll('#new-vend-wt-checks input').forEach(cb => {
    cb.checked = (v.defaultWt || []).includes(cb.value);
  });
}

function saveVendor() {
  const name = document.getElementById('new-vend-name').value.trim();
  if (!name) { alert('Vendor name is required.'); return; }

  const record = {
    code:       document.getElementById('new-vend-code').value,
    name,
    contact:     document.getElementById('new-vend-contact').value.trim(),
    phone:       document.getElementById('new-vend-phone').value.trim(),
    email:       document.getElementById('new-vend-email').value.trim(),
    tin:         document.getElementById('new-vend-tin').value.trim(),
    terms:       document.getElementById('new-vend-terms').value,
    status:      document.getElementById('new-vend-status').value,
    address:     document.getElementById('new-vend-address').value.trim(),
    postalCode:  document.getElementById('new-vend-postal').value.trim(),
    defaultVat:  document.getElementById('new-vend-vat').value,
    defaultWt:   [...document.querySelectorAll('#new-vend-wt-checks input:checked')].map(cb => cb.value),
    checkPayee:  document.getElementById('new-vend-check-payee').value.trim(),
  };

  if (_editingVendorCode) {
    const idx = VENDORS.findIndex(v => v.code === _editingVendorCode);
    if (idx !== -1) VENDORS[idx] = record;
    _editingVendorCode = null;
  } else {
    VENDORS.push(record);
  }
  renderVendors();
  closeModal('modal-add-vendor');
}

/* ─── Post Payment / Collection ─────────────────────────────── */
function nextCollectionId() {
  return `26-05-C${String(COLLECTIONS.length + 1).padStart(3, '0')}`;
}
function nextPaymentId() {
  return `26-05-P${String(PAYMENTS.length + 1).padStart(3, '0')}`;
}

function applyCollection(rec) {
  (rec.invoiceLines || []).forEach(line => {
    const inv = INVOICES.find(i => i.num === line.invoiceNum);
    if (!inv) return;
    inv.paid += line.amount;
    if (inv.paid >= inv.amount) inv.status = 'Paid';
    else if (inv.paid > 0) inv.status = 'Partial';
  });
  const jeRef    = nextJENumber(rec.date);
  const arName   = ACCOUNTS.find(a => a.code === '1101')?.name || 'AR — Trade';
  const acctName = ACCOUNTS.find(a => a.code === rec.acctCode)?.name || rec.acctCode;
  JOURNAL_ENTRIES.push({
    id: jeRef, date: rec.date, ref: jeRef,
    desc: `Collection from ${rec.customer}`,
    status: 'Approved',
    lines: [
      { acct: rec.acctCode, acctName,         desc: 'Cash/bank receipt',            dr: rec.amount, cr: 0          },
      { acct: '1101',       acctName: arName, desc: `AR cleared — ${rec.customer}`, dr: 0,          cr: rec.amount },
    ],
  });
  renderJournalEntries();
}

function applyPayment(rec) {
  (rec.billLines || []).forEach(line => {
    const bill = BILLS.find(b => b.num === line.billNum);
    if (!bill) return;
    bill.paid += line.amount;
    if (bill.paid >= bill.amount) bill.status = 'Paid';
    else if (bill.paid > 0) bill.status = 'Partial';
  });
  const jeRef    = nextJENumber(rec.date);
  const apName   = ACCOUNTS.find(a => a.code === '2001')?.name || 'AP — Trade';
  const acctName = ACCOUNTS.find(a => a.code === rec.acctCode)?.name || rec.acctCode;
  JOURNAL_ENTRIES.push({
    id: jeRef, date: rec.date, ref: jeRef,
    desc: `Payment to ${rec.vendor}`,
    status: 'Approved',
    lines: [
      { acct: '2001',       acctName: apName, desc: `AP cleared — ${rec.vendor}`, dr: rec.amount, cr: 0          },
      { acct: rec.acctCode, acctName,          desc: 'Cash/bank disbursement',     dr: 0,          cr: rec.amount },
    ],
  });
  renderJournalEntries();
}

function postPayment(lifecycle) {
  if (lifecycle === undefined) lifecycle = _currentUser.role === 'Accountant' ? 'Approved' : 'Submitted';
  const vendorName = document.getElementById('pay-bill-vendor')?.textContent || '';
  const date       = document.getElementById('pay-bill-date')?.value || '2026-05-30';
  const amount     = parseAmt(document.getElementById('pay-bill-amount')?.value);
  const method     = document.getElementById('pay-bill-method')?.value || 'Bank Transfer';
  const ref        = document.getElementById('pay-bill-ref')?.value || '';
  const acctInput  = document.querySelector('#pay-bill-acct-wrap input');
  const acctCode   = acctInput?.dataset.code || '1003';
  if (!amount) return;

  const billLines = [];
  document.querySelectorAll('#pay-bill-voucher-list input[type=checkbox]:checked').forEach(cb => {
    const paidAmt = parseAmt(cb.closest('div')?.querySelector('input.pay-line-amt')?.value || '0');
    if (paidAmt > 0) billLines.push({ billNum: cb.value, amount: paidAmt });
  });

  const rec = { id: nextPaymentId(), vendor: vendorName, date, amount, method, ref, acctCode, lifecycle, billLines };
  PAYMENTS.push(rec);
  if (lifecycle === 'Approved') applyPayment(rec);

  renderPayments();
  renderBills();
  renderDashboard();
  closeModal('modal-pay-bill');
  showToast(lifecycle === 'Approved' ? 'Payment posted.' : lifecycle === 'Submitted' ? 'Payment submitted for approval.' : 'Payment saved as draft.');
}

function postCollection(lifecycle) {
  if (lifecycle === undefined) lifecycle = _currentUser.role === 'Accountant' ? 'Approved' : 'Submitted';
  const customerName = document.getElementById('collect-customer')?.textContent || '';
  const date         = document.getElementById('collect-date')?.value || '2026-05-30';
  const amount       = parseAmt(document.getElementById('collect-amount')?.value);
  const method       = document.getElementById('collect-method')?.value || 'Bank Transfer';
  const ref          = document.getElementById('collect-ref')?.value || '';
  const acctInput    = document.querySelector('#collect-acct-wrap input');
  const acctCode     = acctInput?.dataset.code || '1003';
  if (!amount) return;

  const invoiceLines = [];
  document.querySelectorAll('#collect-invoice-list input[type=checkbox]:checked').forEach(cb => {
    const amt = parseAmt(cb.closest('div')?.querySelector('input.collect-line-amt')?.value || '0');
    if (amt > 0) invoiceLines.push({ invoiceNum: cb.value, amount: amt });
  });

  const rec = { id: nextCollectionId(), customer: customerName, date, amount, method, ref, acctCode, lifecycle, invoiceLines };
  COLLECTIONS.push(rec);
  if (lifecycle === 'Approved') applyCollection(rec);

  renderCollections();
  renderInvoices();
  renderDashboard();
  closeModal('modal-collect');
  showToast(lifecycle === 'Approved' ? 'Collection posted.' : lifecycle === 'Submitted' ? 'Collection submitted for approval.' : 'Collection saved as draft.');
}

/* ─── Lifecycle helpers ─────────────────────────────────────── */
const TODAY_STR = '2026-05-30';

function lcBadge(lc) {
  const map = { Draft:'badge-draft', Submitted:'badge-submitted', Approved:'badge-approved', Cancelled:'badge-cancelled' };
  return `<span class="badge ${map[lc] || 'badge-draft'}">${lc || 'Draft'}</span>`;
}

function lcPayStatus(inv) {
  if (inv.paid >= inv.amount) return `<span class="badge badge-paid">Paid</span>`;
  if (inv.paid > 0)           return `<span class="badge badge-partial">Partial</span>`;
  if (inv.due < TODAY_STR)    return `<span class="badge badge-overdue">Overdue</span>`;
  return `<span class="badge badge-open">Open</span>`;
}

function billPayStatus(b) {
  if (b.paid >= b.amount) return `<span class="badge badge-paid">Paid</span>`;
  if (b.paid > 0)         return `<span class="badge badge-partial">Partial</span>`;
  if (b.due < TODAY_STR)  return `<span class="badge badge-overdue">Overdue</span>`;
  return `<span class="badge badge-open">Open</span>`;
}

/* ─── User role switcher ─────────────────────────────────────── */
function cycleUser() {
  _currentUserIdx = (_currentUserIdx + 1) % USERS.length;
  _currentUser    = USERS[_currentUserIdx];
  const avatarEl = document.getElementById('user-avatar');
  const nameEl   = document.getElementById('user-name');
  const roleEl   = document.getElementById('user-role-label');
  if (avatarEl) { avatarEl.textContent = _currentUser.initials; avatarEl.style.background = _currentUser.color; }
  if (nameEl)   nameEl.textContent  = _currentUser.name;
  if (roleEl)   roleEl.textContent  = _currentUser.role;
  updateUIForRole();
  renderInvoices();
  renderBills();
  renderCollections();
  renderPayments();
  renderJournalEntries();
  renderActionsWidget();
  renderActionsPage();
}

function updateUIForRole() {
  const role = _currentUser.role;
  document.querySelectorAll('.role-accountant-only').forEach(el => {
    el.style.display = role === 'Accountant' ? '' : 'none';
  });
  document.querySelectorAll('.role-viewer-hide').forEach(el => {
    el.style.display = role === 'Viewer' ? 'none' : '';
  });
  document.querySelectorAll('.role-staff-hide').forEach(el => {
    el.style.display = role === 'Accountant' ? '' : 'none';
  });
  const btnNew = document.getElementById('btn-new-global');
  if (btnNew) btnNew.style.display = role === 'Viewer' ? 'none' : '';
}

/* ─── Lifecycle transition ───────────────────────────────────── */
function lcTransition(type, id, newState) {
  let rec;
  if      (type === 'invoice')    rec = INVOICES.find(r => r.num === id);
  else if (type === 'bill')       rec = BILLS.find(r => r.num === id);
  else if (type === 'collection') rec = COLLECTIONS.find(r => r.id === id);
  else if (type === 'payment')    rec = PAYMENTS.find(r => r.id === id);
  else if (type === 'je')         rec = JOURNAL_ENTRIES.find(r => r.id === id);
  if (!rec) return;

  const prevState = rec.lifecycle || rec.status;
  if (type === 'je') rec.status = newState;
  else rec.lifecycle = newState;

  // Audit footprint denorm fields (see docs/audit-trail.md § 3)
  if (newState === 'Submitted') { rec.submittedBy = _currentUser.name; rec.submittedAt = _auditTs(); }
  if (newState === 'Approved')  { rec.approvedBy  = _currentUser.name; rec.approvedAt  = _auditTs(); }
  if (newState === 'Cancelled') { rec.cancelledBy = _currentUser.name; rec.cancelledAt = _auditTs(); }

  // Audit log entry — category is the specific lifecycle event
  const category = { Submitted:'submit', Approved:'approve', Cancelled:'cancel', Draft:'disapprove' }[newState] || newState.toLowerCase();
  const recordType = { invoice:'Invoice', bill:'Bill', collection:'Collection', payment:'Payment', je:'JournalEntry' }[type];
  const recordId   = (type === 'invoice' || type === 'bill') ? rec.num : rec.id;
  logAudit({ category, recordType, recordId, fromState:prevState, toState:newState });

  if (type === 'collection' && newState === 'Approved' && prevState !== 'Approved') {
    applyCollection(rec);
    renderDashboard();
  }
  if (type === 'payment' && newState === 'Approved' && prevState !== 'Approved') {
    applyPayment(rec);
    renderDashboard();
  }

  if (type === 'invoice')         renderInvoices();
  else if (type === 'bill')       renderBills();
  else if (type === 'collection') { renderCollections(); renderInvoices(); }
  else if (type === 'payment')    { renderPayments();    renderBills();    }
  else if (type === 'je')         renderJournalEntries();

  renderActionsWidget();
  renderActionsPage();

  const labels = { Approved:'Approved', Submitted:'Submitted for approval', Draft:'Returned to Draft', Cancelled:'Cancelled' };
  showToast(labels[newState] || newState);
}

/* ─── AR Invoices render ─────────────────────────────────────── */
function renderInvoices() {
  const flt   = document.getElementById('inv-filter-status')?.value || '';
  const tbody = document.getElementById('ar-inv-tbody');
  const tfoot = document.getElementById('ar-inv-tfoot');
  if (!tbody) return;

  const hits = INVOICES.filter(inv => !flt || (inv.lifecycle || 'Approved') === flt);
  const role = _currentUser.role;
  const fmtD = d => d ? new Date(d + 'T00:00').toLocaleDateString('en-PH', { month:'short', day:'numeric', year:'numeric' }) : '—';

  tbody.innerHTML = hits.map(inv => {
    const balance = inv.amount - inv.paid;
    const lc = inv.lifecycle || 'Approved';
    const btns = [];
    if (role !== 'Viewer') {
      if (lc === 'Draft') {
        btns.push(`<button class="btn btn-sm btn-primary" onclick="lcTransition('invoice','${inv.num}','Submitted')">Submit</button>`);
        if (role === 'Accountant')
          btns.push(`<button class="btn btn-sm btn-danger" onclick="lcTransition('invoice','${inv.num}','Cancelled')">Cancel</button>`);
      } else if (lc === 'Submitted') {
        if (role === 'Accountant') {
          btns.push(`<button class="btn btn-sm btn-success" onclick="lcTransition('invoice','${inv.num}','Approved')">Approve</button>`);
          btns.push(`<button class="btn btn-sm btn-ghost"   onclick="lcTransition('invoice','${inv.num}','Draft')">Disapprove</button>`);
          btns.push(`<button class="btn btn-sm btn-danger"  onclick="lcTransition('invoice','${inv.num}','Cancelled')">Cancel</button>`);
        } else {
          btns.push(`<button class="btn btn-sm btn-ghost" onclick="requestCancellation('invoice','${inv.num}')">Req. Cancel</button>`);
        }
      } else if (lc === 'Approved') {
        if (inv.paid < inv.amount)
          btns.push(`<button class="btn btn-sm btn-primary" onclick="openCollectModal('${inv.num}','${inv.customer.replace(/'/g,"\\'")}')" >Collect</button>`);
        if (role === 'Accountant')
          btns.push(`<button class="btn btn-sm btn-danger" onclick="lcTransition('invoice','${inv.num}','Cancelled')">Cancel</button>`);
        else
          btns.push(`<button class="btn btn-sm btn-ghost" onclick="requestCancellation('invoice','${inv.num}')">Req. Cancel</button>`);
      }
    }
    const dueStyle = lc === 'Approved' && inv.due < TODAY_STR && inv.paid < inv.amount ? ' style="color:var(--red);font-weight:700"' : '';
    return `<tr>
      <td><code style="cursor:pointer;color:var(--blue)" onclick="openInvoiceDetail('${inv.num}')">${inv.num}</code></td>
      <td>${inv.customer}</td>
      <td>${fmtD(inv.date)}</td>
      <td${dueStyle}>${fmtD(inv.due)}</td>
      <td class="num">${fmt(inv.amount)}</td>
      <td class="num">${inv.paid > 0 ? fmt(inv.paid) : '—'}</td>
      <td class="num">${balance > 0 ? fmt(balance) : '—'}</td>
      <td>${lcBadge(lc)}</td>
      <td>${lc === 'Approved' || lc === 'Submitted' ? lcPayStatus(inv) : '—'}</td>
      <td style="white-space:nowrap;display:flex;gap:4px;flex-wrap:wrap"><button class="btn btn-sm btn-ghost" onclick="openInvoiceDetail('${inv.num}')">View</button>${btns.join('')}</td>
    </tr>`;
  }).join('') || `<tr><td colspan="10" style="text-align:center;color:var(--text-3);padding:24px">No invoices match the filter</td></tr>`;

  const totAmt  = hits.reduce((s, i) => s + i.amount, 0);
  const totPaid = hits.reduce((s, i) => s + i.paid,   0);
  const totBal  = totAmt - totPaid;
  tfoot.innerHTML = `<tr class="tfoot-row">
    <td colspan="4" class="fw-7">${hits.length} invoice${hits.length !== 1 ? 's' : ''}</td>
    <td class="num fw-7">${fmt(totAmt)}</td>
    <td class="num fw-7">${totPaid > 0 ? fmt(totPaid) : '—'}</td>
    <td class="num fw-7">${totBal > 0 ? fmt(totBal) : '—'}</td>
    <td colspan="3"></td>
  </tr>`;
}

/* Render the full Audit Log page. See docs/audit-trail.md § 4.2. */
function renderAuditLog() {
  const tbody = document.getElementById('audit-tbody');
  const tfoot = document.getElementById('audit-tfoot');
  if (!tbody) return;

  const cat  = document.getElementById('audit-filter-cat')?.value || '';
  const typ  = document.getElementById('audit-filter-type')?.value || '';
  const text = (document.getElementById('audit-filter-text')?.value || '').toLowerCase();

  const hits = AUDIT_LOG.filter(e => {
    if (cat && e.category !== cat) return false;
    if (typ && e.recordType !== typ) return false;
    if (text) {
      const hay = [e.actor, e.recordType, e.recordId, e.event, e.note, JSON.stringify(e.changes || '')].join(' ').toLowerCase();
      if (!hay.includes(text)) return false;
    }
    return true;
  }).slice().reverse();   // newest first

  tbody.innerHTML = hits.map(e => {
    const recCol = e.recordType
      ? `<code style="cursor:pointer;color:var(--blue)" onclick="openRecordHistory('${e.recordType}','${e.recordId}')">${e.recordType} ${e.recordId}</code>`
      : '—';
    const evCol = e.fromState
      ? `<span style="color:var(--text-3)">${e.fromState} → ${e.toState}</span>`
      : (e.event || '—');
    const detail = e.note || (e.changes ? `<code class="text-sm">${JSON.stringify(e.changes)}</code>` : '');
    const label = AUDIT_CAT_LABEL[e.category] || e.category;
    return `<tr>
      <td class="audit-when">${e.ts}</td>
      <td><span class="badge badge-cat-${e.category}">${label}</span></td>
      <td>${e.actor}</td>
      <td>${recCol}</td>
      <td>${evCol}</td>
      <td>${detail}</td>
    </tr>`;
  }).join('') || `<tr><td colspan="6" style="text-align:center;color:var(--text-3);padding:24px">No audit entries match the filter</td></tr>`;

  tfoot.innerHTML = `<tr class="tfoot-row"><td colspan="6" class="fw-7">${hits.length} entr${hits.length !== 1 ? 'ies' : 'y'} (of ${AUDIT_LOG.length} total)</td></tr>`;
}

/* ─── User Management (Accountant only) ──────────────────────
   See docs/auth.md § 3.5. Mockup behavior: any password is accepted,
   but the form still issues a temp password for show.
   ─────────────────────────────────────────────────────────── */

let _editingUserEmail = null;

// Augment USERS in place to add `status` and `lastLogin` for the demo
USERS.forEach(u => { if (!u.status) u.status = 'Active'; if (!u.lastLogin) u.lastLogin = '—'; });

function _randomTempPwd() {
  return Math.random().toString(36).slice(2, 10);
}

function _initialsFor(name) {
  const parts = name.trim().split(/\s+/);
  return ((parts[0]?.[0] || '') + (parts[parts.length-1]?.[0] || '')).toUpperCase();
}

function _colorForUser(idx) {
  return ['#2563eb','#16a34a','#9333ea','#dc2626','#ea580c','#0891b2','#0284c7','#db2777'][idx % 8];
}

function renderUsersPage() {
  const tbody = document.getElementById('users-tbody');
  const tfoot = document.getElementById('users-tfoot');
  if (!tbody) return;

  const search    = (document.getElementById('users-search')?.value || '').toLowerCase();
  const roleFlt   = document.getElementById('users-filter-role')?.value || '';
  const statusFlt = document.getElementById('users-filter-status')?.value || '';

  const hits = USERS.filter(u => {
    if (search && !`${u.name} ${u.email}`.toLowerCase().includes(search)) return false;
    if (roleFlt && u.role !== roleFlt) return false;
    if (statusFlt && (u.status || 'Active') !== statusFlt) return false;
    return true;
  });

  tbody.innerHTML = hits.map(u => `<tr>
    <td>
      <div style="display:flex;align-items:center;gap:10px">
        <div class="user-avatar" style="background:${u.color}">${u.initials}</div>
        <div>
          <div class="fw-6">${u.name}</div>
          ${u.email === _currentUser.email ? '<div class="text-sm text-3">you</div>' : ''}
        </div>
      </div>
    </td>
    <td><code style="font-size:12px">${u.email}</code></td>
    <td><span class="badge badge-${u.role.toLowerCase()}">${u.role}</span></td>
    <td><span class="badge badge-${(u.status||'Active').toLowerCase()}">${u.status || 'Active'}</span></td>
    <td class="text-sm text-3">${u.lastLogin || '—'}</td>
    <td style="white-space:nowrap;display:flex;gap:4px;flex-wrap:wrap">
      <button class="btn btn-sm btn-ghost" onclick="openUserModal('${u.email}')">Edit</button>
      ${u.email !== _currentUser.email ? `
        <button class="btn btn-sm btn-${u.status === 'Active' ? 'danger' : 'success'}" onclick="toggleUserStatus('${u.email}')">${u.status === 'Active' ? 'Disable' : 'Enable'}</button>
      ` : ''}
    </td>
  </tr>`).join('') || `<tr><td colspan="6" style="text-align:center;color:var(--text-3);padding:24px">No users match the filter</td></tr>`;

  tfoot.innerHTML = `<tr class="tfoot-row"><td colspan="6" class="fw-7">${hits.length} user${hits.length !== 1 ? 's' : ''} (of ${USERS.length} total)</td></tr>`;
}

function openUserModal(email) {
  _editingUserEmail = email || null;
  const user = email ? USERS.find(u => u.email === email) : null;
  document.getElementById('user-modal-title').textContent = user ? `Edit User — ${user.name}` : 'New User';
  document.getElementById('user-modal-name').value   = user?.name   || '';
  document.getElementById('user-modal-email').value  = user?.email  || '';
  document.getElementById('user-modal-role').value   = user?.role   || 'Viewer';
  document.getElementById('user-modal-status').value = user?.status || 'Active';
  document.getElementById('user-modal-email').readOnly = !!user;
  document.getElementById('user-modal-pwd').value    = user ? '••••••••' : _randomTempPwd();
  document.getElementById('user-modal-pwd-row').style.display = user ? 'none' : '';
  document.getElementById('user-modal-reset-btn').style.display = user ? '' : 'none';
  document.getElementById('user-modal-error').style.display = 'none';
  openModal('modal-user');
}

function saveUser() {
  const name   = document.getElementById('user-modal-name').value.trim();
  const email  = document.getElementById('user-modal-email').value.trim().toLowerCase();
  const role   = document.getElementById('user-modal-role').value;
  const status = document.getElementById('user-modal-status').value;
  const errEl  = document.getElementById('user-modal-error');
  const setErr = m => { errEl.textContent = m; errEl.style.display = ''; };

  if (!name || !email)            return setErr('Name and email are required.');
  if (!/.+@.+\..+/.test(email))   return setErr('Please enter a valid email.');

  if (_editingUserEmail) {
    const user = USERS.find(u => u.email === _editingUserEmail);
    if (!user) return;
    const changes = {};
    if (user.name   !== name)   { changes.name   = {from:user.name,   to:name};   user.name = name; user.initials = _initialsFor(name); }
    if (user.role   !== role)   { changes.role   = {from:user.role,   to:role};   user.role = role; }
    if (user.status !== status) { changes.status = {from:user.status, to:status}; user.status = status; }
    if (Object.keys(changes).length)
      logAudit({ category:'coa', recordType:'User', recordId:email, event:'edited', changes });
  } else {
    if (USERS.find(u => u.email === email)) return setErr('A user with that email already exists.');
    const newUser = { name, email, role, status, initials:_initialsFor(name), color:_colorForUser(USERS.length), lastLogin:'—' };
    USERS.push(newUser);
    logAudit({ category:'coa', recordType:'User', recordId:email, event:'created', note:`Created as ${role}` });
  }
  closeModal('modal-user');
  renderUsersPage();
  showToast(_editingUserEmail ? 'User updated.' : 'User created. Temp password issued.');
}

function toggleUserStatus(email) {
  const user = USERS.find(u => u.email === email);
  if (!user) return;
  if (user.email === _currentUser.email) { showToast("You can't disable your own account.", 'warn'); return; }
  const next = user.status === 'Active' ? 'Inactive' : 'Active';
  logAudit({ category:'coa', recordType:'User', recordId:email, event:next === 'Inactive' ? 'disabled' : 'enabled', changes:{status:{from:user.status, to:next}} });
  user.status = next;
  renderUsersPage();
  showToast(`User ${next === 'Inactive' ? 'disabled' : 'enabled'}.`);
}

function resetUserPassword() {
  if (!_editingUserEmail) return;
  const newPwd = _randomTempPwd();
  document.getElementById('user-modal-pwd').value = newPwd;
  document.getElementById('user-modal-pwd-row').style.display = '';
  logAudit({ category:'coa', recordType:'User', recordId:_editingUserEmail, event:'password_reset' });
  showToast('Temporary password reset.');
}

/* ─── Cancellation requests (Staff → Accountant queue) ───────
   Staff cannot cancel directly. This files a CancelRequest the Accountant
   resolves from Action Items. See docs/roles-permissions.md § Request Cancel.
   ─────────────────────────────────────────────────────────── */

function requestCancellation(lcType, recordId) {
  const reason = prompt('Reason for cancellation request? (required)');
  if (!reason || !reason.trim()) { showToast('Cancellation request needs a reason.', 'warn'); return; }

  // Reject duplicate pending requests for the same target
  const dup = CANCEL_REQUESTS.find(r => r.lcType === lcType && r.recordId === recordId && r.status === 'Pending');
  if (dup) { showToast('A cancellation request is already pending for this record.', 'warn'); return; }

  const req = {
    id: nextCancelReqId(),
    lcType, recordId,
    recordType: { je:'JournalEntry', invoice:'Invoice', bill:'Bill', collection:'Collection', payment:'Payment' }[lcType],
    requestedBy: _currentUser.name,
    requestedAt: _auditTs(),
    reason: reason.trim(),
    status: 'Pending',
  };
  CANCEL_REQUESTS.push(req);
  logAudit({ category:'cancel', recordType:req.recordType, recordId, event:'cancel_requested', note:reason.trim() });
  renderActionsWidget();
  renderActionsPage();
  showToast('Cancellation request sent to accountant.', 'warn');
}

function approveCancelRequest(id) {
  const req = CANCEL_REQUESTS.find(r => r.id === id);
  if (!req || req.status !== 'Pending') return;
  req.status = 'Approved';
  req.decidedBy = _currentUser.name;
  req.decidedAt = _auditTs();
  logAudit({ category:'cancel', recordType:req.recordType, recordId:req.recordId, event:'cancel_request_approved', note:`Request #${req.id}` });
  // Execute the cancellation via the normal lifecycle service
  lcTransition(req.lcType, req.recordId, 'Cancelled');
}

function rejectCancelRequest(id) {
  const req = CANCEL_REQUESTS.find(r => r.id === id);
  if (!req || req.status !== 'Pending') return;
  req.status = 'Rejected';
  req.decidedBy = _currentUser.name;
  req.decidedAt = _auditTs();
  logAudit({ category:'cancel', recordType:req.recordType, recordId:req.recordId, event:'cancel_request_rejected', note:`Request #${req.id}` });
  renderActionsWidget();
  renderActionsPage();
  showToast('Cancellation request rejected.', 'warn');
}

/* ─── Action items (dashboard widget + dedicated page) ────────
   What needs the current user's action right now:
   - Accountant: Submitted records to approve + pending CoA change requests
   - Staff: Drafts they need to complete and submit
   - Viewer: nothing
   ─────────────────────────────────────────────────────────── */

const ACTION_TYPE_ICON = {
  JournalEntry:'📓', Invoice:'💰', Bill:'🧾',
  Collection:'💵', Payment:'💸', AccountChange:'📋', CancelRequest:'🚫',
  VATChange:'📊', WTChange:'💼',
};

// Store fetched action items from backend
let _backendActionItems = [];

async function fetchBackendActionItems() {
  try {
    const response = await fetch('/dashboard/api/action-items');
    if (response.ok) {
      _backendActionItems = await response.json();
    }
  } catch (error) {
    console.error('Failed to fetch action items:', error);
  }
}

function getActionItems() {
  const role = _currentUser?.role;
  if (!role || role === 'Viewer') return [];
  const items = [];

  if (role === 'Accountant') {
    JOURNAL_ENTRIES.filter(j => j.status === 'Submitted').forEach(j =>
      items.push({type:'JournalEntry', id:j.id, desc:j.desc, by:j.submittedBy || j.createdBy, when:j.submittedAt || j.createdAt || j.date, state:'Submitted', recId:j.id, lcType:'je'}));
    INVOICES.filter(i => i.lifecycle === 'Submitted').forEach(i =>
      items.push({type:'Invoice', id:i.num, desc:`${i.customer} — ₱${fmt(i.amount)}`, by:i.submittedBy || i.createdBy, when:i.submittedAt || i.date, state:'Submitted', recId:i.num, lcType:'invoice'}));
    BILLS.filter(b => b.lifecycle === 'Submitted').forEach(b =>
      items.push({type:'Bill', id:b.num, desc:`${b.vendor} — ₱${fmt(b.amount)}`, by:b.submittedBy || b.createdBy, when:b.submittedAt || b.date, state:'Submitted', recId:b.num, lcType:'bill'}));
    COLLECTIONS.filter(c => c.lifecycle === 'Submitted').forEach(c =>
      items.push({type:'Collection', id:c.id, desc:`${c.customer} — ₱${fmt(c.amount)}`, by:c.submittedBy || c.createdBy, when:c.submittedAt || c.date, state:'Submitted', recId:c.id, lcType:'collection'}));
    PAYMENTS.filter(p => p.lifecycle === 'Submitted').forEach(p =>
      items.push({type:'Payment', id:p.id, desc:`${p.vendor} — ₱${fmt(p.amount)}`, by:p.submittedBy || p.createdBy, when:p.submittedAt || p.date, state:'Submitted', recId:p.id, lcType:'payment'}));
    ACCOUNT_CHANGE_REQUESTS.filter(r => r.status === 'Pending').forEach(r =>
      items.push({type:'AccountChange', id:r.accountCode, desc:`${r.accountName} — ${r.reason}`, by:r.submittedBy || '—', when:r.submittedDate, state:'Pending', recId:r.id, isCoa:true}));
    CANCEL_REQUESTS.filter(r => r.status === 'Pending').forEach(r =>
      items.push({type:'CancelRequest', id:r.recordId, desc:`Cancel ${r.recordType} ${r.recordId} — ${r.reason}`, by:r.requestedBy, when:r.requestedAt, state:'Pending', recId:r.id, isCancelReq:true}));

    // Add backend action items (VAT, WT change requests)
    _backendActionItems.forEach(item => items.push(item));
  } else if (role === 'Staff') {
    JOURNAL_ENTRIES.filter(j => j.status === 'Draft').forEach(j =>
      items.push({type:'JournalEntry', id:j.id, desc:j.desc, by:j.createdBy, when:j.createdAt || j.date, state:'Draft', recId:j.id, lcType:'je'}));
    INVOICES.filter(i => i.lifecycle === 'Draft').forEach(i =>
      items.push({type:'Invoice', id:i.num, desc:`${i.customer} — ₱${fmt(i.amount)}`, by:i.createdBy, when:i.createdAt || i.date, state:'Draft', recId:i.num, lcType:'invoice'}));
    BILLS.filter(b => b.lifecycle === 'Draft').forEach(b =>
      items.push({type:'Bill', id:b.num, desc:`${b.vendor} — ₱${fmt(b.amount)}`, by:b.createdBy, when:b.createdAt || b.date, state:'Draft', recId:b.num, lcType:'bill'}));
    COLLECTIONS.filter(c => c.lifecycle === 'Draft').forEach(c =>
      items.push({type:'Collection', id:c.id, desc:`${c.customer} — ₱${fmt(c.amount)}`, by:c.createdBy, when:c.createdAt || c.date, state:'Draft', recId:c.id, lcType:'collection'}));
    PAYMENTS.filter(p => p.lifecycle === 'Draft').forEach(p =>
      items.push({type:'Payment', id:p.id, desc:`${p.vendor} — ₱${fmt(p.amount)}`, by:p.createdBy, when:p.createdAt || p.date, state:'Draft', recId:p.id, lcType:'payment'}));
  }
  return items;
}

function _actionItemButtons(item) {
  const role = _currentUser.role;
  if (item.isCoa) {
    return `<button class="btn btn-sm btn-success" onclick="approveChangeRequest(${item.recId})">Approve</button>
            <button class="btn btn-sm btn-danger" onclick="rejectChangeRequest(${item.recId})">Reject</button>`;
  }
  // VAT and WT change requests - link to review page
  if (item.type === 'VATChange' || item.type === 'WTChange') {
    return `<button class="btn btn-sm btn-primary" onclick="window.location.href='${item.reviewUrl}'">Review</button>`;
  }
  if (item.isCancelReq) {
    return `<button class="btn btn-sm btn-success" onclick="approveCancelRequest(${item.recId})">Approve Cancel</button>
            <button class="btn btn-sm btn-danger" onclick="rejectCancelRequest(${item.recId})">Reject</button>`;
  }
  if (item.state === 'Submitted' && role === 'Accountant') {
    return `<button class="btn btn-sm btn-success" onclick="lcTransition('${item.lcType}','${item.recId}','Approved')">Approve</button>
            <button class="btn btn-sm btn-ghost"   onclick="lcTransition('${item.lcType}','${item.recId}','Draft')">Disapprove</button>
            <button class="btn btn-sm btn-danger"  onclick="lcTransition('${item.lcType}','${item.recId}','Cancelled')">Cancel</button>`;
  }
  if (item.state === 'Draft') {
    const submit = `<button class="btn btn-sm btn-primary" onclick="lcTransition('${item.lcType}','${item.recId}','Submitted')">Submit</button>`;
    const cancel = role === 'Accountant'
      ? `<button class="btn btn-sm btn-danger" onclick="lcTransition('${item.lcType}','${item.recId}','Cancelled')">Cancel</button>`
      : '';
    return submit + cancel;
  }
  return '';
}

function _actionItemRow(item) {
  return `<div class="action-row">
    <div class="action-icon">${ACTION_TYPE_ICON[item.type] || '•'}</div>
    <div class="action-body">
      <div class="action-id">${item.type} · ${item.id}</div>
      <div class="action-desc">${item.desc}</div>
      <div class="action-state"><span class="badge badge-${item.state.toLowerCase()}">${item.state}</span> by ${item.by || '—'} · ${item.when || '—'}</div>
    </div>
    <div class="action-buttons">${_actionItemButtons(item)}</div>
  </div>`;
}

function renderActionsWidget() {
  const list   = document.getElementById('dashboard-actions-list');
  const sub    = document.getElementById('dashboard-actions-sub');
  const badge  = document.getElementById('nav-action-badge');
  if (!list) return;

  const items = getActionItems();
  if (badge) {
    badge.textContent = items.length;
    badge.style.display = items.length ? '' : 'none';
  }
  if (!items.length) {
    list.innerHTML = `<div class="action-empty">🎉 Nothing needs your action right now.</div>`;
    if (sub) sub.textContent = 'All caught up.';
    return;
  }
  if (sub) {
    const role = _currentUser.role;
    sub.textContent = role === 'Accountant'
      ? `${items.length} record${items.length !== 1 ? 's' : ''} awaiting your decision`
      : `${items.length} draft${items.length !== 1 ? 's' : ''} to complete & submit`;
  }
  const top = items.slice(0, 5);
  const moreCount = items.length - top.length;
  list.innerHTML = top.map(_actionItemRow).join('') +
    (moreCount > 0 ? `<div class="action-empty" style="padding:12px;background:#f8fafc;border-top:1px solid var(--border)">+ ${moreCount} more — <a href="#" onclick="navigate('action-items');return false" style="color:var(--blue);font-weight:600">view all →</a></div>` : '');
}

function renderActionsPage() {
  const root = document.getElementById('actions-page-content');
  const meta = document.getElementById('actions-page-meta');
  if (!root) return;

  const typeFlt  = document.getElementById('actions-filter-type')?.value || '';
  const stateFlt = document.getElementById('actions-filter-state')?.value || '';

  let items = getActionItems();
  if (typeFlt)  items = items.filter(i => i.type === typeFlt);
  if (stateFlt) items = items.filter(i => i.state === stateFlt);

  if (meta) meta.textContent = `${items.length} item${items.length !== 1 ? 's' : ''}`;

  if (!items.length) {
    root.innerHTML = `<div class="card"><div class="action-empty" style="padding:40px">🎉 Nothing matches the filter.</div></div>`;
    return;
  }

  // Group by record type
  const groups = {};
  items.forEach(i => { (groups[i.type] = groups[i.type] || []).push(i); });

  root.innerHTML = Object.entries(groups).map(([type, list]) => `
    <div class="card mb-4">
      <div class="action-section-title">${ACTION_TYPE_ICON[type] || ''} ${type} — ${list.length}</div>
      ${list.map(_actionItemRow).join('')}
    </div>`).join('');
}

/* Render the audit footprint block for a record. See docs/audit-trail.md § 4.1.
   `rec` is the JS object; `recordType`/`recordId` are used for the "View full history" link. */
function renderAuditFootprint(rec, recordType, recordId) {
  const rows = [
    ['Created',   rec.createdBy,   rec.createdAt],
    ['Submitted', rec.submittedBy, rec.submittedAt],
    ['Approved',  rec.approvedBy,  rec.approvedAt],
    ['Cancelled', rec.cancelledBy, rec.cancelledAt],
  ].filter(r => r[1]);

  const body = rows.length
    ? rows.map(([label, who, when]) => `
        <div class="audit-row">
          <span>${label} by <span class="audit-who">${who}</span></span>
          <span class="audit-when">${when || ''}</span>
        </div>`).join('')
    : `<div class="audit-row audit-empty">No audit entries yet</div>`;

  return `<div class="audit-footprint">
    <div class="form-label">Audit Footprint</div>
    ${body}
    <div class="audit-actions">
      <button class="btn btn-ghost btn-sm" onclick="openRecordHistory('${recordType}','${recordId}')">View full history →</button>
    </div>
  </div>`;
}

function openRecordHistory(recordType, recordId) {
  const entries = AUDIT_LOG.filter(e => e.recordType === recordType && e.recordId === recordId);
  const rows = entries.length
    ? entries.map(e => {
        const label = AUDIT_CAT_LABEL[e.category] || e.category;
        const evCol = e.fromState ? `<span style="color:var(--text-3)">${e.fromState} → ${e.toState}</span>` : (e.event || '—');
        return `<tr>
          <td class="audit-when">${e.ts}</td>
          <td><span class="badge badge-cat-${e.category}">${label}</span></td>
          <td>${evCol}</td>
          <td>${e.actor}</td>
          <td>${e.note || (e.changes ? `<code class="text-sm">${JSON.stringify(e.changes)}</code>` : '')}</td>
        </tr>`;
      }).join('')
    : `<tr><td colspan="5" style="text-align:center;color:var(--text-3);padding:16px">No audit entries for this record</td></tr>`;

  const historyHtml = `
    <div class="overlay open" id="modal-record-history" onclick="if(event.target===this)closeModal('modal-record-history')">
      <div class="modal modal-lg">
        <div class="modal-header">
          <span class="modal-title">Audit History — ${recordType} ${recordId}</span>
          <button class="modal-close" onclick="closeModal('modal-record-history')">✕</button>
        </div>
        <div class="modal-body">
          <div style="border:1px solid var(--border);border-radius:6px;overflow:hidden">
            <table>
              <thead><tr><th style="width:140px">Timestamp</th><th style="width:100px">Category</th><th>Event</th><th style="width:140px">Actor</th><th>Note / Changes</th></tr></thead>
              <tbody>${rows}</tbody>
            </table>
          </div>
        </div>
        <div class="modal-footer">
          <button class="btn btn-secondary" onclick="closeModal('modal-record-history')">Close</button>
        </div>
      </div>
    </div>`;
  // Append to body; remove on close
  document.body.insertAdjacentHTML('beforeend', historyHtml);
}

function openInvoiceDetail(num) {
  const inv = INVOICES.find(i => i.num === num);
  if (!inv) return;

  const fmtD    = d => d ? new Date(d + 'T00:00').toLocaleDateString('en-PH', { month:'short', day:'numeric', year:'numeric' }) : '—';
  const cust    = CUSTOMERS.find(c => c.name === inv.customer);
  const lc      = inv.lifecycle || 'Approved';
  const balance = inv.amount - inv.paid;
  const payments = COLLECTIONS.filter(c =>
    (c.lifecycle || 'Approved') !== 'Cancelled' &&
    (c.invoiceLines || []).some(l => l.invoiceNum === num)
  );

  document.getElementById('inv-detail-title').textContent       = `Invoice — ${inv.num}`;
  document.getElementById('inv-detail-num').textContent         = inv.num;
  document.getElementById('inv-detail-customer').textContent    = inv.customer;
  document.getElementById('inv-detail-customer-meta').textContent = cust
    ? [cust.contact, cust.phone, cust.email].filter(Boolean).join(' • ')
    : '—';
  document.getElementById('inv-detail-date').textContent    = fmtD(inv.date);
  document.getElementById('inv-detail-due').textContent     = fmtD(inv.due);
  document.getElementById('inv-detail-amount').textContent  = fmt(inv.amount);
  document.getElementById('inv-detail-paid').textContent    = fmt(inv.paid);
  document.getElementById('inv-detail-balance').textContent = fmt(balance);

  const badgesEl = document.getElementById('inv-detail-badges');
  const payBadge = (lc === 'Approved' || lc === 'Submitted') ? lcPayStatus(inv) : '';
  badgesEl.innerHTML = lcBadge(lc) + payBadge;

  const dueEl = document.getElementById('inv-detail-due');
  dueEl.style.color = (lc === 'Approved' && inv.due < TODAY_STR && inv.paid < inv.amount) ? 'var(--red)' : '';

  const tbody = document.getElementById('inv-detail-payments');
  if (payments.length === 0) {
    tbody.innerHTML = `<tr><td colspan="5" style="text-align:center;color:var(--text-3);padding:16px">No payments recorded for this invoice</td></tr>`;
  } else {
    tbody.innerHTML = payments.map(c => {
      const line = c.invoiceLines.find(l => l.invoiceNum === num);
      return `<tr>
        <td><code>${c.id}</code></td>
        <td>${fmtD(c.date)}</td>
        <td>${c.method || '—'}</td>
        <td>${c.ref || '—'}</td>
        <td class="num">${fmt(line.amount)}</td>
      </tr>`;
    }).join('');
  }

  document.getElementById('inv-detail-audit').innerHTML = renderAuditFootprint(inv, 'Invoice', inv.num);
  openModal('modal-inv-detail');
}

/* ─── AP Bills render ────────────────────────────────────────── */
function renderBills() {
  const flt   = document.getElementById('bill-filter-status')?.value || '';
  const tbody = document.getElementById('ap-bills-tbody');
  const tfoot = document.getElementById('ap-bills-tfoot');
  if (!tbody) return;

  const hits = BILLS.filter(b => !flt || (b.lifecycle || 'Approved') === flt);
  const role = _currentUser.role;
  const fmtD = d => d ? new Date(d + 'T00:00').toLocaleDateString('en-PH', { month:'short', day:'numeric', year:'numeric' }) : '—';

  tbody.innerHTML = hits.map(b => {
    const balance = b.amount - b.paid;
    const lc = b.lifecycle || 'Approved';
    const btns = [];
    if (role !== 'Viewer') {
      if (lc === 'Draft') {
        btns.push(`<button class="btn btn-sm btn-primary" onclick="lcTransition('bill','${b.num}','Submitted')">Submit</button>`);
        if (role === 'Accountant')
          btns.push(`<button class="btn btn-sm btn-danger" onclick="lcTransition('bill','${b.num}','Cancelled')">Cancel</button>`);
      } else if (lc === 'Submitted') {
        if (role === 'Accountant') {
          btns.push(`<button class="btn btn-sm btn-success" onclick="lcTransition('bill','${b.num}','Approved')">Approve</button>`);
          btns.push(`<button class="btn btn-sm btn-ghost"   onclick="lcTransition('bill','${b.num}','Draft')">Disapprove</button>`);
          btns.push(`<button class="btn btn-sm btn-danger"  onclick="lcTransition('bill','${b.num}','Cancelled')">Cancel</button>`);
        } else {
          btns.push(`<button class="btn btn-sm btn-ghost" onclick="requestCancellation('bill','${b.num}')">Req. Cancel</button>`);
        }
      } else if (lc === 'Approved') {
        if (b.paid < b.amount)
          btns.push(`<button class="btn btn-sm btn-primary" onclick="openPayBillModal('${b.num}','${b.vendor.replace(/'/g,"\\'")}')" >Pay</button>`);
        if (role === 'Accountant')
          btns.push(`<button class="btn btn-sm btn-danger" onclick="lcTransition('bill','${b.num}','Cancelled')">Cancel</button>`);
        else
          btns.push(`<button class="btn btn-sm btn-ghost" onclick="requestCancellation('bill','${b.num}')">Req. Cancel</button>`);
      }
    }
    const dueStyle = lc === 'Approved' && b.due < TODAY_STR && b.paid < b.amount ? ' style="color:var(--red);font-weight:700"' : '';
    return `<tr>
      <td><code style="cursor:pointer;color:var(--blue)" onclick="openBillDetail('${b.num}')">${b.num}</code></td>
      <td>${b.vendor}</td>
      <td>${fmtD(b.date)}</td>
      <td${dueStyle}>${fmtD(b.due)}</td>
      <td class="num">${fmt(b.amount)}</td>
      <td class="num">${b.paid > 0 ? fmt(b.paid) : '—'}</td>
      <td class="num">${balance > 0 ? fmt(balance) : '—'}</td>
      <td>${lcBadge(lc)}</td>
      <td>${lc === 'Approved' || lc === 'Submitted' ? billPayStatus(b) : '—'}</td>
      <td style="white-space:nowrap;display:flex;gap:4px;flex-wrap:wrap"><button class="btn btn-sm btn-ghost" onclick="openBillDetail('${b.num}')">View</button>${btns.join('')}</td>
    </tr>`;
  }).join('') || `<tr><td colspan="10" style="text-align:center;color:var(--text-3);padding:24px">No vouchers match the filter</td></tr>`;

  const totAmt  = hits.reduce((s, b) => s + b.amount, 0);
  const totPaid = hits.reduce((s, b) => s + b.paid,   0);
  const totBal  = totAmt - totPaid;
  tfoot.innerHTML = `<tr class="tfoot-row">
    <td colspan="4" class="fw-7">${hits.length} voucher${hits.length !== 1 ? 's' : ''}</td>
    <td class="num fw-7">${fmt(totAmt)}</td>
    <td class="num fw-7">${totPaid > 0 ? fmt(totPaid) : '—'}</td>
    <td class="num fw-7">${totBal > 0 ? fmt(totBal) : '—'}</td>
    <td colspan="3"></td>
  </tr>`;
}

function openBillDetail(num) {
  const bill = BILLS.find(b => b.num === num);
  if (!bill) return;

  const fmtD     = d => d ? new Date(d + 'T00:00').toLocaleDateString('en-PH', { month:'short', day:'numeric', year:'numeric' }) : '—';
  const vend     = VENDORS.find(v => v.name === bill.vendor);
  const lc       = bill.lifecycle || 'Approved';
  const balance  = bill.amount - bill.paid;
  const payments = PAYMENTS.filter(p =>
    (p.lifecycle || 'Approved') !== 'Cancelled' &&
    (p.billLines || []).some(l => l.billNum === num)
  );

  document.getElementById('bill-detail-title').textContent       = `Bill / Voucher — ${bill.num}`;
  document.getElementById('bill-detail-num').textContent         = bill.num;
  document.getElementById('bill-detail-vendor').textContent      = bill.vendor;
  document.getElementById('bill-detail-vendor-meta').textContent = vend
    ? [vend.contact, vend.phone, vend.email].filter(Boolean).join(' • ')
    : '—';
  document.getElementById('bill-detail-date').textContent    = fmtD(bill.date);
  document.getElementById('bill-detail-due').textContent     = fmtD(bill.due);
  document.getElementById('bill-detail-amount').textContent  = fmt(bill.amount);
  document.getElementById('bill-detail-paid').textContent    = fmt(bill.paid);
  document.getElementById('bill-detail-balance').textContent = fmt(balance);

  const badgesEl = document.getElementById('bill-detail-badges');
  const payBadge = (lc === 'Approved' || lc === 'Submitted') ? billPayStatus(bill) : '';
  badgesEl.innerHTML = lcBadge(lc) + payBadge;

  const dueEl = document.getElementById('bill-detail-due');
  dueEl.style.color = (lc === 'Approved' && bill.due < TODAY_STR && bill.paid < bill.amount) ? 'var(--red)' : '';

  const tbody = document.getElementById('bill-detail-payments');
  if (payments.length === 0) {
    tbody.innerHTML = `<tr><td colspan="5" style="text-align:center;color:var(--text-3);padding:16px">No payments recorded for this bill</td></tr>`;
  } else {
    tbody.innerHTML = payments.map(p => {
      const line = p.billLines.find(l => l.billNum === num);
      return `<tr>
        <td><code>${p.id}</code></td>
        <td>${fmtD(p.date)}</td>
        <td>${p.method || '—'}</td>
        <td>${p.ref || '—'}</td>
        <td class="num">${fmt(line.amount)}</td>
      </tr>`;
    }).join('');
  }

  document.getElementById('bill-detail-audit').innerHTML = renderAuditFootprint(bill, 'Bill', bill.num);
  openModal('modal-bill-detail');
}

/* ─── AR Receipts render ─────────────────────────────────────── */
function renderCollections() {
  const flt   = document.getElementById('collect-filter-status')?.value || '';
  const tbody = document.getElementById('ar-receipts-tbody');
  const tfoot = document.getElementById('ar-receipts-tfoot');
  if (!tbody) return;

  const hits = COLLECTIONS.filter(c => !flt || c.lifecycle === flt);
  const role = _currentUser.role;
  const fmtD = d => d ? new Date(d + 'T00:00').toLocaleDateString('en-PH', { month:'short', day:'numeric', year:'numeric' }) : '—';

  tbody.innerHTML = hits.map(c => {
    const lc   = c.lifecycle || 'Draft';
    const invs = (c.invoiceLines || []).map(l => `<code style="font-size:11px">${l.invoiceNum}</code>`).join(' ');
    const btns = [];
    if (role !== 'Viewer') {
      if (lc === 'Draft') {
        btns.push(`<button class="btn btn-sm btn-primary" onclick="lcTransition('collection','${c.id}','Submitted')">Submit</button>`);
        if (role === 'Accountant')
          btns.push(`<button class="btn btn-sm btn-danger" onclick="lcTransition('collection','${c.id}','Cancelled')">Cancel</button>`);
      } else if (lc === 'Submitted') {
        if (role === 'Accountant') {
          btns.push(`<button class="btn btn-sm btn-success" onclick="lcTransition('collection','${c.id}','Approved')">Approve</button>`);
          btns.push(`<button class="btn btn-sm btn-ghost"   onclick="lcTransition('collection','${c.id}','Draft')">Disapprove</button>`);
        } else {
          btns.push(`<button class="btn btn-sm btn-ghost" onclick="requestCancellation('collection','${c.id}')">Req. Cancel</button>`);
        }
      } else if (lc === 'Approved' && role === 'Accountant') {
        btns.push(`<button class="btn btn-sm btn-danger" onclick="lcTransition('collection','${c.id}','Cancelled')">Cancel</button>`);
      }
    }
    return `<tr>
      <td><code>${c.id}</code></td>
      <td>${c.customer}</td>
      <td>${fmtD(c.date)}</td>
      <td>${invs || '—'}</td>
      <td class="num cr">${fmt(c.amount)}</td>
      <td>${c.method}</td>
      <td>${lcBadge(lc)}</td>
      <td style="white-space:nowrap;display:flex;gap:4px;flex-wrap:wrap">${btns.join('')}</td>
    </tr>`;
  }).join('') || `<tr><td colspan="8" style="text-align:center;color:var(--text-3);padding:24px">No receipts found</td></tr>`;

  const total = hits.reduce((s, c) => s + c.amount, 0);
  tfoot.innerHTML = `<tr class="tfoot-row">
    <td colspan="4" class="fw-7">${hits.length} receipt${hits.length !== 1 ? 's' : ''}</td>
    <td class="num fw-7 cr">${fmt(total)}</td>
    <td colspan="3"></td>
  </tr>`;
}

/* ─── AP Payments render ─────────────────────────────────────── */
function renderPayments() {
  const flt   = document.getElementById('payment-filter-status')?.value || '';
  const tbody = document.getElementById('ap-payments-tbody');
  const tfoot = document.getElementById('ap-payments-tfoot');
  if (!tbody) return;

  const hits = PAYMENTS.filter(p => !flt || p.lifecycle === flt);
  const role = _currentUser.role;
  const fmtD = d => d ? new Date(d + 'T00:00').toLocaleDateString('en-PH', { month:'short', day:'numeric', year:'numeric' }) : '—';

  tbody.innerHTML = hits.map(p => {
    const lc   = p.lifecycle || 'Draft';
    const bills = (p.billLines || []).map(l => `<code style="font-size:11px">${l.billNum}</code>`).join(' ');
    const btns = [];
    if (role !== 'Viewer') {
      if (lc === 'Draft') {
        btns.push(`<button class="btn btn-sm btn-primary" onclick="lcTransition('payment','${p.id}','Submitted')">Submit</button>`);
        if (role === 'Accountant')
          btns.push(`<button class="btn btn-sm btn-danger" onclick="lcTransition('payment','${p.id}','Cancelled')">Cancel</button>`);
      } else if (lc === 'Submitted') {
        if (role === 'Accountant') {
          btns.push(`<button class="btn btn-sm btn-success" onclick="lcTransition('payment','${p.id}','Approved')">Approve</button>`);
          btns.push(`<button class="btn btn-sm btn-ghost"   onclick="lcTransition('payment','${p.id}','Draft')">Disapprove</button>`);
        } else {
          btns.push(`<button class="btn btn-sm btn-ghost" onclick="requestCancellation('payment','${p.id}')">Req. Cancel</button>`);
        }
      } else if (lc === 'Approved' && role === 'Accountant') {
        btns.push(`<button class="btn btn-sm btn-danger" onclick="lcTransition('payment','${p.id}','Cancelled')">Cancel</button>`);
      }
    }
    return `<tr>
      <td><code>${p.id}</code></td>
      <td>${p.vendor}</td>
      <td>${fmtD(p.date)}</td>
      <td>${bills || '—'}</td>
      <td class="num dr">${fmt(p.amount)}</td>
      <td>${p.method}</td>
      <td>${lcBadge(lc)}</td>
      <td style="white-space:nowrap;display:flex;gap:4px;flex-wrap:wrap">${btns.join('')}</td>
    </tr>`;
  }).join('') || `<tr><td colspan="8" style="text-align:center;color:var(--text-3);padding:24px">No payments found</td></tr>`;

  const total = hits.reduce((s, p) => s + p.amount, 0);
  tfoot.innerHTML = `<tr class="tfoot-row">
    <td colspan="4" class="fw-7">${hits.length} payment${hits.length !== 1 ? 's' : ''}</td>
    <td class="num fw-7 dr">${fmt(total)}</td>
    <td colspan="3"></td>
  </tr>`;
}

/* ─── Init ─────────────────────────────────────────────────── */
// Seed audit footprint on existing records so detail modals have something to show.
// Real implementation persists these to the DB on every transition.
function _seedAuditFootprint() {
  const setApproved = (r, createdBy, createdAt, approver) => {
    r.createdBy   = createdBy;
    r.createdAt   = createdAt;
    r.submittedBy = createdBy;
    r.submittedAt = createdAt;
    r.approvedBy  = approver || 'Maria Santos';
    r.approvedAt  = (r.date || createdAt) + ' 14:30';
  };
  JOURNAL_ENTRIES.forEach(j => {
    if (j.status === 'Approved') setApproved(j, 'Juan Dela Cruz', (j.date || '2026-05-01') + ' 09:00');
    else { j.createdBy = 'Juan Dela Cruz'; j.createdAt = (j.date || '2026-05-30') + ' 10:00'; }
  });
  INVOICES.forEach(i    => setApproved(i, 'Juan Dela Cruz', (i.date || '2026-05-01') + ' 09:00'));
  BILLS.forEach(b       => setApproved(b, 'Juan Dela Cruz', (b.date || '2026-05-01') + ' 09:00'));
  COLLECTIONS.forEach(c => setApproved(c, 'Juan Dela Cruz', (c.date || '2026-05-28') + ' 09:00'));
  PAYMENTS.forEach(p    => setApproved(p, 'Juan Dela Cruz', (p.date || '2026-05-27') + ' 09:00'));
}

document.addEventListener('DOMContentLoaded', async () => {
  _seedAuditFootprint();
  // Fetch backend action items first
  await fetchBackendActionItems();
  navigate('dashboard');
  renderCOA('All');
  renderPendingApprovals();
  resetJEForm();
  renderCustomers();
  renderVendors();
  renderJournalEntries();
  renderDashboard();
  renderTrialBalance();
  renderIncomeStatement();
  renderBalanceSheet();
  renderSLSP();
  renderAlphalist();
  renderAuditLog();
  renderActionsWidget();
  renderActionsPage();
  renderUsersPage();
  renderARAging();
  renderAPAging();
  render2550Q();
  render0619E();
  render1601EQ();
  render2307List();
  renderInvoices();
  renderBills();
  renderCollections();
  renderPayments();

  // Init user switcher display
  const avatarEl = document.getElementById('user-avatar');
  if (avatarEl) { avatarEl.textContent = _currentUser.initials; avatarEl.style.background = _currentUser.color; }
  updateUIForRole();

  // Topbar date
  const topbarDate = document.getElementById('topbar-date');
  if (topbarDate)
    topbarDate.textContent = new Date('2026-05-30T00:00:00').toLocaleDateString('en-PH', { year:'numeric', month:'long', day:'numeric' });

  // Env badge init
  const ENVS = [
    { key: 'live', label: 'Live',    cls: 'env-live' },
    { key: 'test', label: 'Testing', cls: 'env-test' },
    { key: 'dev',  label: 'Dev',     cls: 'env-dev'  },
  ];
  let _envIdx = 0;
  function applyEnv() {
    const env   = ENVS[_envIdx];
    const badge = document.getElementById('env-badge');
    badge.className = 'live-badge ' + env.cls;
    document.getElementById('env-label').textContent = env.label;
  }
  window.cycleEnv = function() {
    _envIdx = (_envIdx + 1) % ENVS.length;
    applyEnv();
  };
  applyEnv();

  // COA search
  document.getElementById('coa-search')?.addEventListener('input', e => {
    const q = e.target.value.toLowerCase();
    document.querySelectorAll('#coa-tbody tr:not(.group-header)').forEach(tr => {
      tr.style.display = !q || tr.textContent.toLowerCase().includes(q) ? '' : 'none';
    });
    document.querySelectorAll('#coa-tbody tr.group-header').forEach(gh => {
      let next = gh.nextElementSibling;
      let hasVisible = false;
      while (next && !next.classList.contains('group-header')) {
        if (next.style.display !== 'none') { hasVisible = true; break; }
        next = next.nextElementSibling;
      }
      gh.style.display = hasVisible ? '' : 'none';
    });
  });

  const ledgerWrap = document.getElementById('ledger-acct-wrap');
  if (ledgerWrap) {
    const ledgerInput = createSearchSelectTag(ledgerWrap, ACCOUNTS.filter(a => !a.isMain), {
      inputClass: 'input',
      placeholder: 'Search account…',
      onSelect: (a) => renderLedger(a.code),
    });
    const defaultAcct = ACCOUNTS.find(a => a.code === '1003');
    ledgerInput.value        = `${defaultAcct.code} — ${defaultAcct.name}`;
    ledgerInput.dataset.code = defaultAcct.code;
    renderLedger('1003');
  }

  document.getElementById('je-date').valueAsDate = new Date();
  document.getElementById('inv-date').valueAsDate = new Date();
  document.getElementById('bill-date').valueAsDate = new Date();

  createSearchSelectTag(
    document.getElementById('je-party-customer-wrap'),
    CUSTOMERS,
    { inputClass: 'form-control', placeholder: 'Search customer…' }
  );
  createSearchSelectTag(
    document.getElementById('je-party-vendor-wrap'),
    VENDORS,
    { inputClass: 'form-control', placeholder: 'Search vendor…' }
  );

  createSearchSelectTag(
    document.getElementById('inv-customer-wrap'),
    CUSTOMERS,
    {
      inputClass: 'form-control',
      placeholder: 'Search customer…',
      actions: [{ label: '＋ Add Customer', onAction: () => openModal('modal-add-customer') }],
      onSelect: customer => {
        invActiveCustomer = customer;
        applyCustomerDefaults(customer);
      },
    }
  );
  createSearchSelectTag(
    document.getElementById('bill-vendor-wrap'),
    VENDORS,
    {
      inputClass: 'form-control',
      placeholder: 'Search vendor…',
      actions: [{ label: '＋ Add Vendor', onAction: () => openModal('modal-add-vendor') }],
      onSelect: vendor => {
        billActiveVendor = vendor;
        applyVendorDefaults(vendor);
      },
    }
  );
  createSearchSelectTag(
    document.getElementById('pay-bill-acct-wrap'),
    ACCOUNTS.filter(a => a.parent === '1000'),
    { inputClass: 'form-control', placeholder: 'Search account…', onSelect: () => buildPayEntry() }
  );
  createSearchSelectTag(
    document.getElementById('collect-acct-wrap'),
    ACCOUNTS.filter(a => a.parent === '1000'),
    { inputClass: 'form-control', placeholder: 'Search account…', onSelect: () => buildCollectEntry() }
  );
});
