/* Puerto A&M — landing pública. Sin datos financieros en este bundle. */
(function () {
  "use strict";

  const $ = (id) => document.getElementById(id);
  const chatSession = (crypto.randomUUID && crypto.randomUUID()) || "pa-" + Date.now();
  let chatBusy = false;
  let toastTimer = null;

  function toast(message, isError) {
    const el = $("toast");
    el.textContent = message;
    el.className = "toast show" + (isError ? " error" : "");
    clearTimeout(toastTimer);
    toastTimer = setTimeout(() => (el.className = "toast"), 3800);
  }

  /* ---------- Navegación y animaciones ---------- */
  function setupNavigation() {
    const header = $("siteHeader");
    const onScroll = () => header.classList.toggle("scrolled", window.scrollY > 24);
    onScroll();
    window.addEventListener("scroll", onScroll, { passive: true });

    const burger = $("burger");
    const mobileNav = $("mobileNav");
    const closeMenu = () => {
      burger.classList.remove("open");
      burger.setAttribute("aria-expanded", "false");
      mobileNav.classList.remove("open");
      mobileNav.setAttribute("aria-hidden", "true");
      document.body.classList.remove("chat-open");
    };
    burger.addEventListener("click", () => {
      const open = !mobileNav.classList.contains("open");
      burger.classList.toggle("open", open);
      burger.setAttribute("aria-expanded", String(open));
      mobileNav.classList.toggle("open", open);
      mobileNav.setAttribute("aria-hidden", String(!open));
      document.body.classList.toggle("chat-open", open);
    });
    mobileNav.querySelectorAll("a").forEach((link) => link.addEventListener("click", closeMenu));

    const reduceMotion = window.matchMedia("(prefers-reduced-motion: reduce)").matches;
    const targets = document.querySelectorAll(".reveal");
    if (reduceMotion || !("IntersectionObserver" in window)) {
      targets.forEach((el) => el.classList.add("visible"));
    } else {
      const observer = new IntersectionObserver(
        (entries) => {
          entries.forEach((entry) => {
            if (entry.isIntersecting) {
              entry.target.classList.add("visible");
              observer.unobserve(entry.target);
            }
          });
        },
        { threshold: 0.12, rootMargin: "0px 0px -40px" }
      );
      targets.forEach((el) => observer.observe(el));
    }
    $("year").textContent = new Date().getFullYear();
  }

  /* ---------- Configuración pública ---------- */
  async function loadPublicConfig() {
    try {
      const [configRes, healthRes] = await Promise.all([
        fetch("/api/public/config", { cache: "no-store" }),
        fetch("/api/health", { cache: "no-store" }),
      ]);
      if (!configRes.ok) return;
      const cfg = await configRes.json();
      const set = (id, value, fallback) => {
        const el = $(id);
        if (el) el.textContent = value || fallback;
      };
      set("cfgEmail", cfg.email, "Solicítalo en el formulario");
      set("cfgHours", cfg.hours, "Confírmalo en el formulario");
      set("cfgAddress", cfg.address, "Solicítala en el formulario");

      let status = "Asistente en modo local · información pública";
      if (healthRes.ok) {
        const health = await healthRes.json();
        if (health.asistentePublico === "conectado") status = "Asistente en línea · información pública";
      }
      const chip = $("assistantStatus");
      if (chip) chip.textContent = status;
      const mode = $("chatMode");
      if (mode && !chatBusy) mode.textContent = status;
    } catch (_error) {
      /* La página sigue funcionando sin estas opciones. */
    }
  }

  /* ---------- Chat ---------- */
  function openChat() {
    $("chatPanel").classList.add("open");
    $("chatPanel").setAttribute("aria-hidden", "false");
    $("chatFab").setAttribute("aria-expanded", "true");
    setTimeout(() => $("chatInput").focus(), 220);
  }
  function closeChat() {
    $("chatPanel").classList.remove("open");
    $("chatPanel").setAttribute("aria-hidden", "true");
    $("chatFab").setAttribute("aria-expanded", "false");
  }
  function addMessage(text, kind) {
    const node = document.createElement("div");
    node.className = "chat-msg " + kind;
    node.textContent = text;
    $("chatMessages").appendChild(node);
    $("chatMessages").scrollTop = $("chatMessages").scrollHeight;
    return node;
  }
  function renderSuggestions(items) {
    const box = $("chatSuggestions");
    box.replaceChildren();
    (items || []).forEach((text) => {
      const button = document.createElement("button");
      button.type = "button";
      button.textContent = text;
      button.addEventListener("click", () => sendMessage(text));
      box.appendChild(button);
    });
  }

  async function sendMessage(text) {
    const message = String(text || "").trim();
    if (!message || chatBusy) return;
    chatBusy = true;
    addMessage(message, "user");
    $("chatInput").value = "";
    $("chatMode").textContent = "Pensando…";
    const typing = document.createElement("div");
    typing.className = "chat-msg typing";
    typing.innerHTML = "<i></i><i></i><i></i>";
    $("chatMessages").appendChild(typing);
    $("chatMessages").scrollTop = $("chatMessages").scrollHeight;

    try {
      const response = await fetch("/api/public/chat", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ message, sessionId: chatSession }),
      });
      const data = await response.json().catch(() => ({}));
      if (!response.ok) throw new Error(data.detail || "No se pudo conectar");
      typing.remove();
      addMessage(data.answer || "No obtuve una respuesta. Intenta de nuevo.", "bot");
      renderSuggestions(data.suggestions);
      $("chatMode").textContent =
        data.mode === "n8n"
          ? "En línea con n8n"
          : data.mode === "openrouter"
            ? "Asistente IA · información pública"
            : data.mode === "guardrail"
              ? "Modo privado · solo temas públicos"
              : "Modo local · información pública";
    } catch (error) {
      typing.remove();
      addMessage("No pude conectar con el asistente. Puedes usar el formulario de contacto.", "bot");
      $("chatMode").textContent = "Sin conexión";
    } finally {
      chatBusy = false;
    }
  }

  function setupChat() {
    $("chatFab").addEventListener("click", openChat);
    $("chatClose").addEventListener("click", closeChat);
    document.querySelectorAll("[data-open-chat]").forEach((button) => {
      button.addEventListener("click", openChat);
    });
    $("chatForm").addEventListener("submit", (event) => {
      event.preventDefault();
      sendMessage($("chatInput").value);
    });
    document.addEventListener("keydown", (event) => {
      if (event.key === "Escape") closeChat();
    });
    renderSuggestions(["¿Cuál es el horario?", "¿Cómo hago una reserva?", "¿Ofrecen eventos privados?"]);
  }

  /* ---------- Contacto ---------- */
  function setupContact() {
    $("contactForm").addEventListener("submit", async (event) => {
      event.preventDefault();
      const status = $("formStatus");
      status.className = "form-status";
      status.textContent = "Enviando…";
      const button = $("contactSubmit");
      button.disabled = true;
      const payload = {
        name: $("cName").value.trim(),
        email: $("cEmail").value.trim(),
        phone: $("cPhone").value.trim(),
        topic: $("cTopic").value,
        message: $("cMessage").value.trim(),
        website: $("cWebsite").value,
      };
      try {
        const response = await fetch("/api/public/contact", {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify(payload),
        });
        const data = await response.json().catch(() => ({}));
        if (!response.ok) throw new Error(data.detail || "No se pudo enviar");
        status.className = "form-status ok";
        status.textContent = `Recibido. Referencia ${data.reference}. Te responderemos pronto.`;
        $("contactForm").reset();
        toast("Solicitud registrada correctamente");
      } catch (error) {
        status.className = "form-status error";
        status.textContent = error.message || "No se pudo enviar. Intenta de nuevo.";
      } finally {
        button.disabled = false;
      }
    });
  }

  document.addEventListener("DOMContentLoaded", () => {
    setupNavigation();
    setupChat();
    setupContact();
    loadPublicConfig();
  });
})();
