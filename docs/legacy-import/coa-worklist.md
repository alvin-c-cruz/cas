# COA Rebuild Worklist

_Source snapshot: 356 accounts (16 groups, 340 leaves). Names shown proper-cased; tweak per account before Save._

## Group headers — create first (you Save each)

Group codes are 5-digit, zero-padded (`+000`). Classification is a best-guess
for Asset/Liability groups — adjust live. Description: concise one-line purpose
(generated per account at entry).

| ✔ | Code | Name (proper-cased) | Type | Normal balance | Classification |
|---|------|---------------------|------|----------------|----------------|
| ☑ | `11000` | Cash and Cash Equivalents | Asset | debit | Current |
| ☐ | `12000` | Trade Receivable | Asset | debit | Current |
| ☐ | `13000` | Other Current Assets | Asset | debit | Current |
| ☐ | `14000` | Fixed Assets | Asset | debit | Non-Current |
| ☐ | `15000` | Other Assets | Asset | debit | Non-Current |
| ☐ | `21000` | Accounts Payable | Liability | credit | Current |
| ☐ | `22000` | Other Current Liabilities | Liability | credit | Current |
| ☐ | `23000` | Other Liabilities | Liability | credit | Non-Current |
| ☐ | `31000` | Stockholder's Equity | Equity | credit | — |
| ☐ | `41000` | Revenues | Revenue | credit | — |
| ☐ | `51000` | Other Income (Group) | Revenue | credit | — |
| ☐ | `61000` | Direct Materials | Expense | debit | — |
| ☐ | `62000` | Direct Labor | Expense | debit | — |
| ☐ | `63000` | Factory Overhead | Expense | debit | — |
| ☐ | `64000` | Selling Expenses | Expense | debit | — |
| ☐ | `65000` | Administrative Expenses | Expense | debit | — |

> **Leaf renumber exception:** `12000` "Construction in Progress" is being
> recoded to sit after the in-transit accounts (`11701-*`/`11702-*`) — proposed
> `11703` — to free `12000` for the Trade Receivable group.

## Leaves — create after groups, ascending code (you pick parent + Save)

