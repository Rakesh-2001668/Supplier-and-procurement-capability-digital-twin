// Indian tax-ID checks used by the registration and master-change forms (the API runs the same checks, MDM-04).

const CHARS = '0123456789ABCDEFGHIJKLMNOPQRSTUVWXYZ';
const GSTIN_RE = /^[0-9]{2}[A-Z]{5}[0-9]{4}[A-Z][1-9A-Z]Z[0-9A-Z]$/;
const PAN_RE = /^[A-Z]{5}[0-9]{4}[A-Z]$/;

export const STATES: { code: string; name: string }[] = [
  ['01', 'Jammu & Kashmir'], ['02', 'Himachal Pradesh'], ['03', 'Punjab'], ['04', 'Chandigarh'], ['05', 'Uttarakhand'], ['06', 'Haryana'],
  ['07', 'Delhi'], ['08', 'Rajasthan'], ['09', 'Uttar Pradesh'], ['10', 'Bihar'], ['11', 'Sikkim'], ['12', 'Arunachal Pradesh'],
  ['13', 'Nagaland'], ['14', 'Manipur'], ['15', 'Mizoram'], ['16', 'Tripura'], ['17', 'Meghalaya'], ['18', 'Assam'], ['19', 'West Bengal'],
  ['20', 'Jharkhand'], ['21', 'Odisha'], ['22', 'Chhattisgarh'], ['23', 'Madhya Pradesh'], ['24', 'Gujarat'], ['25', 'Daman & Diu'],
  ['26', 'Dadra & Nagar Haveli and Daman & Diu'], ['27', 'Maharashtra'], ['28', 'Andhra Pradesh (old)'], ['29', 'Karnataka'], ['30', 'Goa'],
  ['31', 'Lakshadweep'], ['32', 'Kerala'], ['33', 'Tamil Nadu'], ['34', 'Puducherry'], ['35', 'Andaman & Nicobar Islands'], ['36', 'Telangana'],
  ['37', 'Andhra Pradesh'], ['38', 'Ladakh'], ['97', 'Other territory'],
].map(([code, name]) => ({ code, name }));

export function gstinCheckChar(first14: string): string {
  let total = 0;
  for (let i = 0; i < 14; i++) {
    const product = CHARS.indexOf(first14[i]) * (i % 2 ? 2 : 1);
    total += Math.floor(product / 36) + (product % 36);
  }
  return CHARS[(36 - (total % 36)) % 36];
}

/** Problems with a GSTIN (empty list = valid). */
export function gstinProblems(gstin: string, pan?: string, stateCode?: string): string[] {
  const g = gstin.trim().toUpperCase();
  if (!GSTIN_RE.test(g)) return ['GSTIN must be 15 characters: state code, PAN, entity number, Z and a check character'];
  const out: string[] = [];
  if (!STATES.some((s) => s.code === g.slice(0, 2))) out.push(`State code ${g.slice(0, 2)} is not a GST state code`);
  if (gstinCheckChar(g.slice(0, 14)) !== g[14]) out.push('GSTIN check character does not match – please re-check the number');
  if (pan && pan.trim().toUpperCase() !== g.slice(2, 12)) out.push('PAN must match characters 3–12 of the GSTIN');
  if (stateCode && stateCode !== g.slice(0, 2)) out.push(`GSTIN state ${g.slice(0, 2)} does not match the address state ${stateCode}`);
  return out;
}

export function panValid(pan: string): boolean {
  return PAN_RE.test(pan.trim().toUpperCase());
}

export function pinValid(pin: string): boolean {
  return /^[1-9][0-9]{5}$/.test(pin.trim());
}

export function emailValid(email: string): boolean {
  return /^[^@\s]+@[^@\s]+\.[A-Za-z]{2,}$/.test(email.trim());
}

export function phoneValid(phone: string): boolean {
  return /^\+?[0-9][0-9 -]{7,16}[0-9]$/.test(phone.trim());
}
