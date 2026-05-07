/** Normalize Vietnamese text to NFC before sending to backend. */
export function normalizeNFC(text: string): string {
  return text.normalize("NFC");
}