| ✔ | Code | Name (proper-cased) | Old group (hint) |
|---|------|---------------------|------------------|
| ☐ | `10201` | Accounts Receivable-Trade | 12 Trade Receivable |
| ☐ | `10212` | Creditable Withholding Tax | 15 Other Assets |
| ☐ | `11101` | Cash on Hand/Cash Sales | 11 Cash and Cash Equivalents |
| ☐ | `11102` | Cash on Hand - Dollar | 11 Cash and Cash Equivalents |
| ☐ | `11103` | China Bank $ 520000577 | 11 Cash and Cash Equivalents |
| ☐ | `11104` | BPI-00008-85 | 11 Cash and Cash Equivalents |
| ☐ | `11105` | China Bank-361-0 | 11 Cash and Cash Equivalents |
| ☐ | `11106` | China Bank 2581-4 | 11 Cash and Cash Equivalents |
| ☐ | `11107` | China Bank-302311-8 | 11 Cash and Cash Equivalents |
| ☐ | `11108` | China Bank-280271-8 | 11 Cash and Cash Equivalents |
| ☐ | `11109` | Century Savings Bank-0112-7 | 11 Cash and Cash Equivalents |
| ☐ | `11110` | Revolving Fund | 11 Cash and Cash Equivalents |
| ☐ | `11111` | Petty Cash Fund | 11 Cash and Cash Equivalents |
| ☐ | `11112` | Cash in Bank - Time Deposit (RCC) | 11 Cash and Cash Equivalents |
| ☐ | `11202` | Allowance for Bad Debts | 13 Other Current Assets |
| ☐ | `11203` | Accounts Receivable-PDC | 12 Trade Receivable |
| ☐ | `11204` | Accounts Receivable-Others | 12 Trade Receivable |
| ☐ | `11205` | Accounts Receivable Others-RCC | 12 Trade Receivable |
| ☐ | `11206` | Loan Receivable | 13 Other Current Assets |
| ☐ | `11207` | Deposit/Advances to Supplier | 13 Other Current Assets |
| ☐ | `11208` | Container Deposit | 13 Other Current Assets |
| ☐ | `11209` | Advances to Officers | 13 Other Current Assets |
| ☐ | `11210` | Advances to Employees | 13 Other Current Assets |
| ☐ | `11301` | Raw Materials Inventory-Tincan | 13 Other Current Assets |
| ☐ | `11302` | Finished Goods Inventory-Tincan | 13 Other Current Assets |
| ☐ | `11303` | Work in Process Inventory-Tincan | 13 Other Current Assets |
| ☐ | `11304` | Other Raw Materials Inventory-Tincan | 13 Other Current Assets |
| ☐ | `11401` | Raw Materials Inventory - Plastic | 13 Other Current Assets |
| ☐ | `11402` | Finished Goods Inventory - Plastic | 13 Other Current Assets |
| ☐ | `11403` | Work in Process Inventory - Plastic | 13 Other Current Assets |
| ☐ | `11404` | Other Raw Materials Inventory-Plastic | 13 Other Current Assets |
| ☐ | `11501-P` | Maintenance Supplies Inventory - Plastic | 13 Other Current Assets |
| ☐ | `11501-T` | Maintenance Supplies Inventory - Tincan | 13 Other Current Assets |
| ☐ | `11502` | Factory Supplies Inventory | 13 Other Current Assets |
| ☐ | `11503` | Factory Supplies Inventory - Tincan | 13 Other Current Assets |
| ☐ | `11504` | Factory Supplies Inventory - Plastic | 13 Other Current Assets |
| ☐ | `11601` | Prepaid Expenses | 13 Other Current Assets |
| ☐ | `11602` | Prepaid Interest | 13 Other Current Assets |
| ☐ | `11701` | Raw Materials in Transit - Tincan | 13 Other Current Assets |
| ☐ | `11701-2` | Raw Materials in Transit - Plastic | 13 Other Current Assets |
| ☐ | `11701-3` | Other Raw Materials in Transit - Tincan | 13 Other Current Assets |
| ☐ | `11701-4` | Other Raw Materials in Transit - Plastic | 13 Other Current Assets |
| ☐ | `11702` | Machinery in Transit - Tincan | 13 Other Current Assets |
| ☐ | `11702-2` | Machinery in Transit - Plastic | 13 Other Current Assets |
| ☐ | `11702-3` | Machinery Spare Parts in Transit - Tincan | 13 Other Current Assets |
| ☐ | `11702-4` | Machinery Spare Parts in Transit - Plastic | 13 Other Current Assets |
| ☐ | `12000` | Construction in Progress | 14 Fixed Assets |
| ☐ | `12101` | Land | 14 Fixed Assets |
| ☐ | `12201` | Office Fcty - Taguig | 14 Fixed Assets |
| ☐ | `12202` | Furniture, Fixtures & Eqpt. | 14 Fixed Assets |
| ☐ | `12203` | Transportation Equipment | 14 Fixed Assets |
| ☐ | `12204` | Mach & Eqpt - Tincan | 14 Fixed Assets |
| ☐ | `12205` | Mach & Eqpt - Plastic | 14 Fixed Assets |
| ☐ | `12206` | Machinery Spare Parts - Tincan | 14 Fixed Assets |
| ☐ | `12207` | Machinery Spare Parts - Plastic | 14 Fixed Assets |
| ☐ | `12208` | Motors & Accessories | 14 Fixed Assets |
| ☐ | `12209` | Molds & Dies - Tincan | 14 Fixed Assets |
| ☐ | `12210` | Molds & Dies - Plastic | 14 Fixed Assets |
| ☐ | `12211` | Tools | 14 Fixed Assets |
| ☐ | `12212` | Intangibles | 14 Fixed Assets |
| ☐ | `12301` | Acc. Dep'n-Office Fcty Q.C. (Taguig) | 14 Fixed Assets |
| ☐ | `12302` | Acc. Dep'n-Furnitures, Fixt. & Eqpt. | 14 Fixed Assets |
| ☐ | `12303` | Acc. Dep'n -Transp Eqpt | 14 Fixed Assets |
| ☐ | `12304` | Acc. Dep'n-Mach & Eqpt - Tincan | 14 Fixed Assets |
| ☐ | `12305` | Acc. Dep'n-Mach & Eqpt - Plastic | 14 Fixed Assets |
| ☐ | `12306` | Acc. Dep'n-Mach Spare Parts - Tincan | 14 Fixed Assets |
| ☐ | `12307` | Acc. Dep'n-Mach Spare Parts - Plastic | 14 Fixed Assets |
| ☐ | `12308` | Acc. Dep'n-Motors & Accessories | 14 Fixed Assets |
| ☐ | `12309` | Acc. Dep'n-Molds & Dies - Tincan | 14 Fixed Assets |
| ☐ | `12310` | Acc. Dep'n-Molds & Dies - Plastic | 14 Fixed Assets |
| ☐ | `12311` | Acc. Dep'n -Tools | 14 Fixed Assets |
| ☐ | `12312` | Acc. Dep'n-Intangibles | 14 Fixed Assets |
| ☐ | `12401` | Investment-Various | 15 Other Assets |
| ☐ | `12402` | Investment-Landmark Holdings | 15 Other Assets |
| ☐ | `12403` | Investment-Sanican | 15 Other Assets |
| ☐ | `12404` | Investment-Dowell Treasury | 15 Other Assets |
| ☐ | `12502` | Income Tax Over Paid | 15 Other Assets |
| ☐ | `12601` | Input Tax - Capital Goods | 15 Other Assets |
| ☐ | `12602` | Input Tax - Domestic | 15 Other Assets |
| ☐ | `12603` | Input Tax - Services | 15 Other Assets |
| ☐ | `12604` | Input Tax - Importation | 15 Other Assets |
| ☐ | `12605` | Input Tax Credit | 15 Other Assets |
| ☐ | `12606` | Deferred Input Tax | 15 Other Assets |
| ☐ | `20101` | Accounts Payable-Trade | 21 Accounts Payable |
| ☐ | `20301` | Withholding  Tax Payable-Suppliers | 23 Other Liabilities |
| ☐ | `21102` | Accounts Payable-RLMC | 21 Accounts Payable |
| ☐ | `21103` | Accounts Payable-Others | 22 Other Current Liabilities |
| ☐ | `21104` | Accounts Payable Others-RCC | 22 Other Current Liabilities |
| ☐ | `21201` | Trust Receipts Payable | 22 Other Current Liabilities |
| ☐ | `21301` | Loan Payable | 22 Other Current Liabilities |
| ☐ | `21302` | Julia Chiu | 22 Other Current Liabilities |
| ☐ | `21303` | Change Check | 22 Other Current Liabilities |
| ☐ | `21701` | Customer's Deposit | 22 Other Current Liabilities |
| ☐ | `21801` | Accrued Expenses Payable | 22 Other Current Liabilities |
| ☐ | `22100` | Income Tax Payable | 22 Other Current Liabilities |
| ☐ | `22101` | Income Tax Payable - Tincan | 23 Other Liabilities |
| ☐ | `22102` | Income Tax Payable - Plastic | 23 Other Liabilities |
| ☐ | `22103` | VAT Payable | 23 Other Liabilities |
| ☐ | `22103-1` | Output Tax | 23 Other Liabilities |
| ☐ | `22104` | Withholding Tax Payable-Employees | 23 Other Liabilities |
| ☐ | `22105-1` | Withholding  Tax Payable-Suppliers - 1% | 23 Other Liabilities |
| ☐ | `22105-2` | Withholding  Tax Payable-Suppliers - 2% | 23 Other Liabilities |
| ☐ | `22105-3` | Withholding  Tax Payable-Suppliers - 5% | 23 Other Liabilities |
| ☐ | `22105-4` | Withholding  Tax Payable-Suppliers - 10% | 23 Other Liabilities |
| ☐ | `22105-5` | Withholding Tax Payable-Suppliers - 1/2% | 22 Other Current Liabilities |
| ☐ | `22106` | Dividend Payable | 23 Other Liabilities |
| ☐ | `22201` | SSS Salary Loan Payable | 23 Other Liabilities |
| ☐ | `22202` | HDMF Multi Purpose  Loan Payable | 23 Other Liabilities |
| ☐ | `22203` | HDMF Calamity  Loan Payable | 23 Other Liabilities |
| ☐ | `22204` | NHMFC Payable | 23 Other Liabilities |
| ☐ | `22205` | SSS Premium Payable | 23 Other Liabilities |
| ☐ | `22206` | PhilHealth Premium Payable | 23 Other Liabilities |
| ☐ | `22207` | HDMF Premium Payable | 23 Other Liabilities |
| ☐ | `22208` | Canteen Payable | 23 Other Liabilities |
| ☐ | `22209` | RIC Coop Payable | 23 Other Liabilities |
| ☐ | `31101` | Paid Up Capital | 31 Stockholder's Equity |
| ☐ | `32101` | Retained Earnings | 31 Stockholder's Equity |
| ☐ | `33101` | Income & Expenses Summary | 31 Stockholder's Equity |
| ☐ | `39999` | Suspense Account | 31 Stockholder's Equity |
| ☐ | `41101` | Sales - Tincan | 41 Revenues |
| ☐ | `41102` | VAT Expense - Tincan | 41 Revenues |
| ☐ | `41103` | Income Tax - Tincan | 41 Revenues |
| ☐ | `41104` | Creditable Tax Withheld - Tincan | 41 Revenues |
| ☐ | `41105` | Sales Returns & Allowances - Tincan | 41 Revenues |
| ☐ | `41106` | Sales Discount | 41 Revenues |
| ☐ | `41107` | Bad Debts - Tincan | 41 Revenues |
| ☐ | `41201` | Sales - Plastic | 41 Revenues |
| ☐ | `41202` | VAT Expense - Plastic | 41 Revenues |
| ☐ | `41203` | Income Tax - Plastic | 41 Revenues |
| ☐ | `41204` | Creditable Tax Withheld Plastic | 41 Revenues |
| ☐ | `41205` | Sales Returns & Allowances - Plastic | 41 Revenues |
| ☐ | `41206` | Sales Discount - Plastic | 41 Revenues |
| ☐ | `41207` | Bad Debts - Plastic | 41 Revenues |
| ☐ | `42101` | Scrap Sales-Tincan | 41 Revenues |
| ☐ | `42102` | Scrap Sales-Plastic | 41 Revenues |
| ☐ | `51101` | Dividend Income | 51 Other Income (Group) |
| ☐ | `51102` | Interest Income | 51 Other Income (Group) |
| ☐ | `51103` | Rent Income | 51 Other Income (Group) |
| ☐ | `51104` | Other Income | 51 Other Income (Group) |
| ☐ | `51105` | Gain on Sales of Investment | 51 Other Income (Group) |
| ☐ | `61101` | Raw Materials - Tin Can | 61 Direct Materials |
| ☐ | `61102` | Raw Materials - Plastic | 61 Direct Materials |
| ☐ | `61103` | Other Raw Materials - Tin Can | 61 Direct Materials |
| ☐ | `61104` | Other Raw Materials - Plastic | 61 Direct Materials |
| ☐ | `61105` | Printing & Lithograph | 61 Direct Materials |
| ☐ | `61106` | Printing Cost - Plastic | 61 Direct Materials |
| ☐ | `62101` | Direct Labor Tincan | 62 Direct Labor |
| ☐ | `62102` | Direct Labor Tincan - Overtime | 62 Direct Labor |
| ☐ | `62103` | Direct Labor Plastic | 62 Direct Labor |
| ☐ | `62104` | Direct Labor Plastic - Overtime | 62 Direct Labor |
| ☐ | `63101` | Tolling Services | 61 Direct Materials |
| ☐ | `64101` | Indirect Labor - Tincan/Plastic | 63 Factory Overhead |
| ☐ | `64102` | Indirect Labor - Tincan/Plastic - Overtime | 63 Factory Overhead |
| ☐ | `64103` | Indirect Labor - Tincan | 63 Factory Overhead |
| ☐ | `64104` | Indirect Labor - Tincan - Overtime | 63 Factory Overhead |
| ☐ | `64105` | Indirect Labor - Plastic | 63 Factory Overhead |
| ☐ | `64106` | Indirect Labor - Plastic - Overtime | 63 Factory Overhead |
| ☐ | `64107` | 13th Mo. Pay - Tincan/Plastic | 63 Factory Overhead |
| ☐ | `64108` | 13th Mo. Pay - Tincan | 63 Factory Overhead |
| ☐ | `64109` | 13th Mo. Pay  - Plastic | 63 Factory Overhead |
| ☐ | `64110` | Staff Bonus - Tincan/Plastic | 63 Factory Overhead |
| ☐ | `64111` | Staff Bonus - Tincan | 63 Factory Overhead |
| ☐ | `64112` | Staff Bonus - Plastic | 63 Factory Overhead |
| ☐ | `64113-P` | Separation & Retirement - Plastic | 63 Factory Overhead |
| ☐ | `64113-T` | Separation & Retirement - Tincan | 63 Factory Overhead |
| ☐ | `65101` | FO - Telephone & Postage | 63 Factory Overhead |
| ☐ | `65102` | Factory Supplies - Tin Can | 63 Factory Overhead |
| ☐ | `65103` | Factory Supplies - Plastic | 63 Factory Overhead |
| ☐ | `65104` | FO - Machinery  Supplies & Spare Parts - Tincan | 63 Factory Overhead |
| ☐ | `65105` | FO - Machinery  Supplies & Spare Parts - Plastic | 63 Factory Overhead |
| ☐ | `65106` | FO - Gasoline & Lubricant - Tincan | 63 Factory Overhead |
| ☐ | `65107` | FO - Gasoline & Lubricant - Plastic | 63 Factory Overhead |
| ☐ | `65108` | FO - Lights & Water - Tincan | 63 Factory Overhead |
| ☐ | `65108-01` | FO - Light and Water | 63 Factory Overhead |
| ☐ | `65109` | FO - Lights & Water - Plastic | 63 Factory Overhead |
| ☐ | `65110` | FO - Repair & Maintenance - Tincan | 63 Factory Overhead |
| ☐ | `65111` | FO - Repair & Maintenance - Plastic | 63 Factory Overhead |
| ☐ | `65112` | FO - Vehicle Repairs | 63 Factory Overhead |
| ☐ | `65113-P` | FO - Medical & Hospitalization - Plastic | 63 Factory Overhead |
| ☐ | `65113-T` | FO - Medical & Hospitalization - Tincan | 63 Factory Overhead |
| ☐ | `65114-P` | FO - Employee's Benefit - Plastic | 63 Factory Overhead |
| ☐ | `65114-T` | FO - Employee's Benefit - Tincan | 63 Factory Overhead |
| ☐ | `65115` | FO - Unused Sickleave Tincan | 63 Factory Overhead |
| ☐ | `65116` | FO - Unused Sickleave Plastic | 63 Factory Overhead |
| ☐ | `65117` | FO - Unused Sickleave Tincan/Plastic | 63 Factory Overhead |
| ☐ | `65118` | FO - Uniform | 63 Factory Overhead |
| ☐ | `65119` | FO - Excursion | 63 Factory Overhead |
| ☐ | `65120` | FO - Footwear | 63 Factory Overhead |
| ☐ | `65121` | FO - Educational Assistance | 63 Factory Overhead |
| ☐ | `65122` | FO - Rice Subsidy | 63 Factory Overhead |
| ☐ | `65123` | FO - X'mas T-Shirt | 63 Factory Overhead |
| ☐ | `65124` | FO - Bereavement | 63 Factory Overhead |
| ☐ | `65125` | FO - Health Card | 63 Factory Overhead |
| ☐ | `65125-2` | FO - Health Card - Tincan | 63 Factory Overhead |
| ☐ | `65125-3` | FO - Health Card - Plastic | 63 Factory Overhead |
| ☐ | `65126` | FO - Basketball Uniform | 63 Factory Overhead |
| ☐ | `65127` | FO - Plastic Seminar | 63 Factory Overhead |
| ☐ | `65128` | FO - Employee's Car Repair | 63 Factory Overhead |
| ☐ | `65129` | FO - Tincan Worker Quit Claim | 63 Factory Overhead |
| ☐ | `65130` | FO - Give Away Can Goods | 63 Factory Overhead |
| ☐ | `65131-P` | FO - SSS Premium - Plastic | 63 Factory Overhead |
| ☐ | `65131-T` | FO - SSS Premium - Tincan | 63 Factory Overhead |
| ☐ | `65132-P` | FO - PhilHealth Premium - Plastic | 63 Factory Overhead |
| ☐ | `65132-T` | FO - PhilHealth Premium - Tincan | 63 Factory Overhead |
| ☐ | `65133-P` | FO - HDMF Premium - Plastic | 63 Factory Overhead |
| ☐ | `65133-T` | FO - HDMF Premium - Tincan | 63 Factory Overhead |
| ☐ | `65134-P` | FO - Christmas Expenses - Plastic | 63 Factory Overhead |
| ☐ | `65134-T` | FO - Christmas Expenses - Tincan | 63 Factory Overhead |
| ☐ | `65135` | FO - Transportation | 63 Factory Overhead |
| ☐ | `65135-P` | FO - Transportation - Plastic | 63 Factory Overhead |
| ☐ | `65135-T` | FO - Transportation - Tincan | 63 Factory Overhead |
| ☐ | `65136` | FO - Representation Expenses - Tincan | 63 Factory Overhead |
| ☐ | `65137` | FO - Representation Expenses - Plastic | 63 Factory Overhead |
| ☐ | `65138` | FO - Subsistence Allowance | 63 Factory Overhead |
| ☐ | `65139` | FO - Rental-Bldg | 63 Factory Overhead |
| ☐ | `65140` | FO - Rental-Others | 63 Factory Overhead |
| ☐ | `65141` | FO - Dep'n- Mach & Eqpt Tincan | 63 Factory Overhead |
| ☐ | `65142` | FO - Dep'n - Mach & Eqpt Plastic | 63 Factory Overhead |
| ☐ | `65143` | FO - Dep'n - Transp. Eqpt | 63 Factory Overhead |
| ☐ | `65144` | FO - Dep'n - Molds & Dies Tincan | 63 Factory Overhead |
| ☐ | `65145` | FO - Dep'n - Molds & Dies Plastic | 63 Factory Overhead |
| ☐ | `65146` | FO - Dep'n - Tools | 63 Factory Overhead |
| ☐ | `65147` | FO - Dep'n - Machine Spare Parts Tincan | 63 Factory Overhead |
| ☐ | `65148` | FO - Dep'n - Machine Spare Parts Plastic | 63 Factory Overhead |
| ☐ | `65149` | FO - Dep'n - Motors & Accessories | 63 Factory Overhead |
| ☐ | `65150` | FO - Dep'n - Office Pateros | 63 Factory Overhead |
| ☐ | `65151` | FO - Dep'n - Furniture, Fixture & Eqpt (Tincan) | 63 Factory Overhead |
| ☐ | `65152` | FO - Dep'n - Furniture, Fixture & Eqpt (Plastic) | 63 Factory Overhead |
| ☐ | `65153` | FO - Janitorial Services | 63 Factory Overhead |
| ☐ | `65154` | Pallets | 63 Factory Overhead |
| ☐ | `65155` | FO - Insurance Expenses | 63 Factory Overhead |
| ☐ | `65156` | Patent - Plastic | 63 Factory Overhead |
| ☐ | `65157` | Artwork - Tin Can | 63 Factory Overhead |
| ☐ | `65158` | Artwork - Plastic | 63 Factory Overhead |
| ☐ | `65159` | Product Study - Tin Can | 63 Factory Overhead |
| ☐ | `65160` | Product Study - Plastic | 63 Factory Overhead |
| ☐ | `65161` | Stationery | 63 Factory Overhead |
| ☐ | `65162` | Garbage Disposal | 63 Factory Overhead |
| ☐ | `65163` | FO - Miscellaneous - Tincan | 63 Factory Overhead |
| ☐ | `65164` | FO - Miscellaneous - Plastic | 63 Factory Overhead |
| ☐ | `65165` | Pest Control - Tincan | 63 Factory Overhead |
| ☐ | `65166` | Pest Control - Plastic | 63 Factory Overhead |
| ☐ | `65167` | FO - Amortization - Intangibles | 63 Factory Overhead |
| ☐ | `65168` | FO - Representation Allowance - Plastic | 63 Factory Overhead |
| ☐ | `65169` | FO - Employees Benefit - Tincan/Plastic | 63 Factory Overhead |
| ☐ | `66101` | SE - Salaries & Wages | 64 Selling Expenses |
| ☐ | `66102` | SE - 13th Mo. Pay | 64 Selling Expenses |
| ☐ | `66103` | SE - Staff Bonus | 64 Selling Expenses |
| ☐ | `66104` | SE - Separation & Retirement | 64 Selling Expenses |
| ☐ | `66105` | Commission-Tincan | 64 Selling Expenses |
| ☐ | `66106` | Commission-Plastic | 64 Selling Expenses |
| ☐ | `66107-P` | SE - Delivery Expenses - Plastic | 64 Selling Expenses |
| ☐ | `66107-T` | SE - Delivery Expenses - Tincan | 64 Selling Expenses |
| ☐ | `66108` | SE - Representation Allowances | 64 Selling Expenses |
| ☐ | `66109` | SE - Representation Expenses-Tincan | 64 Selling Expenses |
| ☐ | `66110` | SE - Representation Expenses-Plastic | 64 Selling Expenses |
| ☐ | `66111` | SE - Gasoline & Lubricant - Tincan | 64 Selling Expenses |
| ☐ | `66112` | SE - Gasoline & Lubricant - Plastic | 64 Selling Expenses |
| ☐ | `66113` | SE - Repair & Maintenance | 64 Selling Expenses |
| ☐ | `66114` | SE - Vehicle Repairs | 64 Selling Expenses |
| ☐ | `66115` | SE - Ads & Sales Promo | 64 Selling Expenses |
| ☐ | `66116` | SE - Telephone & Postage - Tincan | 64 Selling Expenses |
| ☐ | `66117` | SE - Telephone & Postage - Plastic | 64 Selling Expenses |
| ☐ | `66118` | SE - Employee's Benefit | 64 Selling Expenses |
| ☐ | `66119` | SE - Unused Sickleave | 64 Selling Expenses |
| ☐ | `66120` | SE - Uniform | 64 Selling Expenses |
| ☐ | `66121` | SE - Salesman Car Registration/Insurance | 64 Selling Expenses |
| ☐ | `66122` | SE - Excursion | 64 Selling Expenses |
| ☐ | `66123` | SE - Birthday Celebrant | 64 Selling Expenses |
| ☐ | `66124` | SE - Salesman Car Tires/Battery | 64 Selling Expenses |
| ☐ | `66125` | SE - Educational Assistance | 64 Selling Expenses |
| ☐ | `66126` | SE - Rice Subsidy | 64 Selling Expenses |
| ☐ | `66127` | SE - Bereavement | 64 Selling Expenses |
| ☐ | `66128` | SE - Health Card | 64 Selling Expenses |
| ☐ | `66129` | SE - Give Away Can Goods | 64 Selling Expenses |
| ☐ | `66130` | SE - Medical & Dental | 64 Selling Expenses |
| ☐ | `66131` | SE - SSS Premium  | 64 Selling Expenses |
| ☐ | `66132` | SE - PhilHealth Premium | 64 Selling Expenses |
| ☐ | `66133` | SE - HDMF Premium | 64 Selling Expenses |
| ☐ | `66134` | SE - Transportation - Tincan | 64 Selling Expenses |
| ☐ | `66135` | SE - Transportation - Plastic | 64 Selling Expenses |
| ☐ | `66136` | SE - Customer Christmas Expenses | 64 Selling Expenses |
| ☐ | `66137` | SE - Dep'n   -   Transp. Eqpt | 64 Selling Expenses |
| ☐ | `66138` | SE - Rental Others | 64 Selling Expenses |
| ☐ | `66139` | SE - Insurance Expenses | 64 Selling Expenses |
| ☐ | `66140` | SE - Donations & Contribution - Tincan | 64 Selling Expenses |
| ☐ | `66141` | SE - Donations & Contribution - Plastic | 64 Selling Expenses |
| ☐ | `66142` | SE - Miscellaneous | 64 Selling Expenses |
| ☐ | `67101` | AE - Salaries & Wages | 65 Administrative Expenses |
| ☐ | `67102` | AE - Mgt. Salaries | 65 Administrative Expenses |
| ☐ | `67103` | AE - 13th Mo. Pay | 65 Administrative Expenses |
| ☐ | `67104` | AE - Management Bonus | 65 Administrative Expenses |
| ☐ | `67105` | AE - Staff Bonus | 65 Administrative Expenses |
| ☐ | `67106` | AE - Office Supplies | 65 Administrative Expenses |
| ☐ | `67107` | AE - Gasoline & Oil | 65 Administrative Expenses |
| ☐ | `67108` | AE - Telephone & Postage | 65 Administrative Expenses |
| ☐ | `67109` | AE - Bad Debts | 65 Administrative Expenses |
| ☐ | `67110` | AE - Medical & Dental | 65 Administrative Expenses |
| ☐ | `67111` | AE - Employee's Benefit | 65 Administrative Expenses |
| ☐ | `67112` | AE - Unused Sickleave | 65 Administrative Expenses |
| ☐ | `67113` | AE - Uniform | 65 Administrative Expenses |
| ☐ | `67114` | AE - Excursion | 65 Administrative Expenses |
| ☐ | `67115` | AE - Seminar/Training | 65 Administrative Expenses |
| ☐ | `67116` | AE - Educational Assistance | 65 Administrative Expenses |
| ☐ | `67117` | AE - Rice Subsidy | 65 Administrative Expenses |
| ☐ | `67118` | AE - Bereavement | 65 Administrative Expenses |
| ☐ | `67119` | AE - Health Card | 65 Administrative Expenses |
| ☐ | `67120` | AE - Give Away Can Goods | 65 Administrative Expenses |
| ☐ | `67121` | AE - Repair & Maintenance | 65 Administrative Expenses |
| ☐ | `67122` | AE - Vehicle Repairs | 65 Administrative Expenses |
| ☐ | `67123` | AE - SSS Premium  | 65 Administrative Expenses |
| ☐ | `67124` | AE - PhilHealth Premium  | 65 Administrative Expenses |
| ☐ | `67125` | AE - HDMF Premium | 65 Administrative Expenses |
| ☐ | `67126` | AE - Separation & Retirement | 65 Administrative Expenses |
| ☐ | `67126-2` | AE - Management Promo | 65 Administrative Expenses |
| ☐ | `67127` | AE - Representation Expenses | 65 Administrative Expenses |
| ☐ | `67128` | AE - Representation Allowance | 65 Administrative Expenses |
| ☐ | `67129` | Office Practitioner Allowance | 65 Administrative Expenses |
| ☐ | `67130` | Professional  Legal & Audit Fee | 65 Administrative Expenses |
| ☐ | `67131` | AE - Rental-Others | 65 Administrative Expenses |
| ☐ | `67132` | AE - Rental Bldg | 65 Administrative Expenses |
| ☐ | `67133` | AE - Membership Dues | 65 Administrative Expenses |
| ☐ | `67134` | AE - Security Services | 65 Administrative Expenses |
| ☐ | `67135` | AE - Subscription Dues | 65 Administrative Expenses |
| ☐ | `67136` | AE - Advertising | 65 Administrative Expenses |
| ☐ | `67137` | Interest Expense | 65 Administrative Expenses |
| ☐ | `67138` | Bank Charges | 65 Administrative Expenses |
| ☐ | `67139` | AE - Taxes & Licenses | 65 Administrative Expenses |
| ☐ | `67139-1` | AE - Penalties and Surcharge | 65 Administrative Expenses |
| ☐ | `67140` | AE - Transportation | 65 Administrative Expenses |
| ☐ | `67141` | AE - Depreciation - Office Bldg. Pateros | 65 Administrative Expenses |
| ☐ | `67142` | AE - Depreciation - Furniture, Fixture & Eqpt | 65 Administrative Expenses |
| ☐ | `67143` | AE - Insurance | 65 Administrative Expenses |
| ☐ | `67144` | AE - Donations & Contribution | 65 Administrative Expenses |
| ☐ | `67145` | AE - Christmas Expenses | 65 Administrative Expenses |
| ☐ | `67146` | AE - Miscellaneous Expenses | 65 Administrative Expenses |
| ☐ | `67147` | A.E. - Mgt. 13th Month Pay | 65 Administrative Expenses |
| ☐ | `67148` | A.E. - Adm. 13th Month Pay | 65 Administrative Expenses |
| ☐ | `69998` | At the Back | 65 Administrative Expenses |
| ☐ | `69999` | Various Expenses | 65 Administrative Expenses |
