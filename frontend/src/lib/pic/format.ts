// Formatting in Indian conventions: ₹ with lakh/crore grouping, IST dates.

const inrFormat = new Intl.NumberFormat('en-IN', { style: 'currency', currency: 'INR', maximumFractionDigits: 2 });
const qtyFormat = new Intl.NumberFormat('en-IN', { maximumFractionDigits: 3 });
const dateFormat = new Intl.DateTimeFormat('en-IN', { day: '2-digit', month: 'short', year: 'numeric', timeZone: 'Asia/Kolkata' });
const dateTimeFormat = new Intl.DateTimeFormat('en-IN', {
  day: '2-digit', month: 'short', year: 'numeric', hour: '2-digit', minute: '2-digit', timeZone: 'Asia/Kolkata',
});

/** Amounts arrive in paise (integer minor units). */
export function inr(minor: number | string | null | undefined): string {
  if (minor === null || minor === undefined || minor === '') return '–';
  return inrFormat.format(Number(minor) / 100);
}

export function crore(minor: number | null | undefined): string {
  if (minor === null || minor === undefined) return '–';
  return `₹${(Number(minor) / 100 / 1e7).toFixed(2)} Cr`;
}

export function qty(value: number | string | null | undefined, uom?: string): string {
  if (value === null || value === undefined || value === '') return '–';
  return `${qtyFormat.format(Number(value))}${uom ? ` ${uom}` : ''}`;
}

export function date(value: string | null | undefined): string {
  if (!value) return '–';
  return dateFormat.format(new Date(value.length === 10 ? `${value}T00:00:00+05:30` : value));
}

export function dateTime(value: string | null | undefined): string {
  if (!value) return '–';
  return dateTimeFormat.format(new Date(value));
}

export function label(value: string | null | undefined): string {
  if (!value) return '–';
  return value.replace(/_/g, ' ').toLowerCase().replace(/^\w/, (c) => c.toUpperCase());
}

export function rupeesToMinor(value: string | number): number {
  return Math.round(Number(value) * 100);
}
