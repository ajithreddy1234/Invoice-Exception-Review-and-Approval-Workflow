export function reviewFieldLabel(path) {
  const match = /^line_items\.(\d+)\.(\w+)$/.exec(path);
  return match ? `Line ${Number(match[1]) + 1} · ${match[2].replaceAll('_', ' ')}` : path.replaceAll('_', ' ');
}

export function reviewSelections(options, candidate, selectedPo, mappings) {
  const poCode = candidate.po_reference.value || selectedPo || (options?.pos?.length === 1 ? options.pos[0].po_code : '');
  const po = options?.pos?.find(p => p.po_code.toLowerCase() === poCode.trim().toLowerCase());
  // A changed PO never carries mappings to a different PO with the same line code.
  return {po, mappings: Object.entries(mappings).filter(([, value]) => value.code && value.po === po?.po_code)
    .map(([index,value]) => ({invoice_line: Number(index), po_line_code: value.code}))};
}
