//módulo: onboarding — primera pantalla conversacional cuando el CV maestro
//está vacío (F4, doc §4.1/§6.2): chat de una pregunta a la vez con "no sé /
//paso", candidato editable con el editor de logros existente y confirmación
//explícita antes de persistir. Nada entra al master sin que el usuario lo
//haya visto y aceptado.

import { api } from "../api.js";
import { commitAchDraft, renderAchievementCard } from "../components.js";
import { h } from "../dom.js";
import { blankAchievement, blankEntryFor } from "../labels.js";
import { toast } from "../notify.js";
import { markDirty, snapshotView, state } from "../state.js";

const QUESTIONS = [
  {
    key: "work",
    label: "Contame de un trabajo o proyecto reciente. ¿Qué hiciste?",
    placeholder: "ej: Desarrollé el backend de una app de delivery…",
  },
  {
    key: "tools",
    label: "¿Con qué herramientas o tecnologías?",
    placeholder: "ej: Python, PostgreSQL, Docker…",
  },
  {
    key: "outcomes",
    label: "¿Hubo algún resultado medible? (tiempo, plata, gente — no hace falta que sea perfecto)",
    placeholder: "ej: reduje el tiempo de respuesta un 40%…",
  },
];

const answers = { work: "", tools: "", outcomes: "" };
let step = 0;
let candidateEntry = null;

function countAchievements(doc) {
  let n = 0;
  Object.values(doc?.cv?.sections || {}).forEach((entries) => {
    if (!Array.isArray(entries)) return;
    entries.forEach((e) => {
      if (e && Array.isArray(e.achievements)) n += e.achievements.length;
    });
  });
  return n;
}

export function mountOnboarding(container, onExit) {
  step = 0;
  answers.work = "";
  answers.tools = "";
  answers.outcomes = "";
  candidateEntry = null;

  const goApplyBtn = h("button", {
    class: "btn btn-primary",
    hidden: "hidden",
    onclick: () => document.querySelector('.tab[data-view="apply"]').click(),
  }, "Generar mi primer CV");
  const progress = h("div", { class: "onb-progress" });
  const chatWrap = h("div", { class: "onb-chat" });
  const candidateWrap = h("div", { class: "onb-candidate" });

  const drawProgress = () => {
    const n = countAchievements(state.masterDoc);
    progress.textContent =
      n >= 4
        ? `Logros cargados: ${n} · ya podés generar tu primer CV.`
        : `Logros cargados: ${n} · podés generar tu primer CV con ${4 - n} más.`;
    goApplyBtn.hidden = n < 4;
  };

  const drawChat = () => {
    chatWrap.innerHTML = "";
    const q = QUESTIONS[step];
    const ta = h("textarea", { class: "highlight-text onb-textarea", placeholder: q.placeholder, "aria-label": q.label });
    setTimeout(() => ta.focus(), 0);
    const send = h("button", {
      class: "btn btn-primary",
      onclick: () => { answers[q.key] = ta.value.trim(); submitAnswers(); },
    }, "Siguiente");
    const skip = h("button", {
      class: "btn btn-ghost",
      onclick: () => {
        if (step < QUESTIONS.length - 1) { step++; drawChat(); } else { submitAnswers(); }
      },
    }, "no sé / paso esta pregunta");
    chatWrap.appendChild(h("p", { class: "onb-question" }, `${QUESTIONS.indexOf(q) + 1}. ${q.label}`));
    chatWrap.appendChild(ta);
    chatWrap.appendChild(h("div", { class: "onb-chat-actions" }, [send, skip]));
  };

  const drawCandidate = () => {
    candidateWrap.innerHTML = "";
    if (!candidateEntry) return;
    const ctx = { doc: state.masterDoc, isTarget: false, onRerender: drawCandidate };
    candidateWrap.appendChild(
      h("p", { class: "onb-candidate-title" }, "Así quedaría tu logro. Revisalo y editá lo que quieras antes de confirmar:")
    );
    candidateWrap.appendChild(renderAchievementCard(candidateEntry, candidateEntry.achievements[0], 0, ctx));
    candidateWrap.appendChild(h("div", { class: "onb-candidate-actions" }, [
      h("button", {
        class: "btn btn-ghost",
        onclick: () => { candidateEntry = null; candidateWrap.innerHTML = ""; chatWrap.hidden = false; step = 0; drawChat(); },
      }, "Rehacer respuesta"),
      h("button", { class: "btn btn-primary", onclick: confirmCandidate }, "Confirmar logro"),
    ]));
  };

  const submitAnswers = async () => {
    chatWrap.hidden = true;
    candidateWrap.innerHTML = "";
    candidateWrap.appendChild(h("p", { class: "onb-thinking" }, "Estructurando tu logro…"));
    try {
      const res = await api("/api/onboarding/structurize", {
        method: "POST",
        body: JSON.stringify(answers),
      });
      const ach = blankAchievement();
      ach.facts = res.facts;
      ach.variants[0].text = res.variant_text;
      ach.variants[0].source = "generated";
      candidateEntry = blankEntryFor("experience", "entries");
      delete candidateEntry.highlights; // D1: una entrada usa un solo formato
      candidateEntry.achievements = [ach];
      drawCandidate();
    } catch (e) {
      candidateWrap.innerHTML = "";
      chatWrap.hidden = false;
      toast("No se pudo estructurar el logro: " + (e.message || "error"));
    }
  };

  const confirmCandidate = async () => {
    if (!candidateEntry) return;
    commitAchDraft(candidateEntry, 0, { onRerender: () => {} });
    const entry = candidateEntry;
    candidateEntry = null;
    state.masterDoc.cv.sections.experience.push(entry);
    markDirty("master");
    try {
      await api("/api/master-cv", { method: "POST", body: JSON.stringify(state.masterDoc) });
      snapshotView("master");
      toast("Logro guardado en tu CV maestro.");
    } catch (e) {
      toast("El logro quedó en el editor, pero no se pudo persistir: " + (e.message || "error"));
    }
    candidateWrap.innerHTML = "";
    chatWrap.hidden = false;
    step = 0;
    drawProgress();
    drawChat();
  };

  container.appendChild(h("div", { class: "onboarding" }, [
    h("h2", { class: "onb-title" }, "Armemos tu CV maestro"),
    h("p", { class: "onb-lede" },
      "Contame tu experiencia como si se lo contaras a un amigo, una cosa a la vez. Después estructuramos cada logro juntos — no necesitás saber nada de formato."),
    progress,
    chatWrap,
    candidateWrap,
    h("div", { class: "onb-ctas" }, [
      goApplyBtn,
      h("button", { class: "btn btn-ghost", onclick: onExit },
        "Terminar por ahora e ir al editor completo"),
    ]),
  ]));
  drawProgress();
  drawChat();
}