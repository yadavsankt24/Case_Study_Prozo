# PF / ESIC compliance knowledge base

Simplified reference notes used by the Ask assistant. They are a proof-of-concept
summary, not legal advice; confirm against current EPFO / ESIC notifications.

## PF employee contribution rate
The employee contributes 12% of EPF wages (basic wages plus dearness allowance and retaining allowance) to the Employees' Provident Fund. In the wagesheet this is the "PF @ 12%" column; in the PF ECR it is the "EE" (employee share) column. The two must match for every member.

## PF employer contribution and EPS split
The employer also contributes 12% of EPF wages. Of this, 8.33% goes to the Employees' Pension Scheme (EPS) on wages up to Rs 15,000 a month (so at most Rs 1,250), and the balance goes to the EPF account. In the ECR these appear as the "EPS" and "ER" columns. EDLI and administrative charges are paid by the employer on top.

## PF wage ceiling
The statutory PF wage ceiling is Rs 15,000 a month. Contributions are mandatory on wages up to the ceiling; contributing on higher wages is optional. EPF, EPS and EDLI wages in the ECR can therefore differ from gross wages.

## PF rounding
PF contributions are rounded to the nearest rupee. This tool therefore accepts a difference of up to Rs 1 between the wagesheet and the ECR before calling it an amount mismatch.

## UAN
The Universal Account Number (UAN) is a 12-digit number issued by EPFO that stays with the member across jobs. The PF ECR lists every member by UAN, so the UAN is the key used to find a wagesheet employee in the PF ECR.

## PF ECR document
The Electronic Challan cum Return (ECR) is filed by the employer on the EPFO portal for each wage month. It lists every member with UAN, name as per ECR, name as per the UAN repository, gross, EPF, EPS and EDLI wages, EE share, EPS share, ER share and NCP days. NCP days are non-contributory period days for which no wages were paid.

## PF due date
PF contributions for a wage month must be paid and the ECR filed by the 15th of the following month. Late payment attracts interest and damages.

## ESIC employee contribution rate
The employee (insured person, IP) contributes 0.75% of gross wages to ESIC. In the wagesheet this is the "ESIC @ 0.75%" column; in the ESIC ECR it is the "IP Contribution" column.

## ESIC employer contribution rate
The employer contributes 3.25% of gross wages to ESIC (rates effective from 1 July 2019). The total contribution is therefore 4% of gross wages.

## ESIC wage ceiling
ESIC applies to employees whose gross wages are up to Rs 21,000 a month (Rs 25,000 for persons with disability). Employees earning an average daily wage up to Rs 176 are exempt from paying the employee share, but the employer share is still payable.

## ESIC contribution period
ESIC has two contribution periods: 1 April to 30 September and 1 October to 31 March. An employee covered at the start of a period stays covered until the end of that period even if wages rise above the ceiling.

## ESIC rounding
ESIC contributions are rounded up to the next higher rupee. For example 0.75% of Rs 13,520 is Rs 101.40, which becomes Rs 102.

## IP number
The Insurance Person (IP) number is a 10-digit number issued by ESIC to each insured employee. The ESIC ECR lists insured persons by IP number, so it is the key used to find a wagesheet employee in the ESIC ECR.

## ESIC due date
ESIC contributions for a month must be paid by the 15th of the following month. Late payment attracts interest and damages.

## Principal employer liability
When contract labour is supplied by a vendor agency, the principal employer (Prozo) is responsible for making sure PF and ESIC are actually deposited. If the contractor fails to pay, the authorities can recover the dues from the principal employer, who can then recover them from the contractor. This is why deductions in the vendor wagesheet are verified against the ECRs every month.

## Meaning of Matched
Matched means the identifier (UAN or IP number) was found in the ECR, the name refers to the same person, and the amount deposited equals the amount deducted in the wagesheet within Rs 1. A "needs review" flag means the name matched only through an initial, a vowel difference or an extra name part, and a person should glance at it.

## Meaning of Name mismatch
Name mismatch means the identifier was found in the ECR but the name belongs to a different person, for example a different first name with the same surname. This can mean the vendor used another worker's UAN or IP number. Action: ask the vendor to confirm the employee's identity and correct the filing.

## Meaning of Amount mismatch
Amount mismatch means the identifier and name match but the deposited amount differs from the wagesheet deduction by more than Rs 1. The tool also recomputes 12% (PF) or 0.75% (ESIC) of the wages printed in the ECR to show whether the deposit or the wagesheet figure is wrong. Action: if the deposit is short, ask the vendor to pay the difference with a revised challan.

## Meaning of Missing
Missing means the employee's UAN or IP number does not appear in the ECR, or the wagesheet has no valid identifier for the employee. Money was deducted from the worker but not deposited for them. Action: ask the vendor for proof of deposit or a supplementary ECR, and hold payment until resolved.

## ECR only members
"In ECR, not in wagesheet" lists people the vendor filed contributions for who are not on the wagesheet. These may be employees deployed at another client, people missing from the wagesheet, or ghost entries. Action: confirm with the vendor.

## Name matching tolerance
Names are compared word by word. Spelling variations (Suneeta/Sunita, Prashad/Prasad), word order, titles (Mr, Smt), spacing and initials are tolerated. A different given name or surname (Rekha/Renu, Rakesh/Ramesh) is always reported as a name mismatch.
