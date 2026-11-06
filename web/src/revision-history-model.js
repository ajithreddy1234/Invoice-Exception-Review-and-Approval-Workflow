import { FIELD_NAMES } from "./model.js";

export function revisionChanges(previous, current) {
  if (!current) return [];
  return [
    ...Object.entries(FIELD_NAMES),
    ["tax_presentation", "Tax presentation"],
    ["line_items", "Line items"],
  ].flatMap(([key, label]) => {
    const fieldValue = (candidate) =>
      key === "line_items" || key === "tax_presentation"
        ? (candidate?.[key] ?? null)
        : (candidate?.[key]?.value ?? null);
    const oldValue = fieldValue(previous),
      newValue = fieldValue(current);
    const oldSource = previous?.[key]?.source ?? null;
    const newSource = current[key]?.source ?? null;
    if (
      JSON.stringify(oldValue) === JSON.stringify(newValue) &&
      JSON.stringify(oldSource) === JSON.stringify(newSource)
    )
      return [];
    return [
      {
        key,
        label,
        before: oldValue,
        after: newValue,
        source: current[key]?.source,
        before_source: oldSource,
        after_source: newSource,
      },
    ];
  });
}
