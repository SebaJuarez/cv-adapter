//módulo: labels — labels de campos y tipos de sección

// ------------------------------------------------------ labels de campos

const FIELD_LABELS = {
  company: "Empresa", position: "Puesto", location: "Ubicación",
  start_date: "Fecha inicio", end_date: "Fecha fin",
  institution: "Institución", area: "Área", degree: "Título",
  name: "Nombre", date: "Fecha", label: "Categoría", details: "Detalle",
};

function fieldLabel(key) {
  return FIELD_LABELS[key] || key.replace(/_/g, " ");
}

// -------------------------------------------------------- section types

function defaultSectionType(name) {
  if (["summary", "objective", "keywords", "interests"].includes(name)) return "text";
  if (["skills", "languages"].includes(name)) return "label_details";
  return "entries";
}

function detectSectionType(name, entries, sectionTypes) {
  if (!entries || entries.length === 0) return null;
  const first = entries[0];
  if (typeof first === "string") return "text";
  if (first && typeof first === "object" && "highlights" in first) return "entries";
  return "label_details";
}

function deriveSectionTypes(doc) {
  const sections = doc?.cv?.sections || {};
  const out = {};
  Object.keys(sections).forEach((name) => {
    out[name] = detectSectionType(name, sections[name], null) || defaultSectionType(name);
  });
  return out;
}

function blankEntryFor(sectionName, type) {
  if (type === "text") return "";
  if (type === "label_details") return { label: "", details: "" };
  if (sectionName === "experience") {
    return { company: "", position: "", location: "", start_date: "", end_date: "", highlights: [] };
  }
  if (sectionName === "education") {
    return { institution: "", area: "", degree: "", start_date: "", end_date: "", highlights: [] };
  }
  return { name: "", date: "", highlights: [] };
}


export { FIELD_LABELS, blankEntryFor, defaultSectionType, deriveSectionTypes, detectSectionType, fieldLabel };
