/** Excel-compatible UTF-8 CSV, with spreadsheet formulas kept as literal text. */
export function serializeCaseBoardCsv(rows: readonly (readonly string[])[]): string {
  const cell = (value: string) => {
    const text = /^[\s]*[=+\-@]|^[\t\r\n]/.test(value) ? `'${value}` : value;
    return `"${text.replaceAll('"', '""')}"`;
  };
  return "\uFEFF" + rows.map((row) => row.map(cell).join(",")).join("\r\n") + "\r\n";
}
